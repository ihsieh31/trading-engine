"""績效追蹤 — 每日 P&L、Sharpe、Sortino、MDD、勝率、損益曲線。"""

from __future__ import annotations
import json
import math
import logging
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import numpy as np
from file_utils import atomic_write_json
from config import Config
import db

log = logging.getLogger(__name__)


class PerformanceTracker:
    """績效追蹤器。

    責任：
    - 每日從 Alpaca 抓取 portfolio history
    - 計算 Sharpe / Sortino / MDD / 勝率 / Profit Factor
    - 從 trades.jsonl 讀取已實現損益
    - 儲存到 performance.json 供 Kelly 計算使用
    - 產生 equity curve 資料（performance_history.json）
    """

    def __init__(self, trading_client, config: Config | None = None):
        self.tc = trading_client
        cfg = config or Config()
        self.DATA_DIR = cfg.DATA_DIR

    # ── Portfolio History ───────────────────────────────────

    def fetch_portfolio_history(self, days: int = 90) -> dict:
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest
            from alpaca.data.enums import Adjustment
            req = GetPortfolioHistoryRequest(
                period=f"{days}D",
                timeframe="1D",
                extended_hours=False,
            )
            history = self.tc.get_portfolio_history(req)

            if hasattr(history, "timestamp") and history.timestamp:
                return {
                    "timestamps": history.timestamp,
                    "equity": history.equity,
                    "profit_loss": history.profit_loss,
                    "profit_loss_pct": history.profit_loss_pct,
                }
            return {}
        except Exception as e:
            log.error(f"fetch_portfolio_history failed: {e}")
            return {}

    # ── Trade Analysis ──────────────────────────────────────

    def load_trades(self) -> list[dict]:
        trades = []
        try:
            trades = db.load_trades(limit=5000)
        except Exception:
            pass
        if trades:
            return trades
        path = self.DATA_DIR / "trades.jsonl"
        if not path.exists():
            return []
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        trades.append(json.loads(line))
        except Exception as e:
            log.error(f"load_trades failed: {e}")
        return trades

    def analyze_trades(self) -> dict:
        trades = self.load_trades()
        if not trades:
            return {
                "total_trades": 0,
                "closed_trades": 0,
                "win_rate": 0.5,
                "avg_win_pct": 1.0,
                "avg_loss_pct": 1.0,
                "profit_factor": 0.0,
                "total_pnl_pct": 0.0,
                "matched_qty": 0,
            }

        trades_sorted = sorted(trades, key=lambda t: t.get("time", ""))
        cost_basis = {}
        total_buy_qty = {}
        closed_trades = []
        matched_qty = 0
        for t in trades_sorted:
            tkr, side = t["ticker"], t["side"]
            qty, price = t.get("qty", 0), t.get("price", 0)
            if side == "buy":
                old_qty = total_buy_qty.get(tkr, 0)
                old_cost = cost_basis.get(tkr, 0.0)
                new_qty = old_qty + qty
                cost_basis[tkr] = (old_cost * old_qty + price * qty) / new_qty if new_qty > 0 else price
                total_buy_qty[tkr] = new_qty
            elif side == "sell":
                avg_cost = cost_basis.get(tkr)
                available = total_buy_qty.get(tkr, 0)
                if avg_cost is None or avg_cost <= 0 or available <= 0:
                    continue
                take = min(qty, available)
                pnl_pct = (price - avg_cost) / avg_cost * 100
                closed_trades.append(pnl_pct)
                matched_qty += take
                total_buy_qty[tkr] = available - take
                if take < qty:
                    log.warning(f"[{tkr}] Sold {qty} but only {available} shares available, "
                                f"difference of {qty - take} unmatched")

        if not closed_trades:
            return {
                "total_trades": len(trades),
                "closed_trades": 0,
                "win_rate": 0.5,
                "avg_win_pct": 1.0,
                "avg_loss_pct": 1.0,
                "profit_factor": 0.0,
                "total_pnl_pct": 0.0,
                "matched_qty": 0,
            }

        wins = [t for t in closed_trades if t > 0]
        losses = [t for t in closed_trades if t <= 0]
        win_rate = len(wins) / len(closed_trades) if closed_trades else 0.5
        avg_win = np.mean(wins) / 100.0 if wins else 0.01
        avg_loss = abs(np.mean(losses)) / 100.0 if losses else 0.01
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 1
        profit_factor = total_wins / total_losses if total_losses != 0 else 0.0

        return {
            "total_trades": len(trades),
            "closed_trades": len(closed_trades),
            "matched_qty": matched_qty,
            "win_rate": round(win_rate, 4),
            "avg_win_pct": round(avg_win, 4),
            "avg_loss_pct": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 4),
            "total_pnl_pct": round(sum(closed_trades), 2) if closed_trades else 0.0,
        }

    # ── Risk Metrics ────────────────────────────────────────

    def compute_risk_metrics(self, history: dict) -> dict:
        if not history or "equity" not in history or len(history["equity"]) < 5:
            return {}

        equity = np.array(history["equity"])
        daily_returns = np.diff(equity) / equity[:-1]
        if len(daily_returns) < 2:
            return {}

        ann_factor = math.sqrt(252)

        avg_return = np.mean(daily_returns)
        std_return = np.std(daily_returns, ddof=1)

        sharpe = (avg_return / std_return * ann_factor) if std_return > 0 else 0.0

        neg_returns = daily_returns[daily_returns < 0]
        downside_std = np.std(neg_returns, ddof=1) if len(neg_returns) > 1 else std_return
        sortino = (avg_return / downside_std * ann_factor) if downside_std > 0 else 0.0

        cumulative = np.cumprod(1 + daily_returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        max_drawdown = float(np.min(drawdowns))

        volatility = float(std_return * ann_factor * 100)

        return {
            "sharpe_ratio": round(float(sharpe), 4),
            "sortino_ratio": round(float(sortino), 4),
            "max_drawdown_pct": round(float(max_drawdown * 100), 2),
            "annualized_volatility_pct": round(volatility, 2),
            "avg_daily_return_pct": round(float(avg_return * 100), 4),
            "num_days": len(daily_returns),
        }

    # ── Snapshot & Store ────────────────────────────────────

    def snapshot(self) -> dict:
        history = self.fetch_portfolio_history(90)
        trade_stats = self.analyze_trades()
        risk_metrics = self.compute_risk_metrics(history)

        acct = {}
        try:
            a = self.tc.get_account()
            acct = {
                "cash": float(a.cash),
                "portfolio_value": float(a.portfolio_value),
                "equity": float(a.equity),
                "last_equity": float(a.last_equity),
            }
        except Exception as e:
            log.warning(f"Account fetch failed: {e}")

        perf = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": acct,
            "trade_stats": trade_stats,
            "risk_metrics": risk_metrics,
            "equity_curve": {
                "timestamps": history.get("timestamps", [])[-60:],
                "equity": history.get("equity", [])[-60:],
            } if history else {},
        }

        atomic_write_json(self.DATA_DIR / "performance.json", perf)

        self._append_history(perf)
        return perf

    def _append_history(self, perf: dict):
        path = self.DATA_DIR / "performance_history.json"
        entries = []
        if path.exists():
            try:
                entries = json.loads(path.read_text())
            except Exception:
                pass
        summary = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "portfolio_value": perf.get("account", {}).get("portfolio_value", 0),
            "equity": perf.get("account", {}).get("equity", 0),
            "sharpe": perf.get("risk_metrics", {}).get("sharpe_ratio", 0),
            "max_drawdown": perf.get("risk_metrics", {}).get("max_drawdown_pct", 0),
            "win_rate": perf.get("trade_stats", {}).get("win_rate", 0),
            "total_trades": perf.get("trade_stats", {}).get("total_trades", 0),
        }
        entries.append(summary)
        atomic_write_json(path, entries)

    def print_summary(self, perf: dict = None):
        if perf is None:
            perf = self.snapshot()

        ts = perf.get("trade_stats", {})
        rm = perf.get("risk_metrics", {})
        acct = perf.get("account", {})

        log.info("=" * 55)
        log.info("PERFORMANCE SUMMARY")
        log.info(f"  Portfolio: ${acct.get('portfolio_value', 0):.2f}")
        log.info(f"  Cash: ${acct.get('cash', 0):.2f}")
        log.info(f"  Total Trades: {ts.get('total_trades', 0)}")
        log.info(f"  Closed Trades: {ts.get('closed_trades', 0)}")
        log.info(f"  Win Rate: {ts.get('win_rate', 0)*100:.1f}%")
        log.info(f"  Profit Factor: {ts.get('profit_factor', 0):.2f}")
        log.info(f"  Sharpe: {rm.get('sharpe_ratio', 0):.2f}")
        log.info(f"  Sortino: {rm.get('sortino_ratio', 0):.2f}")
        log.info(f"  Max DD: {rm.get('max_drawdown_pct', 0):.1f}%")
        log.info(f"  Volatility: {rm.get('annualized_volatility_pct', 0):.1f}%")
        log.info("=" * 55)
