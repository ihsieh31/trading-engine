from __future__ import annotations

import math
import logging
from datetime import datetime, timezone

import db
from knowledge_base import KnowledgeBase
from interfaces_v2 import IMemoryService

log = logging.getLogger(__name__)


class MemoryService(IMemoryService):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"

    def __init__(self, config=None, knowledge_base=None):
        self.config = config or {}
        self._kb = knowledge_base
        self._lazy_kb = knowledge_base is None
        self._working: dict[str, dict] = {}
        if isinstance(config, dict):
            decay_config = config.get("DECAY_LAMBDA", 0.01)
        else:
            decay_config = getattr(config, "DECAY_LAMBDA", 0.01)
        self._decay_lambda = decay_config if isinstance(decay_config, (int, float)) else 0.01

    @property
    def kb(self):
        if self._kb is None and self._lazy_kb:
            self._kb = KnowledgeBase()
        return self._kb

    def write(self, entry: dict, tier: str = "semantic"):
        if tier == self.SEMANTIC:
            try:
                self.kb.add_reflection(entry)
            except Exception as e:
                log.debug(f"Memory kb.write failed: {e}")
            rule = {
                "id": entry.get("id", ""),
                "title": entry.get("title", entry.get("trading_rule", "")),
                "content": entry.get("content", ""),
                "filepath": entry.get("filepath", ""),
                "tags": entry.get("context_tags", entry.get("tags", [])),
                "source": "reflection",
                "confidence": entry.get("confidence", 1.0),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if rule["id"]:
                db.save_rule(rule)
        elif tier == self.WORKING:
            workflow_id = entry.get("workflow_id", "current")
            self._working[workflow_id] = entry

    def query(self, query: str, tier: str = "semantic", ticker: str = "",
              regime: str = "", limit: int = 10) -> list[dict]:
        if tier == self.SEMANTIC:
            try:
                results = self.kb.query(query, k=limit)
            except Exception as e:
                log.warning(f"kb.query failed: {e}")
                results = []
            enriched = []
            rules_map = {r.get("id", ""): r for r in db.load_rules(limit=200)}
            for r in results:
                rid = r.get("id", "")
                rule = rules_map.get(rid)
                if rule:
                    r["decay_score"] = rule.get("decay_score", 1.0)
                    r["decay_weighted"] = r.get("similarity", 1.0) * r["decay_score"]
                else:
                    r["decay_score"] = 1.0
                    r["decay_weighted"] = r.get("similarity", 1.0)
                enriched.append(r)
            enriched.sort(key=lambda x: x["decay_weighted"], reverse=True)
            return enriched[:limit]
        elif tier == self.EPISODIC:
            return db.load_trades(limit=limit)
        elif tier == self.WORKING:
            return [self._working.get("current", {})]
        return []

    def expand_graph(self, node_id: str, hops: int = 1) -> list[dict]:
        seen = {node_id}
        results = []
        current = [node_id]
        for _ in range(hops):
            links = self._get_links(current)
            for link in links:
                target = link.get("to_rule_id", "")
                if target and target not in seen:
                    seen.add(target)
                    rules = [r for r in db.load_rules(limit=500) if r.get("id") == target]
                    results.extend(rules)
            current = [r.get("id", "") for r in results if r.get("id") not in {node_id}]
        return results

    def _get_links(self, rule_ids: list[str]) -> list[dict]:
        try:
            conn = db._get_conn()
            placeholders = ",".join("?" for _ in rule_ids)
            rows = conn.execute(
                f"SELECT * FROM rule_wikilinks WHERE from_rule_id IN ({placeholders})",
                rule_ids
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.debug(f"get_links failed: {e}")
            return []

    def reinforce(self, rule_id: str, delta: float = 0.1):
        db.reinforce_rule(rule_id, delta)

    def detect_conflict(self, new_rule: dict) -> list[dict]:
        new_tags = set(new_rule.get("context_tags", new_rule.get("tags", [])))
        new_outcome = new_rule.get("outcome", "")
        existing = db.load_rules(limit=500)
        conflicts = []
        for rule in existing:
            try:
                import json
                rule_tags = set(json.loads(rule.get("tags_json", "[]")))
            except Exception:
                rule_tags = set()
            overlap = new_tags & rule_tags
            if len(overlap) >= 1:
                rule_outcome = rule.get("outcome", "").lower()
                new_outcome_lower = new_outcome.lower()
                if rule_outcome == "profit" and new_outcome_lower == "loss":
                    conflicts.append(rule)
                elif rule_outcome == "loss" and new_outcome_lower == "profit":
                    conflicts.append(rule)
        return conflicts

    def _apply_decay(self):
        now = datetime.now(timezone.utc)
        rules = db.load_rules(limit=1000)
        for rule in rules:
            rule_id = rule.get("id")
            confidence = rule.get("confidence", 1.0)
            anchor = rule.get("last_reinforced_at") or rule.get("created_at")
            if anchor:
                try:
                    anchor_dt = datetime.fromisoformat(anchor)
                except Exception:
                    anchor_dt = now
                days_since = (now - anchor_dt).total_seconds() / 86400.0
            else:
                days_since = 0.0
            decay_score = confidence * math.exp(-self._decay_lambda * days_since)
            try:
                conn = db._get_conn()
                conn.execute("UPDATE rules SET decay_score = ? WHERE id = ?",
                             (round(decay_score, 4), rule_id))
                conn.commit()
            except Exception as e:
                log.debug(f"Decay update failed for {rule_id}: {e}")

    def _rebuild_index(self):
        try:
            self.kb.rebuild_index()
        except Exception as e:
            log.warning(f"Index rebuild failed: {e}")
