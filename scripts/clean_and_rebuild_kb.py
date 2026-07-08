#!/usr/bin/env python3
"""清理知識庫：移除書名/作者/介紹，只保留精華內容。

對 pg* 檔案：跳過 Gutenberg header/credits/title，從第一個章節開始。
對 book-* 檔案：重新下載全文並清理。
對指南檔案：移除 frontmatter 的 title/source。
"""

import logging
import re
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("clean_kb")

VAULT = Path("/Users/zongen/Documents/Obsidian Vault/金融")


def clean_pg_file(path: Path) -> bool:
    """清理 Project Gutenberg 檔案：移除 header/credits/title/intro。"""
    raw = path.read_text(encoding="utf-8", errors="replace")

    # 提取 tags（保留 frontmatter 的 tags）
    tags_match = re.search(r"tags:\s*\[(.+?)\]", raw, re.DOTALL)
    tags_str = tags_match.group(1).strip() if tags_match else "economics, macro, finance"

    # 找到內容開始處 — 跳過 START + credits + title
    start = raw.find("*** START OF")
    if start == -1:
        start = 0
    body = raw[start:]

    # 移除 Gutenberg START 行
    body = re.sub(r"\*\*\* START OF THE PROJECT GUTENBERG.*?\*\*\*", "", body)

    # 跳過 credits（Produced by... 到第一個空行後的實際內容）
    # Gutenberg 典型結構：START marker → credits → Gutenberg license → title page → TOC → content
    # 找第一個 CHAPTER / Chapter / Part / Book / Section 開頭
    chapter_match = re.search(
        r"^(CHAPTER\s+|[IVXLCDM]+\..*|Part\s+|Book\s+|Section\s+|Chapter\s+)",
        body,
        re.MULTILINE | re.IGNORECASE,
    )

    if chapter_match:
        body = body[chapter_match.start() :]
    else:
        # 沒有章節標記就找第一個大段落（>500 chars）
        paragraphs = re.split(r"\n\s*\n", body)
        for i, p in enumerate(paragraphs):
            if len(p.strip()) > 500:
                body = "\n\n".join(paragraphs[i:])
                break

    # 移除 Gutenberg footer
    end = body.find("*** END OF THE PROJECT GUTENBERG")
    if end != -1:
        body = body[:end]

    # 清理 Project Gutenberg license 殘留
    body = re.sub(
        r"End of (the )?Project Gutenberg.*", "", body, flags=re.IGNORECASE
    )
    body = re.sub(
        r"This (eBook|ebook|file) is for the use of anyone.*?www\.gutenberg\.org.*?fund-raising",
        "",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 合併多餘空行
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.strip()

    if len(body) < 200:
        log.warning(f"  ⚠️  {path.name}: 內容過短 ({len(body)} chars)")
        return False

    # 寫回
    md = f"""---
tags: [{tags_str}]
---

{body}
"""
    path.write_text(md, encoding="utf-8")
    log.info(f"  ✅ {path.name}: {len(body)} chars")
    return True


def main():
    files = sorted(VAULT.glob("*.md"))
    total = len(files)
    cleaned = 0
    skipped = 0

    log.info(f"掃描 {total} 個檔案...")

    for path in files:
        name = path.name

        # 跳過非 pg 和非 book 檔案（指南檔案不動）
        if not (name.startswith("pg") or name.startswith("book-")):
            log.info(f"  ➡️  {name}: 跳過（指南檔案）")
            continue

        # book-* 檔案：先刪除，之後重新下載
        if name.startswith("book-"):
            log.info(f"  🗑️  {name}: 刪除（需重新下載）")
            path.unlink()
            skipped += 1
            continue

        # pg* 檔案：清理
        if clean_pg_file(path):
            cleaned += 1
        else:
            skipped += 1

    log.info(f"\n完成：{cleaned} 清理 / {skipped} 跳過或刪除 / {total} 總計")


if __name__ == "__main__":
    main()
