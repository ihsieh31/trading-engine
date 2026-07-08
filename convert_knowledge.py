#!/usr/bin/env python3
"""批次轉換股票書籍為知識庫 .md 格式。

來源：
- /Users/zongen/Downloads/股票2/*.txt  (Project Gutenberg 純文字)
- /Users/zongen/Downloads/股票/*.md   (現有 markdown)
- /Users/zongen/Downloads/股票2/*.md  (現有 markdown)

不處理：archive.org HTML 包裝的檔案（無法提取純文字）
"""

import glob
import os
import re
from pathlib import Path


# ── 書名 → 主題標籤映射 ────────────────────────────────────

BOOK_META = {
    # ── 股票2 Gutenberg ──
    "pg75570": {"tags": ["psychology", "behavioral-finance", "market-psychology"], "title": "Psychology of the Stock Market"},
    "pg73647": {"tags": ["psychology", "speculation", "behavioral-finance"], "title": "Psychology of Speculation"},
    "pg23171": {"tags": ["trading", "psychology", "wall-street"], "title": "The Tipster"},
    "pg26330": {"tags": ["finance", "market-psychology", "bubble", "crash"], "title": "Frenzied Finance"},
    "pg32027": {"tags": ["banking", "monetary-policy", "finance"], "title": "Banking"},
    "pg44274": {"tags": ["trading", "psychology", "memoir"], "title": "My Adventures, Your Money"},
    "pg54130": {"tags": ["trading", "wall-street", "history"], "title": "Wall Street Stories"},
    "pg59042": {"tags": ["market-history", "exchange", "microstructure"], "title": "The Stock Exchange"},
    "pg70367": {"tags": ["accounting", "fundamental-analysis"], "title": "Accounting Theory and Practice"},
    "pg70377": {"tags": ["trading", "psychology", "wall-street", "market-cycle"], "title": "Fifty Years in Wall Street"},
    "pg70556": {"tags": ["accounting", "fundamental-analysis"], "title": "Accounting Theory and Practice Vol 2"},
    "pg12217": {"tags": ["economics", "macro", "policy"], "title": "Economics Vol 2"},
    "pg22418": {"tags": ["economics", "monetary-policy", "fiat-money"], "title": "Dollars and Sense"},
    # ── 股票 Gutenberg ──
    "pg833": {"tags": ["economics", "marx", "capital"], "title": "Capital Vol 1"},
    "pg11774": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg14418": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg15776": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg15962": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg24518": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg26716": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg26841": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg29256": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg30107": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg31159": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg3300": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg33219": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg33310": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg34463": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg34823": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg35120": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg38138": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg40077": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg41936": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg4239": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg4359": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg44052": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg46423": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg55308": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg57819": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg59518": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg60082": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg60979": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg61605": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg65278": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg66710": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg67363": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg71223": {"tags": ["economics", "macro"], "title": "Economics"},
    "pg75687": {"tags": ["economics", "macro"], "title": "Economics"},
}

# 4 個現有的 .md 檔案
EXISTING_MD = {
    "learning_path": {"tags": ["learning", "strategy", "roadmap"], "title": "Learning Path"},
    "options_trading_guide": {"tags": ["options", "derivatives", "trading"], "title": "Options Trading Guide"},
    "sec_edgar_guide": {"tags": ["sec", "edgar", "fundamental-analysis"], "title": "SEC EDGAR Guide"},
    "trading_rules_cheatsheet": {"tags": ["trading", "rules", "cheatsheet"], "title": "Trading Rules Cheatsheet"},
}


# ── Gutenberg 純文字提取 ──────────────────────────────────

def extract_gutenberg_text(raw: str) -> str:
    """從 Project Gutenberg 純文字中提取書本內容。"""
    # 找到 *** START OF THE PROJECT GUTENBERG EBOOK ***
    start_marker = "*** START OF THE PROJECT GUTENBERG EBOOK"
    end_marker = "*** END OF THE PROJECT GUTENBERG EBOOK"

    start_idx = raw.find(start_marker)
    if start_idx < 0:
        # 嘗試找其他變體
        start_idx = raw.find("*** START OF")
    if start_idx < 0:
        return None

    end_idx = raw.find(end_marker)
    if end_idx < 0:
        end_idx = len(raw)

    text = raw[start_idx:end_idx]

    # 移除 header/footer 區塊
    text = re.sub(r'[*\-]{3,}.*?START OF.*?[*\-]{3,}', '', text, flags=re.DOTALL)
    text = re.sub(r'[*\-]{3,}.*?END OF.*?[*\-]{3,}', '', text, flags=re.DOTALL)

    # 清理多餘空白
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    text = '\n\n'.join(lines)

    # 移除剩餘的 Gutenberg 聲明
    text = re.sub(r'This ebook is for the use of anyone.*?world at no cost.*?terms of the Project Gutenberg License.*?online at www\.gutenberg\.org.*?If you are not located in the United States.*?check the laws of the country where you are located before using this eBook\.', '', text, flags=re.DOTALL)
    text = re.sub(r'Transcriber\'s Note.*?(?:Italic text|This edition).*?(?:\n\n|$)', '', text, flags=re.DOTALL)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ── 轉換單一檔案 ────────────────────────────────────────────

