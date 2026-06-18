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
from collections import Counter, defaultdict
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
# Community synonym mapping
# ---------------------------------------------------------------------------
# Some player-facing terms don't match any entity name in the game data.
# Map them to entity key patterns for direct retrieval.

_COMMUNITY_SYNONYMS: dict[str, dict] = {
    "隐藏天赋": {
        "description": "涂油天赋（Anoint Passives）— 使用蒸馏情绪涂油项链获得的核心天赋",
        "key_prefixes": ["DeliriumAnoint_"],
        "table": "PassiveSkills",
    },
    "涂油天赋": {
        "description": "涂油天赋（Anoint Passives）— 使用蒸馏情绪涂油项链获得的核心天赋",
        "key_prefixes": ["DeliriumAnoint_"],
        "table": "PassiveSkills",
    },
    "涂油": {
        "description": "涂油天赋（Anoint Passives）— 使用蒸馏情绪涂油项链获得的核心天赋",
        "key_prefixes": ["DeliriumAnoint_"],
        "table": "PassiveSkills",
    },
    "彩蛋天赋": {
        "description": "彩蛋天赋 — 需要前置条件才会显示的特殊天赋",
        "keys": ["armour_and_evasion45", "evasion_and_energy_shield37"],
        "table": "PassiveSkills",
    },
}


def _check_community_synonyms(gg, query: str) -> str | None:
    """Check if query matches a known community synonym.

    Returns formatted result string if matched, None otherwise.
    """
    q_lower = query.lower().strip()

    for term, config in _COMMUNITY_SYNONYMS.items():
        if term not in q_lower:
            continue

        table = config["table"]
        entries: list[tuple[str, str, str]] = []  # (key, cn_name, en_name)

        # Collect by key prefixes
        for prefix in config.get("key_prefixes", []):
            for (t, k) in gg.entity_index:
                if t == table and k.startswith(prefix):
                    info = gg.entity_index[(t, k)]
                    cn = info.get("name_sc") or ""
                    en = info.get("name_en") or ""
                    # Deduplicate by CN name
                    if cn and cn not in [e[1] for e in entries]:
                        entries.append((k, cn, en))

        # Collect by explicit keys
        for k in config.get("keys", []):
            info = gg.entity_index.get((table, k))
            if info:
                cn = info.get("name_sc") or ""
                en = info.get("name_en") or ""
                if cn and cn not in [e[1] for e in entries]:
                    entries.append((k, cn, en))

        if not entries:
            continue

        lines = [
            "【游戏数据搜索结果】",
            f"匹配: {config['description']}",
            f"共 {len(entries)} 个天赋:",
            "",
        ]
        for i, (key, cn, en) in enumerate(entries, 1):
            suffix = f" ({en})" if en and en != cn else ""
            lines.append(f"{i}. [{table}:{key}] {cn}{suffix}")

        return "\n".join(lines)

    return None


# ---------------------------------------------------------------------------
# LLM-callable search
# ---------------------------------------------------------------------------

