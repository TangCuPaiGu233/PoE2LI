"""GameGraph service — wraps GameGraph as a singleton for the AI pipeline.

Provides high-level methods to enrich AI prompts with authoritative game data
(Chinese names, ascendancy nodes, skill relationships) from the game_data graph.

Usage in other services:
    from app.services.game_graph_service import (
        get_cn_names,
        get_ascendancy_context,
        query_related,
    )
"""
from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded class name mapping (8 classes, stable across versions)
# ---------------------------------------------------------------------------

CLASS_CN_MAP: dict[str, str] = {
    "Warrior": "战士",
    "Ranger": "游侠",
    "Huntress": "女猎手",
    "Witch": "女巫",
    "Sorceress": "魔巫",
    "Monk": "行者",
    "Mercenary": "佣兵",
    "Druid": "德鲁伊",
}

# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_graph_instance = None
_LOAD_FAILED = False  # prevent repeated load attempts after failure


def _resolve_data_dir() -> str:
    """Locate the poe2_data directory.

    Search order:
    1. BACKEND_DATA_DIR env var      (override)
    2. /app/data/poe2_data           (inside Docker container)
    3. <project>/backend/data/poe2_data  (local dev)
    """
    env_dir = os.environ.get("BACKEND_DATA_DIR")
    if env_dir:
        candidate = os.path.join(env_dir, "poe2_data")
        if os.path.isdir(candidate):
            return candidate

    # Docker: data is at /app/data/poe2_data
    docker_path = "/app/data/poe2_data"
    if os.path.isdir(docker_path):
        return docker_path

    # Local dev: relative to this file → backend/app/services/../../data/poe2_data
    here = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.normpath(os.path.join(here, "..", "..", "data", "poe2_data"))
    if os.path.isdir(local_path):
        return local_path

    return ""


def get_game_graph():
    """Return the singleton GameGraph instance. Loads on first call.

    Returns None if data files are not available (graceful degradation).
    """
    global _graph_instance, _LOAD_FAILED

    if _graph_instance is not None:
        return _graph_instance

    if _LOAD_FAILED:
        return None

    try:
        data_dir = _resolve_data_dir()
        if not data_dir:
            logger.warning("GameGraph: poe2_data directory not found, graph disabled")
            _LOAD_FAILED = True
            return None

        relations_path = os.path.join(data_dir, "game_relations.json")
        if not os.path.exists(relations_path):
            logger.warning(f"GameGraph: {relations_path} not found, graph disabled")
            _LOAD_FAILED = True
            return None

        # Import here to avoid circular imports and to keep GameGraph
        # as an optional dependency (it lives in scripts/)
        scripts_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
        )
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from game_graph import GameGraph

        logger.info(f"GameGraph: loading from {data_dir} ...")
        _graph_instance = GameGraph(relations_path, data_dir, locale="sc")
        logger.info("GameGraph: loaded successfully")
        return _graph_instance

    except Exception as e:
        logger.error(f"GameGraph: failed to load — {e}")
        _LOAD_FAILED = True
        return None


# ---------------------------------------------------------------------------
# High-level API for AI pipeline
# ---------------------------------------------------------------------------

def get_cn_names(class_name: str, asc_name: str) -> tuple[str, str]:
    """Look up Chinese names for a class and ascendancy.

    Args:
        class_name: English class name from PoB (e.g. "Huntress")
        asc_name: English ascendancy name from PoB (e.g. "Spirit Walker")

    Returns:
        (cn_class, cn_asc) — returns original name if lookup fails
    """
    # Class name: use hardcoded map (8 classes, always correct)
    cn_class = CLASS_CN_MAP.get(class_name, class_name)

    # Ascendancy name: look up from GameGraph's Ascendancy table
    cn_asc = asc_name
    gg = get_game_graph()
    if gg is not None:
        found = _lookup_cn_name(gg, asc_name, "Ascendancy")
        if found:
            cn_asc = found

    return cn_class, cn_asc


