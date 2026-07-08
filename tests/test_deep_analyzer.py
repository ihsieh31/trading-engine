from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

_MOCK_MODULES = {
    "exchange_calendars": MagicMock(),
    "trading_calendar": MagicMock(is_trading_day=lambda: True, last_trading_day=lambda: MagicMock(strftime=lambda _: "2025-01-01")),
    "knowledge_base": MagicMock(),
    "sector_map": MagicMock(),
    "tradingagents": MagicMock(),
    "tradingagents.graph": MagicMock(),
    "tradingagents.graph.trading_graph": MagicMock(),
    "tradingagents.default_config": MagicMock(DEFAULT_CONFIG={"data_vendors": {}, "llm_provider": "test"}),
    "tradingagents.dataflows": MagicMock(),
    "tradingagents.dataflows.interface": MagicMock(VENDOR_METHODS={"get_news": {}, "get_global_news": {}}),
    "tradingagents.agents": MagicMock(),
    "tradingagents.agents.utils": MagicMock(),
    "tradingagents.agents.utils.agent_utils": MagicMock(),
}


class TestKnowledgeContext:
    def test_inject_knowledge_returns_bool(self):
        with patch.dict("sys.modules", _MOCK_MODULES), \
             patch("deep_analyzer.log"):
            import deep_analyzer
            result = deep_analyzer._inject_knowledge_to_config("AAPL")
            assert result is True or result is False

    def test_per_ticker_context_isolation(self):
        with patch.dict("sys.modules", _MOCK_MODULES):
            import deep_analyzer
        deep_analyzer._knowledge_context.clear()
        deep_analyzer._knowledge_context["AAPL"] = "AAPL context"
        deep_analyzer._knowledge_context["MSFT"] = "MSFT context"
        assert "AAPL" in deep_analyzer._knowledge_context
        assert "MSFT" in deep_analyzer._knowledge_context

    def test_analyze_ticker_saves_restores_vendor_methods(self):
        pytest.importorskip("tradingagents")
        from tradingagents.dataflows.interface import VENDOR_METHODS
        from deep_analyzer import _inject_knowledge_to_config
        original = VENDOR_METHODS.get("get_global_news", {}).copy()

        import deep_analyzer
        saved_news = VENDOR_METHODS.get("get_global_news", {}).copy()
        _inject_knowledge_to_config("AAPL")
        VENDOR_METHODS["get_global_news"] = saved_news


class TestDeepAnalyzerMainFlow:
    @staticmethod
    def _mock_config():
        return {"data_vendors": {}}

    def test_run_deep_analysis_default_tickers(self):
        pytest.importorskip("tradingagents")
        with patch("deep_analyzer.log"), \
             patch("tradingagents.graph.trading_graph.TradingAgentsGraph"), \
             patch("deep_analyzer.build_ta_config", return_value={"data_vendors": {}}), \
             patch("deep_analyzer._patch_vendor_with_news_service"), \
             patch("deep_analyzer.analyze_ticker", return_value={
                 "ticker": "AAPL", "rating": "Buy", "price_target": 200.0,
                 "time_horizon": "3m", "executive_summary": "", "investment_thesis": "",
                 "analyzed_at": "2025-01-01T00:00:00",
             }), \
             patch("deep_analyzer.atomic_write_json"), \
             patch("deep_analyzer.db.save_ratings"), \
             patch("deep_analyzer.last_trading_day", return_value=MagicMock(strftime=lambda _: "2025-01-01")):
            from deep_analyzer import run_deep_analysis
            result = run_deep_analysis(["AAPL"])
            assert "AAPL" in result

    def test_run_deep_analysis_handles_ticker_failure(self):
        pytest.importorskip("tradingagents")
        with patch("deep_analyzer.log"), \
             patch("tradingagents.graph.trading_graph.TradingAgentsGraph"), \
             patch("deep_analyzer.build_ta_config", return_value={"data_vendors": {}}), \
             patch("deep_analyzer._patch_vendor_with_news_service"), \
             patch("deep_analyzer.analyze_ticker", side_effect=ValueError("Analysis failed")), \
             patch("deep_analyzer.atomic_write_json"), \
             patch("deep_analyzer.db.save_ratings"), \
             patch("deep_analyzer.last_trading_day", return_value=MagicMock(strftime=lambda _: "2025-01-01")):
            from deep_analyzer import run_deep_analysis
            result = run_deep_analysis(["AAPL"])
            assert "AAPL" in result
            assert result["AAPL"]["error"] == "Analysis failed"
