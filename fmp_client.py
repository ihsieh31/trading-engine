from __future__ import annotations
"""Financial Modeling Prep 客户端 — 多 Key 轮换 + 用量追踪（日/月）。
设定 FMP_API_KEYS 环境变量启用（逗号分隔多把 Key），未设定时所有方法回退至现有逻辑。
每月用量自动重置。
"""

import json
import time
import hashlib
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache
from config import Config

import requests

log = logging.getLogger(__name__)

_cfg = Config()
FMP_BASE = "https://financialmodelingprep.com/stable"
DATA_DIR = _cfg.DATA_DIR
_USAGE_FILE = DATA_DIR / "fmp_api_usage.json"
_RATE_LIMIT_DELAY = 0.5
_RATE_LOCK = threading.Lock()
_KEY_BACKOFF: dict[str, float] = {}
_KEY_BACKOFF_LOCK = threading.Lock()
_KEY_BACKOFF_SEC = 120


def _load_usage() -> dict:
    if _USAGE_FILE.exists():
        try:
            return json.loads(_USAGE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_usage(usage: dict):
    _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USAGE_FILE.write_text(json.dumps(usage, indent=2))


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _record_usage(key_hash_val: str):
    usage = _load_usage()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    key = f"fmp:{key_hash_val}"
    if key not in usage:
        usage[key] = {"daily": {}, "monthly": {}}
    usage[key]["daily"][today] = usage[key]["daily"].get(today, 0) + 1
    usage[key]["monthly"][month_key] = usage[key]["monthly"].get(month_key, 0) + 1
    _save_usage(usage)


def print_usage_summary():
    usage = _load_usage()
    if not usage:
        log.info("No FMP API usage recorded yet.")
        return
    lines = ["FMP API Usage Summary:"]
    total_daily = 0
    total_monthly = 0
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    for key, data in sorted(usage.items()):
        d = data.get("daily", {}).get(today, 0)
        m = data.get("monthly", {}).get(month_key, 0)
        total_daily += d
        total_monthly += m
        lines.append(f"  {key}: today={d}, this month={m}")
    lines.append(f"  Total: today={total_daily}, this month={total_monthly}")
    log.info("\n".join(lines))


class MultiKeyRotator:
    """多 Key 轮换器，使用最少次数的 key（同 news_service 模式）。
    自动跳过 backoff 中的 key（402 后冷却 _KEY_BACKOFF_SEC 秒）。
    """

    def __init__(self, keys: list[str]):
        self.keys = keys

    def pick(self) -> str | None:
        if not self.keys:
            return None
        now_ts = time.time()
        usage = _load_usage()
        best_key = None
        best_count = None
        month_key = datetime.now().strftime("%Y-%m")
        with _KEY_BACKOFF_LOCK:
            backoff = dict(_KEY_BACKOFF)
        for k in self.keys:
            kh = _key_hash(k)
            if backoff.get(kh, 0) > now_ts:
                continue
            usage_key = f"fmp:{kh}"
            monthly_usage = usage.get(usage_key, {}).get("monthly", {}).get(month_key, 0)
            if best_count is None or monthly_usage < best_count:
                best_count = monthly_usage
                best_key = k
        return best_key

    def record(self, key: str):
        _record_usage(_key_hash(key))

    def mark_backoff(self, key: str):
        kh = _key_hash(key)
        with _KEY_BACKOFF_LOCK:
            _KEY_BACKOFF[kh] = time.time() + _KEY_BACKOFF_SEC
        log.warning(f"Key {kh} in backoff for {_KEY_BACKOFF_SEC}s (402)")


def _get_keys() -> list[str]:
    return _cfg.FMP_API_KEYS


_rotator = None


def _get_rotator() -> MultiKeyRotator | None:
    global _rotator
    if _rotator is None:
        keys = _get_keys()
        if keys:
            _rotator = MultiKeyRotator(keys)
    return _rotator


_last_request_time = 0.0


def _rate_limit():
    global _last_request_time
    with _RATE_LOCK:
        elapsed = time.time() - _last_request_time
        if elapsed < _RATE_LIMIT_DELAY:
            time.sleep(_RATE_LIMIT_DELAY - elapsed)
        _last_request_time = time.time()


def _clean_stale_backoff():
    now_ts = time.time()
    with _KEY_BACKOFF_LOCK:
        stale = [kh for kh, until in _KEY_BACKOFF.items() if until <= now_ts]
        for kh in stale:
            _KEY_BACKOFF.pop(kh, None)


def _get(endpoint: str, params: dict = None) -> dict | list | None:
    rotator = _get_rotator()
    if rotator is None:
        return None

    _clean_stale_backoff()
    key = rotator.pick()
    if key is None:
        return None

    _rate_limit()

    p = {"apikey": key}
    if params:
        p.update(params)
    try:
        resp = requests.get(f"{FMP_BASE}/{endpoint}", params=p, timeout=15)
        rotator.record(key)
        if resp.status_code == 200:
            return resp.json()
        log.warning(f"FMP API error {resp.status_code} (key={_key_hash(key)}): {endpoint}")
        if resp.status_code in (402, 429, 403):
            rotator.mark_backoff(key)
    except Exception as e:
        log.debug(f"FMP request failed: {endpoint}: {e}")
    return None


# ── Sector & Profile ───────────────────────────────────────

@lru_cache(maxsize=512)
def get_sector(ticker: str) -> str | None:
    data = _get("profile", {"symbol": ticker.upper()})
    if isinstance(data, list) and len(data) > 0:
        return data[0].get("sector")
    return None


def get_industry(ticker: str) -> str | None:
    data = _get("profile", {"symbol": ticker.upper()})
    if isinstance(data, list) and len(data) > 0:
        return data[0].get("industry")
    return None


# ── Stock Universe ─────────────────────────────────────────

def available() -> bool:
    return _get_rotator() is not None


_V3_BASE = "https://financialmodelingprep.com/api/v3"


def _get_v3(endpoint: str, params: dict = None) -> dict | list | None:
    """v3 API 备援（部分 endpoint 还在 v3 上）。"""
    rotator = _get_rotator()
    if rotator is None:
        return None
    _clean_stale_backoff()
    key = rotator.pick()
    if key is None:
        return None
    p = {"apikey": key}
    if params:
        p.update(params)
    try:
        resp = requests.get(f"{_V3_BASE}/{endpoint}", params=p, timeout=15)
        rotator.record(key)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (402, 429, 403):
            rotator.mark_backoff(key)
    except Exception:
        pass
    return None


def get_sp500() -> list[str] | None:
    """回传 S&P 500 成分股列表。"""
    data = _get_v3("sp500_constituent")
    if isinstance(data, list):
        return sorted(set(t["symbol"] for t in data if "symbol" in t))
    return None


def get_nasdaq100() -> list[str] | None:
    data = _get_v3("nasdaq_constituent")
    if isinstance(data, list):
        return sorted(set(t["symbol"] for t in data if "symbol" in t))
    return None


# ── Quote & Price ──────────────────────────────────────────

@lru_cache(maxsize=256)
def get_quote(ticker: str) -> dict | None:
    data = _get("quote", {"symbol": ticker.upper()})
    if isinstance(data, list) and len(data) > 0:
        return data[0]
    return _scrape_yahoo_quote(ticker)


def get_price(ticker: str) -> float | None:
    q = get_quote(ticker)
    if q:
        return q.get("price")
    return None


def batch_quotes(tickers: list[str]) -> dict[str, dict]:
    """顺序逐只报价（不做并发），使用内部 rate limiter + key 轮换 + 备援爬虫。
    回传 {ticker: quote_dict}。
    """
    result: dict[str, dict] = {}
    for ticker in tickers:
        q = get_quote(ticker)
        if q and q.get("price"):
            result[ticker.upper()] = q
    return result


# ── Web Scraping Fallback (Yahoo Finance) ────────────────

_SCRAPE_DELAY = 2.0
_last_scrape = 0.0
_scrape_lock = threading.Lock()


def _scrape_yahoo_quote(ticker: str) -> dict | None:
    """爬取 Yahoo Finance 报价页作为 FMP 不可用时的备援。"""
    global _last_scrape
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html",
    }
    with _scrape_lock:
        elapsed = time.time() - _last_scrape
        if elapsed < _SCRAPE_DELAY:
            time.sleep(_SCRAPE_DELAY - elapsed)
        _last_scrape = time.time()

    try:
        resp = requests.get(
            f"https://finance.yahoo.com/quote/{ticker.upper()}/",
            headers=headers,
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        price_el = soup.select_one('[data-testid="qsp-price"]')
        if not price_el:
            return None
        try:
            price = float(price_el.get("value", price_el.text).replace(",", ""))
        except (ValueError, AttributeError):
            return None
        return {"symbol": ticker.upper(), "price": price}
    except Exception:
        return None


# ── Historical Data ────────────────────────────────────────

@lru_cache(maxsize=64)
def get_historical(ticker: str, days: int = 365) -> list | None:
    """取得历史日线数据（light EOD）。"""
    data = _get("historical-price-eod/light", {"symbol": ticker.upper()})
    if isinstance(data, list):
        cutoff_ts = datetime.now(timezone.utc).timestamp() - days * 86400
        result = []
        for item in data:
            date_str = item.get("date", "")
            if date_str:
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    if dt.timestamp() >= cutoff_ts:
                        result.append({
                            "date": date_str,
                            "close": item.get("close"),
                            "high": item.get("high") or item.get("close"),
                            "low": item.get("low") or item.get("close"),
                            "open": item.get("open") or item.get("close"),
                            "volume": item.get("volume", 0),
                        })
                except ValueError:
                    pass
        return result if result else None
    return None


# ── Technical Indicators ───────────────────────────────────

def get_rsi(ticker: str, period: int = 14) -> float | None:
    return None  # FMP /stable/ 暂无 RSI endpoint, 由 yfinance 计算


def get_sma(ticker: str, period: int = 20) -> float | None:
    return None


def get_macd(ticker: str) -> dict | None:
    return None


# ── News ───────────────────────────────────────────────────

def get_stock_news(ticker: str, max_results: int = 5) -> list | None:
    data = _get("stock-news", {"symbol": ticker.upper(), "limit": max_results})
    if isinstance(data, list):
        return data
    return None


def get_market_news(max_results: int = 10) -> list | None:
    data = _get("stock-news", {"limit": max_results})
    if isinstance(data, list):
        return data
    return None
