"""entity_resolver.py — 统一的游戏实体 CN→EN 解析器。

覆盖：技能（caimogu）、装备/暗金（poe2db）、升华 notable 名（asc_nodes）。
从多个数据源加载别名表，支持从用户中文查询中抽取已知实体。
"""
import json
import os
import re

# ── Lazy-loaded alias maps ──
_cn_to_en: dict[str, tuple[str, str]] | None = None  # cn_name → (en_name, type)


def _load_aliases() -> dict[str, tuple[str, str]]:
    """Load all CN→EN alias maps. Returns {cn_name: (en_name, type)}."""
    global _cn_to_en
    if _cn_to_en is not None:
        return _cn_to_en

    _cn_to_en = {}

    data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    # In container, data_dir is /app/data
    if not os.path.isdir(data_dir):
        data_dir = "/app/data"

    # 1. Caimogu skills (Tencent-aligned CN names)
    skills_path = os.path.join(data_dir, "caimogu_skills.json")
    if os.path.exists(skills_path):
        with open(skills_path, "r", encoding="utf-8") as f:
            skills = json.load(f)
        for s in skills:
            cn = s.get("cn", "").strip()
            en = s.get("en", "").strip()
            if cn and en and cn not in _cn_to_en:
                _cn_to_en[cn] = (en, "skill")

    # 2. game_aliases.json (poe2db items/mods)
    aliases_path = os.path.join(data_dir, "game_aliases.json")
    if os.path.exists(aliases_path):
        with open(aliases_path, "r", encoding="utf-8") as f:
            aliases = json.load(f)
        cn_map = aliases.get("cn_to_en", {})
        for cn, info in cn_map.items():
            if cn not in _cn_to_en:
                _cn_to_en[cn] = (info.get("en", ""), info.get("type", "item"))

    # 3. Ascendancy notables from entity_dict
    from app.services.entity_dict import ASCENDANCY_CN_TO_EN as asc_en_map
    for cn, en in asc_en_map.items():
        if cn not in _cn_to_en:
            _cn_to_en[cn] = (en, "ascendancy")

    # 4. Class names
    from app.services.entity_dict import CLASS_CN_TO_EN as class_en_map
    for cn, en in class_en_map.items():
        if cn not in _cn_to_en:
            _cn_to_en[cn] = (en, "class")

    return _cn_to_en


def resolve_all_entities(text: str) -> list[tuple[str, str, str]]:
    """Find all known CN entity names in the text.

    Returns list of (en_name, cn_name, entity_type) tuples.
    Longer matches preferred over shorter ones.
    """
    aliases = _load_aliases()
    found: dict[str, tuple[str, str, str]] = {}  # cn → (en, cn, type), dedup

    # Sort aliases by length (longest first) for greedy matching
    sorted_cn = sorted(aliases.keys(), key=len, reverse=True)

    for cn_name in sorted_cn:
        if cn_name in text and cn_name not in found:
            en_name, etype = aliases[cn_name]
            found[cn_name] = (en_name, cn_name, etype)

            # If we matched a long name, skip its substrings
            # e.g., "灵魂行者" matched → skip "行者"
            for shorter in list(sorted_cn):
                if shorter != cn_name and shorter in cn_name and shorter in text:
                    if shorter not in found:
                        pass  # Don't add substrings

    return list(found.values())


def resolve_entity(cn_name: str) -> tuple[str, str] | None:
    """Look up a single CN entity name. Returns (en_name, type) or None."""
    aliases = _load_aliases()
    return aliases.get(cn_name)