def convert_gutenberg(src_path: str, output_dir: Path):
    """轉換 Gutenberg 純文字為 .md。"""
    basename = os.path.basename(src_path)
    # 提取 pg 編號
    pg_match = re.search(r'(pg\d+)', basename, re.IGNORECASE)
    pg_id = pg_match.group(1) if pg_match else basename.replace('.txt', '').replace('_', '')[:10]

    meta = BOOK_META.get(pg_id, {"tags": ["economics", "macro", "finance"], "title": basename.replace('.txt', '').replace('_', ' ')})

    with open(src_path, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read()

    text = extract_gutenberg_text(raw)
    if not text or len(text) < 100:
        return None

    # 截斷到 15000 字元（知識庫不需要整本書）
    preview = text[:15000]

    tags = meta["tags"]
    title = meta["title"]

    md = f"""---
title: "{title}"
tags:
  - {tags[0]}
  - {tags[1]}
  - {tags[2] if len(tags) > 2 else ''}
source: "{basename}"
---

# {title}

> 來源：{basename}
> 標籤：{', '.join(tags)}

---

{preview}
"""

    out_name = pg_id + ".md"
    out_path = output_dir / out_name
    out_path.write_text(md, encoding="utf-8")
    return out_path


def convert_existing_md(src_path: str, output_dir: Path):
    """複製現有的 .md 檔案。"""
    basename = os.path.basename(src_path)
    key = basename.replace('.md', '').lower()

    meta = EXISTING_MD.get(key, {"tags": ["finance", "stock-market", "reference"], "title": basename.replace('.md', '')})

    with open(src_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    tags = meta["tags"]
    title = meta["title"]

    md = f"""---
title: "{title}"
tags:
  - {tags[0]}
  - {tags[1]}
  - {tags[2] if len(tags) > 2 else ''}
source: "{basename}"
---

# {title}

> 來源：{basename}
> 標籤：{', '.join(tags)}

---

{content}
"""

    out_path = output_dir / basename
    out_path.write_text(md, encoding="utf-8")
    return out_path


# ── 主流程 ─────────────────────────────────────────────────

def main():
    output_dir = Path("/Users/zongen/Documents/Obsidian Vault/金融")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 清除舊的 .md 檔案（保留 .gitkeep）
    for f in output_dir.glob("*.md"):
        if f.name != '.gitkeep':
            f.unlink()

    converted = 0
    skipped = 0

    # 1. 轉換 Gutenberg 純文字
    print("=== 轉換 Gutenberg 純文字 ===")
    gutenberg_files = []
    for d in ['/Users/zongen/Downloads/股票/', '/Users/zongen/Downloads/股票2/']:
        gutenberg_files.extend(sorted(glob.glob(os.path.join(d, 'pg*.txt'))))

    for f in gutenberg_files:
        basename = os.path.basename(f)
        # 確認是 Gutenberg（不是 archive.org HTML）
        with open(f, 'r', encoding='utf-8', errors='replace') as fh:
            header = fh.read(500)
        if 'Project Gutenberg' in header or 'pgdp.net' in header:
            result = convert_gutenberg(f, output_dir)
            if result:
                print(f"  ✅ {result.name}")
                converted += 1
            else:
                print(f"  ❌ {basename} (提取失敗)")
                skipped += 1

    # 2. 複製現有的 .md 檔案
    print("\n=== 複製現有 .md 檔案 ===")
    md_files = []
    for d in ['/Users/zongen/Downloads/股票/', '/Users/zongen/Downloads/股票2/']:
        md_files.extend(sorted(glob.glob(os.path.join(d, '*.md'))))

    for f in md_files:
        basename = os.path.basename(f)
        result = convert_existing_md(f, output_dir)
        if result:
            print(f"  ✅ {result.name}")
            converted += 1

    print(f"\n=== 總結 ===")
    print(f"  轉換成功: {converted}")
    print(f"  跳過: {skipped}")
    print(f"  輸出: {output_dir}")


if __name__ == "__main__":
    main()
