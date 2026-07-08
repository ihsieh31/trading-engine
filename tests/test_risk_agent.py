from __future__ import annotations

import pytest
from interfaces_v2 import AgentProposal, PortfolioState, RiskAssessment


@pytest.fixture
def risk_agent():
    from agents.risk_agent import RiskAgent
    return RiskAgent()


def test_bear_regime_allows_sell(risk_agent):
    """熊市時 SELL 應該被允許出場，不該被擋。"""
    proposal = AgentProposal(
        agent_name="test", ticker="AAPL", rating="SELL",
        confidence=0.9, thesis="exit", price_target=None,
        time_horizon="short", key_risks=[], supporting_rules_used=[],
    )
    state = PortfolioState(
        positions={}, cash=100000, portfolio_value=100000,
        sector_exposure={}, regime="bear",
    )
    result = risk_agent.evaluate(proposal, state)
    assert result.approved is True, (
        f"SELL should be allowed in bear regime, got veto_reason={result.veto_reason}"
    )


def test_bear_regime_allows_hold(risk_agent):
    """熊市時 HOLD 應該被允許觀望。"""
    proposal = AgentProposal(
        agent_name="test", ticker="AAPL", rating="HOLD",
        confidence=0.6, thesis="wait", price_target=None,
        time_horizon="short", key_risks=[], supporting_rules_used=[],
    )
    state = PortfolioState(
        positions={}, cash=100000, portfolio_value=100000,
        sector_exposure={}, regime="bear",
    )
    result = risk_agent.evaluate(proposal, state)
    assert result.approved is True, (
        f"HOLD should be allowed in bear regime, got veto_reason={result.veto_reason}"
    )


def test_bear_regime_blocks_low_confidence_buy(risk_agent):
    """熊市時低信心(<0.85)的 BUY 應該被擋。"""
    proposal = AgentProposal(
        agent_name="test", ticker="AAPL", rating="BUY",
        confidence=0.5, thesis="buy low", price_target=200,
        time_horizon="short", key_risks=[], supporting_rules_used=[],
    )
    state = PortfolioState(
        positions={}, cash=100000, portfolio_value=100000,
        sector_exposure={}, regime="bear",
    )
    result = risk_agent.evaluate(proposal, state)
    assert result.approved is False
    assert "bear" in result.veto_reason.lower()


def test_bear_regime_allows_high_confidence_buy(risk_agent):
    """熊市時高信心(>=0.85)的 BUY 應該放行進入 Kelly 計算。"""
    proposal = AgentProposal(
        agent_name="test", ticker="AAPL", rating="BUY",
        confidence=0.9, thesis="strong setup", price_target=220,
        time_horizon="short", key_risks=[], supporting_rules_used=[],
    )
    state = PortfolioState(
        positions={}, cash=100000, portfolio_value=100000,
        sector_exposure={}, regime="bear",
    )
    # Should pass regime gate (may still fail on Kelly/sector/etc)
    result = risk_agent.evaluate(proposal, state)
    # The exact approval depends on Kelly calculation, but it should NOT
    # be vetoed with a regime reason
    if not result.approved:
        assert "bear" not in result.veto_reason.lower(), (
            f"Veto should not be regime-based for high conf BUY: {result.veto_reason}"
        )