def get_ascendancy_context(class_name: str, asc_name: str) -> str:
    """Build a structured Chinese text block describing the ascendancy tree.

    Returns empty string if GameGraph is unavailable or lookup fails.
    The output is designed to be appended directly to the homework prompt.
    """
    gg = get_game_graph()
    if gg is None:
        return ""

    try:
        # 1. Find the ascendancy entity in Ascendancy table
        results = gg.find_entity(asc_name, table_filter="Ascendancy")
        if not results:
            return ""

        asc_table, asc_key, _, _ = results[0]

        # 2. Expand 1 hop to get related PassiveSkills
        expanded = gg.expand(asc_table, asc_key, max_hops=1, max_nodes=100)

        # 3. Collect PassiveSkills nodes from the expansion
        notables: list[tuple[str, str]] = []  # (cn_name, en_name)
        smalls: list[tuple[str, str]] = []

        for (t, k), info in expanded["nodes"].items():
            if t != "PassiveSkills":
                continue
            if (t, k) == (asc_table, asc_key):
                continue  # skip the ascendancy entry itself

            node_info = gg.entity_index.get((t, k), {})
            cn_name = node_info.get("name_sc") or ""
            en_name = node_info.get("name_en") or ""

            if not cn_name:
                continue

            # Skip the start node
            if "Start" in k:
                continue

            # Classify by key pattern
            if "Notable" in k:
                notables.append((cn_name, en_name))
            else:
                smalls.append((cn_name, en_name))

        # 4. Build header with Chinese class/ascendancy names
        cn_class = CLASS_CN_MAP.get(class_name, class_name)
        cn_asc = _lookup_cn_name(gg, asc_name, "Ascendancy") or asc_name

        class_part = f"{cn_class}({class_name})" if cn_class != class_name else class_name
        asc_part = f"{cn_asc}({asc_name})" if cn_asc != asc_name else asc_name

        lines = [
            "## 升华天赋参考（来自游戏官方数据）",
            f"职业: {class_part} / 升华: {asc_part}",
            "",
        ]

        # 5. List nodes
        if notables:
            lines.append("### 核心天赋节点")
            for cn, en in notables:
                suffix = f"({en})" if en and en != cn else ""
                lines.append(f"- {cn}{suffix}")
            lines.append("")

        if smalls:
            # Deduplicate smalls and count occurrences
            small_counts: dict[str, tuple[str, int]] = {}
            for cn, en in smalls:
                key = cn
                if key in small_counts:
                    old_en, count = small_counts[key]
                    small_counts[key] = (old_en or en, count + 1)
                else:
                    small_counts[key] = (en, 1)

            lines.append("### 小天赋")
            for cn, (en, count) in small_counts.items():
                suffix = f"({en})" if en and en != cn else ""
                count_str = f" x{count}" if count > 1 else ""
                lines.append(f"- {cn}{suffix}{count_str}")
            lines.append("")

        if not notables and not smalls:
            return ""

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"GameGraph ascendancy context failed: {e}")
        return ""


def query_related(entity_name: str, max_hops: int = 1, max_nodes: int = 50) -> str:
    """General-purpose entity query for Chat context enrichment.

    Finds an entity by name, expands it, and formats the result as text.
    Returns empty string on failure.
    """
    gg = get_game_graph()
    if gg is None or not entity_name:
        return ""

    try:
        results = gg.find_entity(entity_name)
        if not results:
            return ""

        table, key, display, _ = results[0]
        expanded = gg.expand(table, key, max_hops=max_hops, max_nodes=max_nodes)

        lines = [f"【图谱关联: {display}】"]

        # Group edges by relation for readability
        by_relation: dict[str, list[str]] = defaultdict(list)
        for src_t, src_k, rel, dst_t, dst_k, hop in expanded["edges"]:
            if hop != 1:
                continue
            if (src_t, src_k) == (table, key):
                # Forward edge from root
                dst_info = gg.entity_index.get((dst_t, dst_k), {})
                name = dst_info.get("name_sc") or gg._get_display_name((dst_t, dst_k))
                by_relation[rel].append(name)
            elif (dst_t, dst_k) == (table, key):
                # Backward edge to root
                src_info = gg.entity_index.get((src_t, src_k), {})
                name = src_info.get("name_sc") or gg._get_display_name((src_t, src_k))
                by_relation[f"← {rel}"].append(name)

        for rel, targets in by_relation.items():
            lines.append(f"  {rel}: {', '.join(targets[:10])}")

        lines.append("")
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"GameGraph query_related failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lookup_cn_name(gg, en_name: str, preferred_table: str) -> Optional[str]:
    """Look up the simplified Chinese name for an English entity name."""
    if not en_name:
        return None

    results = gg.find_entity(en_name, table_filter=preferred_table)
    if not results:
        return None

    table, key, _, _ = results[0]
    info = gg.entity_index.get((table, key), {})
    return info.get("name_sc") or None
