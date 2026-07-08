from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from config import Config
from interfaces_v2 import IAgent, AgentProposal, AnalysisContext, ReflectionResult

log = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    client_id: str = ""
    ticker: str = ""
    side: str = ""
    qty: int = 0
    filled_qty: int = 0
    avg_price: float = 0.0
    error: str | None = None


class BaseAgent(IAgent):
    def __init__(self, name: str = ""):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def analyze(self, context: AnalysisContext) -> AgentProposal:
        raise NotImplementedError


class AnalystAgent(BaseAgent):
    ANALYST_PROMPT = """You are a professional financial analyst. Analyze the given stock and output a JSON with your decision.

=== Context ===
Ticker: {ticker}
Date: {as_of_date}
Market Regime: {regime}

=== Technical Analysis ===
{technical_snapshot}

=== News Context ===
{news_context}

=== Economics Context ===
{economics_context}

=== Knowledge Base Context ===
{knowledge_context}

=== Output JSON Schema ===
{{
  "rating": "BUY" | "HOLD" | "SELL",
  "confidence": <0.0-1.0>,
  "thesis": "<brief investment thesis>",
  "price_target": <float or null>,
  "time_horizon": "short" | "medium" | "long",
  "key_risks": ["<risk1>", "<risk2>"],
  "supporting_rules_used": ["<rule1>"]
}}
"""

    def __init__(self, llm_client=None, name="analyst"):
        super().__init__(name)
        self._llm_client = llm_client

    def _build_prompt(self, context: AnalysisContext) -> str:
        tech = json.dumps(context.technical_snapshot, indent=2, default=str)
        return self.ANALYST_PROMPT.format(
            ticker=context.ticker,
            as_of_date=context.as_of_date,
            regime=context.regime,
            technical_snapshot=tech,
            news_context=context.news_context,
            economics_context=context.economics_context,
            knowledge_context=context.knowledge_context,
        )

    def _parse_response(self, text: str) -> dict:
        text = text.strip()
        if "```" in text:
            start = text.find("```json")
            if start == -1:
                start = text.find("```")
            if start != -1:
                end = text.find("```", start + 3)
                if end != -1:
                    fence_len = 7 if text[start:start + 7] == "```json" else 3
                    text = text[start + fence_len:end].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.warning(f"AnalystAgent JSON parse failed: {text[:200]}")
            return {}

    def analyze(self, context: AnalysisContext) -> AgentProposal:
        prompt = self._build_prompt(context)
        cfg = Config()
        client = self._llm_client or OpenAI(
            api_key=cfg.OPENAI_COMPATIBLE_API_KEY,
            base_url=cfg.LLM_BACKEND_URL,
        )
        try:
            resp = client.chat.completions.create(
                model=cfg.DEEP_THINK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = self._parse_response(resp.choices[0].message.content)
        except Exception as e:
            log.error(f"AnalystAgent LLM call failed: {e}")
            data = {}

        rating = data.get("rating", "HOLD")
        if rating not in ("BUY", "HOLD", "SELL"):
            rating = "HOLD"
        return AgentProposal(
            agent_name=self.name,
            ticker=context.ticker,
            rating=rating,
            confidence=data.get("confidence", 0.3),
            thesis=data.get("thesis", ""),
            price_target=data.get("price_target"),
            time_horizon=data.get("time_horizon", "short"),
            key_risks=data.get("key_risks", []),
            supporting_rules_used=data.get("supporting_rules_used", []),
        )


class ScreenerAgent(BaseAgent):
    def __init__(self, name="screener"):
        super().__init__(name)

    def analyze(self, context: AnalysisContext) -> AgentProposal:
        try:
            from screener import Screener
            from universe import get_universe
            tickers = get_universe()
            screener = Screener()
            results = screener.screen(tickers, top_n=20)
            matched = [r for r in results if r.ticker == context.ticker]
            if matched:
                r = matched[0]
                rating = "BUY" if r.score >= 3 else "HOLD"
                return AgentProposal(
                    agent_name=self.name,
                    ticker=context.ticker,
                    rating=rating,
                    confidence=min(r.score / 5.0, 1.0),
                    thesis=f"Technical screen score: {r.score}",
                    price_target=None,
                    time_horizon="short",
                    key_risks=[],
                    supporting_rules_used=[f"score_{r.score}"] + r.signals,
                )
        except Exception as e:
            log.error(f"ScreenerAgent failed: {e}")
        return AgentProposal(
            agent_name=self.name,
            ticker=context.ticker,
            rating="HOLD",
            confidence=0.2,
            thesis="Not in screened universe or screen error",
            price_target=None,
            time_horizon="short",
            key_risks=[],
            supporting_rules_used=[],
        )


class ExecutionAgent(BaseAgent):
    def __init__(self, order_manager=None, price_fn=None, account_provider=None, name="execution"):
        super().__init__(name)
        self._order_manager = order_manager
        self._price_fn = price_fn
        self._account_provider = account_provider

    def analyze(self, context: AnalysisContext) -> AgentProposal:
        raise NotImplementedError("ExecutionAgent does not analyze; use execute()")

    def execute(self, decision: "ChairmanDecision") -> OrderResult | None:
        if self._order_manager is None:
            log.error("ExecutionAgent: no order_manager configured")
            return None
        if decision.final_action == "HOLD":
            return None

        from alpaca.trading.enums import OrderSide
        from adapters import PriceProvider

        side = OrderSide.BUY if decision.final_action == "BUY" else OrderSide.SELL
        price_fn = self._price_fn or PriceProvider().get_current_price
        price = price_fn(decision.ticker)
        if not price or price <= 0:
            return OrderResult(success=False, ticker=decision.ticker, error="Cannot get price")

        try:
            if self._account_provider is not None:
                account = self._account_provider.get_account_summary()
                capital = account.portfolio_value
                buying_power = account.buying_power
            else:
                capital = getattr(self._order_manager._cfg, "INITIAL_CAPITAL", 100000)
                buying_power = capital
        except Exception:
            capital = 100000
            buying_power = capital
        dollars = min(capital * decision.position_pct, buying_power)
        qty = max(1, int(dollars / price))

        max_retries = 3
        for attempt in range(max_retries):
            try:
                record = self._order_manager.submit_market_order(
                    ticker=decision.ticker,
                    side=side,
                    qty=qty,
                    reason=decision.rationale[:200],
                )
                if record and record.status not in ("failed",):
                    return OrderResult(
                        success=True,
                        client_id=record.client_id,
                        ticker=decision.ticker,
                        side=decision.final_action,
                        qty=record.qty_requested,
                        filled_qty=record.qty_filled,
                        avg_price=record.avg_fill_price,
                    )
            except Exception as e:
                log.warning(f"Execution attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return OrderResult(success=False, ticker=decision.ticker, error="Max retries exceeded")

    def cancel_open_orders(self):
        if self._order_manager:
            self._order_manager.cancel_all_open()


class ReflectionAgent(BaseAgent):
    def __init__(self, config=None, llm_client=None, memory_service=None, name="reflection"):
        super().__init__(name)
        self._config = config or Config()
        self._llm_client = llm_client
        self._memory_service = memory_service

    def analyze(self, context: AnalysisContext) -> AgentProposal:
        raise NotImplementedError("ReflectionAgent does not analyze; use batch_process()")

    @staticmethod
    def enqueue(ticker: str, side: str, qty: int, price: float, reason: str):
        from reflection_agent import enqueue_reflection
        enqueue_reflection(ticker, side, qty, price, reason)

    def batch_process(self) -> list[ReflectionResult]:
        from reflection_agent import ReflectionAgent as ExistingReflectionAgent
        agent = ExistingReflectionAgent(config=self._config)
        raw_results = agent.batch_process()
        converted = []
        for r in raw_results:
            converted.append(ReflectionResult(
                ticker=r.ticker,
                pnl_pct=r.pnl_pct,
                outcome=r.outcome,
                lesson=r.lesson,
                trading_rule=r.trading_rule,
                context_tags=r.context_tags,
                applies_to=r.applies_to,
                confidence=r.confidence,
                agent_accuracy_feedback={},
                reflected_at=r.reflected_at,
            ))

            # V2: Detect conflicts and reinforce/propagate new rules
            if self._memory_service is not None:
                try:
                    rule_dict = {
                        "id": f"ref-{r.ticker}-{r.reflected_at}",
                        "title": r.trading_rule,
                        "content": r.lesson,
                        "tags": r.context_tags,
                        "confidence": r.confidence,
                        "outcome": r.outcome,
                    }
                    conflicts = self._memory_service.detect_conflict(rule_dict)
                    if conflicts:
                        log.info(f"V2 Rule conflict: '{r.trading_rule[:50]}' conflicts with {len(conflicts)} existing rule(s)")
                    self._memory_service.write(rule_dict, tier="semantic")
                except Exception as e:
                    log.warning(f"V2 rule propagation failed: {e}")

        return converted
