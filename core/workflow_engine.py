from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from event_bus import EventBus, BaseEvent

log = logging.getLogger(__name__)

# ── States ──────────────────────────────────────────────────────
IDLE = "IDLE"
SCREENING = "SCREENING"
ANALYZING = "ANALYZING"
ANALYZING_DEGRADED = "ANALYZING_DEGRADED"
RISK_REVIEW = "RISK_REVIEW"
DECISION = "DECISION"
MONITORING = "MONITORING"
EXECUTING_ENTRY = "EXECUTING_ENTRY"
EXECUTING_EXIT = "EXECUTING_EXIT"
FAILED_ORDER = "FAILED_ORDER"
REFLECTING = "REFLECTING"
HALTED = "HALTED"

ALL_STATES = frozenset({
    IDLE, SCREENING, ANALYZING, ANALYZING_DEGRADED,
    RISK_REVIEW, DECISION, MONITORING,
    EXECUTING_ENTRY, EXECUTING_EXIT, FAILED_ORDER,
    REFLECTING, HALTED,
})

# ── Transition Matrix ───────────────────────────────────────────
# (from_state, event_type) -> to_state
_TRANSITIONS: dict[tuple[str, str], str] = {
    (IDLE, "workflow.start"): SCREENING,
    (SCREENING, "screener.candidates_ready"): ANALYZING,
    (SCREENING, "screener.no_candidates"): IDLE,
    (ANALYZING, "analyst.batch_completed"): RISK_REVIEW,
    (ANALYZING, "system.health_degraded"): ANALYZING_DEGRADED,
    (ANALYZING_DEGRADED, "analyst.batch_completed"): RISK_REVIEW,
    (RISK_REVIEW, "risk.assessment_created"): DECISION,
    (DECISION, "chairman.decision_made"): MONITORING,
    (DECISION, "execution.entry_started"): EXECUTING_ENTRY,
    (EXECUTING_ENTRY, "order.entry_filled"): MONITORING,
    (EXECUTING_ENTRY, "order.failed"): FAILED_ORDER,
    (MONITORING, "signal.exit"): EXECUTING_EXIT,
    (MONITORING, "market.close"): REFLECTING,
    (EXECUTING_EXIT, "order.exit_filled"): REFLECTING,
    (EXECUTING_EXIT, "order.failed"): FAILED_ORDER,
    (FAILED_ORDER, "workflow.retry"): None,  # resolved dynamically
    (REFLECTING, "reflection.completed"): IDLE,
    (HALTED, "system.resume"): IDLE,
}

# Event types that accept any source state
_ANY_STATE_EVENTS = frozenset({"circuit_breaker.tripped"})

# Map: circuit_breaker.tripped target
_CIRCUIT_BREAKER_TARGET = MONITORING


