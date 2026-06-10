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

    # 2. Caimogu items (Tencent-aligned CN, loaded BEFORE poe2db)
    items_path = os.path.join(data_dir, "caimogu_items.json")
    if os.path.exists(items_path):
        with open(items_path, "r", encoding="utf-8") as f:
            for s in json.load(f):
                _add(s.get("cn", "").strip(), s.get("en", "").strip(), "item")

    # 3. game_aliases.json (poe2db items/mods — fallback)
    aliases_path = os.path.join(data_dir, "game_aliases.json")
    if os.path.exists(aliases_path):
        with open(aliases_path, "r", encoding="utf-8") as f:
            aliases = json.load(f)
        for cn, info in aliases.get("cn_to_en", {}).items():
            _add(cn, info.get("en", ""), info.get("type", "item"))

    # 4. Ascendancy names
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

    Three strategies:
    1. Exact substring: known CN name appears in user text
    2. Partial word match: split user text into words, find aliases
       that share significant words (handles colloquial names like
       "扭曲项链" when the actual item is called something else)
    Returns list of (en_name, cn_name, entity_type) tuples.
    """
    aliases = _load_aliases()
    found: dict[str, tuple[str, str, str]] = {}

    # Strategy 1: exact substring (longest first)
    sorted_cn = sorted(aliases.keys(), key=len, reverse=True)
    for cn_name in sorted_cn:
        if cn_name in text and cn_name not in found:
            en_name, etype = aliases[cn_name]
            found[cn_name] = (en_name, cn_name, etype)

    # Strategy 2: if no exact match, try CJK bigram matching
    if not found:
        import re as _re
        def _bigrams(s):
            return {s[i:i+2] for i in range(len(s)-1) if _re.match(r'[一-鿿]{2}', s[i:i+2])}
        user_bigrams = _bigrams(text)
        if user_bigrams:
            for cn_name in sorted_cn:
                if cn_name in found:
                    continue
                alias_bigrams = _bigrams(cn_name)
                common = user_bigrams & alias_bigrams
                if len(common) >= 1:
                    en_name, etype = aliases[cn_name]
                    found[cn_name] = (en_name, cn_name, etype)

    return list(found.values())


def correct_keywords(keywords: list[str], cutoff: float = 0.8) -> list[str]:
    """Fuzzy-match LLM keywords against known EN entity names.

    Three strategies:
    1. Substring: does a known entity name appear within the keyword?
    2. Token fuzzy: split keyword into words, fuzzy-match each against known names
    3. Full fuzzy: for short keywords, fuzzy-match the whole thing
    """
    _load_aliases()
    if not _all_en_names:
        return keywords

    corrected = []
    for kw in keywords:
        matched = None

        # Strategy 1: substring match with accent normalization
        kw_lower = _normalize(kw.lower())
        for name in _all_en_names:
            if len(name) < 5:
                continue
            name_lower = _normalize(name.lower())
            if name_lower in kw_lower:
                matched = name
                break
            if name_lower.startswith("the ") and name_lower[4:] in kw_lower:
                matched = name
                break

        # Strategy 2: token-level fuzzy match
        # Extract significant words from keyword, fuzzy-match against words from known names
        if not matched:
            # Build word → full name index from known entities
            known_word_to_names: dict[str, list[str]] = {}
            for name in _all_en_names:
                for w in re.findall(r"[a-zA-Z']{4,}", _normalize(name)):
                    w_lower = w.lower()
                    if w_lower not in known_word_to_names:
                        known_word_to_names[w_lower] = []
                    known_word_to_names[w_lower].append(name)

            words = re.findall(r"[a-zA-Z']{4,}", _normalize(kw))
            for word in words:
                matches = get_close_matches(word, list(known_word_to_names.keys()), n=1, cutoff=cutoff)
                if matches:
                    # Found matching word → find which full entity names contain it
                    candidates = known_word_to_names.get(matches[0].lower(), [])
                    if candidates:
                        matched = candidates[0]  # Take first match
                        break

        # Strategy 3: full fuzzy for short keywords
        if not matched and len(kw) < 60:
            matches = get_close_matches(kw, _all_en_names, n=1, cutoff=cutoff)
            if matches and matches[0].lower() != kw.lower():
                matched = matches[0]

        if matched:
            corrected.append(matched)
        corrected.append(kw)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for k in corrected:
        if k.lower() not in seen:
            seen.add(k.lower())
            result.append(k)
    return result


def _normalize(text: str) -> str:
    """Normalize text for matching: remove accents, lowercase."""
    import unicodedata
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return text


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
