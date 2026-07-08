from __future__ import annotations
"""訂單生命週期管理 — 提交確認 / partial fill 處理 / retry / cancel-replace / bracket order。"""

import json
import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from file_utils import atomic_write_json
from config import Config
from event_bus import EventBus
from adapters import PriceProvider
import db

from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, TakeProfitRequest, StopLossRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, OrderClass, QueryOrderStatus

log = logging.getLogger(__name__)


@dataclass
class OrderRecord:
    client_id: str
    ticker: str
    side: str
    qty_requested: int
    qty_filled: int = 0
    status: str = "pending"
    alpaca_order_id: str = ""
    avg_fill_price: float = 0.0
    reason: str = ""
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    error: str = ""
    bracket: bool = False
    bracket_sl: float | None = None
    bracket_tp: float | None = None
    reference_price: float = 0.0
    sl_order_id: str = ""
    tp_order_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Status Constants ──────────────────────────────────────────
TERMINAL_STATUSES = {"filled", "canceled", "failed", "expired"}
OPEN_STATUSES = {"submitted", "partially_filled", "accepted", "new"}


class OrderManager:
    """訂單生命週期管理。

    責任：
    - 送出訂單並追蹤狀態
    - 定時檢查 fill status
    - 處理 partial fill：若 N 秒後仍未完全成交則取消餘額
    - 失敗 retry（最多 MAX_RETRIES 次）
    - EOD 取消所有未成交 DAY 訂單
    - 支援 bracket order（同時送出止損/獲利）
    - 所有狀態持久化到 orders.json
    """

    def __init__(self, trading_client, price_fn=None, config=None):
        cfg = config or Config()
        self.tc = trading_client
        self._cfg = cfg
        self._lock = threading.Lock()
        self._orders: dict[str, OrderRecord] = {}
        self._price_fn = price_fn or PriceProvider().get_current_price
        self.MAX_RETRIES = cfg.ORDER_MAX_RETRIES
        self.RETRY_DELAY_SEC = cfg.ORDER_RETRY_DELAY_SEC
        self.FILL_TIMEOUT_SEC = cfg.ORDER_FILL_TIMEOUT_SEC
        self.USE_FRACTIONAL_SHARES = cfg.USE_FRACTIONAL_SHARES
        self._bus = EventBus.get_instance()
        self._load_orders()

    # ── Persistence ────────────────────────────────────────

    def _orders_path(self) -> Path:
        return self._cfg.DATA_DIR / "orders.json"

    def _load_orders(self):
        # Primary source: SQLite
        try:
            db.init_db()
            db_records = db.load_orders()
            self._orders = {}
            for k, v in db_records.items():
                try:
                    self._orders[k] = OrderRecord(**v)
                except TypeError:
                    # Fallback: try from_dict for older records with extra fields
                    try:
                        self._orders[k] = OrderRecord.from_dict(v)
                    except Exception:
                        log.warning(f"Failed to parse order record {k}, skipping")
            if self._orders:
                log.info(f"Loaded {len(self._orders)} orders from SQLite")
                return
        except Exception as e:
            log.warning(f"Failed to load orders from SQLite: {e}")

        # Fallback: JSON file
        path = self._orders_path()
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                self._orders = {k: OrderRecord.from_dict(v) for k, v in raw.items()}
                log.info(f"Loaded {len(self._orders)} orders from JSON fallback")
            except Exception as e:
                log.warning(f"Failed to load orders from JSON: {e}")

    def _save_orders(self):
        # Primary: SQLite (fast, transactional)
        for rec in self._orders.values():
            try:
                db.save_order(rec.to_dict())
            except Exception as e:
                log.warning(f"db.save_order failed: {e}")

        # Backup: JSON file (human-readable, offline access)
        raw = {k: v.to_dict() for k, v in self._orders.items()}
        try:
            atomic_write_json(self._orders_path(), raw)
        except Exception as e:
            log.warning(f"Failed to save orders to JSON: {e}")

    def _next_client_id(self) -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
        return f"ord_{ts}"

    # ── Submit ─────────────────────────────────────────────

    def submit_market_order(
        self,
        ticker: str,
        side: OrderSide,
        qty: int | float,
        reason: str = "",
        bracket_sl: float = None,
        bracket_tp: float = None,
        reference_price: float = 0.0,
    ) -> OrderRecord | None:
        if qty <= 0:
            return None
        if not self.USE_FRACTIONAL_SHARES:
            qty = int(qty)

        client_id = self._next_client_id()
        record = OrderRecord(
            client_id=client_id,
            ticker=ticker,
            side=side.value,
            qty_requested=qty,
            reason=reason,
            created_at=datetime.now(timezone.utc).isoformat(),
            bracket=(bracket_sl is not None or bracket_tp is not None),
            bracket_sl=bracket_sl,
            bracket_tp=bracket_tp,
            reference_price=reference_price,
        )

        try:
            if bracket_sl is not None or bracket_tp is not None:
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    take_profit=TakeProfitRequest(limit_price=bracket_tp) if bracket_tp else None,
                    stop_loss=StopLossRequest(stop_price=bracket_sl) if bracket_sl else None,
                    client_order_id=client_id,
                )
            else:
                req = MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=client_id,
                )

            order = self.tc.submit_order(req)
            record.alpaca_order_id = order.id
            record.status = "submitted"
            record.updated_at = datetime.now(timezone.utc).isoformat()

            if hasattr(order, "legs") and order.legs:
                for leg in order.legs:
                    if leg.side == OrderSide.SELL and leg.type in ("stop", "stop_limit"):
                        record.sl_order_id = leg.id
                    elif leg.side == OrderSide.SELL and leg.type == "limit":
                        record.tp_order_id = leg.id
                if record.sl_order_id or record.tp_order_id:
                    log.info(f"[{ticker}] Stored bracket leg IDs: sl={record.sl_order_id or '—'}, tp={record.tp_order_id or '—'}")

            log.info(f"ORDER SUBMITTED: {side.value} {qty}x {ticker} | ID={order.id} | {reason}")
            self._bus.emit("order_submitted", {
                "ticker": ticker, "side": side.value, "qty": qty,
                "order_id": order.id, "client_id": client_id, "reason": reason,
                "bracket_sl": bracket_sl, "bracket_tp": bracket_tp,
            })

        except Exception as e:
            record.status = "failed"
            record.error = str(e)
            record.updated_at = datetime.now(timezone.utc).isoformat()
            log.error(f"ORDER FAILED: {side.value} {qty}x {ticker}: {e}")
            self._bus.emit("order_failed", {
                "ticker": ticker, "side": side.value, "qty": qty,
                "client_id": client_id, "reason": reason, "error": str(e),
            })

        with self._lock:
            self._orders[client_id] = record
            self._save_orders()
        return record

    # ── Status Check ───────────────────────────────────────

    def check_order_status(self, client_id: str) -> OrderRecord | None:
        with self._lock:
            record = self._orders.get(client_id)
        if record is None:
            return None

        if record.status in TERMINAL_STATUSES:
            return record

        try:
            order = self.tc.get_order_by_id(record.alpaca_order_id)
            new_status = order.status.value
            filled_qty = int(float(order.filled_qty))
            cumulative_avg_price = float(order.filled_avg_price) if order.filled_avg_price else 0.0

            prev_filled = record.qty_filled
            prev_avg_price = record.avg_fill_price
            delta = filled_qty - prev_filled

            if delta > 0:
                if prev_filled > 0 and prev_avg_price > 0:
                    incremental_price = (
                        (filled_qty * cumulative_avg_price - prev_filled * prev_avg_price) / delta
                    )
                else:
                    incremental_price = cumulative_avg_price
                self._record_trade(record, incremental_price, delta)

            record.qty_filled = filled_qty
            record.avg_fill_price = cumulative_avg_price if cumulative_avg_price > 0 else record.avg_fill_price
            record.status = new_status
            record.updated_at = datetime.now(timezone.utc).isoformat()

            if new_status == "filled":
                ref = record.reference_price
                slippage = ""
                if ref > 0 and cumulative_avg_price > 0:
                    slippage_pct = (cumulative_avg_price - ref) / ref * 100
                    slippage = f" | slippage={slippage_pct:+.2f}%"
                log.info(f"ORDER FILLED: {record.side} {filled_qty}x {record.ticker} @ ${cumulative_avg_price:.2f}{slippage}")
                self._bus.emit("order_filled", {
                    "ticker": record.ticker, "side": record.side,
                    "qty": filled_qty, "price": cumulative_avg_price,
                    "client_id": client_id, "order_id": record.alpaca_order_id,
                })
            elif new_status == "partially_filled":
                log.info(f"ORDER PARTIAL: {record.side} {filled_qty}/{record.qty_requested}x {record.ticker} @ ${cumulative_avg_price:.2f}")
            elif new_status in ("rejected", "canceled", "expired"):
                log.warning(f"ORDER {new_status.upper()}: {record.side} {record.ticker} | {order.rejected_at or ''}")
                self._bus.emit("order_rejected", {
                    "ticker": record.ticker, "side": record.side,
                    "client_id": client_id, "status": new_status,
                })

            with self._lock:
                self._orders[client_id] = record
                self._save_orders()

        except Exception as e:
            log.warning(f"check_order({client_id}) failed: {e}")

        return record

    # ── Partial Fill Handling ──────────────────────────────

    def handle_partial_fills(self):
        for cid in list(self._orders.keys()):
            self.check_order_status(cid)
            rec = self._get_record(cid)
            if not rec:
                continue

            if rec.status == "partially_filled":
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(rec.created_at)).total_seconds()
                if elapsed > self.FILL_TIMEOUT_SEC:
                    remaining = rec.qty_requested - rec.qty_filled
                    log.info(f"Partial fill timeout: cancelling {remaining}x {rec.ticker} remainder, retrying...")
                    self._retry_order(cid)

    # ── Cancel ─────────────────────────────────────────────

    def cancel_order(self, client_id: str):
        record = self._get_record(client_id)
        if record is None or record.status in TERMINAL_STATUSES:
            return
        try:
            self.tc.cancel_order_by_id(record.alpaca_order_id)
            self._update_record(client_id, status="canceled")
            log.info(f"ORDER CANCELLED: {record.client_id} ({record.ticker})")
        except Exception as e:
            log.error(f"Cancel failed for {client_id}: {e}")

    def _get_record(self, client_id: str) -> OrderRecord | None:
        with self._lock:
            rec = self._orders.get(client_id)
            if rec:
                return OrderRecord(**rec.to_dict())
            return None

    def _update_record(self, client_id: str, **kwargs):
        with self._lock:
            rec = self._orders.get(client_id)
            if rec is None:
                return
            for k, v in kwargs.items():
                if hasattr(rec, k):
                    setattr(rec, k, v)
            rec.updated_at = datetime.now(timezone.utc).isoformat()
            self._save_orders()

    # ── Retry ──────────────────────────────────────────────

    def _retry_order(self, client_id: str):
        record = self._get_record(client_id)
        if record is None or record.retry_count >= self.MAX_RETRIES:
            log.warning(f"Max retries reached for {client_id}")
            return
        if record.status == "filled":
            return

        if record.bracket:
            self.cancel_bracket_children(record.ticker)

        try:
            self.tc.cancel_order_by_id(record.alpaca_order_id)
        except Exception as e:
            log.error(f"Cancel before retry failed for {client_id}: {e}")

        if record.bracket and record.qty_filled > 0 and record.avg_fill_price > 0:
            sl_pct = self._cfg.STOP_LOSS_PCT
            tp_pct = self._cfg.TAKE_PROFIT_PCT
            sl = round(record.avg_fill_price * (1 - sl_pct), 2)
            tp = round(record.avg_fill_price * (1 + tp_pct), 2)
            if not self.submit_protective_oco(record.ticker, record.qty_filled, sl, tp):
                log.error(f"[{record.ticker}] Retry前補保護單失敗,已成交{record.qty_filled}股暫無保護!")

        try:
            side_enum = OrderSide.BUY if record.side == "buy" else OrderSide.SELL
            qty = record.qty_requested - record.qty_filled
            if qty <= 0:
                return

            new_client_id = self._next_client_id()

            bracket_sl = bracket_tp = None
            if record.bracket_sl is not None or record.bracket_tp is not None:
                current_price = self._price_fn(record.ticker)
                if current_price and current_price > 0:
                    sl_pct = self._cfg.STOP_LOSS_PCT
                    tp_pct = self._cfg.TAKE_PROFIT_PCT
                    bracket_sl = round(current_price * (1 - sl_pct), 2)
                    bracket_tp = round(current_price * (1 + tp_pct), 2)
                else:
                    bracket_sl = record.bracket_sl
                    bracket_tp = record.bracket_tp
                req = MarketOrderRequest(
                    symbol=record.ticker,
                    qty=qty,
                    side=side_enum,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    take_profit=TakeProfitRequest(limit_price=bracket_tp) if bracket_tp else None,
                    stop_loss=StopLossRequest(
                        stop_price=bracket_sl,
                    ) if bracket_sl else None,
                    client_order_id=new_client_id,
                )
            else:
                req = MarketOrderRequest(
                    symbol=record.ticker,
                    qty=qty,
                    side=side_enum,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=new_client_id,
                )

            order = self.tc.submit_order(req)

            with self._lock:
                existing = self._orders.get(client_id)
                if existing is None:
                    return
                existing.retry_count += 1
                existing.alpaca_order_id = order.id
                existing.status = "submitted"
                existing.error = ""
                now = datetime.now(timezone.utc).isoformat()
                existing.updated_at = now
                self._save_orders()

            log.info(f"Retry #{existing.retry_count} for {record.ticker}: new order {order.id}")

        except Exception as e:
            log.error(f"Retry failed for {client_id}: {e}")
            with self._lock:
                rec = self._orders.get(client_id)
                if rec is not None:
                    rec.error = f"Retry failed: {e}"
                    rec.status = "failed"
                    rec.updated_at = datetime.now(timezone.utc).isoformat()
                    self._save_orders()

    def cancel_bracket_children(self, ticker: str) -> int:
        """取消 ticker 所有殘留的 bracket 保護子單（止損/停利），包含已儲存 ID 與啟發式掃描。"""
        cancelled = 0

        # Phase 1: 精確取消 — 用儲存在 OrderRecord 中的 leg IDs
        for rec in self._orders.values():
            if rec.ticker != ticker:
                continue
            for leg_id in (rec.sl_order_id, rec.tp_order_id):
                if not leg_id:
                    continue
                try:
                    self.tc.cancel_order_by_id(leg_id)
                    cancelled += 1
                    log.info(f"[{ticker}] Cancelled stored bracket leg {leg_id}")
                except Exception as e:
                    log.debug(f"[{ticker}] Stored leg {leg_id} already filled/cancelled: {e}")

        # Phase 2: 啟發式掃描 — 取消可能殘留的 bracket 子單（未被記錄的）
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[ticker])
            open_orders = self.tc.get_orders(req)
            for o in open_orders:
                # Only cancel SIMPLE orders that are stop/limit AND were created recently (within 60s of parent)
                if o.order_class != OrderClass.SIMPLE:
                    continue
                if o.type not in ("stop", "stop_limit", "limit"):
                    continue
                # Heuristic: skip orders older than 60s (likely user-placed manual orders)
                try:
                    created = datetime.fromisoformat(o.created_at.replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - created).total_seconds() > 60:
                        continue
                except (AttributeError, ValueError):
                    pass
                try:
                    self.tc.cancel_order_by_id(o.id)
                    cancelled += 1
                    log.info(f"[{ticker}] Cancelled orphan bracket leg {o.id} (type={o.type})")
                except Exception as e:
                    log.debug(f"[{ticker}] Orphan leg {o.id} cancel failed: {e}")
        except Exception as e:
            log.warning(f"[{ticker}] cancel_bracket_children phase 2 failed: {e}")

        if cancelled:
            self._bus.emit("order_cancelled", {"ticker": ticker, "count": cancelled})
        return cancelled

    def submit_protective_oco(self, ticker: str, qty: int, stop_price: float, limit_price: float) -> bool:
        """對既有庫存掛一組 OCO 保護單（止損 + 止利），不下進場單。

        回傳 True 表示至少成功送出一腳。
        """
        from alpaca.trading.requests import TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

        if qty <= 0:
            return False

        success = False
        try:
            req = MarketOrderRequest(
                symbol=ticker,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.OCO,
                take_profit=TakeProfitRequest(limit_price=limit_price),
                stop_loss=StopLossRequest(
                    stop_price=stop_price,
                ),
            )
            order = self.tc.submit_order(req)
            if order and order.id:
                log.info(f"[{ticker}] Protective OCO submitted: SL={stop_price}, TP={limit_price}")
                success = True
        except Exception as e:
            log.error(f"[{ticker}] Failed to submit protective OCO: {e}")

        if not success:
            from notifier import send_message
            send_message(f"🚨 [{ticker}] 保護單 (OCO SL={stop_price} TP={limit_price}) 下單失敗，請人工檢查！")

        return success

    def get_pending_buy_dollars(self) -> float:
        """計算尚未成交的 BUY 訂單總金額（用於曝險計算）。"""
        total = 0.0
        for rec in self._orders.values():
            if rec.side == "buy" and rec.status in ("submitted", "accepted", "new", "partially_filled"):
                remaining = rec.qty_requested - rec.qty_filled
                price = rec.avg_fill_price if rec.avg_fill_price > 0 else rec.reference_price
                if price > 0:
                    total += remaining * price
        return total

    def cancel_all_open(self):
        for cid, rec in list(self._orders.items()):
            if rec.status in OPEN_STATUSES:
                self.cancel_order(cid)

    # ── EOD Cleanup ────────────────────────────────────────

    def eod_cleanup(self):
        cancelled = 0
        for cid, rec in list(self._orders.items()):
            if rec.status in OPEN_STATUSES:
                self.cancel_order(cid)
                cancelled += 1
        if cancelled:
            log.info(f"EOD: cancelled {cancelled} open order(s)")

    # ── Order History ──────────────────────────────────────

    def get_open_orders(self) -> list[OrderRecord]:
        return [
            r for r in self._orders.values()
            if r.status in ("submitted", "partially_filled", "accepted", "new")
        ]

    def has_open_order(self, ticker: str) -> bool:
        for r in self._orders.values():
            if r.ticker == ticker and r.status in ("submitted", "partially_filled", "accepted", "new"):
                return True
        return False

    def get_order_summary(self) -> dict:
        statuses = {}
        for r in self._orders.values():
            statuses[r.status] = statuses.get(r.status, 0) + 1
        return {
            "total_orders": len(self._orders),
            "by_status": statuses,
        }

    # ── Trade Record ───────────────────────────────────────

    def _record_trade(self, record: OrderRecord, price: float, qty: int = 0):
        trade = {
            "time": datetime.now(timezone.utc).isoformat(),
            "ticker": record.ticker,
            "side": record.side,
            "qty": qty if qty > 0 else record.qty_filled,
            "price": price,
            "client_id": record.client_id,
            "alpaca_id": record.alpaca_order_id,
            "reason": record.reason,
        }
        path = self._cfg.DATA_DIR / "trades.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(trade) + "\n")
        try:
            db.save_trade(trade)
        except Exception as e:
            log.debug(f"db.save_trade failed: {e}")

        if record.side == "sell":
            self._enqueue_reflection(record, price, qty)

    def _enqueue_reflection(self, record: OrderRecord, price: float, qty: int):
        try:
            from reflection_agent import enqueue_reflection
            enqueue_reflection(record.ticker, record.side,
                               qty if qty > 0 else record.qty_filled,
                               price, record.reason)
        except Exception as e:
            log.debug(f"Enqueue reflection failed: {e}")

    # ── Periodic Maintenance ───────────────────────────────

    def maintenance_cycle(self):
        self.handle_partial_fills()
        for cid in list(self._orders.keys()):
            rec = self._get_record(cid)
            if not rec or rec.status not in ("submitted", "accepted", "new"):
                continue
            if rec.retry_count >= self.MAX_RETRIES:
                continue
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(rec.created_at)).total_seconds()
            if elapsed > self.FILL_TIMEOUT_SEC and rec.qty_filled == 0:
                self._retry_order(cid)
