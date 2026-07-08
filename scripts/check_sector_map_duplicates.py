#!/usr/bin/env python3
"""Check sector_map.py for duplicate or conflicting ticker-sector assignments.

使用 AST 解析原始碼字面量（而非 import 後的 dict 物件），
在 Python 字典去重「之前」就抓出原始碼中的重複 key。
"""

import ast
import sys
from pathlib import Path


def check_source_duplicates(filepath: str = None) -> bool:
    if filepath is None:
        filepath = str(Path(__file__).resolve().parent.parent / "sector_map.py")
    tree = ast.parse(Path(filepath).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target_ids = [getattr(t, "id", None) for t in node.targets]
            if "SECTOR_MAP" in target_ids and isinstance(node.value, ast.Dict):
                keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                seen: dict[str, list[int]] = {}
                for i, k in enumerate(keys):
                    seen.setdefault(k, []).append(i)
                dupes = {k: v for k, v in seen.items() if len(v) > 1}
                if dupes:
                    print("Source-level duplicate keys found (before Python dedup):")
                    for ticker, positions in sorted(dupes.items()):
                        print(f"  '{ticker}' appears at line positions: {positions}")
                    return False
                print(f"OK — {len(keys)} entries, {len(set(keys))} unique, no source-level duplicates.")
                return True
    print("Could not find SECTOR_MAP dict literal in sector_map.py")
    return True


def main():
    ok = check_source_duplicates()
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
