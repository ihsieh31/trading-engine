from __future__ import annotations
import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


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
def perf(mock_tc):
    from performance import PerformanceTracker
    p = PerformanceTracker(mock_tc)
    with patch("performance.db.load_trades", return_value=[]):
        yield p


class TestLoadTrades:
    def test_load_trades_from_db(self, perf):
        db_trades = [
            {"ticker": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 5, "price": 160.0, "time": "2025-01-02T00:00:00"},
        ]
        with patch("performance.db.load_trades", return_value=db_trades):
            trades = perf.load_trades()
            assert len(trades) == 2
            assert trades[0]["ticker"] == "AAPL"

    def test_load_trades_fallback_to_jsonl(self, perf, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        trades_file = data_dir / "trades.jsonl"
        trades_file.write_text(
            json.dumps({"ticker": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "time": "2025-01-01T00:00:00"}) + "\n"
        )
        orig = perf.DATA_DIR
        perf.DATA_DIR = data_dir
        with patch("performance.db.load_trades", side_effect=Exception("DB unavailable")):
            trades = perf.load_trades()
            assert len(trades) == 1
            assert trades[0]["ticker"] == "AAPL"
        perf.DATA_DIR = orig


class TestAnalyzeTradesWAC:
    def test_weighted_average_cost(self, perf):
        trades = [
            {"ticker": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "AAPL", "side": "buy", "qty": 10, "price": 200.0, "time": "2025-01-02T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 5, "price": 180.0, "time": "2025-01-03T00:00:00"},
        ]
        with patch.object(perf, "load_trades", return_value=trades):
            result = perf.analyze_trades()
            # WAC = (10*100 + 10*200) / 20 = 150; sell 5 @ 180 => P&L = (180-150)/150 = +20%
            assert result["closed_trades"] == 1
            assert result["matched_qty"] == 5
            assert result["win_rate"] == 1.0
            assert result["total_pnl_pct"] == pytest.approx(20.0, rel=0.1)

    def test_multiple_sells_wac(self, perf):
        trades = [
            {"ticker": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 3, "price": 110.0, "time": "2025-01-02T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 3, "price": 90.0, "time": "2025-01-03T00:00:00"},
        ]
        with patch.object(perf, "load_trades", return_value=trades):
            result = perf.analyze_trades()
            assert result["closed_trades"] == 2
            assert result["matched_qty"] == 6

    def test_empty_trades(self, perf):
        with patch.object(perf, "load_trades", return_value=[]):
            result = perf.analyze_trades()
            assert result["total_trades"] == 0
            assert result["matched_qty"] == 0

    def test_buy_then_sell_all_wac(self, perf):
        trades = [
            {"ticker": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 10, "price": 110.0, "time": "2025-01-02T00:00:00"},
        ]
        with patch.object(perf, "load_trades", return_value=trades):
            result = perf.analyze_trades()
            assert result["closed_trades"] == 1
            assert result["matched_qty"] == 10
            assert result["total_pnl_pct"] == pytest.approx(10.0, rel=0.1)

    def test_multiple_tickers(self, perf):
        trades = [
            {"ticker": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "MSFT", "side": "buy", "qty": 5, "price": 200.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 5, "price": 110.0, "time": "2025-01-02T00:00:00"},
            {"ticker": "MSFT", "side": "sell", "qty": 2, "price": 210.0, "time": "2025-01-02T00:00:00"},
        ]
        with patch.object(perf, "load_trades", return_value=trades):
            result = perf.analyze_trades()
            assert result["closed_trades"] == 2
            assert result["matched_qty"] == 7

    def test_sell_more_than_bought_warning(self, perf, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        trades = [
            {"ticker": "AAPL", "side": "buy", "qty": 5, "price": 100.0, "time": "2025-01-01T00:00:00"},
            {"ticker": "AAPL", "side": "sell", "qty": 10, "price": 110.0, "time": "2025-01-02T00:00:00"},
        ]
        with patch.object(perf, "load_trades", return_value=trades):
            result = perf.analyze_trades()
            assert result["matched_qty"] == 5
            assert any("unmatched" in rec.message for rec in caplog.records)
