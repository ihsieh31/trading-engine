from __future__ import annotations
"""知識庫核心 — Obsidian vault 解析 + chromadb 向量儲存 + wikilink graph + 經驗檢索。

用法：
    kb = KnowledgeBase()
    kb.sync_vault()                    # 掃描 Obsidian vault 同步新筆記
    results = kb.query("止損策略")       # 語意檢索
    rules = kb.query_rules({"ticker":"AAPL","regime":"bear"})  # 查詢交易規則
    kb.add_reflection(entry)           # 加入 reflection 產出的規則
"""

import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
TAG_RE = re.compile(r'(?m)^tags?:\s*\[?(.+?)\]?$')


@dataclass
class KBEntry:
    id: str
    title: str
    content: str
    filepath: str
    tags: list[str] = field(default_factory=list)
    wikilinks_out: list[str] = field(default_factory=list)
    source: str = "vault"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            k = key.strip().lower()
            v = val.strip().strip('"').strip("'")
            if k in ("tags", "tag"):
                meta["tags"] = [t.strip() for t in v.replace("[", "").replace("]", "").split(",") if t.strip()]
            else:
                meta[k] = v
    return meta


def _strip_frontmatter(text: str) -> str:
    return FRONTMATTER_RE.sub("", text, count=1)


def _get_title(filepath: str, content: str) -> str:
    title = Path(filepath).stem
    h1 = re.search(r'(?m)^#\s+(.+)$', content)
    if h1:
        title = h1.group(1).strip()
    return title


def _extract_wikilinks(content: str) -> list[str]:
    return list(dict.fromkeys(WIKILINK_RE.findall(content) or []))


_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDER = None
_EMBED_DIM = 384


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
            log.info("Embedding model loaded: all-MiniLM-L6-v2 (384 dim)")
        except Exception as e:
            log.error(f"Failed to load embedding model: {e}")
            _EMBEDDER = False
    return _EMBEDDER if _EMBEDDER is not False else None


def _get_embedding(text: str) -> list[float]:
    text = text[:8000]
    key = _md5(text)
    cached = _EMBEDDING_CACHE.get(key)
    if cached:
        return cached

    embedder = _get_embedder()
    if embedder is None:
        return [0.0] * _EMBED_DIM

    try:
        emb = embedder.encode(text).tolist()
        _EMBEDDING_CACHE[key] = emb
        return emb
    except Exception as e:
        log.warning(f"Embedding failed: {e}")
        return [0.0] * _EMBED_DIM


