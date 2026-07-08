from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_db():
    import db
    db.init_db()


def test_start_creates_workflow():
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine()
    assert we.get_state()["current_state"] == "IDLE"
    assert we.workflow_id is not None


def test_screening_transition():
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine()
    we.start()
    we.advance("workflow.start")
    assert we.get_state()["current_state"] == "SCREENING"


def test_resume_previous_workflow():
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine()
    we.start()
    we.advance("workflow.start")
    wid = we.workflow_id

    we2 = WorkflowEngine()
    we2.resume(wid)
    assert we2.get_state()["current_state"] == "SCREENING"


def test_circuit_breaker_from_any_state():
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine()
    we.start()
    we.advance("workflow.start")
    we.advance("circuit_breaker.tripped")
    assert we.get_state()["current_state"] == "MONITORING"


def test_retry_returns_to_previous_state():
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine()
    we.start()
    we.advance("workflow.start")
    we._context["_previous_state"] = "DECISION"
    we._current_state = "FAILED_ORDER"
    we.retry("test")
    assert we.get_state()["current_state"] == "DECISION"


def test_full_cycle():
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine()
    we.start()
    we.advance("workflow.start")       # IDLE -> SCREENING
    we.advance("screener.candidates_ready")  # SCREENING -> ANALYZING
    assert we.get_state()["current_state"] == "ANALYZING"
