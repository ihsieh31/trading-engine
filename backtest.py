"""回測模組 — 可插拔策略，用 yfinance 歷史數據驗證交易邏輯。"""

from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal
from config import Config

import numpy as np
import yfinance as yf
from pandas import DataFrame, Series

from portfolio_manager import PortfolioManager

log = logging.getLogger(__name__)
cfg = Config()
DATA_DIR = cfg.DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Backtest Strategy ─────────────────────────────────────────

@dataclass
class BacktestSignal:
    action: Literal["buy", "sell", "hold"]
    qty: int = 0  # 0 = all (for sell)
    reason: str = ""  # e.g. "SL", "TP", "MA_exit"


class BacktestStrategy(ABC):
    """回測用策略介面 — 每根 K 線呼叫一次 on_bar()。"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def on_bar(self, date: str, close: float, high: float, low: float,
               volume: float, position: int, entry_price: float, cash: float,
               closed_trades: list[float], lookback_close: Series, **kwargs) -> BacktestSignal:
        ...


class MA20CrossStrategy(BacktestStrategy):
    """MA20 金叉買入，跌破 MA20 賣出，搭配止損/獲利。"""

    def __init__(self, stop_loss_pct: float | None = None, take_profit_pct: float | None = None):
        self._sl_pct = stop_loss_pct or cfg.STOP_LOSS_PCT
        self._tp_pct = take_profit_pct or cfg.TAKE_PROFIT_PCT

    @property
    def name(self) -> str:
        return "ma20_cross"

    def on_bar(self, date: str, close: float, high: float, low: float,
               volume: float, position: int, entry_price: float, cash: float,
               closed_trades: list[float], lookback_close: Series, **kwargs) -> BacktestSignal:
        if len(lookback_close) < 20:
            return BacktestSignal("hold")

        ma20 = lookback_close.iloc[-20:].mean()

        if position == 0:
            if close > ma20:
                kelly_pct = self._backtest_kelly(closed_trades)
                alloc = cash * kelly_pct
                qty = int(alloc / close)
                if qty > 0:
                    return BacktestSignal("buy", qty, "MA20_breakout")
        else:
            if close <= entry_price * (1 - self._sl_pct):
                return BacktestSignal("sell", 0, "SL")
            if close >= entry_price * (1 + self._tp_pct):
                return BacktestSignal("sell", 0, "TP")
            if close < ma20:
                return BacktestSignal("sell", 0, "MA20_exit")

        return BacktestSignal("hold")

    @staticmethod
    def _backtest_kelly(closed_trades: list[float]) -> float:
        if len(closed_trades) < 5:
            return cfg.MAX_POSITION_PCT * 0.5
        wins = [t for t in closed_trades if t > 0]
        losses = [t for t in closed_trades if t <= 0]
        win_rate = len(wins) / len(closed_trades)
        avg_win = float(np.mean(wins)) / 100.0 if wins else 0.01
        avg_loss = float(abs(np.mean(losses))) / 100.0 if losses else 0.01
        return PortfolioManager.compute_kelly_pct(win_rate, avg_win, avg_loss)


# ── Backtest Engine ────────────────────────────────────────────

@dataclass
class BacktestResult:
    ticker: str
    initial_capital: float = 0
    final_value: float = 0
    total_return_pct: float = 0
    total_trades: int = 0
    trades: list[dict] = field(default_factory=list)
    error: str = ""


class BacktestEngine:
    """回測引擎 — 用歷史資料模擬策略。"""

    def __init__(self, strategy: BacktestStrategy | None = None):
        self._strategy = strategy or MA20CrossStrategy()

    @property
    def strategy(self) -> BacktestStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, s: BacktestStrategy):
        self._strategy = s

    def run(self, ticker: str, start_date: str, end_date: str,
            initial_capital: float | None = None) -> BacktestResult:
        result = BacktestResult(ticker=ticker)
        capital = initial_capital or cfg.INITIAL_CAPITAL
        result.initial_capital = capital

        try:
            data = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True, progress=False)
            if data.empty or len(data) < 21:
                result.error = "Insufficient data"
                return result

            close_col = data["Close"]
            high_col = data["High"]
            low_col = data["Low"]
            vol_col = data["Volume"]
            if isinstance(close_col, DataFrame) and ticker in close_col.columns:
                close_col = close_col[ticker]
                high_col = high_col[ticker] if ticker in high_col.columns else high_col
                low_col = low_col[ticker] if ticker in low_col.columns else low_col
                vol_col = vol_col[ticker] if ticker in vol_col.columns else vol_col

            cash = capital
            position = 0
            entry_price = 0
            trades: list[dict] = []
            closed_trades: list[float] = []

            for i in range(20, len(data)):
                date_str = str(data.index[i].date())
                close = float(close_col.iloc[i])
                high = float(high_col.iloc[i])
                low = float(low_col.iloc[i])
                volume = float(vol_col.iloc[i])
                lookback = close_col.iloc[:i + 1]

                signal = self._strategy.on_bar(
                    date=date_str, close=close, high=high, low=low,
                    volume=volume, position=position, entry_price=entry_price,
                    cash=cash, closed_trades=closed_trades,
                    lookback_close=lookback,
                )

                if signal.action == "buy" and position == 0 and signal.qty > 0:
                    cash -= signal.qty * close
                    position = signal.qty
                    entry_price = close
                    trades.append({"action": "BUY", "price": round(close, 2), "date": date_str})

                elif signal.action == "sell" and position > 0:
                    sell_qty = signal.qty if signal.qty > 0 else position
                    cash += sell_qty * close
                    pnl_pct = (close - entry_price) / entry_price * 100
                    closed_trades.append(pnl_pct)
                    label = signal.reason.upper() if signal.reason else "SELL"
                    trades.append({"action": label, "price": round(close, 2), "date": date_str})
                    position -= sell_qty
                    if position <= 0:
                        position = 0
                        entry_price = 0

            final_value = cash + position * float(close_col.iloc[-1])
            result.final_value = round(final_value, 2)
            result.total_return_pct = round((final_value - capital) / capital * 100, 2)
            result.total_trades = len(trades)
            result.trades = trades[:20]

        except Exception as e:
            result.error = str(e)

        return result


# ── High-level runner (backward-compatible) ────────────────────

def backtest_ticker(ticker: str, start_date: str, end_date: str, strategy: BacktestStrategy | None = None) -> dict:
    """對單一標的回測（相容舊 API）。"""
    engine = BacktestEngine(strategy)
    result = engine.run(ticker, start_date, end_date)
    if result.error:
        return {"error": result.error}
    return {
        "initial_capital": result.initial_capital,
        "final_value": result.final_value,
        "total_return_pct": result.total_return_pct,
        "total_trades": result.total_trades,
        "trades": result.trades,
    }


def run_backtest(strategy: BacktestStrategy | None = None):
    """執行完整回測。"""
    watchlist = cfg.WATCHLIST
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    results = {}
    for ticker in watchlist:
        log.info(f"Backtesting {ticker}...")
        results[ticker] = backtest_ticker(ticker, start_date, end_date, strategy)

    output_path = cfg.DATA_DIR / "backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    log.info(f"Backtest complete. Results: {output_path}")
    for ticker, r in results.items():
        if "error" in r:
            log.warning(f"[{ticker}] Error: {r['error']}")
        else:
            log.info(f"[{ticker}] Return: {r['total_return_pct']:.2f}% | Trades: {r['total_trades']}")


if __name__ == "__main__":
    run_backtest()