class KnowledgeBase:
    """知識庫管理。

    用法：
        kb = KnowledgeBase()
        kb.sync_vault()  # 首次同步
        results = kb.query("some query")
    """

    def __init__(self, config=None):
        from config import Config
        self._cfg = config or Config()
        self._client = None
        self._doc_collection = None
        self._rule_collection = None
        self._fallback_rules: dict[str, KBEntry] = {}  # used when chromadb unavailable
        self._chromadb_ok = True
        self.graph: dict[str, set[str]] = {}
        self._load_graph()
        self._vault_path = self._cfg.OBSIDIAN_VAULT_PATH
        self._vault_path.mkdir(parents=True, exist_ok=True)

    @property
    def client(self):
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.PersistentClient(path=str(self._cfg.DATA_DIR / "chromadb"))
            except ImportError:
                log.warning("chromadb not installed — using in-memory fallback")
                self._chromadb_ok = False
                return None
        return self._client

    @property
    def doc_collection(self):
        if not self._chromadb_ok:
            return None
        if self._doc_collection is None and self.client is not None:
            self._doc_collection = self.client.get_or_create_collection("documents")
        return self._doc_collection

    @property
    def rule_collection(self):
        if not self._chromadb_ok:
            return None
        if self._rule_collection is None and self.client is not None:
            self._rule_collection = self.client.get_or_create_collection("trading_rules")
        return self._rule_collection

    # ── Graph Persistence ────────────────────────────────────

    def _save_graph(self):
        serializable = {k: list(v) for k, v in self.graph.items()}
        (self._cfg.DATA_DIR / "wikilink_graph.json").write_text(json.dumps(serializable, indent=2))

    def _load_graph(self):
        gf = self._cfg.DATA_DIR / "wikilink_graph.json"
        if gf.exists():
            try:
                data = json.loads(gf.read_text())
                self.graph = {k: set(v) for k, v in data.items()}
            except Exception as e:
                log.warning(f"Failed to load wikilink graph: {e}")
                self.graph = {}
        else:
            self.graph = {}

    # ── Vault Sync ───────────────────────────────────────────

    def sync_vault(self, full_rescan: bool = False) -> int:
        """掃描 Obsidian vault，同步新/修改的檔案到 chromadb。

        Args:
            full_rescan: True 時強制重新處理所有檔案。

        Returns:
            本次新增或更新的文件數量。
        """
        if not self._vault_path.exists():
            log.warning(f"Obsidian vault not found: {self._vault_path}")
            return 0

        md_files = sorted(self._vault_path.rglob("*.md"))
        if not md_files:
            log.info(f"No markdown files in vault: {self._vault_path}")
            return 0

        if full_rescan:
            existing_ids = set()
        elif self._chromadb_ok and self.doc_collection is not None and self.doc_collection.count() > 0:
            existing_ids = set(self.doc_collection.get()["ids"])
        else:
            existing_ids = set()

        updated = 0

        for fp in md_files:
            rel_path = str(fp.relative_to(self._vault_path))
            content = fp.read_text(encoding="utf-8", errors="replace")
            entry_id = _md5(rel_path)

            content_hash = _md5(content)
            if not full_rescan and entry_id in existing_ids:
                meta = self._get_meta(entry_id)
                if meta and meta.get("content_hash") == content_hash:
                    continue

            frontmatter = _parse_frontmatter(content)
            body = _strip_frontmatter(content)
            title = _get_title(rel_path, content)
            tags = frontmatter.get("tags", [])
            wikilinks = _extract_wikilinks(body)

            try:
                embedding = _get_embedding(f"{title}\n\n{body[:4000]}")
            except Exception as e:
                log.warning(f"Embedding failed for {rel_path}: {e}")
                embedding = [0.0] * _EMBED_DIM

            if not self._chromadb_ok or self.doc_collection is None:
                log.warning(f"ChromaDB unavailable, skipping vault sync for {rel_path}")
                self.graph[title] = set(wikilinks)
                updated += 1
                continue

            self.doc_collection.upsert(
                ids=[entry_id],
                embeddings=[embedding],
                documents=[body[:8000]],
                metadatas=[{
                    "title": title,
                    "tags": ",".join(tags),
                    "source": "vault",
                    "filepath": rel_path,
                    "wiki_links": ",".join(wikilinks),
                    "content_hash": content_hash,
                }],
            )
            self.graph[title] = set(wikilinks)
            updated += 1

        self._save_graph()
        log.info(f"Vault sync: {updated} files processed ({len(md_files)} total)")
        return updated

    def _get_meta(self, entry_id: str) -> dict | None:
        try:
            result = self.doc_collection.get(ids=[entry_id])
            if result and result["metadatas"] and result["metadatas"][0]:
                return result["metadatas"][0]
        except Exception:
            pass
        return None

    # ── Query ────────────────────────────────────────────────

    def query(self, text: str, k: int = 5, source: str | None = None) -> list[KBEntry]:
        """語意檢索知識庫。

        Args:
            text: 查詢文字。
            k: 回傳結果數量。
            source: 過濾來源（"vault" / "reflection"），None 為不限。

        Returns:
            最相關的 KBEntry 列表。
        """
        try:
            query_embedding = _get_embedding(text)
        except Exception as e:
            log.warning(f"Query embedding failed: {e}")
            return []

        where = {"source": source} if source else None
        try:
            results = self.doc_collection.query(
                query_embeddings=[query_embedding],
                n_results=min(k, 20),
                where=where,
            )
        except Exception as e:
            log.warning(f"Chroma query failed: {e}")
            return []

        entries = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                entries.append(KBEntry(
                    id=doc_id,
                    title=meta.get("title", ""),
                    content=doc,
                    filepath=meta.get("filepath", ""),
                    tags=meta.get("tags", "").split(",") if meta.get("tags") else [],
                    wikilinks_out=meta.get("wiki_links", "").split(",") if meta.get("wiki_links") else [],
                    source=meta.get("source", "vault"),
                ))
        return entries

    def query_by_tags(self, tags: list[str], k: int = 20) -> list[KBEntry]:
        """以標籤過濾檢索。"""
        if not tags:
            return []
        # Store tags as JSON array for proper querying
        where = {"tags": {"$contains": tags[0]}}
        try:
            results = self.doc_collection.query(
                query_texts=[" "],
                n_results=k,
                where=where,
            )
        except Exception as e:
            log.warning(f"Tag query failed: {e}")
            return []

        # Post-filter: only return docs where tags match exactly
        entries = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                doc_tags_str = meta.get("tags", "")
                doc_tags = [t.strip() for t in doc_tags_str.split(",") if t.strip()] if doc_tags_str else []
                if not any(tag in doc_tags for tag in tags):
                    continue
                entries.append(KBEntry(
                    id=doc_id,
                    title=meta.get("title", ""),
                    content=doc,
                    filepath=meta.get("filepath", ""),
                    tags=meta.get("tags", "").split(",") if meta.get("tags") else [],
                    wikilinks_out=meta.get("wiki_links", "").split(",") if meta.get("wiki_links") else [],
                    source=meta.get("source", "vault"),
                ))
        return entries

    def get_linked(self, title: str) -> list[str]:
        """從 wikilink graph 取得 [[title]] 連結的所有筆記標題。"""
        return list(self.graph.get(title, set()))

    def get_backlinks(self, title: str) -> list[str]:
        """取得反向連結（哪些筆記連結了 [[title]]）。"""
        backlinks = []
        for node, links in self.graph.items():
            if title in links:
                backlinks.append(node)
        return backlinks

    # ── Reflection Rules ─────────────────────────────────────

    def add_reflection(self, entry: KBEntry):
        """將 reflection agent 產出的交易規則存入 rule_collection。"""
        if not self._chromadb_ok:
            self._fallback_rules[entry.id] = entry
            log.info(f"Reflection rule stored (fallback): {entry.title}")
            return

        try:
            embedding = _get_embedding(entry.content)
        except Exception as e:
            log.warning(f"Reflection embedding failed: {e}")
            embedding = [0.0] * _EMBED_DIM

        try:
            self.rule_collection.upsert(
                ids=[entry.id],
                embeddings=[embedding],
                documents=[entry.content],
                metadatas=[{
                    "title": entry.title,
                    "tags": ",".join(entry.tags),
                    "source": "reflection",
                    "filepath": entry.filepath,
                }],
            )
        except Exception as e:
            log.warning(f"ChromaDB upsert failed, using fallback: {e}")
            self._fallback_rules[entry.id] = entry
        log.info(f"Reflection rule stored: {entry.title}")

    def query_rules(self, context: dict | None = None, k: int = 5) -> list[KBEntry]:
        """查詢最符合當前情境的交易規則。

        Args:
            context: 可選的情境 dict，包含 ticker, sector, regime, rating 等。
            k: 回傳結果數量。

        Returns:
            最相關的規則列表。
        """
        if not self._chromadb_ok:
            return self._query_rules_fallback(context, k)

        try:
            count = self.rule_collection.count()
        except Exception:
            return self._query_rules_fallback(context, k)
        if count == 0:
            return self._query_rules_fallback(context, k)

        query_parts = []
        if context:
            for key in ("ticker", "sector", "regime", "rating", "action"):
                if context.get(key):
                    query_parts.append(f"{key}={context[key]}")
        query_text = " ".join(query_parts) if query_parts else "trading rule"

        try:
            query_embedding = _get_embedding(query_text)
        except Exception as e:
            log.warning(f"Rule query embedding failed: {e}")
            return []

        try:
            results = self.rule_collection.query(
                query_embeddings=[query_embedding],
                n_results=min(k, 10),
            )
        except Exception as e:
            log.warning(f"Rule query failed: {e}")
            return self._query_rules_fallback(context, k)

        entries = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                entries.append(KBEntry(
                    id=doc_id,
                    title=meta.get("title", ""),
                    content=doc,
                    filepath=meta.get("filepath", ""),
                    tags=meta.get("tags", "").split(",") if meta.get("tags") else [],
                    source=meta.get("source", "reflection"),
                ))
        return entries

    def _query_rules_fallback(self, context: dict | None = None, k: int = 5) -> list[KBEntry]:
        """chromadb 不可用時的 fallback 檢索。"""
        if not self._fallback_rules:
            return []
        entries = list(self._fallback_rules.values())
        if context and context.get("ticker"):
            ticker = context["ticker"].lower()
            matched = [e for e in entries if ticker in e.filepath.lower() or ticker in e.content.lower()]
            if matched:
                return matched[:k]
        return entries[:k]

    # ── Maintenance ──────────────────────────────────────────

    def query_rules_by_ticker(self, ticker: str, k: int = 3) -> list[KBEntry]:
        """查詢與特定 ticker 相關的交易規則。"""
        return self.query_rules({"ticker": ticker, "action": ""}, k=k)

    def get_stats(self) -> dict:
        """取得知識庫統計資訊。"""
        if self._chromadb_ok:
            try:
                doc_count = self.doc_collection.count() if self.doc_collection else 0
                rule_count = self.rule_collection.count() if self.rule_collection else 0
            except Exception:
                doc_count = len(self._fallback_rules)
                rule_count = 0
        else:
            doc_count = 0
            rule_count = len(self._fallback_rules)
        return {
            "documents": doc_count,
            "rules": rule_count,
            "graph_nodes": len(self.graph),
            "vault_path": str(self._vault_path),
            "chromadb_available": self._chromadb_ok,
        }

    def count_documents(self) -> int:
        try:
            return self.doc_collection.count() if self.doc_collection else 0
        except Exception:
            return 0

    def count_rules(self) -> int:
        if self._fallback_rules:
            return len(self._fallback_rules)
        try:
            return self.rule_collection.count() if self.rule_collection else 0
        except Exception:
            return 0
