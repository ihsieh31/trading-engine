from __future__ import annotations
"""多供應商新聞服務 — 支援多 API Key 輪換 + 使用次數追蹤。"""

import json
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

_USAGE_FILE = None


def _usage_file() -> Path:
    global _USAGE_FILE
    if _USAGE_FILE is None:
        from config import Config
        _USAGE_FILE = Config().DATA_DIR / "news_api_usage.json"
    return _USAGE_FILE


def _load_usage() -> dict:
    uf = _usage_file()
    if uf.exists():
        try:
            return json.loads(uf.read_text())
        except Exception:
            pass
    return {}


def _save_usage(usage: dict):
    uf = _usage_file()
    uf.parent.mkdir(parents=True, exist_ok=True)
    uf.write_text(json.dumps(usage, indent=2))


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _record_usage(provider: str, key_hash_val: str):
    usage = _load_usage()
    today = datetime.now().strftime("%Y-%m-%d")
    key = f"{provider}:{key_hash_val}"
    if key not in usage:
        usage[key] = {}
    usage[key][today] = usage[key].get(today, 0) + 1
    _save_usage(usage)


def print_usage_summary():
    usage = _load_usage()
    if not usage:
        log.info("No news API usage recorded yet.")
        return
    lines = ["News API Usage Summary:"]
    total = 0
    for key, days in sorted(usage.items()):
        key_total = sum(days.values())
        total += key_total
        days_str = ", ".join(f"{d}: {c}" for d, c in sorted(days.items()))
        lines.append(f"  {key}: {key_total} total ({days_str})")
    lines.append(f"  Total: {total}")
    log.info("\n".join(lines))


@dataclass
class NewsItem:
    title: str
    snippet: str
    url: str
    source: str = ""
    published_date: Optional[str] = None

    def to_text(self) -> str:
        date_str = f" ({self.published_date})" if self.published_date else ""
        return f"[{self.source}]{date_str} {self.title}\n  {self.snippet}\n  {self.url}"


@dataclass
class NewsResponse:
    query: str
    results: list[NewsItem] = field(default_factory=list)
    provider: str = ""
    success: bool = True
    error: Optional[str] = None

    def to_context(self, max_results: int = 5) -> str:
        if not self.results:
            return f"No news found for '{self.query}'."
        items = self.results[:max_results]
        lines = [f"News results for '{self.query}' (via {self.provider}):"]
        for i, item in enumerate(items, 1):
            lines.append(f"\n{i}. {item.to_text()}")
        return "\n".join(lines)


class MultiKeyRotator:
    """多 Key 輪換器，使用最少次數的 key。"""

    def __init__(self, keys: list[str], provider: str):
        self.keys = keys
        self.provider = provider

    def pick(self) -> str | None:
        if not self.keys:
            return None
        usage = _load_usage()
        best_key = None
        best_count = None
        for k in self.keys:
            kh = _key_hash(k)
            usage_key = f"{self.provider}:{kh}"
            total = sum(usage.get(usage_key, {}).values())
            if best_count is None or total < best_count:
                best_count = total
                best_key = k
        return best_key

    def record(self, key: str):
        _record_usage(self.provider, _key_hash(key))


