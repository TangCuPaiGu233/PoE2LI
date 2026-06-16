"""Normalize raw extraction edges into kb_edges format."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_edges(raw_edges: list[dict]) -> list[dict]:
    """Convert parser output edges to canonical kb_edges rows.

    Each parser output: {src_id, src_cn, relation, dst_id, dst_cn}
    Each kb_edge row: {src_entity_key, dst_entity_key, relation, weight, source}

    Rules:
    - Deduplicate by (src, dst, relation)
    - Assign weight based on relation confidence
    """
    seen: set[tuple[str, str, str]] = set()
    normalized: list[dict] = []

    RELATION_WEIGHTS = {
        "belongs_to": 1.0,
        "supports": 0.9,
        "requires_weapon": 0.9,
        "has_tag": 1.0,
        "grants_buff": 0.8,
        "based_on": 1.0,
        "drops_from": 0.7,
        "has_mod": 0.8,
        "has_implicit": 1.0,
        "has_mod_pool": 0.8,
        "applies_to": 0.9,
        "is_prefix": 1.0,
        "is_suffix": 1.0,
        "has_effect": 0.8,
        "found_in_map": 0.7,
        "contains_boss": 0.8,
        "connects_to": 0.6,
        "rewards": 0.7,
        "requires_npc": 0.7,
        "uses_currency": 0.9,
        "modifies_item": 0.8,
        "grants_stat": 0.9,
        "requires_allocation": 1.0,
    }

    for edge in raw_edges:
        key = (edge["src_id"], edge["relation"], edge["dst_id"])
        if key in seen:
            continue
        seen.add(key)

        src_key = edge["src_id"].replace(":", "_", 1)
        dst_key = edge["dst_id"].replace(":", "_", 1)
        weight = RELATION_WEIGHTS.get(edge["relation"], 0.5)

        normalized.append({
            "src_entity_key": src_key,
            "dst_entity_key": dst_key,
            "relation": edge["relation"],
            "weight": weight,
            "source": "poe2db_crawler_v1",
        })

    return normalized


def load_raw_edges(filepath: str = "data/raw_edges.jsonl") -> list[dict]:
    edges: list[dict] = []
    path = Path(filepath)
    if not path.exists():
        return edges
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                edges.append(json.loads(line))
    return edges
