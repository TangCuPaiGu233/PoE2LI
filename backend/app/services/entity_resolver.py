"""entity_resolver.py — 统一的游戏实体 CN→EN 解析器 + EN 关键词拼写纠错。

覆盖：技能（caimogu）、装备/暗金（poe2db）、升华 notable 名（asc_nodes）、升华/职业。
策略：
  1. CN 精确匹配 → 注入 EN 名
  2. LLM 关键词 → fuzzy 匹配已知 EN 实体名 → 纠正拼写
"""
import json
import os
import re
from difflib import get_close_matches

# ── Lazy-loaded alias maps ──
_cn_to_en: dict[str, tuple[str, str]] | None = None
_all_en_names: list[str] | None = None  # All known EN entity names for fuzzy matching


def _load_aliases() -> dict[str, tuple[str, str]]:
    global _cn_to_en, _all_en_names
    if _cn_to_en is not None:
        return _cn_to_en

    _cn_to_en = {}
    _all_en_names = []

    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")

    def _add(cn, en, etype):
        if cn and en and cn not in _cn_to_en:
            _cn_to_en[cn] = (en, etype)
            if en not in _all_en_names:
                _all_en_names.append(en)

    # 1. Caimogu skills
    skills_path = os.path.join(data_dir, "caimogu_skills.json")
    if os.path.exists(skills_path):
        with open(skills_path, "r", encoding="utf-8") as f:
            for s in json.load(f):
                _add(s.get("cn", "").strip(), s.get("en", "").strip(), "skill")

    # 2. game_aliases.json (poe2db items/mods)
    aliases_path = os.path.join(data_dir, "game_aliases.json")
    if os.path.exists(aliases_path):
        with open(aliases_path, "r", encoding="utf-8") as f:
            aliases = json.load(f)
        for cn, info in aliases.get("cn_to_en", {}).items():
            _add(cn, info.get("en", ""), info.get("type", "item"))

    # 3. Ascendancy names
    from app.services.entity_dict import ASCENDANCY_CN_TO_EN as asc_en_map
    for cn, en in asc_en_map.items():
        _add(cn, en, "ascendancy")

    # 4. Class names
    from app.services.entity_dict import CLASS_CN_TO_EN as class_en_map
    for cn, en in class_en_map.items():
        _add(cn, en, "class")

    # 5. Ascendancy notables — extract from DB (EN only, for spell-check)
    _load_notables()

    return _cn_to_en


def _load_notables():
    """Load notable names from asc_nodes chunks (for spell-check only, no CN)."""
    global _all_en_names
    try:
        from app.core.database import SessionLocal
        from app.models.build import KnowledgeChunk
        db = SessionLocal()
        chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.chunk_type == "asc_nodes"
        ).all()
        for c in chunks:
            data = json.loads(c.content)
            st = data.get("search_text", "")
            for m in re.finditer(r'\[notable\] ([^:]+):', st):
                name = m.group(1).strip()
                if name and name not in _all_en_names:
                    _all_en_names.append(name)
        db.close()
    except Exception:
        pass  # Skip if DB not available (e.g., during startup)


def resolve_all_entities(text: str) -> list[tuple[str, str, str]]:
    """Find all known CN entity names in the text.
    Returns list of (en_name, cn_name, entity_type) tuples.
    """
    aliases = _load_aliases()
    found: dict[str, tuple[str, str, str]] = {}

    sorted_cn = sorted(aliases.keys(), key=len, reverse=True)
    for cn_name in sorted_cn:
        if cn_name in text and cn_name not in found:
            en_name, etype = aliases[cn_name]
            found[cn_name] = (en_name, cn_name, etype)

    return list(found.values())


def correct_keywords(keywords: list[str], cutoff: float = 0.75) -> list[str]:
    """Fuzzy-match LLM keywords against known EN entity names.

    If a keyword closely matches a known entity, return the corrected name.
    This fixes LLM spelling mistakes like 'Moriigan' → 'Morrigan'.
    """
    _load_aliases()
    if not _all_en_names:
        return keywords

    corrected = []
    for kw in keywords:
        # Try fuzzy match against known names
        matches = get_close_matches(kw, _all_en_names, n=1, cutoff=cutoff)
        if matches and matches[0].lower() != kw.lower():
            corrected.append(matches[0])
        else:
            corrected.append(kw)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for k in corrected:
        if k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return result


def resolve_entity(cn_name: str) -> tuple[str, str] | None:
    """Look up a single CN entity name. Returns (en_name, type) or None."""
    aliases = _load_aliases()
    return aliases.get(cn_name)


# ── Notable → Ascendancy mapping (lazy-loaded from DB) ──
_notable_to_asc: dict[str, str] | None = None


def _load_notable_asc_map() -> dict[str, str]:
    """Build {notable_name_lower: ascendancy_name} from asc_nodes chunks."""
    global _notable_to_asc
    if _notable_to_asc is not None:
        return _notable_to_asc
    _notable_to_asc = {}
    try:
        from app.core.database import SessionLocal
        from app.models.build import KnowledgeChunk
        db = SessionLocal()
        chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.chunk_type == "asc_nodes"
        ).all()
        for c in chunks:
            data = json.loads(c.content)
            asc_name = data.get("ascendancy", "")
            if not asc_name:
                continue
            st = data.get("search_text", "")
            for m in re.finditer(r'\[notable\] ([^:]+):', st):
                name = m.group(1).strip()
                if name:
                    _notable_to_asc[name.lower()] = asc_name
        db.close()
    except Exception:
        pass
    return _notable_to_asc


def find_asc_for_notable(keywords: list[str]) -> str | None:
    """Check if any keyword matches a known notable, return its ascendancy name."""
    notable_map = _load_notable_asc_map()
    for kw in keywords:
        asc = notable_map.get(kw.lower())
        if asc:
            return asc
    return None
