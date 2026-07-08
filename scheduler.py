"""排程守護行程 — 全自動掃描→篩選→分析→監控。
支援動態 rebalancing、績效追蹤、regime-aware 排程。
"""

import os
import sys
import signal
import subprocess
import json
import logging
from logging.handlers import RotatingFileHandler
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import db as db_module
from config import Config
from health import ping
from file_utils import atomic_write_json
from event_bus import EventBus

_cfg = Config()
DATA_DIR = _cfg.DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(DATA_DIR / "scheduler.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).parent
PID_FILE = DATA_DIR / ".scheduler.pid"
STATUS_FILE = DATA_DIR / ".scheduler_status.json"
SHORTLIST_FILE = DATA_DIR / ".shortlist.json"


class Scheduler:
    def __init__(self, container=None):
        self.monitor_process = None
        self.running = True
        self._container = container
        self._check_single_instance()
        self._setup_signal_handlers()
        self._write_pid()
        self._last_perf_snapshot = 0
        self._last_daily_recap = 0
        self._last_watchlist_refresh = 0
        self._monitor_crash_count = 0
        self._max_monitor_restarts = 5

    def _check_single_instance(self):
        if PID_FILE.exists():
            try:
                old_pid = int(PID_FILE.read_text())
                os.kill(old_pid, 0)
                log.error(f"Another instance running (PID {old_pid}), exiting")
                sys.exit(1)
            except (OSError, ValueError):
                pass
            PID_FILE.unlink(missing_ok=True)

    # ── Daemon Infrastructure ────────────────────────────────

    def _setup_signal_handlers(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        log.info(f"Received {sig_name}, shutting down...")
        self.running = False

    def _write_pid(self):
        PID_FILE.write_text(str(os.getpid()))
        self._update_status("starting")

    def _cleanup_pid(self):
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    def _update_status(self, state: str, msg: str = ""):
        status = {
            "state": state,
            "pid": os.getpid(),
            "time": datetime.now(timezone.utc).isoformat(),
            "monitor_pid": self.monitor_process.pid if self.monitor_process else None,
            "message": msg,
        }
        atomic_write_json(STATUS_FILE, status)

    # ── Screener ─────────────────────────────────────────────

    def run_screener(self) -> list[str]:
        self._update_status("screening")
        log.info("=" * 60)
        log.info("STAGE 1: Technical Screening")

        universe_source = _cfg.UNIVERSE_SOURCE
        top_n = _cfg.SCREENER_TOP_N
        min_score = _cfg.SCREENER_MIN_SCORE
        workers = _cfg.SCREENER_WORKERS

        from universe import get_universe
        from screener import Screener

        universe = get_universe(universe_source)
        log.info(f"Universe: {len(universe)} stocks ({universe_source})")

        screener = Screener(max_workers=workers)
        results = screener.screen(universe, top_n=top_n, min_score=min_score)
        screener.print_summary(results)

        shortlist = [r.ticker for r in results]
        atomic_write_json(SHORTLIST_FILE, shortlist)
        log.info(f"Shortlisted {len(shortlist)} stocks for deep analysis.")
        return shortlist

    # ── Deep Analysis ────────────────────────────────────────

    def run_deep_analysis(self, tickers: list[str]):
        log.info("=" * 60)
        log.info(f"STAGE 2: Deep Analysis — {len(tickers)} stocks")
        self._update_status("analyzing")

        tickers_file = DATA_DIR / ".analyze_tickers.json"
        atomic_write_json(tickers_file, tickers)

        try:
            result = subprocess.run(
                [sys.executable, "deep_analyzer.py", str(tickers_file)],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=7200,
            )
            if result.returncode == 0:
                log.info("Deep analysis completed.")
                self._update_status("analysis_ok")
                self._mark_deep_analysis_run()
            else:
                stderr = result.stderr[:500]
                log.error(f"Deep analysis failed: {stderr}")
                self._update_status("analysis_failed", stderr)
        except subprocess.TimeoutExpired:
            log.error("Deep analysis timed out.")
            self._update_status("analysis_timeout")
        except Exception as e:
            log.error(f"Deep analysis error: {e}")
            self._update_status("analysis_error", str(e))

    def _should_run_deep_analysis(self) -> bool:
        return self._ts_older_than("deep_analysis", 7 * 24)

    def _mark_deep_analysis_run(self):
        self._ts_write("deep_analysis")

    # ── Timestamp Helpers ─────────────────────────────────────

    def _ts_path(self, name: str) -> Path:
        return DATA_DIR / f".last_{name}"

    def _ts_read(self, name: str) -> float:
        p = self._ts_path(name)
        try:
            return float(p.read_text().strip())
        except (ValueError, OSError):
            return 0.0

    def _ts_write(self, name: str):
        self._ts_path(name).write_text(str(time.time()))

    def _ts_age_hours(self, name: str) -> float:
        return (time.time() - self._ts_read(name)) / 3600

    def _ts_older_than(self, name: str, hours: float) -> bool:
        return self._ts_age_hours(name) >= hours

    # ── Priority Re-Analysis ──────────────────────────────────

    def _check_priority_reanalysis(self):
        priority_file = DATA_DIR / ".priority_reanalyze.json"
        if not priority_file.exists():
            return
        try:
            flagged = json.loads(priority_file.read_text())
        except Exception:
            return
        if not flagged:
            return

        log.info(f"Priority re-analysis requested for {len(flagged)} tickers: {flagged}")
        self._update_status("priority_analysis")
        for ticker in flagged:
            try:
                self.reanalyze_ticker(ticker)
            except Exception as e:
                log.error(f"[{ticker}] Priority re-analysis failed: {e}")
        priority_file.unlink(missing_ok=True)
        log.info("Priority re-analysis complete.")
        self._update_status("analysis_ok")

    def reanalyze_ticker(self, ticker: str):
        ratings_path = DATA_DIR / "ratings.json"

        result = subprocess.run(
            [sys.executable, "deep_analyzer.py", ticker],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            log.error(f"[{ticker}] reanalyze_ticker failed: {result.stderr[:300]}")
            return

        # 子行程 deep_analyzer.py 已將新評等寫入 ratings.json，此處重新讀取而非用分析前快照
        try:
            ratings = json.loads(ratings_path.read_text())
            if isinstance(ratings, dict):
                if ticker in ratings:
                    ratings[ticker]["reanalyzed_at"] = datetime.now(timezone.utc).isoformat()
                    from file_utils import atomic_write_json
                    atomic_write_json(ratings_path, ratings)
                    log.info(f"[{ticker}] Priority re-analysis done: new rating = {ratings[ticker].get('rating')}")
        except Exception as e:
            log.error(f"[{ticker}] Failed to stamp reanalyzed_at: {e}")

    # ── Mid-Week Re-Analysis ─────────────────────────────────

    def _check_midweek_reanalysis(self) -> bool:
        """如果帳戶單日 P&L 波動 >3% 或上次分析超過 3 天，觸發重新分析。"""
        if not self._ts_older_than("midweek", 12):
            return False

        last_run = DATA_DIR / ".last_deep_analysis"
        if not last_run.exists():
            return True

        age_hours = 0
        try:
            ts = float(last_run.read_text().strip())
            age_hours = (time.time() - ts) / 3600
        except (ValueError, OSError):
            return True

        if age_hours >= 72:
            return True

        try:
            if self._container is not None:
                tc = self._container.trading_client
            else:
                from alpaca.trading.client import TradingClient
                tc = TradingClient(
                    _cfg.ALPACA_API_KEY,
                    _cfg.ALPACA_API_SECRET,
                    paper=_cfg.IS_PAPER,
                )
            acct = tc.get_account()
            equity = float(acct.equity)
            last_eq = float(acct.last_equity)
            daily_change_pct = (equity - last_eq) / last_eq * 100 if last_eq > 0 else 0

            if abs(daily_change_pct) > 3.0:
                log.info(f"Triggering mid-week reanalysis: daily P&L swing {daily_change_pct:.1f}%")
                return True
        except Exception as e:
            log.warning(f"Mid-week check failed: {e}")

        return False

    # ── Performance Snapshot ─────────────────────────────────

    def _performance_snapshot(self):
        try:
            if self._container is not None:
                tc = self._container.trading_client
                tracker = self._container.performance_tracker
            else:
                from alpaca.trading.client import TradingClient
                from performance import PerformanceTracker
                tc = TradingClient(
                    _cfg.ALPACA_API_KEY,
                    _cfg.ALPACA_API_SECRET,
                    paper=_cfg.IS_PAPER,
                )
                tracker = PerformanceTracker(tc, config=_cfg)
            tracker.snapshot()
            tracker.print_summary()
            self._last_perf_snapshot = time.time()
        except Exception as e:
            log.warning(f"Performance snapshot failed: {e}")

    # ── Monitor Process ──────────────────────────────────────

    def start_monitor(self):
        log.info("STAGE 3: Starting price monitor...")
        monitor_log = open(DATA_DIR / "monitor_subprocess.log", "a")
        self.monitor_process = subprocess.Popen(
            [sys.executable, "monitor.py"],
            cwd=str(SCRIPT_DIR),
            stdout=monitor_log,
            stderr=subprocess.STDOUT,
        )
        log.info(f"Monitor PID: {self.monitor_process.pid}")
        self._update_status("monitoring")

    def stop_monitor(self):
        if self.monitor_process is None:
            return
        log.info("Stopping price monitor...")
        try:
            self.monitor_process.terminate()
            self.monitor_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.monitor_process.kill()
        self.monitor_process = None
        self._update_status("idle")

    def restart_monitor(self):
        self.stop_monitor()
        time.sleep(2)
        self.start_monitor()

    # ── Offline Learning ──────────────────────────────────────

    def _offline_learning_cycle(self):
        """盤後／非交易時段執行學習任務。

        STAGE 4: Offline Learning
          1. 同步 Obsidian vault 新筆記（knowledge_base.sync_vault）
          2. 處理 reflection queue（reflection_agent.batch_process）
        """
        if not self._ts_older_than("learning", 6):
            return

        from trading_calendar import is_market_open_now
        from datetime import timezone as dt_timezone
        now = datetime.now(dt_timezone.utc)
        if is_market_open_now(now):
            return

        log.info("=" * 60)
        log.info("STAGE 4: Offline Learning")

        try:
            from knowledge_base import KnowledgeBase
            kb = KnowledgeBase()
            updated = kb.sync_vault()
            if updated > 0:
                log.info(f"Knowledge base: {updated} new/updated documents")

            rules_count = kb.count_rules()
            log.info(f"Knowledge base: {kb.count_documents()} documents, {rules_count} rules")
        except Exception as e:
            log.warning(f"Knowledge base sync failed: {e}")

        try:
            from reflection_agent import ReflectionAgent
            agent = ReflectionAgent()
            qsize = agent.queue_size()
            if qsize > 0:
                log.info(f"Reflection queue: {qsize} pending")
                results = agent.batch_process()
                log.info(f"Reflection: {len(results)} trades reviewed")
        except Exception as e:
            log.warning(f"Reflection batch failed: {e}")

        # V2: Apply decay to rules and detect conflicts
        if self._container is not None:
            try:
                ms = self._container.memory_service
                ms._apply_decay()
                log.debug("V2 MemoryService: decay applied")
            except Exception as e:
                log.warning(f"V2 decay failed: {e}")
            try:
                # Detect conflicts for recently added rules
                recent_rules = db_module.load_rules(limit=20)
                for rule in recent_rules:
                    conflicts = ms.detect_conflict(rule)
                    if conflicts:
                        log.info(f"V2 Rule conflict detected: {rule.get('title', '')} conflicts with {len(conflicts)} existing rule(s)")
            except Exception as e:
                log.warning(f"V2 conflict detection failed: {e}")

        self._ts_write("learning")

    # ── Morning Status ───────────────────────────────────────

    def _log_morning_status(self):
        last_analysis = DATA_DIR / ".last_deep_analysis"
        if last_analysis.exists():
            ts = datetime.fromtimestamp(float(last_analysis.read_text().strip()))
            log.info(f"Last deep analysis: {ts.strftime('%Y-%m-%d %H:%M')}")
        if SHORTLIST_FILE.exists():
            shortlist = json.loads(SHORTLIST_FILE.read_text())
            log.info(f"Watchlist: {len(shortlist)} stocks")
        log.info(f"Monitor PID: {self.monitor_process.pid if self.monitor_process else 'N/A'}")
        log.info(f"Status file: {STATUS_FILE}")
        log.info(f"Logs: {DATA_DIR}/monitor.log, {DATA_DIR}/deep_analyzer.log")

    # ── Main Loop ────────────────────────────────────────────

    def run(self):
        EventBus.get_instance().emit("scheduler_started", {
            "pid": os.getpid(),
            "data_dir": str(DATA_DIR),
        })
        log.info("=" * 60)
        log.info("TRADING ENGINE DAEMON STARTED")
        log.info(f"PID: {os.getpid()}")
        log.info(f"Data dir: {DATA_DIR}")
        log.info("=" * 60)

        if self._should_run_deep_analysis():
            shortlist = self.run_screener()
            self.run_deep_analysis(shortlist)
        else:
            log.info("Using existing analysis (last run < 7 days).")
            if SHORTLIST_FILE.exists():
                shortlist = json.loads(SHORTLIST_FILE.read_text())
                log.info(f"Previous shortlist: {len(shortlist)} stocks")

        self.start_monitor()
        self._log_morning_status()

        while self.running:
            try:
                time.sleep(60)
                ping("scheduler")

                if self.monitor_process and self.monitor_process.poll() is not None:
                    self._monitor_crash_count += 1
                    if self._monitor_crash_count > self._max_monitor_restarts:
                        log.error(f"Monitor crashed {self._monitor_crash_count} times — HALTED")
                        self._update_status("halted")
                        break
                    backoff = min(2 ** self._monitor_crash_count, 120)
                    log.warning(f"Monitor crashed (#{self._monitor_crash_count}). Restarting in {backoff}s...")
                    time.sleep(backoff)
                    self.restart_monitor()

                now = time.time()

                if now - self._last_perf_snapshot > 3600:
                    self._performance_snapshot()

                if self._ts_older_than("daily_recap", 24):
                    self._ts_write("daily_recap")
                    log.info("Daily recap timestamp refreshed.")

                weekly = self._should_run_deep_analysis()
                midweek = self._check_midweek_reanalysis()

                if weekly or midweek:
                    reason = "Weekly cycle" if weekly else "Mid-week reanalysis triggered"
                    log.info(f"{reason} due.")

                    if weekly:
                        shortlist = self.run_screener()
                        self._ts_write("watchlist_refresh")
                    else:
                        shortlist = json.loads(SHORTLIST_FILE.read_text()) if SHORTLIST_FILE.exists() else self.run_screener()

                    self.run_deep_analysis(shortlist)
                    self._log_morning_status()

                self._check_priority_reanalysis()
                self._offline_learning_cycle()

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Scheduler error: {e}", exc_info=True)
                time.sleep(300)

        self.stop_monitor()
        try:
            if self._container is not None:
                self._container.order_manager.cancel_all_open()
                self._container.order_manager.eod_cleanup()
            else:
                from alpaca.trading.client import TradingClient
                from order_manager import OrderManager
                tc = TradingClient(
                    _cfg.ALPACA_API_KEY,
                    _cfg.ALPACA_API_SECRET,
                    paper=_cfg.IS_PAPER,
                )
                orders = OrderManager(tc, config=_cfg)
                orders.cancel_all_open()
                orders.eod_cleanup()
            log.info("Orders cleaned up on shutdown.")
        except Exception as e:
            log.warning(f"Order cleanup failed: {e}")
        EventBus.get_instance().emit("scheduler_shutdown", {})
        self._cleanup_pid()
        self._update_status("stopped")
        log.info("Scheduler shutdown complete.")


if __name__ == "__main__":
    from file_utils import validate_env
    validate_env("scheduler")
    scheduler = Scheduler()
    scheduler.run()
