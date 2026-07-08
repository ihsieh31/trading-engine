from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_db():
    import db
    db.init_db()


def test_working_tier_store_and_query():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    ms._working["current"] = {"key": "value"}
    result = ms.query("", tier="working")
    assert result == [{"key": "value"}]


def test_working_tier_by_workflow_id():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    ms.write({"workflow_id": "wf1", "data": "test"}, tier="working")
    # query always returns "current" key
    result = ms.query("", tier="working")
    assert result == [{}]  # "current" key not set


def test_episodic_tier_returns_list():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    result = ms.query("", tier="episodic")
    assert isinstance(result, list)


def test_semantic_tier_without_kb_does_not_crash():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    # Should not raise even without a real knowledge base
    result = ms.query("test query", tier="semantic")
    assert isinstance(result, list)


def test_write_semantic_does_not_crash():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    # Writing without chromadb should not crash
    ms.write({"id": "test-rule", "title": "test", "content": "test"}, tier="semantic")


def test_decay_does_not_crash():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    ms._apply_decay()


def test_detect_conflict_empty():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    result = ms.detect_conflict({"tags": ["test"]})
    assert isinstance(result, list)


def test_expand_graph_returns_list():
    from memory.memory_service import MemoryService
    ms = MemoryService()
    result = ms.expand_graph("nonexistent")
    assert isinstance(result, list)