class WorkflowEngine:
    def __init__(self, container=None):
        self._current_state = IDLE
        self._workflow_id = str(uuid.uuid4())
        self._trace_id = str(uuid.uuid4())
        self._context: dict[str, Any] = {}
        self._container = container
        self._halted = False
        self._bus = EventBus.get_instance()

    # ── Public API ──────────────────────────────────────────────

    def start(self, workflow_id: str = "") -> None:
        if workflow_id:
            self._workflow_id = workflow_id
            existing = self._load_state()
            if existing:
                self._current_state = existing.get("current_state", IDLE)
                self._context = existing.get("context", {})
                self._trace_id = existing.get("trace_id", self._trace_id)
                log.info("Resumed workflow %s at state %s", self._workflow_id, self._current_state)
                self._bus.emit(BaseEvent(
                    "workflow.state_changed",
                    payload={"from": "", "to": self._current_state, "workflow_id": self._workflow_id},
                    workflow_id=self._workflow_id,
                    trace_id=self._trace_id,
                ))
                return

        self._current_state = IDLE
        self._context = {}
        self._workflow_id = workflow_id or self._workflow_id
        self._trace_id = str(uuid.uuid4())
        self._halted = False
        self._save_state()
        self._bus.emit(BaseEvent(
            "workflow.state_changed",
            payload={"from": "", "to": self._current_state, "workflow_id": self._workflow_id},
            workflow_id=self._workflow_id,
            trace_id=self._trace_id,
        ))
        log.info("Started new workflow %s at %s", self._workflow_id, self._current_state)

    def advance(self, event: BaseEvent | str, payload: dict | None = None) -> None:
        if isinstance(event, str):
            event = BaseEvent(event_type=event, payload=payload or {},
                              workflow_id=self._workflow_id, trace_id=self._trace_id)

        event_type = event.event_type
        from_state = self._current_state

        # Circuit breaker: any state -> MONITORING or HALTED
        if event_type in _ANY_STATE_EVENTS:
            if event_type == "circuit_breaker.tripped":
                to_state = _CIRCUIT_BREAKER_TARGET
                self._halted = True
                self._transition(to_state, reason=f"circuit_breaker.tripped from {from_state}")
                return

        # workflow.retry: FAILED_ORDER -> previous stable state
        if event_type == "workflow.retry":
            if from_state != FAILED_ORDER:
                raise ValueError(f"workflow.retry not allowed from {from_state}")
            previous = self._context.get("_previous_state", IDLE)
            retry_count = self._context.get("_retry_count", 0) + 1
            self._context["_retry_count"] = retry_count
            self._transition(previous, reason=f"retry #{retry_count}")
            return

        # Look up static transition
        key = (from_state, event_type)
        if key not in _TRANSITIONS:
            raise ValueError(
                f"Invalid transition: {from_state} -> {event_type}"
            )

        to_state = _TRANSITIONS[key]

        # Handle dynamic target for workflow.retry
        if to_state is None and event_type == "workflow.retry":
            previous = self._context.get("_previous_state", IDLE)
            retry_count = self._context.get("_retry_count", 0) + 1
            self._context["_retry_count"] = retry_count
            self._transition(previous, reason=f"retry #{retry_count}")
            return

        if to_state is None:
            raise ValueError(f"Unresolved transition: {from_state} -> {event_type}")

        # Store previous state before transition for retry support
        self._context["_previous_state"] = from_state
        self._transition(to_state, reason=event_type)

    def get_state(self, workflow_id: str = "") -> dict:
        wid = workflow_id or self._workflow_id
        record = self._load_state(wid)
        if record:
            return {
                "workflow_id": record["id"],
                "current_state": record.get("current_state", IDLE),
                "context": record.get("context", {}),
                "trace_id": record.get("trace_id", ""),
                "created_at": record.get("created_at", ""),
                "updated_at": record.get("updated_at", ""),
            }
        return {
            "workflow_id": self._workflow_id,
            "current_state": self._current_state,
            "context": dict(self._context),
            "trace_id": self._trace_id,
        }

    def retry(self, workflow_id: str, step: str = "") -> None:
        if self._current_state != FAILED_ORDER:
            log.warning("retry called but current state is %s (not FAILED_ORDER)", self._current_state)
        previous = self._context.get("_previous_state", IDLE)
        retry_count = self._context.get("_retry_count", 0) + 1
        self._context["_retry_count"] = retry_count
        if step:
            self._context["_retry_step"] = step
        log.info("Retrying workflow %s from %s (attempt %d)", workflow_id, previous, retry_count)
        self._transition(previous, reason=f"retry #{retry_count}")

    def resume(self, workflow_id: str) -> None:
        record = self._load_state(workflow_id)
        if record is None:
            raise ValueError(f"Workflow {workflow_id} not found in database")
        self._workflow_id = record["id"]
        self._current_state = record.get("current_state", IDLE)
        self._context = record.get("context", {})
        self._trace_id = record.get("trace_id", str(uuid.uuid4()))
        self._halted = False
        log.info("Resumed workflow %s at state %s", self._workflow_id, self._current_state)

    # ── Internal ────────────────────────────────────────────────

    def _transition(self, to_state: str, reason: str = "") -> None:
        from_state = self._current_state
        if not self._is_valid_transition(from_state, to_state):
            valid_targets = self._valid_targets(from_state)
            raise ValueError(
                f"Invalid transition: {from_state} -> {to_state}. "
                f"Valid targets from {from_state}: {valid_targets}"
            )

        self._current_state = to_state
        self._save_state()
        self._bus.emit(BaseEvent(
            "workflow.state_changed",
            payload={
                "from": from_state,
                "to": to_state,
                "reason": reason,
                "workflow_id": self._workflow_id,
            },
            workflow_id=self._workflow_id,
            trace_id=self._trace_id,
        ))
        log.info("Workflow %s: %s -> %s (%s)", self._workflow_id, from_state, to_state, reason)

    def _is_valid_transition(self, from_state: str, to_state: str) -> bool:
        if from_state not in ALL_STATES:
            return False
        if to_state not in ALL_STATES:
            return False
        return to_state in self._valid_targets(from_state)

    def _valid_targets(self, from_state: str) -> set[str]:
        targets: set[str] = set()
        for (fs, evt), ts in _TRANSITIONS.items():
            if fs == from_state and ts is not None:
                targets.add(ts)
        # circuit_breaker.tripped goes to MONITORING from any state
        targets.add(_CIRCUIT_BREAKER_TARGET)
        # retry from FAILED_ORDER -> previous state
        if from_state == FAILED_ORDER:
            prev = self._context.get("_previous_state", IDLE)
            if prev in ALL_STATES:
                targets.add(prev)
        return targets

    # ── Persistence ─────────────────────────────────────────────

    def _save_state(self) -> None:
        try:
            import db
            existing = self._load_state()
            created_at = existing.get("created_at") if existing else datetime.now(timezone.utc).isoformat()
            db.save_workflow({
                "id": self._workflow_id,
                "current_state": self._current_state,
                "context": dict(self._context),
                "trace_id": self._trace_id,
                "created_at": created_at,
            })
        except Exception as exc:
            log.debug("Failed to save workflow state: %s", exc)

    def _load_state(self, workflow_id: str = "") -> dict | None:
        wid = workflow_id or self._workflow_id
        try:
            import db
            return db.load_workflow(wid)
        except Exception as exc:
            log.debug("Failed to load workflow %s: %s", wid, exc)
            return None

    # ── Properties ──────────────────────────────────────────────

    @property
    def context(self) -> dict[str, Any]:
        return self._context

    @property
    def workflow_id(self) -> str:
        return self._workflow_id

    @property
    def trace_id(self) -> str:
        return self._trace_id
