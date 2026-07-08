from __future__ import annotations
"""盤中監控引擎 — 交易時段每 30 秒檢查價格，純程式判斷。
整合 PortfolioManager / OrderManager / PerformanceTracker / RegimeDetector。
"""

import json
import time
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from config import Config
from logging.handlers import RotatingFileHandler
from file_utils import atomic_write_json

from alpaca.trading.enums import OrderSide
from trading_calendar import is_market_open_now, is_trading_day, last_trading_day, today_et
from portfolio_manager import PortfolioManager
from order_manager import OrderManager
from performance import PerformanceTracker
from regime import RegimeDetector
from safety import CircuitBreaker
from health import ping
from notifier import send_message
from news_service import NewsService
from adapters import PriceProvider, AccountProvider
from event_bus import EventBus
import db

_cfg = Config()
DATA_DIR = _cfg.DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(DATA_DIR / "monitor.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


class PriceMonitor:
    def __init__(self, config=None, strategies=None, container=None):
        cfg = config or _cfg
        self._cfg = cfg
        self._container = container
        db.init_db()

        if container is not None:
            self.trading_client = container.trading_client
            self.data_client = container.data_client
            self._price_provider = container.price_provider
            self._account_provider = container.account_provider
        else:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical.stock import StockHistoricalDataClient
            self.trading_client = TradingClient(
                cfg.ALPACA_API_KEY,
                cfg.ALPACA_API_SECRET,
                paper=cfg.IS_PAPER,
            )
            self.data_client = StockHistoricalDataClient(
                cfg.ALPACA_API_KEY,
                cfg.ALPACA_API_SECRET,
            )
            self._price_provider = PriceProvider(alpaca_data_client=self.data_client)
            self._account_provider = AccountProvider(trading_client=self.trading_client)

        self.orders = OrderManager(self.trading_client, config=cfg, price_fn=self.get_current_price)
        self.portfolio = PortfolioManager(trading_client=self.trading_client,
                                           price_fn=self.get_current_price,
                                           order_manager=self.orders,
                                           account_provider=self._account_provider,
                                           config=cfg)
        self.performance = PerformanceTracker(self.trading_client, config=cfg)
        self.regime = RegimeDetector()
        self.breaker = CircuitBreaker(self.trading_client, config=cfg)

        self.ratings_path = cfg.DATA_DIR / "ratings.json"
        self.ratings = {}
        self._load_ratings()

        self.positions = {}
        self.alerted_buy: dict[str, float] = {}
        self.last_trading_date = None
        self._morning_briefed = False
        self._last_regime = None
        self._last_snapshot_time = 0.0
        self._news_service = NewsService()
        self._last_news_check: dict[str, float] = {}
        self._priority_flagged_path = cfg.DATA_DIR / ".priority_reanalyze.json"

        if strategies is not None:
            self._strategies = strategies
        else:
            from strategy import CompositeStrategy, RatingStrategy, StopLossTakeProfitStrategy
            self._strategies = CompositeStrategy([
                StopLossTakeProfitStrategy(),
                RatingStrategy(),
            ])

    # ── Ratings ──────────────────────────────────────────────

    def _load_ratings(self):
        if self.ratings_path.exists():
            with open(self.ratings_path) as f:
                self.ratings = json.load(f)

    def _refresh_ratings(self):
        if not self.ratings_path.exists():
            return
        try:
            new_ratings = json.loads(self.ratings_path.read_text())
            changed = any(
                self.ratings.get(t, {}).get("rating") != new_ratings[t].get("rating")
                for t in new_ratings
            )
            if changed:
                old = self.ratings
                self.ratings = new_ratings
                log.info("Ratings updated from deep analysis.")
                self._check_rating_changes(old, new_ratings)
        except Exception as e:
            log.error(f"Failed to refresh ratings: {e}")

    def _check_rating_changes(self, old: dict, new: dict):
        for tkr, info in new.items():
            old_rating = old.get(tkr, {}).get("rating", "")
            new_rating = info.get("rating", "")
            if old_rating and old_rating != new_rating:
                log.info(f"[{tkr}] Rating changed: {old_rating} -> {new_rating}")

    # ── Positions ────────────────────────────────────────────

    def get_positions(self):
        self.positions = self.portfolio.get_positions_dict()
        return self.positions

    # ── Price ────────────────────────────────────────────────

    def get_current_price(self, ticker: str) -> float | None:
        return self._price_provider.get_current_price(ticker)

    # ── Order Execution ──────────────────────────────────────

    def execute_order(self, ticker: str, side: OrderSide, qty: int, reason: str = ""):
        if qty <= 0:
            return None

        is_protective = (side == OrderSide.SELL and reason in ("Stop Loss", "Take Profit"))
        if self.orders.has_open_order(ticker) and not is_protective:
            log.debug(f"[{ticker}] Open order exists, skipping {side} x{qty}")
            return None
        if is_protective and self.orders.has_open_order(ticker):
            for r in self.orders.get_open_orders():
                if r.ticker == ticker:
                    self.orders.cancel_order(r.client_id)
            log.warning(f"[{ticker}] 止損/停利觸發,已撤未成交掛單以確保出場")

        is_add_on = (side == OrderSide.BUY) and (ticker in self.positions)

        if side == OrderSide.SELL or is_add_on:
            cancelled = self.orders.cancel_bracket_children(ticker)
            if cancelled:
                log.info(f"[{ticker}] Cleared {cancelled} bracket child order(s) before {reason}")

        bracket_sl = bracket_tp = None
        reference_price = 0.0
        if side == OrderSide.BUY:
            sl_pct = self._cfg.STOP_LOSS_PCT
            tp_pct = self._cfg.TAKE_PROFIT_PCT
            price = self.get_current_price(ticker)
            if price and price > 0:
                reference_price = price
                bracket_sl = round(price * (1 - sl_pct), 2)
                bracket_tp = round(price * (1 + tp_pct), 2)

        record = self.orders.submit_market_order(
            ticker=ticker,
            side=side,
            qty=qty,
            reason=reason,
            bracket_sl=bracket_sl,
            bracket_tp=bracket_tp,
            reference_price=reference_price,
        )

        if is_add_on and record and record.status != "failed":
            self._rebuild_full_position_bracket(ticker)

        is_partial_sell = (side == OrderSide.SELL and record and record.status != "failed"
                           and ticker in self.positions
                           and abs(int(float(self.positions[ticker]["qty"]))) > 0)
        if is_partial_sell:
            self._rebuild_full_position_bracket(ticker)

        if record and record.status != "failed":
            if side == OrderSide.BUY:
                self.alerted_buy[ticker] = time.time()
        return record

    def _rebuild_full_position_bracket(self, ticker: str, max_wait_sec: int = 60):
        """加碼成交後，用新的混合平均成本對全部庫存重建 OCO 保護單。"""
        sl_pct = self._cfg.STOP_LOSS_PCT
        tp_pct = self._cfg.TAKE_PROFIT_PCT

        waited = 0
        while waited < max_wait_sec:
            positions = self.portfolio.get_positions_dict()
            pos = positions.get(ticker)
            if pos:
                avg_entry = pos["avg_entry_price"]
                qty = abs(int(float(pos["qty"])))
                new_sl = round(avg_entry * (1 - sl_pct), 2)
                new_tp = round(avg_entry * (1 + tp_pct), 2)
                ok = self.orders.submit_protective_oco(ticker, qty, new_sl, new_tp)
                if ok:
                    log.info(f"[{ticker}] Rebuilt protective OCO: avg_entry=${avg_entry:.2f}, "
                             f"SL=${new_sl}, TP=${new_tp}")
                else:
                    send_message(f"🚨 [{ticker}] 加碼後保護單 OCO 重建失敗 (SL={new_sl} TP={new_tp})，請人工檢查！")
                return
            time.sleep(2)
            waited += 2
        send_message(f"🚨 [{ticker}] 無法在 {max_wait_sec}s 內確認更新後部位以重建保護單 — 可能已無保護！")

    # ── Stop Loss / Take Profit ──────────────────────────────

    def _build_strategy_context(self) -> object:
        """建構 StrategyContext 供策略使用。"""
        from strategy import StrategyContext
        om = self.orders
        return StrategyContext(
            positions=self.positions,
            ratings=self.ratings,
            regime=self._last_regime,
            config=self._cfg,
            portfolio=self.portfolio,
            orders=om,
            price_provider=self._price_provider,
            pending_buy_dollars=om.get_pending_buy_dollars() if om else 0.0,
        )

    def run_strategies(self, allow_entries: bool = True):
        """執行所有已註冊策略並處理產生的訊號。

        Args:
            allow_entries: 是否允許買入訊號（受熔斷/kill switch 控制）。
        """
        ctx = self._build_strategy_context()
        signals = self._strategies.generate_signals(ctx)

        for s in signals:
            if s.action.value == "buy" and not allow_entries:
                continue
            if s.action.value == "buy":
                last_time = self.alerted_buy.get(s.ticker, 0)
                cooldown = self._cfg.BUY_COOLDOWN_SECONDS
                if time.time() - last_time < cooldown:
                    continue

            # V2 Chairman decision pipeline (when feature flag enabled)
            if self._cfg.USE_CHAIRMAN_DECISION and s.action.value == "buy" and self._container is not None:
                try:
                    from interfaces_v2 import AgentProposal, PortfolioState
                    container = self._container
                    price = self.get_current_price(s.ticker) or 0
                    proposal = AgentProposal(
                        agent_name="strategy",
                        ticker=s.ticker,
                        rating="BUY",
                        confidence=0.7,
                        thesis=s.reason,
                        price_target=price * 1.1,
                        time_horizon="short",
                        key_risks=[],
                        supporting_rules_used=[],
                    )
                    portfolio_value = float(self.portfolio.get_account_summary().portfolio_value)
                    positions = self.portfolio.get_positions_dict()
                    from sector_map import get_sector_exposure
                    sector_exposure = get_sector_exposure(positions, portfolio_value)
                    state = PortfolioState(
                        positions=positions,
                        cash=float(self.portfolio.get_account_summary().cash),
                        portfolio_value=portfolio_value,
                        sector_exposure=sector_exposure,
                        regime=self._last_regime.get("regime", "unknown") if self._last_regime else "unknown",
                    )
                    risk = container.risk_agent.evaluate(proposal, state)
                    decision = container.chairman_agent.decide([proposal], risk)
                    if decision.final_action != "BUY":
                        log.info(f"[{s.ticker}] V2 Chairman vetoed: {decision.conflict_resolution} — {decision.rationale}")
                        continue
                    # Use Chairman's position_pct for qty calculation
                    dollars = portfolio_value * decision.position_pct
                    s.qty = max(1, int(dollars / price)) if price > 0 else s.qty
                except Exception as e:
                    log.warning(f"V2 Chairman decision failed (falling through to default): {e}")

            record = self.execute_order(s.ticker, OrderSide[s.action.name], s.qty, s.reason)
            if record and record.status != "failed" and s.reason == "Stop Loss":
                self.alerted_buy[s.ticker] = time.time()

    # ── Regime ───────────────────────────────────────────────

    def refresh_regime(self):
        regime = self.regime.detect(market_open=self.is_trading_hours())
        if regime["regime"] != "unknown":
            self._last_regime = regime
        return regime

    # ── Trading Hours ────────────────────────────────────────

    def is_trading_hours(self):
        return is_market_open_now()

    # ── News & Gap Monitoring ─────────────────────────────────

    def _check_position_news(self):
        """對持倉股票做輕量新聞掃描，發現明顯負面訊號時記錄告警。"""
        interval_sec = self._cfg.POSITION_NEWS_CHECK_INTERVAL_SEC
        now = time.time()

        NEGATIVE_KEYWORDS = [
            "missed estimates", "misses estimates", "lowers guidance", "cuts guidance",
            "halted", "halt", "investigation", "sec probe", "recall", "lawsuit",
            "downgrade", "bankruptcy", "delisting", "fraud",
        ]
        NEGATION_WORDS = {"not", "no", "n't", "deny", "denies", "denied", "avoid",
                          "avoids", "avoided", "without", "unrelated", "cleared"}

        def _is_negative_hit(text: str, keyword: str, window: int = 4) -> bool:
            words = text.split()
            first_word = keyword.split()[0]
            for i, w in enumerate(words):
                if first_word in w.lower():
                    context = words[max(0, i - window):i]
                    if any(neg in " ".join(context).lower() for neg in NEGATION_WORDS):
                        return False
                    return True
            return False

        for ticker in list(self.positions.keys()):
            last_check = self._last_news_check.get(ticker, 0)
            if now - last_check < interval_sec:
                continue
            self._last_news_check[ticker] = now

            try:
                resp = self._news_service.search_stock_news(ticker, max_results=5)
                if not resp.success or not resp.results:
                    continue
                for item in resp.results:
                    text = f"{item.title} {item.snippet}"
                    for kw in NEGATIVE_KEYWORDS:
                        if _is_negative_hit(text.lower(), kw):
                            log.warning(f"[{ticker}] Negative news signal detected ('{kw}'): {item.title}")
                            import html
                            send_message(f"⚠️ [{ticker}] Possible negative news: {html.escape(item.title)}\n{item.url}")
                            self._flag_priority_reanalysis(ticker)
                            break
            except Exception as e:
                log.debug(f"[{ticker}] Position news check failed: {e}")

    def _flag_priority_reanalysis(self, ticker: str):
        flagged = []
        if self._priority_flagged_path.exists():
            try:
                flagged = json.loads(self._priority_flagged_path.read_text())
            except Exception:
                pass
        if ticker not in flagged:
            flagged.append(ticker)
            atomic_write_json(self._priority_flagged_path, flagged)
            log.info(f"[{ticker}] Flagged for priority re-analysis in next scheduler cycle")

    def _check_gap_and_tradability(self):
        """開盤時檢查持倉是否跳空過大，或資產是否已不可交易。"""
        gap_threshold = self._cfg.GAP_ALERT_PCT
        for ticker, pos in list(self.positions.items()):
            try:
                asset = self.trading_client.get_asset(ticker)
                if not asset.tradable:
                    log.warning(f"[{ticker}] Asset no longer tradable! status={asset.status}")
                    send_message(f"🚨 [{ticker}] No longer tradable (status={asset.status}), review manually.")
                    continue
            except Exception as e:
                log.debug(f"[{ticker}] Asset status check failed: {e}")

            entry = pos["avg_entry_price"]
            current = pos["current_price"]
            if entry > 0:
                gap_pct = (current - entry) / entry
                if abs(gap_pct) >= gap_threshold and ticker not in self.alerted_buy:
                    log.warning(f"[{ticker}] Large price move since entry: {gap_pct*100:.1f}%")

    # ── Morning Briefing ─────────────────────────────────────

    def _morning_briefing(self):
        self._morning_briefed = True
        log.info("=" * 60)
        log.info("MARKET OPEN — Morning Briefing")
        EventBus.get_instance().emit("monitor_morning_briefing", {
            "regime": self._last_regime,
            "positions_count": len(self.positions),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        regime = self._last_regime or {}
        log.info(f"  Regime: {regime.get('regime', 'unknown')} | SPY={regime.get('spy_price', '?')} | Size Mult: {regime.get('position_size_mult', 1.0)}")

        try:
            account = self.trading_client.get_account()
            log.info(f"  Cash: ${float(account.cash):.2f}")
            log.info(f"  Portfolio: ${float(account.portfolio_value):.2f}")
        except Exception as e:
            log.error(f"  Account info: {e}")

        order_summary = self.orders.get_order_summary()
        log.info(f"  Orders: {order_summary.get('total_orders', 0)} total | {order_summary.get('by_status', {})}")

        if self.positions:
            log.info("  Current Positions:")
            for t, p in self.positions.items():
                log.info(f"    {t}: {p['qty']} @ ${p['avg_entry_price']:.2f} (PnL: ${p['unrealized_pl']:.2f})")
        else:
            log.info("  No open positions.")

        log.info("  Ratings:")
        for t, r in self.ratings.items():
            pt = r.get("price_target")
            pt_str = f" -> ${pt:.2f}" if pt else ""
            err = " [ERROR]" if r.get("error") else ""
            log.info(f"    {t}: {r.get('rating', 'Hold')}{pt_str}{err}")
        log.info("=" * 60)

        self.portfolio.save_snapshot(regime)

        self._check_gap_and_tradability()

    # ── Daily Recap ──────────────────────────────────────────

    def _daily_recap(self):
        try:
            perf = self.performance.snapshot()
            self.performance.print_summary(perf)
        except Exception as e:
            log.error(f"Performance snapshot failed: {e}")

        recap_data = {}
        try:
            account = self.trading_client.get_account()
            positions_data = []
            for t, p in self.positions.items():
                positions_data.append({
                    "ticker": t,
                    "qty": p["qty"],
                    "avg_entry": round(p["avg_entry_price"], 2),
                    "current_price": round(p["current_price"], 2),
                    "unrealized_pnl": round(p.get("unrealized_pl", 0), 2),
                })

            recap_data = {
                "date": today_et().isoformat(),
                "cash": round(float(account.cash), 2),
                "portfolio_value": round(float(account.portfolio_value), 2),
                "positions": positions_data,
                "regime": self._last_regime,
                "total_unrealized_pnl": round(sum(p.get("unrealized_pl", 0) for p in self.positions.values()), 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            atomic_write_json(self._cfg.DATA_DIR / f"recap_{today_et().isoformat()}.json", recap_data)
            log.info(f"Daily recap saved.")
            regime_name = (self._last_regime or {}).get("regime", "?")
            msg = (
                f" Daily Recap {recap_data['date']}\n"
                f"Value: ${recap_data['portfolio_value']:,.2f}\n"
                f"Cash: ${recap_data['cash']:,.2f}\n"
                f"PnL: ${recap_data['total_unrealized_pnl']:+,.2f}\n"
                f"Positions: {len(recap_data['positions'])}\n"
                f"Regime: {regime_name}"
            )
            send_message(msg)
        except Exception as e:
            log.error(f"Daily recap failed: {e}")

        EventBus.get_instance().emit("monitor_daily_recap", recap_data if recap_data else {
            "date": today_et().isoformat(),
        })

        self.orders.eod_cleanup()

    # ── Main Cycle ───────────────────────────────────────────

    def run_cycle(self):
        EventBus.get_instance().emit("monitor_cycle_started", {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self._refresh_ratings()
        self.refresh_regime()
        self.get_positions()

        if not self._morning_briefed and is_trading_day():
            self._morning_briefing()

        account = None
        value = None
        cash = 0.0
        try:
            account = self.trading_client.get_account()
            value = float(account.portfolio_value)
            cash = float(account.cash)
        except Exception as e:
            log.error(f"Account info failed: {e}")

        kill_switch = (self._cfg.DATA_DIR / ".kill").exists()
        if kill_switch:
            log.warning("KILL SWITCH ACTIVE — delete .kill to resume")

        account_read_failed = value is None

        if account_read_failed:
            log.warning("Account data unavailable this cycle — skipping new trades as a precaution (fail-safe).")
        elif kill_switch:
            log.warning("KILL SWITCH ACTIVE — delete .kill to resume")

        breaker_tripped = self.breaker.check(value) if value is not None else self.breaker.tripped

        if not account_read_failed:
            self.orders.maintenance_cycle()
            entries_allowed = not (breaker_tripped or kill_switch)
            self.run_strategies(allow_entries=entries_allowed)
        else:
            log.warning("Account data unavailable — no trading this cycle.")

        self._check_position_news()

        now = time.time()
        if now - self._last_snapshot_time > 300:
            self.portfolio.save_snapshot(self._last_regime)
            self._last_snapshot_time = now

        pnl = sum(p.get("unrealized_pl", 0) for p in self.positions.values())
        log.info(f"ACCOUNT: Cash=${cash:.2f} | Value=${value:.2f} | PnL=${pnl:.2f} | Positions={len(self.positions)}")
        ping("monitor")

    def run_forever(self):
        log.info("PriceMonitor started. Waiting for market open...")
        interval = self._cfg.MONITOR_INTERVAL_SECONDS

        while True:
            try:
                now = datetime.now()
                today_key = today_et().isoformat()

                if self.is_trading_hours():
                    self.run_cycle()
                    self.last_trading_date = today_key
                    self._morning_briefed = True
                else:
                    if self.last_trading_date and self.last_trading_date != today_key:
                        if is_trading_day(date.fromisoformat(self.last_trading_date)):
                            self._daily_recap()
                        self.last_trading_date = today_key
                        self._morning_briefed = False
                    log.debug("Outside trading hours.")

                time.sleep(interval)
            except KeyboardInterrupt:
                log.info("Shutdown requested.")
                EventBus.get_instance().emit("monitor_shutdown", {"reason": "keyboard_interrupt"})
                self._daily_recap()
                break
            except Exception as e:
                log.error(f"Cycle error: {e}", exc_info=True)
                time.sleep(60)


if __name__ == "__main__":
    from file_utils import validate_env
    validate_env("monitor")
    monitor = PriceMonitor()
    monitor.run_forever()
