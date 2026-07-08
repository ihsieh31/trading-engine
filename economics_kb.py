from __future__ import annotations
"""Economics knowledge base — loaded from economics-knowledge skill YAML.
Provides query methods for injecting economic context into trading analysis."""

import re
import logging
from pathlib import Path

log = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).parent / "economics-knowledge.yaml"


class EconomicsKnowledgeBase:
    def __init__(self, skill_path: Path = SKILL_PATH):
        self._theories: list[dict] = []
        self._concepts: list[dict] = []
        self._insights: list[str] = []
        self._formulas: list[dict] = []
        self._quotes: list[str] = []
        self._loaded = False
        if skill_path.exists():
            self._load(skill_path)
        else:
            log.warning(f"Economics skill not found at {skill_path}")

    def _load(self, path: Path):
        text = path.read_text(encoding="utf-8")
        current_section = None
        current_item: dict | None = None

        for line in text.split("\n"):
            # Detect sections
            if line.startswith("### === CORE THEORIES"):
                current_section = "theories"
                continue
            elif line.startswith("### === KEY CONCEPTS"):
                current_section = "concepts"
                continue
            elif line.startswith("### === ACTIONABLE INSIGHTS"):
                current_section = "insights"
                continue
            elif line.startswith("### === PRACTICAL FORMULAS"):
                current_section = "formulas"
                continue
            elif line.startswith("### === KEY QUOTES"):
                current_section = "quotes"
                continue

            if current_section is None:
                continue

            line = line.rstrip()

            if current_section == "theories":
                if line.startswith("- **") and "** (" in line:
                    # New theory entry
                    m = re.match(r'- \*\*(.+?)\*\*\s*\((.+?)\)', line)
                    if m:
                        current_item = {
                            "name": m.group(1),
                            "source": m.group(2),
                            "description": "",
                            "proponents": "",
                        }
                        self._theories.append(current_item)
                elif line.startswith("  - ") and current_item is not None:
                    val = line[4:]
                    if val.startswith("Proponents: "):
                        current_item["proponents"] = val[12:]
                    else:
                        current_item["description"] = val
                elif line.strip() == "":
                    current_item = None

            elif current_section == "concepts":
                if line.startswith("- **") and "** (" in line:
                    m = re.match(r'- \*\*(.+?)\*\*\s*\((.+?)\)', line)
                    if m:
                        current_item = {
                            "term": m.group(1),
                            "source": m.group(2),
                            "definition": "",
                        }
                        self._concepts.append(current_item)
                elif line.startswith("  - ") and current_item is not None:
                    current_item["definition"] = line[4:]
                elif line.strip() == "":
                    current_item = None

            elif current_section == "insights":
                if line.startswith("- ") and not line.startswith("- **"):
                    text_val = line[2:]
                    # Remove trailing source tag
                    text_val = re.sub(r'\s+_\(source: .+?\)_$', '', text_val)
                    if text_val.strip():
                        self._insights.append(text_val.strip())

            elif current_section == "formulas":
                if line.startswith("- **") and "** (" in line:
                    m = re.match(r'- \*\*(.+?)\*\*\s*\((.+?)\)', line)
                    if m:
                        current_item = {
                            "name": m.group(1),
                            "source": m.group(2),
                            "formula": "",
                            "explanation": "",
                        }
                        self._formulas.append(current_item)
                elif line.startswith("  - Formula: ") and current_item is not None:
                    current_item["formula"] = line[13:]
                elif line.startswith("  - ") and current_item is not None and not line.startswith("  - Formula:"):
                    current_item["explanation"] = line[4:]
                elif line.strip() == "":
                    current_item = None

            elif current_section == "quotes":
                if line.startswith('- "') and '" —' in line:
                    m = re.match(r'- "(.+)" — (.+)$', line)
                    if m:
                        self._quotes.append(f'"{m.group(1)}" — {m.group(2)}')

        self._loaded = True
        log.info(
            f"Loaded economics KB: {len(self._theories)} theories, "
            f"{len(self._concepts)} concepts, {len(self._insights)} insights, "
            f"{len(self._formulas)} formulas, {len(self._quotes)} quotes"
        )

    def query(self, ticker: str = "", sector: str = "", regime: str = "",
              max_theories: int = 5, max_insights: int = 5, max_quotes: int = 2) -> str:
        """Query economics knowledge relevant to the given context."""
        if not self._loaded:
            return ""

        ticker_l = ticker.lower()
        sector_l = sector.lower()
        regime_l = regime.lower()

        # Score and rank theories by relevance
        scored_theories = []
        for t in self._theories:
            score = 0
            name = t.get("name", "").lower()
            desc = t.get("description", "").lower()
            src = t.get("source", "").lower()

            # Sector match
            if sector_l and sector_l in name + desc + src:
                score += 2
            # Ticker symbol match (unlikely in economics texts)
            if ticker_l and ticker_l in name + desc:
                score += 1
            # Regime match
            if regime_l:
                if regime_l in name:
                    score += 3
                elif regime_l in desc:
                    score += 2

            # Always include high-general theories (like Business Cycle, Inflation, etc.)
            for keyword in ["business cycle", "inflation", "interest rate", "monetary policy",
                            "fiscal policy", "market cycle", "recession", "economic growth",
                            "credit cycle", "liquidity", "risk management", "valuation",
                            "supply and demand", "trend", "momentum"]:
                if keyword in name or keyword in desc:
                    score += 1

            if score > 0:
                scored_theories.append((score, t))

        scored_theories.sort(key=lambda x: -x[0])

        # Score insights
        scored_insights = []
        for ins in self._insights:
            score = 0
            ins_l = ins.lower()
            if sector_l and sector_l in ins_l:
                score += 2
            if regime_l and regime_l in ins_l:
                score += 2
            for keyword in ["cycle", "crash", "bubble", "panic", "trend", "risk",
                            "inflation", "recession", "valuation", "margin", "stop"]:
                if keyword in ins_l:
                    score += 1
            if score > 0:
                scored_insights.append((score, ins))

        scored_insights.sort(key=lambda x: -x[0])

        # Build context string
        parts = []
        parts.append("=== 經濟學相關知識 ===")

        if scored_theories:
            parts.append(f"\n相關理論（{len(scored_theories[:max_theories])} 條）：")
            for _, t in scored_theories[:max_theories]:
                name = t.get("name", "")
                desc = t.get("description", "")
                props = t.get("proponents", "")
                line = f"- {name}"
                if desc:
                    line += f": {desc[:150]}"
                if props:
                    line += f" ({props[:80]})"
                parts.append(line)

        if scored_insights:
            parts.append(f"\n可操作見解（{len(scored_insights[:max_insights])} 條）：")
            for _, ins in scored_insights[:max_insights]:
                parts.append(f"- {ins[:200]}")

        if self._quotes and max_quotes > 0:
            import random
            selected = random.sample(self._quotes, min(max_quotes, len(self._quotes)))
            parts.append(f"\n經典引文：")
            for q in selected:
                parts.append(f"- {q[:200]}")

        return "\n".join(parts)

    def get_macro_context(self, regime: str = "") -> str:
        """Get macro-economic context relevant for current regime."""
        if not self._loaded:
            return ""

        regime_l = regime.lower()
        relevant = []

        for t in self._theories:
            name = t.get("name", "").lower()
            desc = t.get("description", "").lower()
            # Find theories related to macro/market cycles
            if any(kw in name + desc for kw in ["business cycle", "economic cycle", "market cycle",
                                                  "recession", "inflation", "monetary policy",
                                                  "credit cycle", "financial crisis", "deflation",
                                                  "stagflation", "recovery", "expansion"]):
                relevant.append(t)

        parts = ["=== 宏觀經濟背景 ==="]
        for t in relevant[:8]:
            name = t.get("name", "")
            desc = t.get("description", "")
            parts.append(f"- {name}: {desc[:150]}")

        return "\n".join(parts)


_economics_kb: EconomicsKnowledgeBase | None = None


def get_economics_kb() -> EconomicsKnowledgeBase:
    global _economics_kb
    if _economics_kb is None:
        _economics_kb = EconomicsKnowledgeBase()
    return _economics_kb
