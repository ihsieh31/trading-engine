from __future__ import annotations
import pytest
from pathlib import Path


@pytest.fixture
def sample_skill(tmp_path):
    content = """name: economics-knowledge
description: Test skill

### === CORE THEORIES & PRINCIPLES ===
- **Business Cycle Theory** (test_source)
  - The economy moves in cycles of expansion and contraction driven by credit and investment.
  - Proponents: Joseph Schumpeter
- **Inflation Dynamics** (test_source)
  - Inflation is caused by excess money supply chasing limited goods.
  - Proponents: Milton Friedman
- **Supply and Demand** (test_source)
  - Prices adjust to balance supply and demand in competitive markets.

### === KEY CONCEPTS ===
- **GDP** (test_source)
  - Gross Domestic Product measures total economic output.
- **Inflation Rate** (test_source)
  - The percentage change in price level over time.

### === ACTIONABLE INSIGHTS ===
- During market panics, buy quality assets at discounted prices.
- Trend following works best in strong bull or bear markets.
- Use stop-losses to protect capital during high volatility.

### === PRACTICAL FORMULAS ===
- **Sharpe Ratio** (test_source)
  - Formula: (Return - RiskFreeRate) / StdDev
  - Measures risk-adjusted return.

### === KEY QUOTES ===
- "The market can stay irrational longer than you can stay solvent." — Keynes
"""
    f = tmp_path / "test_skill.yaml"
    f.write_text(content)
    return f


class TestEconomicsKB:
    def test_load_skill(self, sample_skill):
        from economics_kb import EconomicsKnowledgeBase
        kb = EconomicsKnowledgeBase(sample_skill)
        assert len(kb._theories) == 3
        assert len(kb._concepts) == 2
        assert len(kb._insights) == 3
        assert len(kb._formulas) == 1
        assert len(kb._quotes) == 1

    def test_query_returns_context(self, sample_skill):
        from economics_kb import EconomicsKnowledgeBase
        kb = EconomicsKnowledgeBase(sample_skill)
        result = kb.query(ticker="AAPL", sector="Technology")
        assert "經濟學相關知識" in result
        assert "Business Cycle Theory" in result or "Inflation" in result
        assert "相關理論" in result

    def test_query_with_regime(self, sample_skill):
        from economics_kb import EconomicsKnowledgeBase
        kb = EconomicsKnowledgeBase(sample_skill)
        result = kb.query(ticker="SPY", sector="ETF", regime="bear")
        assert "相關理論" in result

    def test_query_relevance_scoring(self, sample_skill):
        from economics_kb import EconomicsKnowledgeBase
        kb = EconomicsKnowledgeBase(sample_skill)
        result = kb.query(ticker="", sector="", regime="inflation")
        # Inflation should get high relevance score
        assert "Inflation Dynamics" in result

    def test_empty_on_no_file(self):
        from economics_kb import EconomicsKnowledgeBase
        kb = EconomicsKnowledgeBase(Path("/nonexistent/path.yaml"))
        assert kb._theories == []
        assert kb._insights == []
        assert kb.query() == ""

    def test_get_macro_context(self, sample_skill):
        from economics_kb import EconomicsKnowledgeBase
        kb = EconomicsKnowledgeBase(sample_skill)
        result = kb.get_macro_context(regime="bull")
        assert "宏觀經濟背景" in result
        assert "Business Cycle Theory" in result

    def test_singleton_getter(self):
        import economics_kb
        # Reset singleton
        economics_kb._economics_kb = None
        kb1 = economics_kb.get_economics_kb()
        kb2 = economics_kb.get_economics_kb()
        assert kb1 is kb2
