"""Unit tests for retrieval dedup and name glue detection (no DB)."""

import json

from app.services.name_validation import is_concatenated_name
from app.services.retrieval_pipeline import dedup_by_parent_entity


def _chunk(cid: int, parent: str | None, sim: float) -> dict:
    payload = {}
    if parent:
        payload["parent_entity_id"] = parent
    return {
        "id": cid,
        "content": json.dumps(payload),
        "similarity": sim,
    }


def test_dedup_by_parent_keeps_best_similarity():
    chunks = [
        _chunk(1, "unique_foo", 0.5),
        _chunk(2, "unique_foo", 0.9),
        _chunk(3, "unique_bar", 0.7),
        _chunk(4, None, 0.6),
    ]
    out = dedup_by_parent_entity(chunks)
    ids = [c["id"] for c in out]
    assert 2 in ids
    assert 1 not in ids
    assert 3 in ids
    assert 4 in ids


def test_is_concatenated_name_cases():
    assert is_concatenated_name("MjölnerTorment Club") is True
    assert is_concatenated_name("Silent Thunder") is False
