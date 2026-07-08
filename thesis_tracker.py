"""Thesis Tracker — 投資論點管理與偏移檢測。

功能：
  1. 開倉時記錄 Mirror Test 論點
  2. 定期檢查論點是否仍然成立
  3. 區分三種變化：事實變了 / 價格變了 / 措辭變了
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from config import Config
from lib.financial_rigor import cross_validate

log = logging.getLogger(__name__)

THESIS_DIR_NAME = "theses"


def _theses_dir() -> Path:
    path = Config().DATA_DIR / THESIS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_thesis(ticker: str, rationale: str, price: float, rating: str) -> dict:
    """記錄開倉論點（Mirror Test 結果）。"""
    entry = {
        "ticker": ticker,
        "rationale": rationale,
        "price_at_entry": price,
        "rating_at_entry": rating,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "fact_snapshot": {},
        "thesis_checks": [],
    }
    path = _theses_dir() / f"{ticker}.json"
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False))
    log.info(f"[Thesis] Recorded for {ticker} @ ${price:.2f} ({rating})")
    return entry


def load_thesis(ticker: str) -> Optional[dict]:
    path = _theses_dir() / f"{ticker}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        log.warning(f"[Thesis] Failed to load {ticker}: {e}")
        return None


def list_active_theses() -> list[dict]:
    theses = []
    for p in _theses_dir().glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("status") == "active":
                theses.append(data)
        except Exception:
            continue
    return theses


def close_thesis(ticker: str, exit_price: float, reason: str):
    thesis = load_thesis(ticker)
    if thesis is None:
        return
    thesis["status"] = "closed"
    thesis["price_at_exit"] = exit_price
    thesis["close_reason"] = reason
    thesis["closed_at"] = datetime.now(timezone.utc).isoformat()
    path = _theses_dir() / f"{ticker}.json"
    path.write_text(json.dumps(thesis, indent=2, ensure_ascii=False))


ChangeType = Literal["fact_change", "price_change", "wording_change"]


def detect_drift(thesis: dict, current_price: float, current_facts: dict = None) -> dict:
    """檢測論點偏移，區分三種變化類型。

    Args:
        thesis: 原始論點 dict
        current_price: 當前股價
        current_facts: 當前基本面快照（營收、毛利率等）

    Returns:
        {"drift_type": ChangeType, "confidence": float, "details": str}
    """
    if thesis.get("status") != "active":
        return {"drift_type": None, "confidence": 0.0, "details": "Thesis is closed"}

    entry_price = thesis.get("price_at_entry", 0)
    price_change_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

    fact_change_conf = 0.0
    wording_change_conf = 0.0

    if current_facts:
        snapshot = thesis.get("fact_snapshot", {})
        if snapshot:
            changes = []
            for key, old_val in snapshot.items():
                new_val = current_facts.get(key)
                if new_val is not None and old_val is not None:
                    dev = abs(new_val - old_val) / abs(old_val) * 100 if old_val != 0 else 0
                    if dev > 15:
                        changes.append(f"{key}: {old_val} → {new_val} ({dev:.0f}% change)")
            if len(changes) >= 2:
                fact_change_conf = min(1.0, len(changes) * 0.3)
            elif len(changes) == 1:
                fact_change_conf = 0.2

    rationale = thesis.get("rationale", "")
    sentences = [s.strip() for s in rationale.split(".") if len(s.strip()) > 10]
    original_rating = thesis.get("rating_at_entry", "")

    if current_price > 0 and entry_price > 0:
        abs_change = abs(price_change_pct)
        if abs_change > 20:
            wording_change_conf = 0.1

    if fact_change_conf > wording_change_conf and fact_change_conf > 0.3:
        drift_type = "fact_change"
        confidence = fact_change_conf
        details = f"Fundamentals changed ({len(current_facts or {})} metrics)"
    elif abs(price_change_pct) > 30 and fact_change_conf < 0.2:
        drift_type = "price_change"
        confidence = min(0.8, abs(price_change_pct) / 100)
        details = f"Price moved {price_change_pct:+.1f}% without fundamental change"
    else:
        drift_type = "wording_change"
        confidence = max(fact_change_conf, 0.05)
        details = "No significant fact or price change detected"

    return {
        "drift_type": drift_type,
        "confidence": round(confidence, 2),
        "details": details,
        "price_change_pct": round(price_change_pct, 1),
        "sentence_count": len(sentences),
        "original_rating": original_rating,
    }


def run_thesis_check(ticker: str, current_price: float, current_facts: dict = None) -> dict:
    """對指定標的執行完整的論點檢查。"""
    thesis = load_thesis(ticker)
    if thesis is None:
        return {"status": "no_thesis", "ticker": ticker}
    drift = detect_drift(thesis, current_price, current_facts)
    result = {
        "status": "checked",
        "ticker": ticker,
        "drift": drift,
        "thesis_recorded_at": thesis.get("recorded_at", ""),
        "price_at_entry": thesis.get("price_at_entry", 0),
        "rating_at_entry": thesis.get("rating_at_entry", ""),
    }
    if drift.get("drift_type") == "fact_change":
        log.warning(f"[Thesis] {ticker}: fact change detected — {drift['details']}")
    elif drift.get("drift_type") == "price_change":
        log.info(f"[Thesis] {ticker}: price change ({drift['price_change_pct']:+.1f}%) — "
                 f"review if thesis still holds")
    return result
