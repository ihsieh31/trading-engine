from __future__ import annotations
"""领域层接口定义 — 实现依赖反转，让领域逻辑不依赖基础设施。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Position:
    ticker: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    change_today: float


@dataclass
class AccountSummary:
    cash: float
    portfolio_value: float
    buying_power: float
    equity: float
    last_equity: float
    daytrade_count: int
    stale: bool = False


@dataclass
class OrderResult:
    order_id: str
    status: str
    client_id: str
    filled_qty: int = 0
    filled_avg_price: float = 0.0
    legs: list[dict] | None = None


class IPriceProvider(ABC):
    @abstractmethod
    def get_current_price(self, ticker: str) -> float | None:
        ...


class IAccountProvider(ABC):
    @abstractmethod
    def get_account_summary(self) -> AccountSummary:
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        ...


class IOrderExecutor(ABC):
    @abstractmethod
    def submit_market_order(
        self, ticker: str, side: str, qty: int, time_in_force: str = "day",
        bracket_sl: float | None = None, bracket_tp: float | None = None,
        client_order_id: str = "",
    ) -> OrderResult | None:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> dict | None:
        ...

    @abstractmethod
    def get_open_orders(self, ticker: str | None = None) -> list[dict]:
        ...


class ITradeRecorder(ABC):
    @abstractmethod
    def record_trade(self, ticker: str, side: str, qty: int, price: float,
                     client_id: str, reason: str = ""):
        ...

    @abstractmethod
    def get_trades(self, limit: int = 50) -> list[dict]:
        ...
