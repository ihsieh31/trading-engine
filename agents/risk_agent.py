from __future__ import annotations

import logging
from typing import Any

from interfaces_v2 import IRiskAgent, AgentProposal, PortfolioState, RiskAssessment
from portfolio_manager import PortfolioManager
from sector_map import get_sector

log = logging.getLogger(__name__)


class RiskAgent(IRiskAgent):
    def __init__(self, portfolio_manager=None, config=None, name="risk"):
        self._pm = portfolio_manager or PortfolioManager()
        self._config = config
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, proposal: AgentProposal, portfolio_state: PortfolioState) -> RiskAssessment:
        ticker = proposal.ticker
        portfolio_value = portfolio_state.portfolio_value or 1
        positions = portfolio_state.positions or {}
        regime = portfolio_state.regime

        # 1. Regime gating
        # Bear regime: restrict new BUY entries (unless very high confidence),
        # but allow SELL/HOLD (exit/hold actions are fine in a bear market).
        if regime == "bear" and proposal.rating == "BUY":
            if proposal.confidence < 0.85:
                return RiskAssessment(
                    ticker=ticker, approved=False, position_pct=0.0,
                    kelly_pct=0.0, sector_exposure_pct=0.0,
                    veto_reason="Bear regime restricts new BUY entries unless very high confidence",
                )

        # 2. Kelly-based position size
        kelly_inputs = self._pm.get_kelly_inputs()
        kelly_pct = PortfolioManager.compute_kelly_pct(
            kelly_inputs["win_rate"], kelly_inputs["avg_win"], kelly_inputs["avg_loss"],
            kelly_fraction=self._pm.kelly_fraction,
            max_position_pct=self._pm.max_position_pct,
            min_position_pct=self._pm.min_position_pct,
        )
        if kelly_pct <= 0 and proposal.rating == "BUY":
            return RiskAssessment(
                ticker=ticker, approved=False, position_pct=0.0,
                kelly_pct=0.0, sector_exposure_pct=0.0,
                veto_reason="Kelly calculation suggests no edge",
            )

        # 3. Position size limit
        max_pos_pct = self._pm.max_position_pct
        if proposal.rating == "BUY":
            proposed_pct = min(kelly_pct, max_pos_pct) * proposal.confidence
        else:
            proposed_pct = 0.0

        # 4. Sector exposure
        sector = get_sector(ticker)
        current_sector_exposure = portfolio_state.sector_exposure.get(sector, 0.0)
        if current_sector_exposure >= self._pm.max_sector_pct:
            return RiskAssessment(
                ticker=ticker, approved=False, position_pct=0.0,
                kelly_pct=kelly_pct, sector_exposure_pct=current_sector_exposure,
                veto_reason=f"Sector {sector} exposure {current_sector_exposure:.1%} >= limit {self._pm.max_sector_pct:.0%}",
            )

        # 5. Total exposure check
        current_total = sum(
            float(p.get("market_value", 0)) / portfolio_value
            for p in positions.values() if hasattr(p, "get")
        ) if positions else 0.0
        if current_total + proposed_pct > self._pm.max_total_exposure:
            return RiskAssessment(
                ticker=ticker, approved=False, position_pct=0.0,
                kelly_pct=kelly_pct, sector_exposure_pct=current_sector_exposure,
                veto_reason=f"Total exposure {current_total:.1%} + {proposed_pct:.1%} would exceed limit {self._pm.max_total_exposure:.0%}",
            )

        return RiskAssessment(
            ticker=ticker,
            approved=True,
            position_pct=proposed_pct,
            kelly_pct=kelly_pct,
            sector_exposure_pct=current_sector_exposure,
            veto_reason=None,
        )
