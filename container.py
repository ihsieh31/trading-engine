from __future__ import annotations
"""DI 容器 — 集中管理所有模組的建立與依賴注入。"""

import logging
from pathlib import Path
from config import Config
from adapters import PriceProvider, AccountProvider, OrderExecutor
from interfaces import IPriceProvider, IAccountProvider, IOrderExecutor

log = logging.getLogger(__name__)


class ModuleContainer:
    """DI 容器, 避免各模組重複建立 Client / Provider。

    Usage::

        container = ModuleContainer()
        container.portfolio_manager  # 自動 lazy init
        container.monitor            # 自動 lazy init
    """

    def __init__(self, config: Config | None = None):
        self._cfg = config or Config()
        self._trading_client = None
        self._data_client = None

        # ── Providers (interfaces) ─────────────────────────────
        self._price_provider: IPriceProvider | None = None
        self._account_provider: IAccountProvider | None = None
        self._order_executor: IOrderExecutor | None = None

        # ── Domain modules (lazy) ──────────────────────────────
        self._news_service = None
        self._order_manager = None
        self._portfolio_manager = None
        self._performance_tracker = None
        self._regime_detector = None
        self._circuit_breaker = None
        self._knowledge_base = None
        self._reflection_agent = None
        self._price_monitor = None
        self._scheduler = None
        self._memory_service = None
        self._workflow_engine = None

    # ── Infrastructure ─────────────────────────────────────────

    @property
    def config(self) -> Config:
        return self._cfg

    @property
    def event_bus(self):
        from event_bus import EventBus
        return EventBus.get_instance()

    @property
    def trading_client(self):
        if self._trading_client is None:
            from alpaca.trading.client import TradingClient
            self._trading_client = TradingClient(
                self._cfg.ALPACA_API_KEY,
                self._cfg.ALPACA_API_SECRET,
                paper=self._cfg.IS_PAPER,
            )
        return self._trading_client

    @property
    def data_client(self):
        if self._data_client is None:
            from alpaca.data.historical.stock import StockHistoricalDataClient
            self._data_client = StockHistoricalDataClient(
                self._cfg.ALPACA_API_KEY,
                self._cfg.ALPACA_API_SECRET,
            )
        return self._data_client

    # ── Providers ──────────────────────────────────────────────

    @property
    def price_provider(self) -> IPriceProvider:
        if self._price_provider is None:
            self._price_provider = PriceProvider(alpaca_data_client=self.data_client)
        return self._price_provider

    @property
    def account_provider(self) -> IAccountProvider:
        if self._account_provider is None:
            self._account_provider = AccountProvider(trading_client=self.trading_client)
        return self._account_provider

    @property
    def order_executor(self) -> IOrderExecutor:
        if self._order_executor is None:
            self._order_executor = OrderExecutor(trading_client=self.trading_client)
        return self._order_executor

    # ── Domain Modules ─────────────────────────────────────────

    @property
    def news_service(self):
        if self._news_service is None:
            from news_service import NewsService
            self._news_service = NewsService()
        return self._news_service

    @property
    def order_manager(self):
        if self._order_manager is None:
            from order_manager import OrderManager
            self._order_manager = OrderManager(
                self.trading_client,
                config=self._cfg,
                price_fn=self.price_provider.get_current_price,
            )
        return self._order_manager

    @property
    def portfolio_manager(self):
        if self._portfolio_manager is None:
            from portfolio_manager import PortfolioManager
            self._portfolio_manager = PortfolioManager(
                trading_client=self.trading_client,
                price_fn=self.price_provider.get_current_price,
                order_manager=self.order_manager,
                account_provider=self.account_provider,
                config=self._cfg,
            )
        return self._portfolio_manager

    @property
    def performance_tracker(self):
        if self._performance_tracker is None:
            from performance import PerformanceTracker
            self._performance_tracker = PerformanceTracker(
                self.trading_client,
                config=self._cfg,
            )
        return self._performance_tracker

    @property
    def regime_detector(self):
        if self._regime_detector is None:
            from regime import RegimeDetector
            self._regime_detector = RegimeDetector()
        return self._regime_detector

    @property
    def circuit_breaker(self):
        if self._circuit_breaker is None:
            from safety import CircuitBreaker
            self._circuit_breaker = CircuitBreaker(
                self.trading_client,
                config=self._cfg,
            )
        return self._circuit_breaker

    @property
    def knowledge_base(self):
        if self._knowledge_base is None:
            from knowledge_base import KnowledgeBase
            self._knowledge_base = KnowledgeBase(config=self._cfg)
        return self._knowledge_base

    @property
    def reflection_agent(self):
        if self._reflection_agent is None:
            from reflection_agent import ReflectionAgent
            self._reflection_agent = ReflectionAgent(config=self._cfg)
        return self._reflection_agent

    @property
    def strategies(self):
        from strategy import CompositeStrategy, RatingStrategy, StopLossTakeProfitStrategy
        return CompositeStrategy([
            StopLossTakeProfitStrategy(),
            RatingStrategy(),
        ])

    @property
    def backtest_engine(self):
        from backtest import BacktestEngine, MA20CrossStrategy
        return BacktestEngine(MA20CrossStrategy())

    @property
    def price_monitor(self):
        if self._price_monitor is None:
            from monitor import PriceMonitor
            self._price_monitor = PriceMonitor(config=self._cfg, strategies=self.strategies, container=self)
        return self._price_monitor

    @property
    def scheduler(self):
        if self._scheduler is None:
            from scheduler import Scheduler
            self._scheduler = Scheduler(container=self)
        return self._scheduler

    @property
    def dashboard(self):
        from dashboard import configure as _dashboard_configure
        _dashboard_configure(container=self)
        from dashboard import app as _dashboard_app
        return _dashboard_app

    # ── V2 Agents ────────────────────────────────────────────────

    @property
    def analyst_agent(self):
        from agents.base import AnalystAgent
        return AnalystAgent(name="analyst")

    @property
    def screener_agent(self):
        from agents.base import ScreenerAgent
        return ScreenerAgent(name="screener")

    @property
    def risk_agent(self):
        from agents.risk_agent import RiskAgent
        return RiskAgent(portfolio_manager=self.portfolio_manager, config=self._cfg)

    @property
    def chairman_agent(self):
        from agents.chairman_agent import ChairmanAgent
        return ChairmanAgent(memory_service=self.memory_service, config=self._cfg)

    @property
    def execution_agent(self):
        from agents.base import ExecutionAgent
        return ExecutionAgent(
            order_manager=self.order_manager,
            price_fn=self.price_provider.get_current_price,
            account_provider=self.account_provider,
        )

    @property
    def reflection_agent_v2(self):
        from agents.base import ReflectionAgent
        return ReflectionAgent(config=self._cfg, memory_service=self.memory_service)

    @property
    def memory_service(self):
        if self._memory_service is None:
            from memory.memory_service import MemoryService
            self._memory_service = MemoryService(config=self._cfg, knowledge_base=self.knowledge_base)
        return self._memory_service

    @property
    def workflow_engine(self):
        if self._workflow_engine is None:
            from core.workflow_engine import WorkflowEngine
            self._workflow_engine = WorkflowEngine(container=self)
        return self._workflow_engine
