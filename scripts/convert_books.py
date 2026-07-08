#!/usr/bin/env python3
"""Convert /Users/zongen/Downloads/股票2/ trading book .txt files
to Obsidian .md files in /Users/zongen/Documents/Obsidian Vault/金融/."""

import re
import os
from pathlib import Path

SRC = Path("/Users/zongen/Downloads/股票2")
DST = Path("/Users/zongen/Documents/Obsidian Vault/金融")

def clean_gutenberg(text: str) -> str:
    """Strip Project Gutenberg headers/footers."""
    start = text.find("*** START OF")
    if start >= 0:
        text = text[start:]
    end = text.find("*** END OF")
    if end >= 0:
        text = text[:end]
    text = re.sub(r"(?m)^.*\*\*\* START OF.*$", "", text)
    text = re.sub(r"(?m)^.*\*\*\* END OF.*$", "", text)
    return text.strip()

def guess_tags(path: Path) -> list[str]:
    name = path.stem
    tags = ["finance", "trading"]
    name_lower = name.lower()
    if "wyckoff" in name_lower:
        tags.extend(["wyckoff", "technical-analysis"])
    if "gann" in name_lower:
        tags.extend(["gann", "technical-analysis"])
    if "dow" in name_lower:
        tags.extend(["dow-theory", "technical-analysis"])
    if "thorp" in name_lower:
        tags.extend(["kelly-criterion", "quantitative"])
    if "loeb" in name_lower:
        tags.extend(["value-investing", "risk-management"])
    if "option" in name_lower or "arbitrage" in name_lower:
        tags.extend(["options", "arbitrage"])
    if "psychology" in name_lower:
        tags.extend(["behavioral-finance", "psychology"])
    if "economics" in name_lower:
        tags.extend(["economics", "macroeconomics"])
    if "accounting" in name_lower:
        tags.extend(["accounting", "fundamental-analysis"])
    if "stock exchange" in name_lower or "nyse" in name_lower or "duguid" in name_lower:
        tags.extend(["market-structure", "history"])
    if "banking" in name_lower:
        tags.extend(["banking", "economics"])
    if "speculation" in name_lower or "tipster" in name_lower or "lefevre" in name_lower:
        tags.extend(["speculation", "market-psychology"])
    if "frenzied" in name_lower or "lawson" in name_lower:
        tags.extend(["market-history", "panic"])
    return tags

def make_title(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^pg\d+_", "", name)
    name = name.replace("_", " ").replace("-", " ").strip()
    # Remove common suffixes
    for s in ["txt", "text"]:
        if name.lower().endswith(s):
            name = name[:-len(s)].strip()
    return name

def convert(path: Path) -> str | None:
    try:
        raw = path.read_text("utf-8", errors="replace")
    except Exception as e:
        print(f"  SKIP {path.name}: {e}")
        return None

    body = clean_gutenberg(raw)
    if not body:
        return None

    title = make_title(path)
    tags = guess_tags(path)
    tag_str = ", ".join(tags)
    frontmatter = "---\n" + f"tags: [{tag_str}]\n" + 'source: "classic-book"\n' + "---\n\n" + f"# {title}\n\n"
    return frontmatter + body

def main():
    DST.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.txt"))
    converted = 0
    for fp in files:
        print(f"  {fp.name}...", end=" ")
        md = convert(fp)
        if md:
            out = DST / f"{fp.stem}.md"
            out.write_text(md)
            print(f"✅ ({len(md)} chars)")
            converted += 1
        else:
            print("SKIP")
    print(f"\nDone: {converted}/{len(files)} files converted → {DST}")

if __name__ == "__main__":
    main()
