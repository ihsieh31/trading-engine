#!/usr/bin/env python3
"""從 Archive.org 下載經典交易書籍的純文字版，轉成知識庫 markdown 檔。"""

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("convert")

OUTPUT_DIR = Path("/Users/zongen/Documents/Obsidian Vault/金融")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# (filename_stem, archive_id, title, tags)
BOOKS = [
    ("gann_45_years", "45yearsinwallstr0000gann",
     "45 Years in Wall Street (Gann)", ["gann", "technical-analysis", "trading-psychology"]),
    ("wyckoff_day_traders_bible", "DayTradersBibleMySecretsToTradingInStocks1919",
     "Day Trader's Bible (Wyckoff)", ["wyckoff", "technical-analysis", "trading-psychology"]),
    ("wyckoff_how_i_trade_invest", "cu31924031269552",
     "How I Trade and Invest (Wyckoff)", ["wyckoff", "trading-strategy", "risk-management"]),
    ("loeb_battle_investment_survival", "battleforinvestm00gera",
     "The Battle for Investment Survival (Loeb)", ["trading-psychology", "risk-management", "value-investing"]),
    ("thorp_beat_the_market", "beatmarketscient00thor",
     "Beat the Market (Thorp)", ["quantitative", "options", "arbitrage"]),
    ("hamilton_dow_barometer", "stockmarketbarom00hami",
     "The Stock Market Barometer (Hamilton)", ["dow-theory", "technical-analysis", "market-timing"]),
    ("nelson_abc_options", "abcofoptionsarbi00nelsuoft",
     "ABC of Options and Arbitrage (Nelson)", ["options", "arbitrage", "quantitative"]),
    ("nyse_history_1905", "newyorkstockexch01unse",
     "The New York Stock Exchange (1905)", ["market-history", "institutions", "regulation"]),
]


def fetch_text(identifier: str):
    urls = [
        f"https://archive.org/stream/{identifier}/{identifier}_djvu.txt",
        f"https://archive.org/stream/{identifier}/{identifier}.txt",
    ]
    for url in urls:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urlopen(req, timeout=60)
            data = resp.read().decode("utf-8", errors="replace")
            if len(data) > 1000:
                log.info(f"  Downloaded {len(data)} bytes from {url.split('/')[-1]}")
                return data
        except Exception as e:
            log.debug(f"  {url}: {e}")
    return None


def clean_text(raw: str) -> str:
    lines = raw.split("\n")
    cleaned = []
    in_header = True
    for line in lines:
        # Skip OCR/IA header noise
        if in_header:
            if re.match(r"^\s*Page\s+\d+", line) or re.match(r"^\s*[-\s]*$", line):
                continue
            if "Generated for" in line or "Internet Archive" in line or "http://" in line:
                continue
            if line.strip() and len(line.strip()) > 20:
                in_header = False
        # Skip page numbers and OCR artifacts
        if re.match(r"^\s*\d+\s*$", line) and len(line.strip()) < 7:
            continue
        cleaned.append(line.rstrip())
    text = "\n".join(cleaned).strip()
    # Remove multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def make_md(title: str, body: str, tags: list[str]) -> str:
    tag_str = ", ".join(tags)
    lines = [
        "---",
        f"tags: [{tag_str}]",
        "---",
        "",
        f"# {title}",
        "",
        body,
        "",
    ]
    return "\n".join(lines)


def main():
    total = len(BOOKS)
    for i, (stem, archive_id, title, tags) in enumerate(BOOKS, 1):
        out_path = OUTPUT_DIR / f"book-{stem}.md"
        if out_path.exists():
            log.info(f"[{i}/{total}] {title} — 已存在，跳過")
            continue

        log.info(f"[{i}/{total}] {title} (id={archive_id}) ...")
        raw = fetch_text(archive_id)
        if not raw:
            log.warning(f"  ❌ 無法下載，跳過")
            continue

        body = clean_text(raw)
        if len(body) < 500:
            log.warning(f"  ❌ 內容過短 ({len(body)} chars)，跳過")
            continue

        md = make_md(title, body, tags)
        out_path.write_text(md, encoding="utf-8")
        log.info(f"  ✅ 寫入 {out_path} ({len(md)} chars)")
        time.sleep(1)  # rate limit

    log.info(f"\n完成！共 {total} 本，輸出至 {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