class NewsService:
    def __init__(self, config=None):
        from config import Config
        cfg = config or Config()
        self.tavily_keys = cfg.TAVILY_API_KEYS
        self.tavily_rotator = MultiKeyRotator(self.tavily_keys, "tavily") if self.tavily_keys else None

        self.brave_keys = cfg.BRAVE_API_KEYS
        self.brave_rotator = MultiKeyRotator(self.brave_keys, "brave") if self.brave_keys else None

        self.serpapi_keys = cfg.SERPAPI_API_KEYS
        self.serpapi_rotator = MultiKeyRotator(self.serpapi_keys, "serpapi") if self.serpapi_keys else None

        self._fmp_available = False
        try:
            from fmp_client import available as fmp_avail
            self._fmp_available = fmp_avail()
        except Exception:
            pass

    def search_stock_news(self, ticker: str, company_name: str = "", max_results: int = 5) -> NewsResponse:
        query = f"{company_name or ticker} ({ticker}) stock latest news"
        return self._search_all(query, max_results)

    def search_market_news(self, query: str, max_results: int = 5) -> NewsResponse:
        return self._search_all(query, max_results)

    def _search_all(self, query: str, max_results: int) -> NewsResponse:
        providers = []
        if self._fmp_available:
            providers.append(("fmp", self._search_fmp))
        if self.tavily_rotator:
            providers.append(("tavily", self._search_tavily))
        if self.brave_rotator:
            providers.append(("brave", self._search_brave))
        if self.serpapi_rotator:
            providers.append(("serpapi", self._search_serpapi))

        last_error = None
        for name, func in providers:
            try:
                resp = func(query, max_results)
                if resp and resp.results:
                    return resp
            except Exception as e:
                last_error = str(e)
                log.debug(f"[{name}] search failed: {e}")

        return NewsResponse(query=query, success=False, error=last_error or "All providers failed")

    def _search_tavily(self, query: str, max_results: int) -> Optional[NewsResponse]:
        try:
            from tavily import TavilyClient
        except ImportError:
            log.warning("tavily-python not installed. Run: pip install tavily-python")
            return None

        key = self.tavily_rotator.pick()
        if not key:
            return None

        client = TavilyClient(api_key=key)
        resp = client.search(query=query, search_depth="advanced", max_results=max_results, topic="news")
        self.tavily_rotator.record(key)

        items = []
        for r in resp.get("results", []):
            items.append(NewsItem(
                title=r.get("title", ""),
                snippet=r.get("content", ""),
                url=r.get("url", ""),
                source=r.get("source", "tavily"),
                published_date=r.get("published_date"),
            ))
        return NewsResponse(query=query, results=items, provider="tavily")

    def _search_brave(self, query: str, max_results: int) -> Optional[NewsResponse]:
        key = self.brave_rotator.pick()
        if not key:
            return None

        headers = {"Accept": "application/json", "X-Subscription-Token": key}
        params = {"q": query, "count": max_results, "freshness": "day"}
        resp = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            log.warning(f"Brave API error: {resp.status_code}")
            return None
        self.brave_rotator.record(key)

        data = resp.json()
        items = []
        for r in data.get("web", {}).get("results", []):
            items.append(NewsItem(
                title=r.get("title", ""),
                snippet=r.get("description", ""),
                url=r.get("url", ""),
                source="brave",
                published_date=r.get("age"),
            ))
        return NewsResponse(query=query, results=items, provider="brave")

    def _search_serpapi(self, query: str, max_results: int) -> Optional[NewsResponse]:
        key = self.serpapi_rotator.pick()
        if not key:
            return None

        params = {
            "q": query,
            "api_key": key,
            "engine": "google_news",
            "gl": "us",
            "hl": "en",
        }
        resp = requests.get("https://serpapi.com/search", params=params, timeout=15)
        if resp.status_code != 200:
            log.warning(f"SerpAPI error: {resp.status_code}")
            return None
        self.serpapi_rotator.record(key)

        data = resp.json()
        items = []
        for r in data.get("news_results", []):
            items.append(NewsItem(
                title=r.get("title", ""),
                snippet=r.get("snippet", ""),
                url=r.get("link", ""),
                source=r.get("source", "serpapi"),
                published_date=r.get("date"),
            ))
        return NewsResponse(query=query, results=items, provider="serpapi")

    def _search_fmp(self, query: str, max_results: int):
        try:
            from fmp_client import get_stock_news as fmp_news
            # Extract ticker from query format "Company (TICKER) stock news"
            import re
            m = re.search(r"\(([A-Za-z]+)\)", query)
            ticker = m.group(1) if m else query.split()[0]
            data = fmp_news(ticker, max_results)
            if not data:
                return None
            items = []
            for r in data:
                items.append(NewsItem(
                    title=r.get("title", ""),
                    snippet=r.get("text", "") or r.get("description", ""),
                    url=r.get("url", ""),
                    source=r.get("site", "fmp") or "fmp",
                    published_date=r.get("publishedDate", ""),
                ))
            return NewsResponse(query=query, results=items, provider="fmp")
        except Exception as e:
            log.debug(f"FMP news search failed: {e}")
        return None
