"""深度分析模組 — 呼叫 TradingAgents 對 WATCHLIST 做完整多 Agent 分析。
每週跑一次，產生 ratings.json 供盤中監控使用。

TradingAgents propagate() 回傳 (final_state, processed_signal)：
- final_state["final_trade_decision"] 是 PortfolioManager 產生的 markdown，
  格式：
    **Rating**: Buy
    **Executive Summary**: ...
    **Investment Thesis**: ...
    **Price Target**: 195.50
    **Time Horizon**: 3-6 months
- processed_signal 只是 rating 字串（"Buy" / "Hold" / ...）

我們從 final_state["final_trade_decision"] 的 markdown 中解析：
  rating, price_target, time_horizon, executive_summary
"""

from __future__ import annotations
import json
import os
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
import time
from config import Config

from news_service import NewsService
from trading_calendar import last_trading_day
from file_utils import atomic_write_json
from notifier import send_message
import db

_cfg = Config()
DATA_DIR = _cfg.DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(DATA_DIR / "deep_analyzer.log", maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

_news_service = None
_knowledge_context: dict[str, str] = {}


def _get_news_service() -> NewsService:
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service


def _patch_vendor_with_news_service():
    """將 NewsService 註冊為額外的 news vendor (monkey-patch)。"""
    from tradingagents.dataflows.interface import VENDOR_METHODS
    ns = _get_news_service()

    def get_news_multiprovider(ticker: str, start_date: str, end_date: str) -> str:
        try:
            resp = ns.search_stock_news(ticker, max_results=5)
            if resp.success and resp.results:
                return resp.to_context(max_results=10)
        except Exception as e:
            log.debug(f"NewsService failed for {ticker}: {e}")
        return ""

    def get_global_news_multiprovider(curr_date: str, look_back_days=None, limit=None) -> str:
        try:
            resp = ns.search_market_news("stock market finance news", max_results=5)
            if resp.success and resp.results:
                return resp.to_context(max_results=10)
        except Exception as e:
            log.debug(f"NewsService global failed: {e}")
        return ""

    if "news_service" not in VENDOR_METHODS["get_news"]:
        VENDOR_METHODS["get_news"]["news_service"] = get_news_multiprovider
    if "news_service" not in VENDOR_METHODS["get_global_news"]:
        VENDOR_METHODS["get_global_news"]["news_service"] = get_global_news_multiprovider

    log.info("NewsService registered as news vendor 'news_service'.")


def build_ta_config() -> dict:
    """建構 TradingAgents 設定，使用 Agnes API。"""
    from tradingagents.default_config import DEFAULT_CONFIG
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai_compatible"
    config["deep_think_llm"] = _cfg.DEEP_THINK_MODEL
    config["quick_think_llm"] = _cfg.QUICK_THINK_MODEL
    config["backend_url"] = _cfg.LLM_BACKEND_URL
    config["temperature"] = 0.1
    config["max_debate_rounds"] = 2
    return config


CURRENTLY_ANALYZING_FILE = DATA_DIR / ".currently_analyzing"


_FIELD_PATTERN = re.compile(
    r"\*\*(?P<field>[A-Za-z\s]+)\*\*\s*[:\-]\s*(?P<value>.+?)(?=\n\*\*|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def parse_pm_decision(markdown_text: str, ticker: str = "") -> dict:
    """從 PortfolioManager 的 markdown 輸出解析結構化資料。

    預期輸入格式（render_pm_decision 產生）：
      **Rating**: Buy

      **Executive Summary**: ...

      **Investment Thesis**: ...

      **Price Target**: 195.50

      **Time Horizon**: 3-6 months
    """
    result = {
        "rating": "Hold",
        "executive_summary": "",
        "investment_thesis": "",
        "price_target": None,
        "time_horizon": None,
    }

    fields = {m.group("field").strip().lower(): m.group("value").strip() for m in _FIELD_PATTERN.finditer(markdown_text)}

    rating_raw = fields.get("rating", "")
    rating_match = re.match(r"(Buy|Overweight|Hold|Underweight|Sell)", rating_raw, re.IGNORECASE)
    if rating_match:
        result["rating"] = rating_match.group(1)
    elif ticker:
        log.error(f"[{ticker}] Could not parse **Rating** field from LLM output — "
                  f"defaulting to Hold. First 200 chars: {markdown_text[:200]!r}")
        send_message(f"⚠️ [{ticker}] LLM 評等格式解析失敗，已預設為 Hold。請檢查 deep_analyzer.log")

    price_raw = fields.get("price target", "")
    if price_raw:
        try:
            pt = float(re.sub(r"[^0-9.]", "", price_raw))
            if 0 < pt < 10000:
                result["price_target"] = pt
        except ValueError:
            pass

    time_raw = fields.get("time horizon", fields.get("time_horizon", ""))
    if time_raw:
        result["time_horizon"] = time_raw.replace("\n", " ").strip()

    exec_raw = fields.get("executive summary", fields.get("executive_summary", ""))
    if exec_raw:
        result["executive_summary"] = re.sub(r"\s+", " ", exec_raw).strip()

    thesis_raw = fields.get("investment thesis", fields.get("investment_thesis", ""))
    if thesis_raw:
        result["investment_thesis"] = re.sub(r"\s+", " ", thesis_raw).strip()

    return result


def _inject_knowledge_to_config(ticker: str) -> bool:
    """從知識庫查詢相關經驗 + 經濟學知識，透過 per-ticker context dict 注入 TradingAgents。"""
    try:
        from knowledge_base import KnowledgeBase
        from sector_map import get_sector
        from economics_kb import get_economics_kb
        kb = KnowledgeBase()
        sector = get_sector(ticker)
        experiences = kb.query(f"{ticker} {sector} stock trading pattern", k=3)
        rules = kb.query_rules({"ticker": ticker, "sector": sector})

        extra_lines = []
        if experiences:
            extra_lines.append("=== 相關經驗知識 ===")
            for i, exp in enumerate(experiences[:3], 1):
                extra_lines.append(f"{i}. [{exp.title}]({exp.filepath}): {exp.content[:200]}")
        if rules:
            extra_lines.append("=== 歷史交易規則 ===")
            for i, rule in enumerate(rules[:3], 1):
                extra_lines.append(f"{i}. {rule.content[:200]}")

        # Inject economics knowledge
        try:
            ekb = get_economics_kb()
            econ_context = ekb.query(ticker=ticker, sector=sector)
            if econ_context:
                extra_lines.append("")
                extra_lines.append(econ_context)
                log.info(f"[{ticker}] Injected economics knowledge")
        except Exception as e:
            log.debug(f"[{ticker}] Economics KB query failed: {e}")

        if extra_lines:
            _knowledge_context[ticker] = "\n".join(extra_lines)
            log.info(f"[{ticker}] Injected {len(experiences)} experiences + {len(rules)} rules + economics KB")
            return True

    except ImportError:
        log.warning(f"[{ticker}] knowledge_base not available, skipping injection")
    except Exception as e:
        log.error(f"[{ticker}] Knowledge injection failed: {e}")
    return False


def analyze_ticker(ticker: str, graph: "TradingAgentsGraph | None" = None) -> dict:
    """對單一標的執行深度分析。

    當 USE_STRUCTURED_ANALYST=true 時使用 V2 AnalystAgent，
    否則使用既有 TradingAgents pipeline。
    """
    from config import Config
    cfg = Config()
    trade_date = last_trading_day().strftime("%Y-%m-%d")

    if cfg.USE_STRUCTURED_ANALYST:
        return _analyze_with_analyst_agent(ticker, trade_date)

    from tradingagents.graph.trading_graph import TradingAgentsGraph
    return _analyze_with_trading_agents(ticker, graph or TradingAgentsGraph(), trade_date)


def _analyze_with_analyst_agent(ticker: str, trade_date: str) -> dict:
    """使用 V2 AnalystAgent 進行結構化分析。"""
    from agents.base import AnalystAgent
    from adapters import PriceProvider
    from news_service import NewsService
    from economics_kb import get_economics_kb
    from knowledge_base import KnowledgeBase
    from regime import RegimeDetector
    from interfaces_v2 import AnalysisContext

    log.info(f"[{ticker}] V2 AnalystAgent analysis...")

    regime = RegimeDetector().detect()
    price = PriceProvider().get_current_price(ticker)
    news = NewsService().search_market_news(f"{ticker} stock", max_results=3)
    econ = get_economics_kb().query(ticker=ticker, regime=regime.get("regime", ""))
    kb = KnowledgeBase()
    docs = kb.query(f"{ticker} analysis", k=3)
    knowledge = " ".join(d.content for d in docs) if docs else ""

    context = AnalysisContext(
        ticker=ticker,
        as_of_date=trade_date,
        technical_snapshot={"price": price} if price else {},
        news_context=news,
        economics_context=econ,
        knowledge_context=knowledge,
        regime=regime.get("regime", "unknown"),
    )

    agent = AnalystAgent()
    proposal = agent.analyze(context)

    log.info(f"[{ticker}] V2 Rating: {proposal.rating} | Confidence: {proposal.confidence}")

    return {
        "ticker": ticker,
        "rating": proposal.rating,
        "price_target": proposal.price_target,
        "time_horizon": proposal.time_horizon,
        "executive_summary": proposal.thesis,
        "investment_thesis": proposal.thesis,
        "confidence": proposal.confidence,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def _analyze_with_trading_agents(ticker: str, graph: "TradingAgentsGraph", trade_date: str) -> dict:
    """既有 TradingAgents pipeline 分析。"""
    from tradingagents.dataflows.interface import VENDOR_METHODS
    log.info(f"[{ticker}] Starting TradingAgents analysis...")

    saved_news = VENDOR_METHODS.get("get_global_news", {}).copy()
    _inject_knowledge_to_config(ticker)

    final_state, processed_signal = graph.propagate(ticker, trade_date)

    VENDOR_METHODS["get_global_news"] = saved_news

    markdown_decision = final_state.get("final_trade_decision", "")
    parsed = parse_pm_decision(markdown_decision, ticker=ticker)

    if parsed["rating"] == "Hold" and processed_signal:
        parsed["rating"] = processed_signal

    log.info(f"[{ticker}] Rating: {parsed['rating']} | Price Target: {parsed['price_target']}")

    return {
        "ticker": ticker,
        "rating": parsed["rating"],
        "price_target": parsed["price_target"],
        "time_horizon": parsed["time_horizon"],
        "executive_summary": parsed["executive_summary"],
        "investment_thesis": parsed["investment_thesis"],
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def run_deep_analysis(tickers: list[str] = None, prune_stale: bool | None = None):
    """執行完整的深度分析週期。
    
    Args:
        tickers: 要分析的名單。為 None 時從 WATCHLIST 環境變數讀取。
        prune_stale: 是否清除不在 watchlist 中的舊評等。None 時自動判斷（完整批次 True，單股 False）。
    """
    if tickers is None:
        tickers = _cfg.WATCHLIST
        if prune_stale is None:
            prune_stale = True
    else:
        if prune_stale is None:
            prune_stale = len(tickers) >= 3
    watchlist = [t.strip() for t in tickers if t.strip()]
    config = build_ta_config()

    if CURRENTLY_ANALYZING_FILE.exists():
        try:
            meta = json.loads(CURRENTLY_ANALYZING_FILE.read_text())
            pid, started = meta.get("pid"), meta.get("started", 0)
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    alive = False
            if alive and (time.time() - started) < 7200:
                log.warning("Another analysis is already in progress — skipping this run")
                return {}
            log.warning("偵測到陳舊分析鎖,強制覆蓋接管")
        except Exception:
            pass

    _patch_vendor_with_news_service()
    config["data_vendors"]["news_data"] = "yfinance,news_service"

    CURRENTLY_ANALYZING_FILE.write_text(json.dumps({"pid": os.getpid(), "started": time.time(), "tickers": watchlist}))

    from tradingagents.graph.trading_graph import TradingAgentsGraph
    graph = TradingAgentsGraph(config=config)
    new_results = {}
    output_path = DATA_DIR / "ratings.json"

    for ticker in watchlist:
        try:
            result = analyze_ticker(ticker, graph)
        except Exception as e:
            log.error(f"[{ticker}] Failed: {e}", exc_info=True)
            result = {
                "ticker": ticker,
                "rating": "Hold",
                "price_target": None,
                "time_horizon": None,
                "executive_summary": "",
                "investment_thesis": f"Analysis failed: {e}",
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
        new_results[ticker] = result

    CURRENTLY_ANALYZING_FILE.unlink(missing_ok=True)

    existing = {}
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
        except Exception:
            pass
    existing.update(new_results)
    if prune_stale:
        keep = set(_cfg.WATCHLIST)
        existing = {t: v for t, v in existing.items() if t in keep}
    atomic_write_json(output_path, existing)
    try:
        db.save_ratings(existing)
    except Exception as e:
        log.debug(f"db.save_ratings failed: {e}")

    log.info(f"Deep analysis complete. {len(new_results)} tickers analyzed, saved to {output_path}")
    # Clean up stale queue file so dashboard shows accurate status
    queue_file = DATA_DIR / ".analyze_tickers.json"
    if queue_file.exists():
        queue_file.unlink()
    from news_service import print_usage_summary
    print_usage_summary()
    return new_results


if __name__ == "__main__":
    from file_utils import validate_env
    validate_env("deep_analyzer")
    import sys as _sys
    tickers_arg = None
    if len(_sys.argv) > 1:
        arg = _sys.argv[1]
        try:
            with open(arg) as _f:
                tickers_arg = json.load(_f)
            log.info(f"Loaded {len(tickers_arg)} tickers from {arg}")
        except (IOError, json.JSONDecodeError):
            try:
                tickers_arg = json.loads(arg)
            except json.JSONDecodeError:
                tickers_arg = [t.strip() for t in arg.split(",") if t.strip()]
    run_deep_analysis(tickers=tickers_arg)
