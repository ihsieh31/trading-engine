from __future__ import annotations
import os
import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def set_test_env(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("ALPACA_API_KEY", "test_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
    monkeypatch.setenv("INITIAL_CAPITAL", "100000")
    monkeypatch.setenv("MAX_POSITION_PCT", "0.10")
    monkeypatch.setenv("MAX_TOTAL_EXPOSURE", "0.50")
    monkeypatch.setenv("SLIPPAGE_BUFFER", "0.001")
