from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from config import Config
from interfaces_v2 import IChairmanAgent, AgentProposal, ChairmanDecision, RiskAssessment, IMemoryService
import db

log = logging.getLogger(__name__)


class ChairmanAgent(IChairmanAgent):
    def __init__(self, memory_service=None, config=None, name="chairman"):
        self._memory_service = memory_service
        self._config = config or Config()
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def decide(self, proposals: list[AgentProposal], risk_assessment: RiskAssessment | None = None) -> ChairmanDecision:
        if not proposals:
            return ChairmanDecision(
                ticker="", final_action="HOLD", confidence=0.0, position_pct=0.0,
                vote_breakdown=[], conflict_resolution="none",
                rationale="No proposals received",
            )

        ticker = proposals[0].ticker

        # Step 1: Calibrate confidence using rolling accuracy
        calibrated: list[tuple[AgentProposal, float, float]] = []
        for p in proposals:
            acc = db.get_agent_accuracy(p.agent_name, lookback=90)
            calibrated_conf = p.confidence * (0.5 + 0.5 * acc)
            calibrated.append((p, calibrated_conf, acc))

        # Step 2: Weighted vote aggregation
        weighted_scores: dict[str, float] = {}
        total_weight = 0.0
        vote_breakdown: list[dict] = []

        for p, conf, acc in calibrated:
            weight = conf
            total_weight += weight
            weighted_scores[p.rating] = weighted_scores.get(p.rating, 0.0) + weight
            vote_breakdown.append({
                "agent": p.agent_name,
                "rating": p.rating,
                "raw_confidence": p.confidence,
                "calibrated_confidence": round(conf, 3),
                "accuracy": round(acc, 3),
                "weight": round(weight, 3),
            })

        final_action = "HOLD"
        max_weight = 0.0
        for rating, w in weighted_scores.items():
            if w > max_weight:
                max_weight = w
                final_action = rating

        confidence = max_weight / total_weight if total_weight > 0 else 0.0
        conflict_resolution = "weighted_vote"
        rationale = f"Weighted vote: {dict(sorted(weighted_scores.items(), key=lambda x: -x[1]))}"

        # Step 3a: Rule override check — query semantic tier for rules
        if self._memory_service is not None:
            try:
                rules = self._memory_service.query(
                    f"ticker:{ticker} action:{final_action}",
                    tier=self._memory_service.SEMANTIC,
                )
                high_conf = [r for r in rules if r.get("confidence", 0) >= 0.8]
                if high_conf:
                    best = high_conf[0]
                    text = best.get("content", "") or best.get("title", "")
                    if any(w in text.lower() for w in ("avoid", "不追買", "不建立", "不進場", "wait", "hold")):
                        final_action = "HOLD"
                        conflict_resolution = "rule_override"
                        rationale = f"Rule override: {best.get('title', '')} — {text[:100]}"
            except Exception as e:
                log.warning(f"Rule override query failed: {e}")

        # Step 3b: Risk veto
        if risk_assessment is not None and not risk_assessment.approved:
            final_action = "HOLD"
            conflict_resolution = "risk_veto"
            rationale = f"Risk veto: {risk_assessment.veto_reason}"

        # Step 3c: LLM arbitration (last resort — only when vote is conflicted and close)
        if conflict_resolution == "weighted_vote" and len({p.rating for p in proposals}) > 1:
            if max_weight / total_weight < 0.6:
                llm_action = self._llm_arbitrate(proposals, ticker, weighted_scores)
                if llm_action:
                    final_action = llm_action
                    conflict_resolution = "llm_arbitration"
                    rationale = f"LLM arbitration: {final_action} (weighted vote was indecisive)"

        # Determine position_pct
        position_pct = 0.0
        if final_action == "BUY":
            position_pct = confidence * self._config.MAX_POSITION_PCT
            if risk_assessment is not None and risk_assessment.approved:
                position_pct = min(position_pct, risk_assessment.position_pct)

        return ChairmanDecision(
            ticker=ticker,
            final_action=final_action,
            confidence=confidence,
            position_pct=position_pct,
            vote_breakdown=vote_breakdown,
            conflict_resolution=conflict_resolution,
            rationale=rationale,
        )

    def _build_arbitration_prompt(
        self, proposals: list[AgentProposal], ticker: str, weighted_scores: dict[str, float]
    ) -> str:
        lines = [f"Agents disagree on {ticker}. Decide the final action (BUY/SELL/HOLD).\n"]
        lines.append("Votes:")
        for p in proposals:
            lines.append(f"  - {p.agent_name}: {p.rating} (conf={p.confidence}, thesis=\"{p.thesis}\")")
        lines.append(f"\nWeighted scores: {json.dumps(weighted_scores)}")
        lines.append("\nRespond with exactly one word: BUY, SELL, or HOLD")
        return "\n".join(lines)

    def _llm_arbitrate(
        self,
        proposals: list[AgentProposal],
        ticker: str,
        weighted_scores: dict[str, float],
    ) -> str | None:
        cfg = self._config
        client = OpenAI(
            api_key=cfg.OPENAI_COMPATIBLE_API_KEY,
            base_url=cfg.LLM_BACKEND_URL,
        )
        prompt = self._build_arbitration_prompt(proposals, ticker, weighted_scores)
        try:
            resp = client.chat.completions.create(
                model=cfg.QUICK_THINK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            text = resp.choices[0].message.content.strip().upper()
            for candidate in ("BUY", "SELL", "HOLD"):
                if candidate in text:
                    return candidate
            return "HOLD"
        except Exception as e:
            log.error(f"LLM arbitration failed: {e}")
            return None
