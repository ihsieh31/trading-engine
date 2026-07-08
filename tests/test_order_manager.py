from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

pytest.importorskip("alpaca.trading")


@pytest.fixture
def mock_tc():
    tc = MagicMock()
    tc.get_account.return_value = MagicMock(
        cash="50000",
        portfolio_value="100000",
        buying_power="200000",
        equity="100000",
        last_equity="99000",
        daytrade_count=0,
    )
    return tc


@pytest.fixture
def om(mock_tc):
    from order_manager import OrderManager
    with patch("order_manager.OrderManager._load_orders", return_value=[]):
        om = OrderManager(mock_tc)
        yield om


class TestInitDb:
    def test_init_db_called_on_construction(self, mock_tc):
        with patch("order_manager.db.init_db") as mock_init:
            from order_manager import OrderManager
            OrderManager(mock_tc)
            mock_init.assert_called_once()


class TestSaveOrdersDualWrite:
    def test_submit_market_order_dual_write(self, om, mock_tc):
        from alpaca.trading.enums import OrderSide
        mock_tc.submit_order.return_value = MagicMock(
            id="alpaca-001",
            status="filled",
            qty=10,
            filled_qty=10,
            filled_avg_price="150.0",
            created_at="2025-01-01T00:00:00",
        )
        with patch("order_manager.db.save_order") as mock_save:
            om.submit_market_order("AAPL", OrderSide.BUY, 10, reason="test")
            mock_save.assert_called_once()

    def test_save_orders_dual_write(self, om, mock_tc):
        from order_manager import OrderRecord
        rec = OrderRecord(
            client_id="test-001", ticker="AAPL", side="buy",
            qty_requested=10, qty_filled=10,
        )
        om._orders["test-001"] = rec
        with patch("order_manager.db.save_order") as mock_save:
            om._save_orders()
            assert mock_save.call_count >= 1

    def test_record_trade_dual_write(self, om):
        from order_manager import OrderRecord
        record = OrderRecord(
            client_id="t-001",
            ticker="AAPL",
            side="buy",
            qty_requested=10,
            qty_filled=10,
            status="filled",
            alpaca_order_id="a-001",
            avg_fill_price=150.0,
            reason="test",
        )
        with patch("order_manager.db.save_trade") as mock_save:
            om._record_trade(record, 150.0, 10)
            mock_save.assert_called_once()


class TestFractionalShares:
    def test_submit_market_order_float_qty(self, om, mock_tc):
        from alpaca.trading.enums import OrderSide
        mock_tc.submit_order.return_value = MagicMock(
            id="alpaca-001", status="filled", qty=10.5, filled_qty=10,
            filled_avg_price="150.0", created_at="2025-01-01T00:00:00",
        )
        om.submit_market_order("AAPL", OrderSide.BUY, 10.5, reason="test")


class TestRetryOrderBracketCancel:
    def test_retry_cancels_bracket_children_first(self, om, mock_tc):
        from order_manager import OrderRecord
        rec = OrderRecord(
            client_id="retry-001", ticker="AAPL", side="buy",
            qty_requested=10, status="failed",
            alpaca_order_id="a-001",
        )
        rec.bracket = True
        om._orders["retry-001"] = rec
        with patch.object(om, "cancel_bracket_children") as mock_cancel:
            om._retry_order("retry-001")
            mock_cancel.assert_called_once_with("AAPL")


class TestCancelAllOpen:
    def test_cancel_all_open(self, om, mock_tc):
        from order_manager import OrderRecord
        mock_tc.reset_mock()
        rec1 = OrderRecord(
            client_id="o-001", ticker="AAPL", side="buy",
            qty_requested=10, status="submitted", alpaca_order_id="a-001",
        )
        rec2 = OrderRecord(
            client_id="o-002", ticker="MSFT", side="sell",
            qty_requested=5, status="partially_filled", alpaca_order_id="a-002",
        )
        om._orders["o-001"] = rec1
        om._orders["o-002"] = rec2
        om.cancel_all_open()
        assert mock_tc.cancel_order_by_id.call_count == 2


    def test_eod_cleanup(self, om, mock_tc):
        from order_manager import OrderRecord
        rec = OrderRecord(
            client_id="o-001", ticker="AAPL", side="buy",
            qty_requested=10, status="submitted", alpaca_order_id="a-001",
        )
        om._orders["o-001"] = rec
        om.eod_cleanup()
        assert mock_tc.cancel_order_by_id.call_count == 1
