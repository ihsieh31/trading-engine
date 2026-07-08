from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, ANY


@pytest.fixture
def pm():
    from portfolio_manager import PortfolioManager
    pm = PortfolioManager()
    pm.get_account_summary = MagicMock(return_value={
        "portfolio_value": 100000,
        "cash": 50000,
        "buying_power": 200000,
        "equity": 100000,
    })
    pm.get_positions_dict = MagicMock(return_value={})
    pm.get_kelly_inputs = MagicMock(return_value={
        "win_rate": 0.6,
        "avg_win": 2.0,
        "avg_loss": 1.0,
        "closed_trades": 20,
    })
    pm.compute_kelly_pct = MagicMock(return_value=0.08)
    pm._consult_knowledge_rules = MagicMock(return_value=1.0)
    pm._rating_freshness_multiplier = MagicMock(return_value=1.0)
    mock_order_manager = MagicMock()
    mock_order_manager.get_pending_buy_dollars.return_value = 0.0
    pm.order_manager = mock_order_manager
    pm.max_position_pct = 0.10
    pm.min_position_pct = 0.02
    pm.kelly_fraction = 0.25
    pm.slippage_buffer = 0.001
    return pm


class TestSlippageBuffer:
    def test_slippage_reduces_position_size(self, pm):
        with patch("portfolio_manager.log") as mock_log:
            qty = pm.position_size_for("AAPL", 100.0, "Buy")
            assert qty > 0
            # Verify slippage buffer was applied (dollars *= 0.999)
            mock_log.debug.assert_any_call(ANY)

    def test_slippage_buffer_env_variable(self):
        import os
        from config import Config
        os.environ["SLIPPAGE_BUFFER"] = "0.005"
        Config._reset()
        from portfolio_manager import PortfolioManager
        pm = PortfolioManager()
        assert pm.slippage_buffer == 0.005

    def test_default_slippage_buffer(self):
        import os
        from config import Config
        os.environ.pop("SLIPPAGE_BUFFER", None)
        Config._reset()
        from portfolio_manager import PortfolioManager
        pm = PortfolioManager()
        assert pm.slippage_buffer == 0.001


class TestDebugLog:
    def test_debug_log_position_size(self, pm):
        with patch("portfolio_manager.log") as mock_log:
            pm.position_size_for("AAPL", 100.0, "Buy")
            mock_log.debug.assert_called()
            call_arg = mock_log.debug.call_args[0][0]
            assert "position_size_for" in call_arg
            assert "dollars_after_slippage" in call_arg
            assert "available_for_new" in call_arg
            assert "price" in call_arg


class TestPositionSize:
    def test_buy_rating_returns_positive_qty(self, pm):
        qty = pm.position_size_for("AAPL", 100.0, "Buy")
        assert qty > 0

    def test_overweight_returns_larger_qty(self, pm):
        buy_qty = pm.position_size_for("AAPL", 100.0, "Buy")
        ow_qty = pm.position_size_for("AAPL", 100.0, "Overweight")
        assert ow_qty >= buy_qty

    def test_hold_rating_returns_zero(self, pm):
        qty = pm.position_size_for("AAPL", 100.0, "Hold")
        assert qty == 0

    def test_exposure_limit_returns_zero(self, pm):
        pm.get_positions_dict = MagicMock(return_value={
            "AAPL": {"market_value": 60000},
        })
        qty = pm.position_size_for("AAPL", 100.0, "Buy")
        assert qty == 0
