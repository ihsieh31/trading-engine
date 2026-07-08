from __future__ import annotations
"""Event Bus V2 — 結構化、可持久化事件匯流排。

使用方式::

    bus = EventBus.get_instance()

    @bus.on("order.filled")
    def handler(event: BaseEvent):
        print(event.payload["ticker"], event.payload["qty"])

    bus.emit(BaseEvent("order.filled", {"ticker": "AAPL", "qty": 10}))
"""

import json
import uuid
import logging
from typing import Callable, Any
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger(__name__)

Handler = Callable[["BaseEvent"], None]


class BaseEvent:
    """結構化事件基底，所有事件統一格式。"""

    def __init__(self, event_type: str, payload: dict | None = None,
                 workflow_id: str = "", trace_id: str = "",
                 event_id: str = ""):
        self.event_id = event_id or str(uuid.uuid4())
        self.event_type = event_type
        self.occurred_at = datetime.now(timezone.utc).isoformat()
        self.workflow_id = workflow_id
        self.trace_id = trace_id
        self.payload = payload or {}

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "workflow_id": self.workflow_id,
            "trace_id": self.trace_id,
            "payload": self.payload,
        }


class EventBus:
    _instance: EventBus | None = None

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers: dict[str, list[Handler]] = defaultdict(list)
            cls._instance._persist_enabled = True
        return cls._instance

    def on(self, event: str, handler: Handler | None = None):
        if handler is not None:
            self._handlers[event].append(handler)
            return lambda: self._handlers[event].remove(handler)

        def decorator(fn: Handler) -> Callable[[], None]:
            self._handlers[event].append(fn)
            return lambda: self._handlers[event].remove(fn)

        return decorator

    def emit(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None:
        """發射事件。支援舊式 emit("event_name", data) 與新式 emit(BaseEvent(...))。"""
        if isinstance(event, str):
            event = BaseEvent(event_type=event, payload=data or {})

        # 持久化
        if self._persist_enabled:
            try:
                import db
                db.save_event(
                    event_type=event.event_type,
                    payload=event.payload,
                    event_id=event.event_id,
                    workflow_id=event.workflow_id,
                    trace_id=event.trace_id,
                )
            except Exception as e:
                log.debug(f"Event persist failed: {e}")

        # 同步呼叫 handler
        for handler in self._handlers.get(event.event_type, []):
            try:
                handler(event)
            except Exception as e:
                log.error(f"Event handler error for '{event.event_type}': {e}")

    def get_events(self, trace_id: str = "", event_type: str = "",
                   workflow_id: str = "", limit: int = 100) -> list[dict]:
        try:
            import db
            return db.get_events(trace_id=trace_id, event_type=event_type,
                                  workflow_id=workflow_id, limit=limit)
        except Exception:
            return []

    @classmethod
    def get_instance(cls) -> EventBus:
        return cls()

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
