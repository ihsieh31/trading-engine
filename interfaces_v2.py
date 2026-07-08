from __future__ import annotations
"""V2 接口定义 — 多智能体协同、风险评估、工作流引擎与记忆服务。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AgentProposal:
    agent_name: str
    ticker: str
    rating: str  # BUY / HOLD / SELL
    confidence: float  # 0-1
    thesis: str
    price_target: float | None
    time_horizon: str
    key_risks: list[str]
    supporting_rules_used: list[str]


@dataclass
class RiskAssessment:
    ticker: str
    approved: bool
    position_pct: float  # Kelly-based position size as fraction of capital
    kelly_pct: float
    sector_exposure_pct: float
    veto_reason: str | None


@dataclass
class ChairmanDecision:
    ticker: str
    final_action: str  # BUY / HOLD / SELL
    confidence: float
    position_pct: float
    vote_breakdown: list[dict]
    conflict_resolution: str  # weighted_vote / rule_override / risk_veto / llm_arbitration / none
    rationale: str


@dataclass
class ReflectionResult:
    ticker: str
    pnl_pct: float
    outcome: str  # win / loss / breakeven
    lesson: str
    trading_rule: str
    context_tags: list[str]
    applies_to: str
    confidence: float
    agent_accuracy_feedback: dict
    reflected_at: str


@dataclass
class AnalysisContext:
    ticker: str
    as_of_date: str
    technical_snapshot: dict
    news_context: str
    economics_context: str
    knowledge_context: str
    regime: str


@dataclass
class PortfolioState:
    positions: dict
    cash: float
    portfolio_value: float
    sector_exposure: dict
    regime: str


class IAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AgentProposal:
        ...


class IRiskAgent(ABC):
    @abstractmethod
    def evaluate(self, proposal: AgentProposal, portfolio_state: PortfolioState) -> RiskAssessment:
        ...


class IChairmanAgent(ABC):
    @abstractmethod
    def decide(self, proposals: list[AgentProposal], risk_assessment: RiskAssessment) -> ChairmanDecision:
        ...


class IWorkflowEngine(ABC):
    @abstractmethod
    def start(self, workflow_id: str):
        ...

    @abstractmethod
    def advance(self, workflow_id: str, event: str):
        ...

    @abstractmethod
    def get_state(self, workflow_id: str) -> dict:
        ...

    @abstractmethod
    def retry(self, workflow_id: str, step: str):
        ...


class IMemoryService(ABC):
    @abstractmethod
    def write(self, entry: dict):
        ...

    @abstractmethod
    def query(self, query: str, tier: str) -> list[dict]:
        ...

    @abstractmethod
    def expand_graph(self, node: str, hops: int) -> list[dict]:
        ...


class IPlugin(ABC):
    @property
    @abstractmethod
    def manifest(self) -> dict:
        ...

    @abstractmethod
    def on_load(self, config: dict):
        ...

    @abstractmethod
    def on_unload(self):
        ...


class INewsProvider(ABC):
    """新聞資料來源介面（供 Plugin 實作）。"""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> str:
        ...

    @abstractmethod
    def search_market_news(self, query: str, max_results: int = 5) -> str:
        ...


class INewsProviderPlugin(IPlugin, INewsProvider):
    """Plugin 形式的新聞資料來源。"""


class IStrategyPlugin(IPlugin):
    @abstractmethod
    def evaluate(self, position: dict, market_data: dict) -> dict:
        ...
