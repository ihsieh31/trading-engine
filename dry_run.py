#!/usr/bin/env python3
"""Dry-run: 載入所有模組、檢查 API 連線、跑一次篩選，不下單。"""

import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dry_run")

PASS = 0
FAIL = 0

def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        log.info(f"  ✅ {label}")
    else:
        FAIL += 1
        log.error(f"  ❌ {label} — {detail}")

def step(name):
    log.info("")
    log.info("=" * 60)
    log.info(f"  {name}")
    log.info("=" * 60)

step("1. 環境變數與 Config")
from config import Config
cfg = Config()
check("Config() 建立成功", True)
check("IS_PAPER", cfg.IS_PAPER, f"IS_PAPER={cfg.IS_PAPER}")
check("WATCHLIST 不為空", len(cfg.WATCHLIST) > 0, f"WATCHLIST={cfg.WATCHLIST}")
check("ALPACA_API_KEY 存在", bool(cfg.ALPACA_API_KEY))
check("ALPACA_API_SECRET 存在", bool(cfg.ALPACA_API_SECRET))

step("2. 模組匯入")
modules = [
    "db", "config", "event_bus", "adapters", "container",
    "interfaces_v2", "strategy", "regime", "screener",
    "portfolio_manager", "order_manager", "performance",
    "monitor", "scheduler", "deep_analyzer", "reflection_agent",
    "knowledge_base", "sector_map", "trading_calendar",
    "safety", "file_utils", "news_service", "notifier",
    "agents.base", "agents.risk_agent", "agents.chairman_agent",
    "core.workflow_engine", "memory.memory_service",
]
for m in modules:
    try:
        __import__(m)
        check(f"import {m}", True)
    except Exception as e:
        check(f"import {m}", False, str(e))

step("3. Alpaca API 連線")
try:
    from alpaca.trading.client import TradingClient
    tc = TradingClient(cfg.ALPACA_API_KEY, cfg.ALPACA_API_SECRET, paper=cfg.IS_PAPER)
    acct = tc.get_account()
    check("get_account() 成功", True, f"status={acct.status}, equity={acct.equity}, daytrade_count={acct.daytrade_count}")
    check("帳戶狀態為 ACTIVE", acct.status == "ACTIVE", acct.status)
except Exception as e:
    check("Alpaca API 連線", False, str(e))
    tc = None

step("4. 交易日曆")
from trading_calendar import is_market_open_now, get_trading_hours_et, is_trading_day
try:
    now = time.time()
    open_now = is_market_open_now()
    hours = get_trading_hours_et()
    check("is_market_open_now()", True, f"open={open_now}")
    check("get_trading_hours_et()", hours.get("is_trading_day") is not None, f"result={hours}")
except Exception as e:
    check("交易日曆", False, str(e))

step("5. 取得目前持倉與帳戶")
if tc:
    try:
        positions = tc.get_all_positions()
        check(f"get_all_positions()", True, f"{len(positions)} 筆持倉")
    except Exception as e:
        check("get_all_positions()", False, str(e))

step("6. 知識庫初始化")
try:
    from knowledge_base import KnowledgeBase
    kb = KnowledgeBase()
    check("KnowledgeBase() 建立", True)
    check("chromadb 可用", kb._chromadb_ok)
except Exception as e:
    check("知識庫初始化", False, str(e))

step("7. V2 元件初始化")
from container import ModuleContainer
try:
    container = ModuleContainer()
    check("ModuleContainer() 建立", True)
    ra = container.risk_agent
    check("risk_agent 可用", ra is not None)
    ca = container.chairman_agent
    check("chairman_agent 可用", ca is not None)
except Exception as e:
    check("V2 容器初始化", False, str(e))

step("8. 執行一次 Screener 篩選")
from screener import Screener
try:
    screener = Screener(max_workers=4)
    results = screener.screen(cfg.WATCHLIST[:5], top_n=5)
    check("篩選器完成", True, f"掃描 {len(cfg.WATCHLIST[:5])} 標的，取得 {len(results)} 結果")
    if results:
        best = results[0]
        check("篩選結果範例", True, f"{best.ticker} score={best.score} rsi={best.rsi} signals={best.signals}")
except Exception as e:
    check("Screener 執行", False, str(e))

step("9. SQLite 資料庫")
import db
try:
    db.init_db()
    rules = db.load_rules()
    check("init_db + load_rules", True, f"{len(rules)} 條規則")
    events = db.get_events(limit=5)
    check("get_events", True, f"{len(events)} 筆事件")
except Exception as e:
    check("資料庫操作", False, str(e))

step("10. MemoryService 與 WorkflowEngine")
try:
    from memory.memory_service import MemoryService
    ms = MemoryService()
    check("MemoryService() 建立", True)
    ms._apply_decay()
    check("_apply_decay() 不拋錯", True)
except Exception as e:
    check("MemoryService", False, str(e))

try:
    from core.workflow_engine import WorkflowEngine
    we = WorkflowEngine(container)
    check("WorkflowEngine() 建立", True)
    state = we.get_state()
    check("workflow.get_state()", True, str(state))
except Exception as e:
    check("WorkflowEngine", False, str(e))

step("11. Performance 計算")
try:
    from performance import PerformanceTracker
    pt = PerformanceTracker(tc)
    perf = pt.snapshot()
    check("PerformanceTracker.snapshot()", True, f"{len(perf)} keys")
except Exception as e:
    check("PerformanceTracker", False, str(e))

step("12. Regime 偵測")
try:
    from regime import RegimeDetector
    rd = RegimeDetector()
    regime = rd.detect()
    check("regime.detect()", True, f"regime={regime.get('regime')} size_mult={regime.get('position_size_mult')}")
except Exception as e:
    check("RegimeDetector", False, str(e))

log.info("")
log.info("=" * 60)
log.info(f"  Dry-Run 完成：{PASS} ✅ / {FAIL} ❌ / {PASS+FAIL} 總檢查項")
log.info("=" * 60)

if FAIL > 0:
    sys.exit(1)
