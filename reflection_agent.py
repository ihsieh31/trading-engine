from __future__ import annotations
"""交易覆盤引擎 — 平倉後自動分析交易結果，提煉可複用的 trading rule。

流程：
  1. 外部呼叫 enqueue_reflection() 寫入 data/reflection_queue.json
  2. Scheduler 盤後呼叫 ReflectionAgent.batch_process()
  3. 對每筆待覆盤交易，呼叫 LLM 分析 → 產出 ReflectionResult
  4. 存入 knowledge_base.rule_collection
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Literal
from openai import OpenAI
from config import Config
from event_bus import EventBus

log = logging.getLogger(__name__)

REFLECTION_PROMPT = """你是專業的交易覆盤教練。分析以下交易並輸出結構化覆盤。

=== 交易資料 ===
標的: {ticker} ({sector})
入場日期: {entry_date} | 持有 {holding_days} 天
入場價格: ${entry_price} | 出場價格: ${exit_price}
損益: {pnl_pct}%
入場理由: {entry_reason}
出場理由: {exit_reason}
入場時市場 regime: {regime_at_entry}
出場時市場 regime: {regime_at_exit}
入場時評級: {rating}

=== 相關經濟學背景 ===
{economics_context}

=== 請輸出以下 JSON 格式 ===
{{
  "outcome": "win" | "loss" | "breakeven",
  "lesson": "一句話總結關鍵成敗原因",
  "trading_rule": "具體可複用的交易規則（不要泛泛而談，要像「財報前不建立新倉位」這種可操作規則）",
  "context_tags": ["相關標籤，逗號分隔"],
  "applies_to": "這條規則適用的情境描述"
}}
"""


@dataclass
class ReflectionResult:
    ticker: str
    pnl_pct: float
    outcome: Literal["win", "loss", "breakeven"]
    lesson: str
    trading_rule: str
    context_tags: list[str] = field(default_factory=list)
    applies_to: str = ""
    confidence: float = 1.0
    reflected_at: str = ""

    def to_kb_entry(self) -> "KBEntry":
        from knowledge_base import KBEntry
        import hashlib
        content = f"# {self.trading_rule}\n\n**Lesson**: {self.lesson}\n\n**Applies to**: {self.applies_to}\n\n**Source ticker**: {self.ticker}\n**Outcome**: {self.outcome}\n**PnL**: {self.pnl_pct:+.2f}%"
        return KBEntry(
            id=f"rule_{hashlib.md5(self.trading_rule.encode()).hexdigest()[:12]}",
            title=self.trading_rule,
            content=content,
            filepath=f"reflection/{self.ticker}/{self.reflected_at[:10]}",
            tags=self.context_tags,
            source="reflection",
        )


def _queue_path() -> Path:
    return Config().DATA_DIR / "reflection_queue.json"

def enqueue_reflection(ticker: str, side: str, qty: int, price: float, reason: str):
    """將平倉交易排入覆盤佇列。由 order_manager._record_trade() 呼叫。"""
    entry = {
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "price": price,
        "reason": reason,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }
    qpath = _queue_path()
    queue = []
    if qpath.exists():
        try:
            queue = json.loads(qpath.read_text())
        except Exception:
            queue = []
    queue.append(entry)
    qpath.write_text(json.dumps(queue, indent=2))
    log.info(f"[Reflection] Queued {side} {qty}x {ticker} @ ${price:.2f}")


def _gather_trade_context(ticker: str, sell_entry: dict) -> dict | None:
    """從歷史資料收集交易的完整上下文。"""
    trades_path = Config().DATA_DIR / "trades.jsonl"
    if not trades_path.exists():
        return None

    buys = []
    sells = []
    try:
        with open(trades_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                t = json.loads(line)
                if t.get("ticker") != ticker:
                    continue
                if t.get("side") == "buy":
                    buys.append(t)
                elif t.get("side") == "sell":
                    sells.append(t)
    except Exception as e:
        log.warning(f"Failed to read trades for {ticker}: {e}")
        return None

    if not buys:
        return None

    # FIFO: match all sells before this one against buys to find
    # the unmatched buys that correspond to this sell.
    buys.sort(key=lambda x: x.get("time", ""))
    sells.sort(key=lambda x: x.get("time", ""))
    sell_time = sell_entry.get("enqueued_at", "") or sell_entry.get("time", "")
    prior_sells = [s for s in sells if (s.get("time", "") or "") < sell_time]

    remaining = list(buys)  # copy
    for ps in prior_sells:
        need = ps.get("qty", 0)
        while need > 0 and remaining:
            q = remaining[0].get("qty", 0)
            if q <= need:
                need -= q
                remaining.pop(0)
            else:
                # split: reduce qty of first buy
                remaining[0]["qty"] = q - need
                need = 0

    if not remaining:
        log.warning(f"[{ticker}] All buys consumed by prior sells; can't compute trade context")
        return None

    total_qty = sum(b.get("qty", 0) for b in remaining)
    total_cost = sum(b.get("qty", 0) * b.get("price", 0) for b in remaining)
    entry_price = total_cost / total_qty if total_qty > 0 else 0
    first_buy = remaining[0]
    b_date = first_buy.get("time", "")[:10]
    s_date = sell_entry.get("enqueued_at", "")[:10]
    holding_days = 0
    if b_date and s_date:
        try:
            b_dt = datetime.strptime(b_date, "%Y-%m-%d")
            s_dt = datetime.strptime(s_date, "%Y-%m-%d")
            holding_days = (s_dt - b_dt).days
        except ValueError:
            pass

    exit_price = float(sell_entry.get("price", 0))
    pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

    from file_utils import read_json
    ratings = read_json(Config().DATA_DIR / "ratings.json")
    rating_info = ratings.get(ticker, {})

    regime_path = Config().DATA_DIR / "portfolio_snapshot.json"
    regime_info = read_json(regime_path).get("regime", {})

    from sector_map import get_sector
    return {
        "ticker": ticker,
        "sector": get_sector(ticker),
        "entry_date": b_date,
        "holding_days": max(holding_days, 0),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "entry_reason": first_buy.get("reason", ""),
        "exit_reason": sell_entry.get("reason", ""),
        "regime_at_entry": regime_info.get("regime", "unknown"),
        "regime_at_exit": regime_info.get("regime", "unknown"),
        "rating": rating_info.get("rating", "Hold"),
    }


def _call_llm_reflection(context: dict) -> dict:
    """呼叫 Agnes API 執行交易覆盤。"""
    from economics_kb import get_economics_kb
    try:
        ekb = get_economics_kb()
        econ_context = ekb.query(
            ticker=context.get("ticker", ""),
            sector=context.get("sector", ""),
            regime=context.get("regime_at_exit", ""),
            max_theories=3, max_insights=3, max_quotes=1,
        )
    except Exception:
        econ_context = "（經濟學知識庫暫不可用）"
    context["economics_context"] = econ_context

    prompt = REFLECTION_PROMPT.format(**context)
    cfg = Config()
    client = OpenAI(
        api_key=cfg.OPENAI_COMPATIBLE_API_KEY,
        base_url=cfg.LLM_BACKEND_URL,
    )
    resp = client.chat.completions.create(
        model=cfg.DEEP_THINK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(f"LLM reflection response not valid JSON: {raw[:200]}")
        parsed = {}

    return parsed


class ReflectionAgent:
    """交易覆盤引擎。"""

    def __init__(self, config=None):
        self._cfg = config or Config()
        self._kb = None

    def _queue_path(self) -> Path:
        return self._cfg.DATA_DIR / "reflection_queue.json"

    @property
    def kb(self):
        if self._kb is None:
            from knowledge_base import KnowledgeBase
            self._kb = KnowledgeBase(config=self._cfg)
        return self._kb

    def batch_process(self) -> list[ReflectionResult]:
        """處理覆盤佇列中的所有待覆盤交易。

        Returns:
            本次處理的 ReflectionResult 列表。
        """
        qpath = self._queue_path()
        if not qpath.exists():
            return []

        try:
            queue = json.loads(qpath.read_text())
        except Exception as e:
            log.warning(f"Failed to read reflection queue: {e}")
            return []

        if not queue:
            return []

        results = []
        kept = []

        for entry in queue:
            if entry.get("side") != "sell":
                kept.append(entry)
                continue

            ticker = entry.get("ticker", "")
            context = _gather_trade_context(ticker, entry)

            if context is None:
                log.warning(f"[{ticker}] Cannot gather trade context, keeping in queue")
                kept.append(entry)
                continue

            try:
                llm_output = _call_llm_reflection(context)
                outcome = llm_output.get("outcome", "breakeven")
                if outcome not in ("win", "loss", "breakeven"):
                    outcome = "breakeven"

                result = ReflectionResult(
                    ticker=ticker,
                    pnl_pct=context["pnl_pct"],
                    outcome=outcome,
                    lesson=llm_output.get("lesson", ""),
                    trading_rule=llm_output.get("trading_rule", ""),
                    context_tags=llm_output.get("context_tags", []),
                    applies_to=llm_output.get("applies_to", ""),
                    reflected_at=datetime.now(timezone.utc).isoformat(),
                )

                kb_entry = result.to_kb_entry()
                self.kb.add_reflection(kb_entry)
                results.append(result)
                log.info(f"[{ticker}] Reflection done: {result.outcome} — {result.trading_rule[:60]}")
                EventBus.get_instance().emit("reflection_completed", {
                    "ticker": ticker, "outcome": result.outcome,
                    "pnl_pct": result.pnl_pct, "trading_rule": result.trading_rule,
                })
            except Exception as e:
                log.error(f"[{ticker}] Reflection failed: {e}")
                kept.append(entry)

        qpath.write_text(json.dumps(kept, indent=2))
        log.info(f"Reflection batch: {len(results)} processed, {len(kept)} remaining in queue")
        return results

    def queue_size(self) -> int:
        qpath = self._queue_path()
        if not qpath.exists():
            return 0
        try:
            return len(json.loads(qpath.read_text()))
        except Exception:
            return 0


def test_reflection(ticker: str = "AAPL"):
    """手動測試用：對指定 ticker 模擬覆盤。"""
    dummy_entry = {
        "ticker": ticker,
        "side": "sell",
        "qty": 10,
        "price": 150.0,
        "reason": "Stop loss triggered",
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }
    enqueue_reflection(ticker, "sell", 10, 150.0, "Stop loss triggered")
    agent = ReflectionAgent()
    results = agent.batch_process()
    for r in results:
        log.info("=== %s === | Outcome: %s | Lesson: %s | Rule: %s | Tags: %s",
                 r.ticker, r.outcome, r.lesson, r.trading_rule, r.context_tags)
    return results


if __name__ == "__main__":
    import sys
    log.warning("Running in test mode — uses a temporary queue file to avoid production data corruption")
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    test_reflection(ticker)
