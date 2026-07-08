from __future__ import annotations
"""資金管理模組 — 基於 Kelly Criterion 的部位規模、投資組合風險控管、再平衡。"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sector_map import sector_allows, get_sector
from config import Config
from adapters import PriceProvider

log = logging.getLogger(__name__)


class PortfolioManager:
    def __init__(self, trading_client=None, price_fn=None, order_manager=None,
                 account_provider=None, config=None):
        cfg = config or Config()
        self._cfg = cfg
        self.tc = trading_client
        self._account_provider = account_provider
        self.price_fn = price_fn or PriceProvider().get_current_price
        self.order_manager = order_manager
        self.capital = cfg.INITIAL_CAPITAL
        self.max_position_pct = cfg.MAX_POSITION_PCT
        self.max_total_exposure = cfg.MAX_TOTAL_EXPOSURE
        self.max_sector_pct = cfg.MAX_SECTOR_PCT
        self.kelly_fraction = cfg.KELLY_FRACTION
        self.min_position_pct = cfg.MIN_POSITION_PCT
        self.slippage_buffer = cfg.SLIPPAGE_BUFFER

    def get_account_summary(self) -> dict:
        if self._account_provider is not None:
            try:
                acct = self._account_provider.get_account_summary()
                result = {
                    "cash": acct.cash,
                    "portfolio_value": acct.portfolio_value,
                    "buying_power": acct.buying_power,
                    "equity": acct.equity,
                    "last_equity": acct.last_equity,
                    "daytrade_count": acct.daytrade_count,
                    "stale": acct.stale,
                }
                self._last_known_account = result
                return result
            except Exception as e:
                log.error(f"Account provider failed: {e}")
        try:
            acct = self.tc.get_account()
            result = {
                "cash": float(acct.cash),
                "portfolio_value": float(acct.portfolio_value),
                "buying_power": float(acct.buying_power),
                "equity": float(acct.equity),
                "last_equity": float(acct.last_equity),
                "daytrade_count": int(acct.daytrade_count),
                "stale": False,
            }
            self._last_known_account = result
            return result
        except Exception as e:
            log.error(f"get_account failed: {e}")
            if getattr(self, "_last_known_account", None):
                stale = dict(self._last_known_account)
                stale["stale"] = True
                log.warning("Using last known account snapshot (stale=True) instead of INITIAL_CAPITAL fallback.")
                return stale
            return {}

    def get_positions_dict(self) -> dict:
        if self._account_provider is not None:
            try:
                positions = self._account_provider.get_positions()
                return {
                    t: {
                        "qty": p.qty,
                        "avg_entry_price": p.avg_entry_price,
                        "current_price": p.current_price,
                        "market_value": p.market_value,
                        "cost_basis": p.cost_basis,
                        "unrealized_pl": p.unrealized_pl,
                        "unrealized_plpc": p.unrealized_plpc,
                        "change_today": p.change_today,
                    }
                    for t, p in positions.items() if abs(p.qty) > 0.001
                }
            except Exception as e:
                log.error(f"Account provider positions failed: {e}")
        try:
            pos_list = self.tc.get_all_positions()
            return {
                p.symbol: {
                    "qty": float(p.qty),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "cost_basis": float(p.cost_basis),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc),
                    "change_today": float(p.change_today),
                }
                for p in pos_list if abs(float(p.qty)) > 0.001
            }
        except Exception as e:
            log.error(f"get_positions failed: {e}")
            return {}

    @staticmethod
    def compute_kelly_pct(win_rate: float, avg_win: float, avg_loss: float,
                          kelly_fraction: float = 0.25, max_position_pct: float = 0.10,
                          min_position_pct: float = 0.02) -> float:
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return min_position_pct
        b = avg_win / avg_loss
        p = win_rate
        q = 1 - p
        kelly = (p * b - q) / b
        return max(0.0, min(kelly * kelly_fraction, max_position_pct))

    def get_kelly_inputs(self) -> dict:
        path = self._cfg.DATA_DIR / "performance.json"
        if not path.exists():
            return {"win_rate": 0.5, "avg_win": 1.0, "avg_loss": 1.0, "closed_trades": 0}
        try:
            perf = json.loads(path.read_text())
            ts = perf.get("trade_stats", {})
            return {
                "win_rate": ts.get("win_rate", 0.5),
                "avg_win": ts.get("avg_win_pct", 1.0),
                "avg_loss": ts.get("avg_loss_pct", 1.0),
                "closed_trades": ts.get("closed_trades", 0),
            }
        except Exception:
            return {"win_rate": 0.5, "avg_win": 1.0, "avg_loss": 1.0, "closed_trades": 0}

    def _rating_freshness_multiplier(self, analyzed_at: str) -> float:
        if not analyzed_at:
            return 1.0
        try:
            analyzed_dt = datetime.fromisoformat(analyzed_at)
            if analyzed_dt.tzinfo is None:
                analyzed_dt = analyzed_dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - analyzed_dt).total_seconds() / 86400
        except Exception:
            return 1.0
        if age_days <= 3:
            return 1.0
        if age_days >= 10:
            return 0.0
        return max(0.0, 1.0 - (age_days - 3) / 7)

    def position_size_for(self, ticker: str, price: float, rating: str, regime: dict = None,
                           positions: dict = None, extra_committed: float = 0.0,
                           analyzed_at: str = "", portfolio_value: float = None,
                           order_manager: object = None) -> int:
        if portfolio_value is None:
            acct = self.get_account_summary()
            portfolio_value = acct.get("portfolio_value", self.capital)
        if positions is None:
            positions = self.get_positions_dict()

        om = order_manager or self.order_manager
        pending = om.get_pending_buy_dollars() if om else 0.0
        current_exposure = sum(p["market_value"] for p in positions.values()) + extra_committed + pending
        available_for_new = portfolio_value * self.max_total_exposure - current_exposure
        if available_for_new <= 0:
            log.info(f"[{ticker}] Exposure limit reached (incl. ${extra_committed:.0f} committed this cycle).")
            return 0

        base_pct = self.max_position_pct
        if rating == "Overweight":
            base_pct = min(base_pct * 1.5, 0.20)
        elif rating == "Buy":
            base_pct = self.max_position_pct
        elif rating in ("Hold", "Underweight"):
            return 0

        freshness_mult = self._rating_freshness_multiplier(analyzed_at)
        if freshness_mult <= 0:
            log.info(f"[{ticker}] Rating too stale (analyzed_at={analyzed_at}), skipping new/add position.")
            return 0

        kelly_inputs = self.get_kelly_inputs()
        warmup = kelly_inputs.get("closed_trades", 0) < 10

        kelly_pct = self.compute_kelly_pct(
            kelly_inputs["win_rate"], kelly_inputs["avg_win"], kelly_inputs["avg_loss"],
            kelly_fraction=self.kelly_fraction, max_position_pct=self.max_position_pct,
            min_position_pct=self.min_position_pct,
        )

        if warmup:
            warmup_pct = min(base_pct, self.max_position_pct * 0.5)
            base_pct = min(base_pct, max(kelly_pct, warmup_pct)) if kelly_pct > 0 else warmup_pct
            log.info(f"[{ticker}] Warmup period ({kelly_inputs['closed_trades']} closed trades) — "
                     f"using conservative sizing {base_pct:.3f}")
        else:
            if kelly_pct <= 0:
                log.info(f"[{ticker}] Kelly={kelly_pct:.3f} 無優勢,略過進場")
                return 0
            base_pct = min(base_pct, kelly_pct)
            if kelly_pct <= self.min_position_pct:
                log.info(f"[{ticker}] Kelly={kelly_pct:.3f} (win_rate={kelly_inputs['win_rate']:.2f}, "
                         f"avg_win={kelly_inputs['avg_win']:.2f}, avg_loss={kelly_inputs['avg_loss']:.2f}) — "
                         f"sizing reduced, NOT falling back to MAX_POSITION_PCT")

        base_pct *= freshness_mult

        if regime:
            regime_mult = regime.get("position_size_mult", 1.0)
            base_pct *= regime_mult

        learned_mult = self._consult_knowledge_rules(ticker, rating, regime)
        base_pct *= learned_mult
        log.debug(f"[{ticker}] Knowledge rule multiplier: {learned_mult:.2f} → base_pct={base_pct:.4f}")

        raw_dollars = portfolio_value * base_pct
        dollars = min(raw_dollars, available_for_new)
        if dollars < portfolio_value * self.min_position_pct:
            log.info(f"[{ticker}] Sized position (${dollars:.0f}) below min threshold, skipping entry.")
            return 0
        dollars *= (1.0 - self.slippage_buffer)
        log.debug(f"[{ticker}] position_size_for: base_pct={base_pct:.4f}, raw_dollars={raw_dollars:.2f}, "
                  f"dollars_after_slippage={dollars:.2f}, price={price:.4f}, available_for_new={available_for_new:.2f}")
        qty = int(dollars / price)
        return max(qty, 0)

    def _consult_knowledge_rules(self, ticker: str, rating: str, regime: dict | None = None) -> float:
        """從知識庫查詢相關交易規則，回傳部位規模乘數（預設 1.0）。

        Returns:
            乘數，範圍 0.0 ~ 1.5。
        """
        try:
            from knowledge_base import KnowledgeBase
            from sector_map import get_sector
            kb = KnowledgeBase()
            rules = kb.query_rules({
                "ticker": ticker,
                "sector": get_sector(ticker),
                "regime": regime.get("regime", "") if regime else "",
                "rating": rating,
            }, k=3)
            if not rules:
                return 1.0

            total_mult = 1.0
            for rule in rules:
                rule_text = rule.content.lower()
                if any(w in rule_text for w in ("不追買", "不建立", "不進場", "等待")):
                    total_mult *= 0.7
                    log.info(f"[{ticker}] KB rule suggests caution: {rule.title[:60]}")
                if any(w in rule_text for w in ("加碼", "突破確認", "趨勢明確")):
                    total_mult *= 1.2
            return max(0.0, min(total_mult, 1.5))
        except Exception as e:
            log.debug(f"[{ticker}] Knowledge rules consultation failed: {e}")
            return 1.0

    def _technical_confirms_entry(self, ticker: str) -> bool:
        """下單前輕量重新驗證技術面。"""
        try:
            from screener import Screener
            result = Screener(max_workers=1)._analyze_one(ticker)
            if result.error:
                log.warning(f"[{ticker}] Technical re-check failed ({result.error}), allowing entry by default")
                return True
            confirmed = result.score > 0
            if not confirmed:
                log.info(f"[{ticker}] Technical re-check FAILED: score={result.score} "
                         f"(signals={result.signals}) — skipping entry despite Buy rating")
            return confirmed
        except Exception as e:
            log.warning(f"[{ticker}] Technical re-check error: {e}, allowing entry by default")
            return True

    def _regime_allows(self, rating: str, regime: dict = None) -> bool:
        if not regime:
            return True
        if regime.get("regime") == "bear":
            return rating == "Overweight"
        return True

    def should_reduce_position(self, ticker: str, rating: str, regime: dict = None,
                                 analyzed_at: str = "") -> bool:
        if rating in ("Sell", "Underweight"):
            return True
        fh = self._rating_freshness_multiplier(analyzed_at)
        if fh <= 0:
            log.warning(f"[{ticker}] Rating too stale (analyzed_at={analyzed_at}), treating as Hold and flagging review")
            return False
        if regime and regime.get("regime") == "bear" and rating != "Overweight":
            return True
        return False

    def reduction_multiplier(self, ticker: str, rating: str, regime: dict = None) -> float:
        if regime and regime.get("regime") == "bear" and rating != "Overweight":
            return 0.5
        return 1.0

    def should_add_to_position(self, ticker: str, rating: str, position: dict, regime: dict = None,
                                 portfolio_value: float = None) -> bool:
        if rating not in ("Buy", "Overweight"):
            return False
        if not self._regime_allows(rating, regime):
            return False
        if portfolio_value is None:
            portfolio_value = self.get_account_summary().get("portfolio_value", 1)
        current_pct = position["market_value"] / max(portfolio_value, 1)
        if current_pct >= self.max_position_pct:
            return False
        return True

    def rebalance_targets(self, ratings: dict, regime: dict = None) -> list[dict]:
        acct = self.get_account_summary()
        portfolio_value = acct.get("portfolio_value", self.capital)
        positions = self.get_positions_dict()
        actions = []

        committed_dollars = 0.0
        committed_by_sector: dict[str, float] = {}

        for ticker, info in ratings.items():
            rating = info.get("rating", "Hold")
            if info.get("error"):
                continue

            if ticker in positions:
                if self.should_reduce_position(ticker, rating, regime, analyzed_at=info.get("analyzed_at", "")):
                    pos = positions[ticker]
                    mult = self.reduction_multiplier(ticker, rating, regime)
                    qty = max(1, int(abs(float(pos["qty"])) * mult))
                    actions.append({
                        "ticker": ticker,
                        "action": "sell",
                        "qty": qty,
                        "reason": f"Rating downgrade to {rating}" + (" (bear partial)" if mult < 1 else ""),
                    })
                elif self.should_add_to_position(ticker, rating, positions[ticker], regime,
                                                  portfolio_value=portfolio_value):
                    sector = get_sector(ticker)
                    sector_committed = committed_by_sector.get(sector, 0.0)
                    if not sector_allows(ticker, positions, portfolio_value, self.max_sector_pct,
                                          extra_committed=sector_committed):
                        continue
                    pos = positions[ticker]
                    price = pos["current_price"]
                    price = price if price > 0 else info.get("price_target", price)
                    price_target = info.get("price_target")
                    if price_target and price >= price_target:
                        log.info(f"[{ticker}] Price ${price:.2f} >= target ${price_target:.2f}, "
                                 f"skipping add-on (already at/above target).")
                        continue
                    if price > 0:
                        add_qty = self.position_size_for(ticker, price, rating, regime, positions,
                                                          extra_committed=committed_dollars,
                                                          analyzed_at=info.get("analyzed_at", ""),
                                                          portfolio_value=portfolio_value)
                        if add_qty > 0:
                            dollars = add_qty * price
                            committed_dollars += dollars
                            committed_by_sector[sector] = sector_committed + dollars
                            actions.append({
                                "ticker": ticker,
                                "action": "buy",
                                "qty": add_qty,
                                "reason": f"Add to position ({rating})",
                            })
            else:
                if rating in ("Buy", "Overweight") and self._regime_allows(rating, regime):
                    sector = get_sector(ticker)
                    sector_committed = committed_by_sector.get(sector, 0.0)
                    if not self._technical_confirms_entry(ticker):
                        continue
                    if not sector_allows(ticker, positions, portfolio_value, self.max_sector_pct,
                                          extra_committed=sector_committed):
                        continue
                    price = self.get_current_price(ticker)
                    if not price or price <= 0:
                        log.warning(f"[{ticker}] Cannot get price, skipping new position.")
                        continue
                    price_target = info.get("price_target")
                    if price_target and price >= price_target:
                        log.info(f"[{ticker}] Price ${price:.2f} >= target ${price_target:.2f}, skipping.")
                        continue
                    qty = self.position_size_for(ticker, price, rating, regime, positions,
                                                  extra_committed=committed_dollars,
                                                  analyzed_at=info.get("analyzed_at", ""),
                                                  portfolio_value=portfolio_value)
                    if qty > 0:
                        dollars = qty * price
                        committed_dollars += dollars
                        committed_by_sector[sector] = sector_committed + dollars
                        actions.append({
                            "ticker": ticker,
                            "action": "buy",
                            "qty": qty,
                            "reason": f"New position ({rating})",
                        })

        self._log_rebalance(actions, regime)
        return actions

    def _log_rebalance(self, actions: list, regime: dict = None):
        log.info(f"Rebalance: {len(actions)} action(s)")
        for a in actions:
            log.info(f"  {a['action'].upper()} {a['ticker']} x{a['qty']} | {a['reason']}")

    def get_current_price(self, ticker: str) -> float:
        return self.price_fn(ticker)

    def save_snapshot(self, regime: dict = None):
        acct = self.get_account_summary()
        positions = self.get_positions_dict()
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": acct,
            "positions": positions,
            "regime": regime,
        }
        from file_utils import atomic_write_json
        atomic_write_json(self._cfg.DATA_DIR / "portfolio_snapshot.json", snapshot)
