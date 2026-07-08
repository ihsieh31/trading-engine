from __future__ import annotations
"""自動熔斷保護 — 每日虧損上限 + MDD 保護。

啟動時讀取 .breaker 檔保留熔斷狀態。
delete .breaker 檔 = 手動復原。
"""

import json
import time
import logging
from datetime import datetime, timezone, date
from pathlib import Path
from trading_calendar import today_et
from notifier import send_message
from file_utils import atomic_write_json
from config import Config

log = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self, trading_client, config: Config | None = None):
        self.tc = trading_client
        cfg = config or Config()
        self.max_daily_loss = cfg.MAX_DAILY_LOSS_PCT
        self.max_drawdown = cfg.MAX_DRAWDOWN_PCT
        self.BREAKER_FILE = cfg.DATA_DIR / ".breaker"

        self.tripped = False
        self.peak_value = 0.0
        self.day_start_value = 0.0
        self.today_key = ""

        self._load()

    def _state_path(self):
        return self.BREAKER_FILE.parent / ".breaker_state.json"

    def _load(self):
        if self.BREAKER_FILE.exists():
            self.tripped = True
            log.warning("CIRCUIT BREAKER TRIPPED — skipping all trades. Delete .breaker to reset.")

        state = self._state_path()
        if state.exists():
            try:
                data = json.loads(state.read_text())
                self.peak_value = data.get("peak", 0.0)
                self.day_start_value = data.get("day_start", 0.0)
                self.today_key = data.get("today_key", "")
            except Exception:
                pass

    def _save(self):
        state = {
            "peak": self.peak_value,
            "day_start": self.day_start_value,
            "today_key": self.today_key,
            "tripped": self.tripped,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_json(self._state_path(), state)

    def check(self, portfolio_value: float) -> bool:
        if self.tripped:
            return True

        if portfolio_value <= 0:
            log.warning(f"Breaker check skipped: invalid portfolio_value={portfolio_value}")
            return False

        self.peak_value = max(self.peak_value, portfolio_value)

        today = today_et().isoformat()
        if today != self.today_key:
            try:
                last_eq = float(self.tc.get_account().last_equity)
                self.day_start_value = last_eq if last_eq > 0 else portfolio_value
            except Exception:
                self.day_start_value = portfolio_value
            self.today_key = today

        daily_pct = (portfolio_value - self.day_start_value) / self.day_start_value * 100
        drawdown_pct = (portfolio_value - self.peak_value) / self.peak_value * 100

        if -daily_pct >= self.max_daily_loss * 100:
            cross_check_upl = 0.0
            cross_check_ok = False
            try:
                pos_list = self.tc.get_all_positions()
                cross_check_upl = sum(float(p.unrealized_pl) for p in pos_list)
                cross_check_ok = True
            except Exception:
                pass
            if cross_check_ok and cross_check_upl >= 0 and daily_pct < -1:
                log.warning(f"Daily loss {daily_pct:.1f}% but positions show profit ${cross_check_upl:.0f} — likely deposit/withdrawal, skipping breaker")
            else:
                log.error(f"CIRCUIT BREAKER: Daily loss {daily_pct:.1f}% exceeds {self.max_daily_loss*100:.0f}% limit")
                self._trip()
                return True

        if -drawdown_pct >= self.max_drawdown * 100:
            log.error(f"CIRCUIT BREAKER: Drawdown {drawdown_pct:.1f}% exceeds {self.max_drawdown*100:.0f}% limit")
            self._trip()
            return True

        self._save()
        return False

    def _trip(self):
        self.tripped = True
        atomic_write_json(self.BREAKER_FILE, {"tripped_at": datetime.now(timezone.utc).isoformat()})
        self._save()
        log.error("CIRCUIT BREAKER ACTIVATED — delete .breaker to resume trading")
        send_message("🚨 CIRCUIT BREAKER TRIPPED — trading halted. Delete .breaker to resume.")

    def reset(self):
        if self.BREAKER_FILE.exists():
            self.BREAKER_FILE.unlink()
        if self._state_path().exists():
            self._state_path().unlink()
        self.tripped = False
        self.peak_value = 0.0
        self.day_start_value = 0.0
        self.today_key = ""
        log.info("Circuit breaker reset")
