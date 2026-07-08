from __future__ import annotations
"""共用檔案工具 — 原子寫入、环境变量校验等操作，避免多行程讀取到寫入到一半的檔案。"""

import os
import json
import logging
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, content: str):
    path = Path(path)
    dir_ = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path: str | Path) -> dict:
    """安全讀取 JSON 檔案，失敗回傳 {}。"""
    path = Path(path)
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def atomic_write_json(path: str | Path, data):
    atomic_write_text(path, json.dumps(data, indent=2, default=str))


_REQUIRED_VARS = {
    "scheduler": ["ALPACA_API_KEY", "ALPACA_API_SECRET"],
    "monitor": ["ALPACA_API_KEY", "ALPACA_API_SECRET"],
    "deep_analyzer": ["OPENAI_COMPATIBLE_API_KEY"],
    "dashboard": [],
}

_WARNED_VARS = set()


def validate_env(module_name: str = "scheduler"):
    """啟動時校驗必要環境變數，缺失時發出警告。"""
    from config import Config
    cfg = Config()
    required = _REQUIRED_VARS.get(module_name, [])
    for var in required:
        val = getattr(cfg, var, None)
        if not val:
            if var not in _WARNED_VARS:
                _WARNED_VARS.add(var)
                log = logging.getLogger(__name__)
                log.warning(f"Missing required env var: {var} — {module_name} may not function correctly")
    # optional but recommended
    optional = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DASHBOARD_TOKEN", "HEALTHCHECK_URL"}
    for var in optional:
        val = getattr(cfg, var, None)
        if not val and var not in _WARNED_VARS:
            _WARNED_VARS.add(var)
            log = logging.getLogger(__name__)
            log.info(f"Optional env var {var} not set — related features disabled")