def search_game(
    query: str,
    table_filter: str | None = None,
    expand_hops: int = 1,
    max_results: int = 30,
) -> str:
    """LLM-callable game data search.

    Searches GameGraph (119k entities, 212k edges) for matching entities,
    auto-expands the best match to show related data, and returns formatted
    Chinese+English text for the LLM to use.

    Returns an explicit "not found" message if nothing matches — the LLM
    should treat this as authoritative proof that the entity doesn't exist
    in PoE2's current game data.
    """
    gg = get_game_graph()
    if gg is None:
        return "【游戏数据暂不可用，请勿凭训练数据回答】"

    if not query or not query.strip():
        return "【游戏数据搜索结果】\n查询为空，请提供具体名称。"

    query = query.strip()

    # ---- Community synonym lookup ----
    # Some queries use community terms that don't match any entity name.
    # Map them to known entity key prefixes for direct retrieval.
    synonym_result = _check_community_synonyms(gg, query)
    if synonym_result:
        return synonym_result

    try:
        results = gg.find_entity(query, table_filter=table_filter)
        if not results:
            return (
                f"【游戏数据搜索结果】\n"
                f"未找到与 \"{query}\" 匹配的游戏实体。\n"
                f"⚠️ 这意味着该内容在 PoE2 当前版本中可能不存在，请勿凭训练数据编造。"
            )

        # Split exact vs partial
        exact = [r for r in results if r[3] == "exact"]
        partial = [r for r in results if r[3] == "partial"]
        total = len(exact) + len(partial)

        # Table-grouped summary for AI quick parsing
        table_counts = Counter(table for table, _, _, _ in results)
        table_summary = ", ".join(f"{t} ({c})" for t, c in table_counts.most_common())

        lines = [
            f"【游戏数据搜索结果】",
            f"匹配: {total} 个（{len(exact)} 精确）",
            f"分布: {table_summary}",
            "",
        ]

        # List search results (cap at 15, summarize remainder by table)
        list_cap = min(max_results, 15)
        shown = 0
        for table, key, display, match_type in results[:list_cap]:
            tag = "精确" if match_type == "exact" else "部分"
            lines.append(f"{shown + 1}. [{tag}] {table}:{key} — {display}")
            shown += 1

        remaining = results[list_cap:]
        if remaining:
            rem_counts = Counter(t for t, _, _, _ in remaining)
            rem_summary = ", ".join(f"{t} ({c})" for t, c in rem_counts.most_common())
            lines.append(f"  ... 还有 {len(remaining)} 个结果: {rem_summary}")

        # Auto-expand the best match only for specific queries (<=5 exact matches).
        # For broad queries with many matches, the list summary is more useful.
        if len(exact) <= 5 and total <= 10:
            best = exact[0] if exact else partial[0]
            best_table, best_key, best_display, _ = best
            expanded = gg.expand(best_table, best_key, max_hops=expand_hops, max_nodes=40)

            lines.append(f"\n--- {best_display} 关联数据 ---")

            # Group edges by relation
            by_relation: dict[str, list[str]] = defaultdict(list)
            for src_t, src_k, rel, dst_t, dst_k, hop in expanded["edges"]:
                if hop != 1:
                    continue
                if (src_t, src_k) == (best_table, best_key):
                    dst_info = gg.entity_index.get((dst_t, dst_k), {})
                    name = dst_info.get("name_sc") or gg._get_display_name((dst_t, dst_k))
                    by_relation[rel].append(name)
                elif (dst_t, dst_k) == (best_table, best_key):
                    src_info = gg.entity_index.get((src_t, src_k), {})
                    name = src_info.get("name_sc") or gg._get_display_name((src_t, src_k))
                    by_relation[f"← {rel}"].append(name)

            if by_relation:
                for rel, targets in by_relation.items():
                    lines.append(f"  {rel}: {', '.join(targets[:12])}")
            else:
                lines.append("  （无关联数据）")

            # For Ascendancy entities, also list passive skill nodes
            if best_table == "Ascendancy":
                asc_nodes = _collect_ascendancy_nodes(gg, expanded)
                if asc_nodes:
                    lines.append("")
                    for section in asc_nodes:
                        lines.append(section)

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"GameGraph search_game failed: {e}")
        return f"【游戏数据搜索异常】{e}"


def _collect_ascendancy_nodes(gg, expanded: dict) -> list[str]:
    """Collect PassiveSkills nodes from an ascendancy expansion."""
    notables: list[str] = []
    smalls: list[str] = []

    for (t, k), info in expanded["nodes"].items():
        if t != "PassiveSkills":
            continue
        if "Start" in k:
            continue

        node_info = gg.entity_index.get((t, k), {})
        cn = node_info.get("name_sc") or ""
        en = node_info.get("name_en") or ""
        if not cn:
            continue

        suffix = f"({en})" if en and en != cn else ""
        entry = f"{cn}{suffix}"

        if "Notable" in k:
            notables.append(entry)
        else:
            smalls.append(entry)

    sections = []
    if notables:
        sections.append("  核心天赋: " + ", ".join(notables))
    if smalls:
        # Deduplicate smalls
        small_counts: dict[str, int] = {}
        for s in smalls:
            small_counts[s] = small_counts.get(s, 0) + 1
        parts = [f"{s} x{c}" if c > 1 else s for s, c in small_counts.items()]
        sections.append("  小天赋: " + ", ".join(parts))
    return sections


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
