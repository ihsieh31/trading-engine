"""全域設定 — 整份專案唯一的環境變數讀取點。"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

log = logging.getLogger(__name__)


def _bool(val: str) -> bool:
    return val.strip().lower() in ("1", "true", "yes")


class Config:
    """Singleton — 一個 process 只載入一次 .env。

    所有 env var 在此統一讀取、型別轉換，各模組不再個別呼叫 os.getenv()。
    """

    _instance: Config | None = None

    def __new__(cls) -> Config:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if self._loaded:
            return
        load_dotenv()
        self._resolve_config()
        self._validate_required()
        self._loaded = True

    def _resolve_config(self) -> None:
        # ── Paths ──────────────────────────────────────────────
        data_dir_default = os.getenv("_CONFIG_DATA_DIR_DEFAULT", "data")
        self.DATA_DIR = Path(os.getenv("DATA_DIR", data_dir_default)).resolve()
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.ECONOMICS_SKILL_PATH = Path(
            os.getenv("ECONOMICS_SKILL_PATH", Path(__file__).parent / "economics-knowledge.yaml")
        )
        self.OBSIDIAN_VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", "/Users/zongen/Documents/Obsidian Vault/金融"))

        # ── Alpaca ─────────────────────────────────────────────
        self.ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
        self.ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET", "")
        self.IS_PAPER = _bool(os.getenv("IS_PAPER", "true"))

        # ── LLM ────────────────────────────────────────────────
        self.LLM_BACKEND_URL = os.getenv("LLM_BACKEND_URL", "https://apihub.agnes-ai.com/v1")
        self.DEEP_THINK_MODEL = os.getenv("DEEP_THINK_MODEL", "agnes-2.0-flash")
        self.QUICK_THINK_MODEL = os.getenv("QUICK_THINK_MODEL", "agnes-2.0-flash")
        self.OPENAI_COMPATIBLE_API_KEY = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")

        # ── Risk Management ────────────────────────────────────
        self.INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000"))
        self.MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.10"))
        self.MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "0.50"))
        self.MAX_SECTOR_PCT = float(os.getenv("MAX_SECTOR_PCT", "0.25"))
        self.STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.05"))
        self.TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.15"))
        self.KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
        self.MIN_POSITION_PCT = float(os.getenv("MIN_POSITION_PCT", "0.02"))
        self.SLIPPAGE_BUFFER = float(os.getenv("SLIPPAGE_BUFFER", "0.001"))
        self.MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))
        self.MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "0.15"))

        # ── Order Management ───────────────────────────────────
        self.ORDER_MAX_RETRIES = int(os.getenv("ORDER_MAX_RETRIES", "3"))
        self.ORDER_RETRY_DELAY_SEC = int(os.getenv("ORDER_RETRY_DELAY_SEC", "10"))
        self.ORDER_FILL_TIMEOUT_SEC = int(os.getenv("ORDER_FILL_TIMEOUT_SEC", "300"))
        self.USE_FRACTIONAL_SHARES = _bool(os.getenv("USE_FRACTIONAL_SHARES", "false"))

        # ── Screening ──────────────────────────────────────────
        self.UNIVERSE_SOURCE = os.getenv("UNIVERSE_SOURCE", "sp500")
        self.SCREENER_TOP_N = int(os.getenv("SCREENER_TOP_N", "20"))
        self.SCREENER_MIN_SCORE = float(os.getenv("SCREENER_MIN_SCORE", "0"))
        self.SCREENER_WORKERS = int(os.getenv("SCREENER_WORKERS", "10"))

        # ── Monitoring ─────────────────────────────────────────
        self.MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "30"))
        self.BUY_COOLDOWN_SECONDS = int(os.getenv("BUY_COOLDOWN_SECONDS", "3600"))
        self.GAP_ALERT_PCT = float(os.getenv("GAP_ALERT_PCT", "0.08"))
        self.POSITION_NEWS_CHECK_INTERVAL_SEC = int(os.getenv("POSITION_NEWS_CHECK_INTERVAL_SEC", "1800"))

        # ── V2 Feature Flags ────────────────────────────────────
        self.USE_STRUCTURED_ANALYST = _bool(os.getenv("USE_STRUCTURED_ANALYST", "false"))
        self.USE_CHAIRMAN_DECISION = _bool(os.getenv("USE_CHAIRMAN_DECISION", "false"))

        # ── Watchlist ──────────────────────────────────────────
        watchlist_raw = os.getenv("WATCHLIST", "AAPL,MSFT,NVDA,TSLA,META,AMZN,GOOGL")
        self.WATCHLIST = [t.strip() for t in watchlist_raw.split(",") if t.strip()]

        # ── News API Keys ──────────────────────────────────────
        self.TAVILY_API_KEYS = self._split_keys(os.getenv("TAVILY_API_KEYS", ""))
        self.BRAVE_API_KEYS = self._split_keys(os.getenv("BRAVE_API_KEYS", ""))
        self.SERPAPI_API_KEYS = self._split_keys(os.getenv("SERPAPI_API_KEYS", ""))

        # ── FMP ────────────────────────────────────────────────
        fmp_raw = os.getenv("FMP_API_KEYS", os.getenv("FMP_API_KEY", ""))
        self.FMP_API_KEYS = self._split_keys(fmp_raw)

        # ── Notifications ──────────────────────────────────────
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
        self.HEALTHCHECK_URL = os.getenv("HEALTHCHECK_URL", "")

        # ── Dashboard ──────────────────────────────────────────
        self.DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")
        self.DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8899"))

    @staticmethod
    def _split_keys(raw: str) -> list[str]:
        return [k.strip() for k in raw.split(",") if k.strip()]

    def _validate_required(self) -> None:
        required = {
            "ALPACA_API_KEY": self.ALPACA_API_KEY,
            "ALPACA_API_SECRET": self.ALPACA_API_SECRET,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            log.warning("Missing required env vars: %s — set them in .env", ", ".join(missing))

    def dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
