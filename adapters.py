from __future__ import annotations
"""基础设施层 — Alpaca / yfinance / FMP 适配器，实作 interfaces.py 定义的接口。"""

import logging
from datetime import datetime, timezone, timedelta

from interfaces import (
    IPriceProvider, IAccountProvider, IOrderExecutor,
    AccountSummary, Position, OrderResult,
)

log = logging.getLogger(__name__)


class PriceProvider(IPriceProvider):
    """多源价格提供器：Alpaca → FMP → yfinance。"""

    def __init__(self, alpaca_data_client=None):
        self._data_client = alpaca_data_client

    def get_current_price(self, ticker: str) -> float | None:
        # 1. Alpaca latest trade
        if self._data_client is not None:
            try:
                from alpaca.data.requests import StockLatestTradeRequest
                req = StockLatestTradeRequest(symbol_or_symbols=ticker)
                trade = self._data_client.get_stock_latest_trade(req)
                vals = trade.get(ticker)
                if vals:
                    return float(vals.price)
            except Exception as e:
                log.debug("Alpaca latest trade failed for %s: %s", ticker, e)
            try:
                from alpaca.data.requests import StockBarsRequest
                from alpaca.data import TimeFrame
                req = StockBarsRequest(
                    symbol_or_symbols=ticker,
                    timeframe=TimeFrame.Day,
                    start=datetime.now(timezone.utc) - timedelta(days=5),
                )
                df = self._data_client.get_stock_bars(req).df
                if not df.empty:
                    if ticker in df.columns:
                        return float(df[ticker].iloc[-1]["close"])
                    return float(df.loc[ticker].iloc[-1]["close"])
            except Exception as e:
                log.debug("Alpaca bars failed for %s: %s", ticker, e)

        # 2. FMP
        try:
            from fmp_client import get_price as fmp_price, available
            if available():
                p = fmp_price(ticker)
                if p and p > 0:
                    return p
        except Exception as e:
            log.debug("FMP price failed for %s: %s", ticker, e)

        # 3. yfinance (stale daily close — last resort)
        try:
            import yfinance as yf
            df = yf.download(ticker, period="2d", interval="1d", auto_adjust=True, progress=False)
            if not df.empty:
                return float(df["Close"].iloc[-1])
        except Exception as e:
            log.debug("yfinance failed for %s: %s", ticker, e)

        return None


class AccountProvider(IAccountProvider):
    """Alpaca 账户和持仓提供器。"""

    def __init__(self, trading_client=None):
        self._tc = trading_client
        self._last_known = None

    def get_account_summary(self) -> AccountSummary:
        if self._tc is None:
            return AccountSummary(cash=0, portfolio_value=0, buying_power=0,
                                  equity=0, last_equity=0, daytrade_count=0, stale=True)
        try:
            a = self._tc.get_account()
            result = AccountSummary(
                cash=float(a.cash),
                portfolio_value=float(a.portfolio_value),
                buying_power=float(a.buying_power),
                equity=float(a.equity),
                last_equity=float(a.last_equity),
                daytrade_count=int(a.daytrade_count),
            )
            self._last_known = result
            return result
        except Exception as e:
            log.error(f"get_account failed: {e}")
            if self._last_known:
                stale = AccountSummary(**{k: getattr(self._last_known, k) for k in
                                          ["cash", "portfolio_value", "buying_power",
                                           "equity", "last_equity", "daytrade_count"]})
                stale.stale = True
                return stale
            return AccountSummary(cash=0, portfolio_value=0, buying_power=0,
                                  equity=0, last_equity=0, daytrade_count=0, stale=True)

    def get_positions(self) -> dict[str, Position]:
        if self._tc is None:
            return {}
        try:
            pos_list = self._tc.get_all_positions()
            return {
                p.symbol: Position(
                    ticker=p.symbol,
                    qty=float(p.qty),
                    avg_entry_price=float(p.avg_entry_price),
                    current_price=float(p.current_price),
                    market_value=float(p.market_value),
                    cost_basis=float(p.cost_basis),
                    unrealized_pl=float(p.unrealized_pl),
                    unrealized_plpc=float(p.unrealized_plpc),
                    change_today=float(p.change_today),
                )
                for p in pos_list if abs(float(p.qty)) > 0.001
            }
        except Exception as e:
            log.error(f"get_positions failed: {e}")
            return {}


class OrderExecutor(IOrderExecutor):
    """Alpaca 订单执行器。"""

    def __init__(self, trading_client=None):
        self._tc = trading_client

    def submit_market_order(
        self, ticker: str, side: str, qty: int, time_in_force: str = "day",
        bracket_sl: float | None = None, bracket_tp: float | None = None,
        client_order_id: str = "",
    ) -> OrderResult | None:
        if self._tc is None or qty <= 0:
            return None
        try:
            from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
            from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

            side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
            tif = TimeInForce.GTC if time_in_force == "gtc" else TimeInForce.DAY

            if bracket_sl is not None or bracket_tp is not None:
                req = MarketOrderRequest(
                    symbol=ticker, qty=qty, side=side_enum,
                    time_in_force=tif, order_class=OrderClass.BRACKET,
                    take_profit=TakeProfitRequest(limit_price=bracket_tp) if bracket_tp else None,
                    stop_loss=StopLossRequest(stop_price=bracket_sl) if bracket_sl else None,
                    client_order_id=client_order_id or None,
                )
            else:
                req = MarketOrderRequest(
                    symbol=ticker, qty=qty, side=side_enum,
                    time_in_force=tif, client_order_id=client_order_id or None,
                )

            order = self._tc.submit_order(req)
            legs = []
            if hasattr(order, "legs") and order.legs:
                legs = [{"id": leg.id, "side": str(leg.side), "type": str(leg.type)} for leg in order.legs]
            return OrderResult(
                order_id=order.id,
                status=order.status.value if hasattr(order.status, "value") else str(order.status),
                client_id=client_order_id,
                legs=legs,
            )
        except Exception as e:
            log.error(f"Order failed: {ticker} {side} {qty}: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        if self._tc is None:
            return False
        try:
            self._tc.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            log.error(f"Cancel failed {order_id}: {e}")
            return False

    def get_order(self, order_id: str) -> dict | None:
        if self._tc is None:
            return None
        try:
            o = self._tc.get_order_by_id(order_id)
            return {
                "id": o.id, "symbol": o.symbol, "side": str(o.side),
                "qty": str(o.qty), "filled_qty": str(o.filled_qty),
                "filled_avg_price": str(o.filled_avg_price or "0"),
                "status": str(o.status), "type": str(o.type),
                "rejected_at": getattr(o, "rejected_at", ""),
            }
        except Exception as e:
            log.warning(f"get_order failed {order_id}: {e}")
            return None

    def get_open_orders(self, ticker: str | None = None) -> list[dict]:
        if self._tc is None:
            return []
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            params = {"status": QueryOrderStatus.OPEN}
            if ticker:
                params["symbols"] = [ticker]
            orders = self._tc.get_orders(GetOrdersRequest(**params))
            return [
                {"id": o.id, "symbol": o.symbol, "side": str(o.side),
                 "qty": str(o.qty), "filled_qty": str(o.filled_qty),
                 "status": str(o.status), "type": str(o.type),
                 "order_class": str(getattr(o, "order_class", "")),
                 "leg": {"id": getattr(o, "leg_id", "")}}
                for o in orders
            ]
        except Exception as e:
            log.warning(f"get_open_orders failed: {e}")
            return []
