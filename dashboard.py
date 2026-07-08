"""Trading Engine Dashboard — localhost web 監控面板。
啟動： python dashboard.py [port]
訪問： http://localhost:8899
"""

import json
import math
import time
import secrets
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from config import Config
from flask import Flask, jsonify, send_file, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_cfg = Config()
DATA_DIR = _cfg.DATA_DIR
DASHBOARD_TOKEN = _cfg.DASHBOARD_TOKEN
if not DASHBOARD_TOKEN:
    DASHBOARD_TOKEN = secrets.token_hex(32)
    log.info(f"DASHBOARD_TOKEN not set — generated random token: {DASHBOARD_TOKEN}")
    log.info("Set DASHBOARD_TOKEN in .env to use a fixed token.")

_container = None


def configure(container=None):
    global _container
    _container = container


app = Flask(__name__)


@app.after_request
def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:8899"
    response.headers["Access-Control-Allow-Headers"] = "X-Dashboard-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# ── NaN Sanitizer ───────────────────────────────────────────────

def clean(v):
    """Recursively replace NaN/Inf with None so JSON is always valid."""
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, dict):
        return {k: clean(v) for k, v in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def safe_json(v, default=None):
    """Convert NaN/Inf to None, pass other values through."""
    if v is None:
        return default
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return default
    return v


def safe_float(v, default=0.0):
    """Parse float, return default on failure, None on NaN/Inf."""
    try:
        x = float(v) if v is not None else default
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return default


@app.before_request
def _check_token():
    if not DASHBOARD_TOKEN:
        return None
    token = request.headers.get("X-Dashboard-Token", "")
    if token != DASHBOARD_TOKEN:
        return jsonify(clean({"error": "unauthorized"})), 401

# ── Helpers ──────────────────────────────────────────────────────

def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def read_jsonl(path: Path, n: int = 30) -> list:
    if not path.exists():
        return []
    try:
        lines = path.read_text().strip().split("\n")
        return [json.loads(l) for l in lines if l.strip()][-n:]
    except Exception:
        return []


# ── API Endpoints ─────────────────────────────────────────────────

@app.route("/")
def index():
    html_path = Path(__file__).parent / "dashboard.html"
    if html_path.exists():
        return html_path.read_text()
    return "Dashboard HTML not found", 404


@app.route("/api/status")
def api_status():
    s = read_json(DATA_DIR / ".scheduler_status.json")
    pid = s.get("pid")
    uptime = ""
    if pid:
        try:
            import psutil
            p = psutil.Process(pid)
            created = datetime.fromtimestamp(p.create_time())
            uptime = str(datetime.now() - created).split(".")[0]
        except Exception:
            pass
    return jsonify(clean({
        "state": s.get("state", "unknown"),
        "pid": pid,
        "uptime": uptime,
        "time": s.get("time", ""),
        "message": s.get("message", ""),
        "monitor_pid": s.get("monitor_pid"),
    }))


@app.route("/api/regime")
def api_regime():
    r = read_json(DATA_DIR / "portfolio_snapshot.json").get("regime", {})
    if not r:
        from regime import RegimeDetector
        try:
            r = RegimeDetector().detect()
        except Exception:
            r = {}
    return jsonify(clean({
        "regime": r.get("regime", "unknown"),
        "spy_price": safe_json(r.get("spy_price")),
        "ma50": safe_json(r.get("ma50")),
        "ma200": safe_json(r.get("ma200")),
        "position_size_mult": safe_json(r.get("position_size_mult"), 1.0),
        "price_vs_ma50_pct": safe_json(r.get("price_vs_ma50_pct")),
        "price_vs_ma200_pct": safe_json(r.get("price_vs_ma200_pct")),
        "atr_pct": safe_json(r.get("atr_pct")),
        "atr_percentile": safe_json(r.get("atr_percentile")),
    }))


@app.route("/api/account")
def api_account():
    try:
        if _container is not None:
            tc = _container.trading_client
        else:
            from alpaca.trading.client import TradingClient
            tc = TradingClient(_cfg.ALPACA_API_KEY, _cfg.ALPACA_API_SECRET, paper=_cfg.IS_PAPER)
        acct = tc.get_account()
        positions = tc.get_all_positions()

        pos_list = []
        total_pnl = 0.0
        sector_exposure = {}
        from sector_map import get_sector
        for p in positions:
            qty = safe_float(p.qty)
            if abs(qty or 0) < 0.001:
                continue
            upnl = safe_float(p.unrealized_pl)
            mval = safe_float(p.market_value)
            total_pnl += upnl or 0
            ticker = p.symbol
            sector = get_sector(ticker)
            sector_exposure[sector] = sector_exposure.get(sector, 0) + (mval or 0)
            pos_list.append({
                "ticker": ticker,
                "qty": qty,
                "avg_entry": safe_float(p.avg_entry_price),
                "current_price": safe_float(p.current_price),
                "market_value": mval,
                "unrealized_pnl": upnl,
                "unrealized_plpc": safe_float(p.unrealized_plpc) * 100 if p.unrealized_plpc else None,
                "change_today": safe_float(p.change_today) * 100 if p.change_today else None,
                "sector": sector,
            })

        portfolio_value = safe_float(acct.portfolio_value)
        sector_pcts = {s: round(v / portfolio_value * 100, 1) if portfolio_value else 0
                       for s, v in sorted(sector_exposure.items(), key=lambda x: -x[1])}

        return jsonify(clean({
            "cash": safe_float(acct.cash),
            "portfolio_value": portfolio_value,
            "buying_power": safe_float(acct.buying_power),
            "equity": safe_float(acct.equity),
            "last_equity": safe_float(acct.last_equity),
            "positions": pos_list,
            "total_unrealized_pnl": round(total_pnl, 2) if total_pnl else 0,
            "position_count": len(pos_list),
            "day_trade_count": int(safe_float(acct.daytrade_count) or 0),
            "sector_exposure": sector_pcts,
        }))
    except Exception as e:
        log.warning(f"Account API failed: {e}")
        return jsonify(clean({"error": str(e)})
)

@app.route("/api/ratings")
def api_ratings():
    ratings = read_json(DATA_DIR / "ratings.json")
    now = datetime.now(timezone.utc)

    results = []
    for ticker, info in ratings.items():
        analyzed_at = info.get("analyzed_at", "")
        age_days = None
        if analyzed_at:
            try:
                adt = datetime.fromisoformat(analyzed_at)
                if adt.tzinfo is None:
                    adt = adt.replace(tzinfo=timezone.utc)
                age_days = (now - adt).total_seconds() / 86400
            except Exception:
                pass
        results.append({
            "ticker": ticker,
            "rating": info.get("rating", "Hold"),
            "price_target": info.get("price_target"),
            "time_horizon": info.get("time_horizon", ""),
            "executive_summary": info.get("executive_summary", ""),
            "investment_thesis": info.get("investment_thesis", ""),
            "error": info.get("error", ""),
            "analyzed_at": analyzed_at,
            "age_days": round(age_days, 1) if age_days is not None else None,
        })

    last_run = DATA_DIR / ".last_deep_analysis"
    last_analysis_time = ""
    if last_run.exists():
        try:
            ts = float(last_run.read_text().strip())
            last_analysis_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    currently_analyzing = []
    ca_file = DATA_DIR / ".currently_analyzing"
    if ca_file.exists():
        try:
            meta = json.loads(ca_file.read_text())
            currently_analyzing = meta if isinstance(meta, list) else meta.get("tickers", [])
        except Exception:
            currently_analyzing = []

    return jsonify(clean({
        "ratings": results,
        "count": len(results),
        "last_analysis": last_analysis_time,
        "analyzing": currently_analyzing,
    }))


@app.route("/api/orders")
def api_orders():
    orders = read_json(DATA_DIR / "orders.json")
    order_list = []
    for cid, o in orders.items():
        order_list.append({
            "client_id": cid,
            "ticker": o.get("ticker", ""),
            "side": o.get("side", ""),
            "qty_requested": safe_json(o.get("qty_requested"), 0),
            "qty_filled": safe_json(o.get("qty_filled"), 0),
            "status": o.get("status", ""),
            "avg_fill_price": safe_json(o.get("avg_fill_price"), 0),
            "reason": o.get("reason", ""),
            "created_at": o.get("created_at", ""),
            "retry_count": safe_json(o.get("retry_count"), 0),
            "error": o.get("error", ""),
        })
    order_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    by_status = {}
    for o in order_list:
        s = o["status"]
        by_status[s] = by_status.get(s, 0) + 1

    return jsonify(clean({
        "orders": order_list[:50],
        "total": len(order_list),
        "by_status": by_status,
    }))


@app.route("/api/trades")
def api_trades():
    trades = read_jsonl(DATA_DIR / "trades.jsonl", 50)
    trades.reverse()
    return jsonify(clean(trades))


@app.route("/api/performance")
def api_performance():
    perf = read_json(DATA_DIR / "performance.json")
    ts = perf.get("trade_stats", {})
    rm = perf.get("risk_metrics", {})
    acct = perf.get("account", {})

    eq = perf.get("equity_curve", {})
    equity_points = []
    if eq.get("timestamps") and eq.get("equity"):
        for ts_s, val in zip(eq["timestamps"][-60:], eq["equity"][-60:]):
            try:
                ts_str = datetime.fromtimestamp(ts_s).strftime("%m/%d") if isinstance(ts_s, (int, float)) else str(ts_s)[5:10]
                equity_points.append({"date": ts_str, "value": round(val, 2)})
            except Exception:
                pass

    history = []
    hist_path = DATA_DIR / "performance_history.json"
    if hist_path.exists():
        try:
            history = json.loads(hist_path.read_text())
        except Exception:
            pass

    return jsonify(clean({
        "equity_curve": equity_points,
        "history": history[-90:],
        "portfolio_value": safe_json(acct.get("portfolio_value"), 0),
        "win_rate": safe_json(ts.get("win_rate"), 0),
        "profit_factor": safe_json(ts.get("profit_factor"), 0),
        "total_trades": safe_json(ts.get("total_trades"), 0),
        "closed_trades": safe_json(ts.get("closed_trades"), 0),
        "sharpe": safe_json(rm.get("sharpe_ratio"), 0),
        "sortino": safe_json(rm.get("sortino_ratio"), 0),
        "max_drawdown": safe_json(rm.get("max_drawdown_pct"), 0),
        "volatility": safe_json(rm.get("annualized_volatility_pct"), 0),
        "avg_daily_return": safe_json(rm.get("avg_daily_return_pct"), 0),
    }))


@app.route("/api/analysis-queue")
def api_analysis_queue():
    tickers_file = DATA_DIR / ".analyze_tickers.json"
    if not tickers_file.exists():
        return jsonify(clean({"total": 0, "pending": [], "analyzing": None, "completed": []})
)
    try:
        all_tickers = json.loads(tickers_file.read_text())
    except Exception:
        all_tickers = []

    ratings = read_json(DATA_DIR / "ratings.json")
    completed = [t for t in all_tickers if t in ratings]
    pending = [t for t in all_tickers if t not in completed]

    return jsonify(clean({
        "total": len(all_tickers),
        "pending": pending[:5],
        "pending_count": len(pending),
        "completed": [{"ticker": t, "rating": ratings[t].get("rating", "Hold")} for t in completed],
        "completed_count": len(completed),
    }))


# ── Main ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    from file_utils import validate_env
    validate_env("dashboard")
    port = _cfg.DASHBOARD_PORT
    log.info(f"Dashboard starting on http://127.0.0.1:{port}")
    log.info(f"Data dir: {DATA_DIR}")
    app.run(host="127.0.0.1", port=port, debug=False)
