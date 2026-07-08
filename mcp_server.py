"""MCP Server — 將 Trading Engine 暴露為 MCP 工具供 AI 助手呼叫。

啟動： python mcp_server.py
通訊協定： JSON-RPC 2.0 over stdio（標準 MCP 傳輸）。

可用工具：
  - get_account    — 帳戶摘要
  - get_positions  — 持倉列表
  - get_regime     — 市場 regime
  - get_ratings    — 評級列表
  - portfolio_stats — 績效統計
  - recent_trades  — 近期交易
  - knowledge_stats — 知識庫統計
  - query_rules    — 查詢交易規則
  - get_knowledge  — 語意搜尋知識庫
  - get_config     — 目前設定（不含敏感值）
"""

from __future__ import annotations
import json
import sys
import logging
from typing import Any

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

import db
from container import ModuleContainer

_container: ModuleContainer | None = None


def _get_container() -> ModuleContainer:
    global _container
    if _container is None:
        _container = ModuleContainer()
    return _container


# ── Tool Definitions (MCP schema) ─────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_account",
        "description": "取得 Alpaca 交易帳戶摘要（權益、現金、購買力）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_positions",
        "description": "取得目前所有持倉",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_regime",
        "description": "取得目前市場 regime（bull/bear/ranging/high_vol）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_ratings",
        "description": "取得目前所有 ticker 的評級",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "portfolio_stats",
        "description": "取得投資組合績效統計（Sharpe、MDD、勝率等）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "recent_trades",
        "description": "取得近期交易記錄",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "回傳筆數", "default": 20},
            },
        },
    },
    {
        "name": "knowledge_stats",
        "description": "取得知識庫統計",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_rules",
        "description": "查詢符合當前情境的交易規則",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "股票代號（選填）"},
                "sector": {"type": "string", "description": "產業（選填）"},
                "regime": {"type": "string", "description": "市場 regime（選填）"},
                "k": {"type": "integer", "description": "回傳數量", "default": 5},
            },
        },
    },
    {
        "name": "get_knowledge",
        "description": "語意搜尋知識庫",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋文字"},
                "k": {"type": "integer", "description": "回傳數量", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_config",
        "description": "取得目前系統設定（不含秘密）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_workflow_status",
        "description": "取得目前工作流狀態（最近 5 筆）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_decision_trail",
        "description": "取得指定 ticker 或 trace_id 的完整決策鏈",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "股票代號（選填）"},
                "trace_id": {"type": "string", "description": "追蹤 ID（選填）"},
            },
        },
    },
    {
        "name": "get_agent_accuracy",
        "description": "取得各 agent 的 rolling accuracy",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ── Tool Handlers ──────────────────────────────────────────────

async def _handle_tool(name: str, args: dict) -> Any:
    c = _get_container()

    if name == "get_account":
        try:
            acct = c.account_provider.get_account_summary()
            return {"cash": acct.cash, "portfolio_value": acct.portfolio_value,
                    "buying_power": acct.buying_power, "equity": acct.equity,
                    "daytrade_count": acct.daytrade_count, "stale": acct.stale}
        except Exception as e:
            return {"error": str(e)}

    if name == "get_positions":
        try:
            positions = c.account_provider.get_positions()
            return {t: {"qty": p.qty, "avg_entry": p.avg_entry_price,
                        "current": p.current_price, "market_value": p.market_value,
                        "unrealized_pl": p.unrealized_pl, "unrealized_plpc": p.unrealized_plpc}
                    for t, p in positions.items()}
        except Exception as e:
            return {"error": str(e)}

    if name == "get_regime":
        try:
            regime = c.regime_detector.detect()
            return {k: v for k, v in regime.items() if not k.startswith("_")}
        except Exception as e:
            return {"error": str(e)}

    if name == "get_ratings":
        try:
            from file_utils import read_json
            ratings = read_json(c.config.DATA_DIR / "ratings.json")
            return {t: {"rating": r.get("rating", ""),
                        "price_target": r.get("price_target", ""),
                        "analyzed_at": r.get("analyzed_at", "")}
                    for t, r in ratings.items()}
        except Exception as e:
            return {"error": str(e)}

    if name == "portfolio_stats":
        try:
            perf = c.performance_tracker
            result = perf.analyze_trades()
            return result
        except Exception as e:
            return {"error": str(e)}

    if name == "recent_trades":
        try:
            import db
            db.init_db()
            trades = db.load_trades(limit=args.get("limit", 20))
            return trades
        except Exception as e:
            return {"error": str(e)}

    if name == "knowledge_stats":
        try:
            return c.knowledge_base.get_stats()
        except Exception as e:
            return {"error": str(e)}

    if name == "query_rules":
        try:
            context = {k: args[k] for k in ("ticker", "sector", "regime") if args.get(k)}
            rules = c.knowledge_base.query_rules(context, k=args.get("k", 5))
            return [{"title": r.title, "content": r.content[:300], "tags": r.tags,
                     "source": r.source, "filepath": r.filepath} for r in rules]
        except Exception as e:
            return {"error": str(e)}

    if name == "get_knowledge":
        try:
            entries = c.knowledge_base.query(args["query"], k=args.get("k", 5))
            return [{"title": e.title, "content": e.content[:300], "tags": e.tags,
                     "source": e.source, "filepath": e.filepath} for e in entries]
        except Exception as e:
            return {"error": str(e)}

    if name == "get_config":
        cfg = c.config
        safe = {k: v for k, v in cfg.dict().items()
                if not any(secret in k.upper() for secret in ("KEY", "SECRET", "TOKEN", "PASSWORD"))}
        return safe

    if name == "get_workflow_status":
        try:
            workflows = db.list_workflows(limit=5)
            result = []
            for w in workflows:
                result.append({
                    "id": w["id"],
                    "current_state": w["current_state"],
                    "trace_id": w["trace_id"],
                    "created_at": w["created_at"],
                    "updated_at": w["updated_at"],
                })
            return result
        except Exception as e:
            return {"error": str(e)}

    if name == "get_decision_trail":
        try:
            trace_id = args.get("trace_id", "")
            ticker = args.get("ticker", "")
            if trace_id:
                events = db.get_events(trace_id=trace_id, limit=50)
            elif ticker:
                safe_ticker = ticker.replace("%", r"\%").replace("_", r"\_")
                conn = db._get_conn()
                rows = conn.execute(
                    "SELECT * FROM events WHERE payload_json LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 50",
                    (f"%{safe_ticker}%",)
                ).fetchall()
                events = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["payload"] = json.loads(d.pop("payload_json", "{}"))
                    except Exception:
                        d["payload"] = {}
                    events.append(d)
            else:
                return {"error": "Provide ticker or trace_id"}
            return [
                {
                    "event_type": e["event_type"],
                    "event_id": e["event_id"],
                    "workflow_id": e["workflow_id"],
                    "trace_id": e["trace_id"],
                    "occurred_at": e["occurred_at"],
                    "payload": e.get("payload", {}),
                }
                for e in events
            ]
        except Exception as e:
            return {"error": str(e)}

    if name == "get_agent_accuracy":
        try:
            conn = db._get_conn()
            rows = conn.execute(
                "SELECT DISTINCT agent_name FROM agent_confidence_log"
            ).fetchall()
            agents = [r["agent_name"] for r in rows]
            result = {}
            for agent in agents:
                acc = db.get_agent_accuracy(agent)
                result[agent] = round(acc, 4)
            return result
        except Exception as e:
            return {"error": str(e)}

    return {"error": f"Unknown tool: {name}"}


# ── JSON-RPC 2.0 over stdio ────────────────────────────────────

def _read_message() -> dict | None:
    """從 stdin 讀取一封 MCP 訊息（JSON-RPC 2.0）。"""
    try:
        raw = sys.stdin.readline()
        if not raw:
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, EOFError):
        return None


def _write_message(msg: dict):
    """寫入一封 MCP 訊息到 stdout。"""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


async def _process_request(req: dict) -> dict:
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "trading-engine-mcp", "version": "0.1.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            result = await _handle_tool(name, arguments)
            content = [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": content}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": str(e)}}

    if method == "notifications/initialized":
        return None  # no response for notifications

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


async def main():
    """主循環：讀取 stdin → 處理 → 寫入 stdout。"""
    while True:
        req = _read_message()
        if req is None:
            break
        resp = await _process_request(req)
        if resp is not None:
            _write_message(resp)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
