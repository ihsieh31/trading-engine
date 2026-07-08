from __future__ import annotations
import json
import pytest
from pathlib import Path


class TestInitDb:
    def test_init_db_creates_tables(self):
        import db
        db.init_db()
        conn = db._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [r["name"] for r in tables]
        assert "orders" in names
        assert "trades" in names
        assert "ratings" in names

    def test_init_db_is_idempotent(self):
        import db
        db.init_db()
        db.init_db()
        conn = db._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [r["name"] for r in tables]
        assert "orders" in names


class TestSaveLoadOrders:
    def test_save_and_load_order(self):
        import db
        db.init_db()
        order = {
            "client_id": "test-001",
            "ticker": "AAPL",
            "side": "buy",
            "qty_requested": 10,
            "qty_filled": 10,
            "status": "filled",
            "alpaca_order_id": "alpaca-001",
            "avg_fill_price": 150.0,
            "reason": "test",
            "retry_count": 0,
            "bracket_sl": None,
            "bracket_tp": None,
            "parent_id": "",
            "is_bracket_child": False,
            "created_at": "2025-01-01T00:00:00",
        }
        db.save_order(order)
        loaded = db.load_orders()
        assert "test-001" in loaded
        assert loaded["test-001"]["ticker"] == "AAPL"
        assert loaded["test-001"]["side"] == "buy"

    def test_load_orders_empty(self):
        import db
        db.init_db()
        conn = db._get_conn()
        conn.execute("DELETE FROM orders")
        loaded = db.load_orders()
        assert loaded == {}


class TestSaveLoadTrades:
    def test_save_and_load_trade(self):
        import db
        db.init_db()
        trade = {
            "ticker": "AAPL",
            "side": "buy",
            "qty": 10,
            "price": 150.0,
            "time": "2025-01-01T00:00:00",
            "client_id": "t-001",
        }
        db.save_trade(trade)
        trades = db.load_trades(limit=100)
        assert len(trades) == 1
        assert trades[0]["ticker"] == "AAPL"

    def test_load_trades_limit(self):
        import db
        db.init_db()
        for i in range(5):
            db.save_trade({
                "ticker": "AAPL",
                "side": "buy",
                "qty": 1,
                "price": 100.0 + i,
                "time": f"2025-01-01T00:0{i}:00",
                "client_id": f"t-{i:03d}",
            })
        trades = db.load_trades(limit=3)
        assert len(trades) == 3


class TestSaveLoadRatings:
    def test_save_and_load_ratings(self):
        import db
        db.init_db()
        ratings = {
            "AAPL": {"rating": "Buy", "price_target": 200.0},
            "MSFT": {"rating": "Hold", "price_target": None},
        }
        db.save_ratings(ratings)
        loaded = db.load_ratings()
        assert loaded["AAPL"]["rating"] == "Buy"
        assert loaded["MSFT"]["rating"] == "Hold"

    def test_save_ratings_overwrite(self):
        import db
        db.init_db()
        db.save_ratings({"AAPL": {"rating": "Buy"}})
        db.save_ratings({"MSFT": {"rating": "Hold"}})
        loaded = db.load_ratings()
        # save_ratings does full replace — only MSFT remains
        assert "AAPL" not in loaded
        assert loaded["MSFT"]["rating"] == "Hold"
