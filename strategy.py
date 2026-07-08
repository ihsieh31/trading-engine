from __future__ import annotations
"""策略層 — 將交易決策邏輯抽離為可組合的策略物件。"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Any
from enum import Enum

log = logging.getLogger(__name__)


class Action(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class TradeSignal:
    ticker: str
    action: Action
    qty: int
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyContext:
    """提供策略所需的所有外部依賴與資料。"""
    positions: dict  # {ticker: {qty, avg_entry_price, current_price, ...}}
    ratings: dict    # {ticker: {rating, price_target, analyzed_at, ...}}
    regime: dict | None = None
    config: Any = None  # Config instance
    portfolio: Any = None   # PortfolioManager
    orders: Any = None      # OrderManager
    price_provider: Any = None  # IPriceProvider
    pending_buy_dollars: float = 0.0


class BaseStrategy(ABC):
    """交易策略基底。

    實作 generate_signals() 回傳 TradeSignal 列表。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def generate_signals(self, ctx: StrategyContext) -> list[TradeSignal]:
        ...


class RatingStrategy(BaseStrategy):
    """根據 Deep Analyzer 評級產生買賣訊號。"""

    @property
    def name(self) -> str:
        return "rating"

    def generate_signals(self, ctx: StrategyContext) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        regime = ctx.regime or {}
        portfolio = ctx.portfolio

        actions = portfolio.rebalance_targets(ctx.ratings, regime)
        for a in actions:
            signals.append(TradeSignal(
                ticker=a["ticker"],
                action=Action(a["action"]),
                qty=a["qty"],
                reason=a["reason"],
            ))
        return signals


class StopLossTakeProfitStrategy(BaseStrategy):
    """根據持倉成本檢查止損/停利。"""

    @property
    def name(self) -> str:
        return "sl_tp"

    def generate_signals(self, ctx: StrategyContext) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        if not ctx.config:
            return signals

        sl_pct = ctx.config.STOP_LOSS_PCT
        tp_pct = ctx.config.TAKE_PROFIT_PCT

        for ticker, pos in ctx.positions.items():
            entry = pos.get("avg_entry_price", 0)
            current = pos.get("current_price", 0)
            qty = abs(int(pos.get("qty", 0)))
            if entry <= 0 or current <= 0 or qty <= 0:
                continue

            if current <= entry * (1 - sl_pct):
                signals.append(TradeSignal(
                    ticker=ticker, action=Action.SELL, qty=qty,
                    reason="Stop Loss",
                    metadata={"entry": entry, "current": current, "threshold": entry * (1 - sl_pct)},
                ))
            elif current >= entry * (1 + tp_pct):
                signals.append(TradeSignal(
                    ticker=ticker, action=Action.SELL, qty=qty,
                    reason="Take Profit",
                    metadata={"entry": entry, "current": current, "threshold": entry * (1 + tp_pct)},
                ))

        return signals


class CompositeStrategy(BaseStrategy):
    """組合多個策略，匯總所有訊號。"""

    def __init__(self, strategies: list[BaseStrategy]):
        self._strategies = strategies

    @property
    def name(self) -> str:
        return "+".join(s.name for s in self._strategies)

    def add(self, strategy: BaseStrategy):
        self._strategies.append(strategy)

    def generate_signals(self, ctx: StrategyContext) -> list[TradeSignal]:
        all_signals: list[TradeSignal] = []
        for s in self._strategies:
            try:
                sigs = s.generate_signals(ctx)
                all_signals.extend(sigs)
                log.debug(f"Strategy '{s.name}' generated {len(sigs)} signal(s)")
            except Exception as e:
                log.error(f"Strategy '{s.name}' failed: {e}")
        return all_signals
