from __future__ import annotations
"""SQLite 持久层 — WAL 模式保障崩溃安全 + 事务性读写。
逐步取代 file_utils.py 的文件式存储。
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = None  # lazy init in _get_conn
DB_PATH = None


def _setup_db_path():
    global DATA_DIR, DB_PATH
    from config import Config
    DATA_DIR = Config().DATA_DIR
    DB_PATH = DATA_DIR / "trading.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """取得线程本地连接（每个线程一条 connection，WAL 模式支持并发读）。"""
    if DB_PATH is None:
        _setup_db_path()
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


def init_db():
    """初始化数据库结构（幂等）。"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            client_id      TEXT PRIMARY KEY,
            ticker         TEXT NOT NULL,
            side           TEXT NOT NULL,
            qty_requested  INTEGER NOT NULL,
            qty_filled     INTEGER DEFAULT 0,
            status         TEXT DEFAULT 'pending',
            alpaca_order_id TEXT DEFAULT '',
            avg_fill_price REAL DEFAULT 0.0,
            reason         TEXT DEFAULT '',
            retry_count    INTEGER DEFAULT 0,
            bracket        INTEGER DEFAULT 0,
            bracket_sl     REAL,
            bracket_tp     REAL,
            reference_price REAL DEFAULT 0.0,
            sl_order_id    TEXT DEFAULT '',
            tp_order_id    TEXT DEFAULT '',
            error          TEXT DEFAULT '',
            created_at     TEXT DEFAULT '',
            updated_at     TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            time         TEXT NOT NULL,
            ticker       TEXT NOT NULL,
            side         TEXT NOT NULL,
            qty          INTEGER NOT NULL,
            price        REAL NOT NULL,
            client_id    TEXT DEFAULT '',
            alpaca_id    TEXT DEFAULT '',
            reason       TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS ratings (
            ticker           TEXT PRIMARY KEY,
            rating           TEXT DEFAULT 'Hold',
            price_target     REAL,
            time_horizon     TEXT,
            executive_summary TEXT DEFAULT '',
            investment_thesis TEXT DEFAULT '',
            analyzed_at      TEXT,
            error            TEXT,
            reanalyzed_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS performance (
            date           TEXT PRIMARY KEY,
            portfolio_value REAL DEFAULT 0,
            equity         REAL DEFAULT 0,
            cash           REAL DEFAULT 0,
            sharpe         REAL DEFAULT 0,
            sortino        REAL DEFAULT 0,
            max_drawdown   REAL DEFAULT 0,
            win_rate       REAL DEFAULT 0,
            total_trades   INTEGER DEFAULT 0,
            closed_trades  INTEGER DEFAULT 0,
            profit_factor  REAL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_ticker ON orders(ticker);
        CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(time);
        CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);

        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type   TEXT NOT NULL,
            event_id     TEXT,
            workflow_id  TEXT,
            trace_id     TEXT,
            occurred_at  TEXT NOT NULL,
            payload_json TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
        CREATE INDEX IF NOT EXISTS idx_events_workflow ON events(workflow_id);

        CREATE TABLE IF NOT EXISTS workflow_instances (
            id            TEXT PRIMARY KEY,
            current_state TEXT NOT NULL DEFAULT 'IDLE',
            context_json  TEXT DEFAULT '{}',
            trace_id      TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_workflow_state ON workflow_instances(current_state);

        CREATE TABLE IF NOT EXISTS agent_confidence_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name      TEXT NOT NULL,
            ticker          TEXT NOT NULL,
            predicted_rating TEXT NOT NULL,
            actual_outcome  TEXT NOT NULL,
            correct         INTEGER NOT NULL DEFAULT 0,
            confidence_raw  REAL DEFAULT 0.0,
            created_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_agent_log_name ON agent_confidence_log(agent_name);

        CREATE TABLE IF NOT EXISTS rules (
            id                TEXT PRIMARY KEY,
            title             TEXT NOT NULL,
            content           TEXT DEFAULT '',
            filepath          TEXT DEFAULT '',
            tags_json         TEXT DEFAULT '[]',
            source            TEXT DEFAULT 'reflection',
            confidence        REAL DEFAULT 1.0,
            created_at        TEXT NOT NULL,
            last_reinforced_at TEXT,
            decay_score       REAL DEFAULT 1.0,
            superseded_by     TEXT
        );

        CREATE TABLE IF NOT EXISTS rule_wikilinks (
            from_rule_id TEXT NOT NULL,
            to_rule_id   TEXT NOT NULL,
            weight       REAL DEFAULT 1.0,
            PRIMARY KEY (from_rule_id, to_rule_id)
        );
    """)
    conn.commit()


# ── Orders ─────────────────────────────────────────────────────

def save_order(order_dict: dict):
    """写入或更新一笔订单（upsert）。"""
    if order_dict is None:
        return
    conn = _get_conn()
    fields = {
        "client_id": order_dict.get("client_id", ""),
        "ticker": order_dict.get("ticker", ""),
        "side": order_dict.get("side", ""),
        "qty_requested": order_dict.get("qty_requested", 0),
        "qty_filled": order_dict.get("qty_filled", 0),
        "status": order_dict.get("status", "pending"),
        "alpaca_order_id": order_dict.get("alpaca_order_id", ""),
        "avg_fill_price": order_dict.get("avg_fill_price", 0.0),
        "reason": order_dict.get("reason", ""),
        "retry_count": order_dict.get("retry_count", 0),
        "bracket": 1 if order_dict.get("bracket") else 0,
        "bracket_sl": order_dict.get("bracket_sl"),
        "bracket_tp": order_dict.get("bracket_tp"),
        "reference_price": order_dict.get("reference_price", 0.0),
        "sl_order_id": order_dict.get("sl_order_id", ""),
        "tp_order_id": order_dict.get("tp_order_id", ""),
        "error": order_dict.get("error", ""),
        "created_at": order_dict.get("created_at", ""),
        "updated_at": order_dict.get("updated_at", ""),
    }
    conn.execute("""
        INSERT OR REPLACE INTO orders
        (client_id, ticker, side, qty_requested, qty_filled, status,
         alpaca_order_id, avg_fill_price, reason, retry_count,
         bracket, bracket_sl, bracket_tp, reference_price,
         sl_order_id, tp_order_id, error, created_at, updated_at)
        VALUES (:client_id, :ticker, :side, :qty_requested, :qty_filled, :status,
                :alpaca_order_id, :avg_fill_price, :reason, :retry_count,
                :bracket, :bracket_sl, :bracket_tp, :reference_price,
                :sl_order_id, :tp_order_id, :error, :created_at, :updated_at)
    """, fields)
    conn.commit()


def load_orders() -> dict:
    """回传 {client_id: dict} 格式的全部订单。"""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM orders").fetchall()
    result = {}
    for r in rows:
        d = dict(r)
        d["bracket"] = bool(d["bracket"])
        result[d.pop("client_id")] = d
    return result


def get_open_orders(ticker: str | None = None) -> list[dict]:
    conn = _get_conn()
    open_statuses = ("submitted", "partially_filled", "accepted", "new", "pending")
    if ticker:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status IN (?,?,?,?,?) AND ticker=?",
            (*open_statuses, ticker)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status IN (?,?,?,?,?)",
            open_statuses
        ).fetchall()
    return [dict(r) for r in rows]


# ── Trades ─────────────────────────────────────────────────────

def save_trade(trade_dict: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO trades (time, ticker, side, qty, price, client_id, alpaca_id, reason)
        VALUES (:time, :ticker, :side, :qty, :price, :client_id, :alpaca_id, :reason)
    """, {
        "time": trade_dict.get("time", datetime.now(timezone.utc).isoformat()),
        "ticker": trade_dict.get("ticker", ""),
        "side": trade_dict.get("side", ""),
        "qty": trade_dict.get("qty", 0),
        "price": trade_dict.get("price", 0.0),
        "client_id": trade_dict.get("client_id", ""),
        "alpaca_id": trade_dict.get("alpaca_id", ""),
        "reason": trade_dict.get("reason", ""),
    })
    conn.commit()


def load_trades(limit: int = 100) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY time DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Ratings ────────────────────────────────────────────────────

def save_ratings(ratings_dict: dict):
    """全量覆盖 ratings。"""
    if ratings_dict is None:
        return
    conn = _get_conn()
    conn.execute("BEGIN")
    conn.execute("DELETE FROM ratings")
    for ticker, info in ratings_dict.items():
        conn.execute("""
            INSERT INTO ratings (ticker, rating, price_target, time_horizon,
                                 executive_summary, investment_thesis,
                                 analyzed_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            info.get("rating", "Hold"),
            info.get("price_target"),
            info.get("time_horizon"),
            info.get("executive_summary", ""),
            info.get("investment_thesis", ""),
            info.get("analyzed_at"),
            info.get("error", ""),
        ))
    conn.commit()


def load_ratings() -> dict:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM ratings").fetchall()
    return {r["ticker"]: dict(r) for r in rows}


# ── Performance ────────────────────────────────────────────────

def save_performance_snapshot(perf_dict: dict):
    conn = _get_conn()
    ts = perf_dict.get("timestamp", datetime.now(timezone.utc).isoformat())
    date_str = ts[:10] if "T" in ts else ts
    acct = perf_dict.get("account", {})
    ts_data = perf_dict.get("trade_stats", {})
    rm = perf_dict.get("risk_metrics", {})
    conn.execute("""
        INSERT OR REPLACE INTO performance
        (date, portfolio_value, equity, cash, sharpe, sortino,
         max_drawdown, win_rate, total_trades, closed_trades, profit_factor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        date_str,
        acct.get("portfolio_value", 0),
        acct.get("equity", 0),
        acct.get("cash", 0),
        rm.get("sharpe_ratio", 0),
        rm.get("sortino_ratio", 0),
        rm.get("max_drawdown_pct", 0),
        ts_data.get("win_rate", 0),
        ts_data.get("total_trades", 0),
        ts_data.get("closed_trades", 0),
        ts_data.get("profit_factor", 0),
    ))
    conn.commit()


# ── V2: Events ──────────────────────────────────────────────────

def save_event(event_type: str, payload: dict, event_id: str = "",
               workflow_id: str = "", trace_id: str = ""):
    conn = _get_conn()
    conn.execute("""
        INSERT INTO events (event_type, event_id, workflow_id, trace_id, occurred_at, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        event_type, event_id, workflow_id, trace_id,
        datetime.now(timezone.utc).isoformat(),
        json.dumps(payload, default=str),
    ))
    conn.commit()


def get_events(trace_id: str = "", event_type: str = "",
               workflow_id: str = "", limit: int = 100) -> list[dict]:
    conn = _get_conn()
    params = []
    clauses = []
    if trace_id:
        clauses.append("trace_id = ?")
        params.append(trace_id)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if workflow_id:
        clauses.append("workflow_id = ?")
        params.append(workflow_id)

    where = " AND ".join(clauses) if clauses else "1=1"
    rows = conn.execute(
        f"SELECT * FROM events WHERE {where} ORDER BY id DESC LIMIT ?",
        (*params, limit)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json", "{}"))
        except Exception:
            d["payload"] = {}
        result.append(d)
    return result


# ── V2: Workflow Instances ──────────────────────────────────────

def save_workflow(instance: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO workflow_instances
        (id, current_state, context_json, trace_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        instance["id"],
        instance.get("current_state", "IDLE"),
        json.dumps(instance.get("context", {}), default=str),
        instance.get("trace_id", ""),
        instance.get("created_at", datetime.now(timezone.utc).isoformat()),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()


def load_workflow(workflow_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM workflow_instances WHERE id = ?", (workflow_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["context"] = json.loads(d.pop("context_json", "{}"))
    except Exception:
        d["context"] = {}
    return d


def list_workflows(limit: int = 10) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM workflow_instances ORDER BY updated_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── V2: Agent Confidence Log ────────────────────────────────────

def save_agent_confidence(agent_name: str, ticker: str,
                          predicted: str, actual: str, correct: bool,
                          confidence_raw: float = 0.0):
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO agent_confidence_log
            (agent_name, ticker, predicted_rating, actual_outcome, correct, confidence_raw, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_name, ticker, predicted, actual, int(correct),
            confidence_raw, datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    except Exception:
        log.debug("agent_confidence_log table not available yet")


def get_agent_accuracy(agent_name: str, lookback: int = 90) -> float:
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT CAST(SUM(correct) AS REAL) / COUNT(*) as acc
            FROM (
                SELECT correct FROM agent_confidence_log
                WHERE agent_name = ?
                ORDER BY id DESC LIMIT ?
            )
        """, (agent_name, lookback)).fetchone()
        if row and row["acc"] is not None:
            return row["acc"]
    except Exception:
        log.debug("agent_confidence_log table not available yet")
    return 0.5


# ── V2: Rules ───────────────────────────────────────────────────

def save_rule(rule: dict):
    conn = _get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO rules
        (id, title, content, filepath, tags_json, source,
         confidence, created_at, last_reinforced_at, decay_score, superseded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rule["id"], rule["title"], rule.get("content", ""),
        rule.get("filepath", ""), json.dumps(rule.get("tags", [])),
        rule.get("source", "reflection"),
        rule.get("confidence", 1.0),
        rule.get("created_at", datetime.now(timezone.utc).isoformat()),
        rule.get("last_reinforced_at"),
        rule.get("decay_score", 1.0),
        rule.get("superseded_by"),
    ))
    conn.commit()


def load_rules(limit: int = 100) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM rules ORDER BY decay_score DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def reinforce_rule(rule_id: str, confidence_delta: float = 0.1):
    conn = _get_conn()
    conn.execute("""
        UPDATE rules SET
            confidence = MIN(1.0, confidence + ?),
            last_reinforced_at = ?,
            decay_score = MIN(1.0, decay_score + ?)
        WHERE id = ?
    """, (confidence_delta, datetime.now(timezone.utc).isoformat(),
          confidence_delta, rule_id))
    conn.commit()


def find_similar_rules_by_tags(tags: list[str], min_confidence: float = 0.3) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM rules WHERE confidence >= ? ORDER BY decay_score DESC LIMIT 20",
        (min_confidence,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            rule_tags = json.loads(d.get("tags_json", "[]"))
        except Exception:
            rule_tags = []
        if any(t in rule_tags for t in tags):
            result.append(d)
    return result
