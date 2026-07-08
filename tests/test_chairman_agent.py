from __future__ import annotations

import pytest
from interfaces_v2 import AgentProposal, RiskAssessment, ChairmanDecision


@pytest.fixture(autouse=True)
def _ensure_db():
    import db
    db.init_db()


class FakeMemoryService:
    SEMANTIC = "semantic"

    def __init__(self, rules=None):
        self._rules = rules or []

    def query(self, query, tier=None, **kwargs):
        return self._rules


def test_empty_proposals_returns_hold():
    from agents.chairman_agent import ChairmanAgent
    ca = ChairmanAgent(memory_service=FakeMemoryService())
    decision = ca.decide([])
    assert decision.final_action == "HOLD"
    assert decision.conflict_resolution == "none"


def test_single_proposal_wins():
    from agents.chairman_agent import ChairmanAgent
    ca = ChairmanAgent(memory_service=FakeMemoryService())
    proposals = [
        AgentProposal("a1", "AAPL", "BUY", 0.9, "good", 200, "short", [], []),
    ]
    decision = ca.decide(proposals)
    assert decision.final_action == "BUY"
    assert decision.conflict_resolution == "weighted_vote"
    assert len(decision.vote_breakdown) == 1


def test_weighted_vote_majority():
    from agents.chairman_agent import ChairmanAgent
    ca = ChairmanAgent(memory_service=FakeMemoryService())
    proposals = [
        AgentProposal("a1", "AAPL", "BUY", 0.9, "good", 200, "short", [], []),
        AgentProposal("a2", "AAPL", "BUY", 0.8, "also good", 210, "short", [], []),
        AgentProposal("a3", "AAPL", "HOLD", 0.5, "unsure", None, "short", [], []),
    ]
    decision = ca.decide(proposals)
    assert decision.final_action == "BUY"
    assert decision.conflict_resolution == "weighted_vote"


def test_risk_veto_overrides_vote():
    from agents.chairman_agent import ChairmanAgent
    ca = ChairmanAgent(memory_service=FakeMemoryService())
    proposals = [
        AgentProposal("a1", "AAPL", "BUY", 0.9, "good", 200, "short", [], []),
    ]
    risk = RiskAssessment("AAPL", approved=False, position_pct=0.0,
                          kelly_pct=0.0, sector_exposure_pct=0.0,
                          veto_reason="Sector limit exceeded")
    decision = ca.decide(proposals, risk)
    assert decision.final_action == "HOLD"
    assert decision.conflict_resolution == "risk_veto"
    assert "Sector" in decision.rationale


def test_rule_override_when_high_conf_rule_matches():
    from agents.chairman_agent import ChairmanAgent
    fake_memory = FakeMemoryService(rules=[
        {"confidence": 0.9, "content": "avoid AAPL during earnings week", "title": "No AAPL earnings"},
    ])
    ca = ChairmanAgent(memory_service=fake_memory)
    proposals = [
        AgentProposal("a1", "AAPL", "BUY", 0.9, "good", 200, "short", [], []),
    ]
    decision = ca.decide(proposals)
    assert decision.final_action == "HOLD", (
        f"Rule override should force HOLD, got {decision.final_action}"
    )
    assert decision.conflict_resolution == "rule_override", (
        f"Should be rule_override, got {decision.conflict_resolution}"
    )


def test_rule_override_not_triggered_with_low_conf_rule():
    from agents.chairman_agent import ChairmanAgent
    fake_memory = FakeMemoryService(rules=[
        {"confidence": 0.3, "content": "avoid AAPL", "title": "Low conf rule"},
    ])
    ca = ChairmanAgent(memory_service=fake_memory)
    proposals = [
        AgentProposal("a1", "AAPL", "BUY", 0.9, "good", 200, "short", [], []),
    ]
    decision = ca.decide(proposals)
    # Low confidence rule (< 0.8) should NOT trigger override
    assert decision.final_action == "BUY", (
        f"Low conf rule should not override, got {decision.final_action}"
    )
