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

from app.services.name_validation import is_trusted_en_name

# ── Lazy-loaded alias maps ──
_cn_to_en: dict[str, tuple[str, str, int, str]] | None = None
_all_en_names: list[str] | None = None
_aliases_mtime: float | None = None  # All known EN entity names for fuzzy matching


def _aliases_file_mtime() -> float | None:
    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    path = os.path.join(data_dir, "game_aliases.json")
    try:
        return os.path.getmtime(path) if os.path.exists(path) else None
    except OSError:
        return None


def _load_aliases() -> dict[str, tuple[str, str, int, str]]:
    global _cn_to_en, _all_en_names, _aliases_mtime
    mtime = _aliases_file_mtime()
    if _cn_to_en is not None and mtime is not None and _aliases_mtime == mtime:
        return _cn_to_en
    if _cn_to_en is not None and mtime is None and _aliases_mtime is None:
        return _cn_to_en
    _aliases_mtime = mtime
    _cn_to_en = None
    _all_en_names = None

    _cn_to_en = {}
    _all_en_names = []

    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")

    def _add(cn, en, etype, confidence=50, source="unknown"):
        if not cn or not en:
            return
        if confidence < 85 and not is_trusted_en_name(en):
            return
        existing = _cn_to_en.get(cn)
        if existing and confidence < existing[2]:
            return
        _cn_to_en[cn] = (en, etype, confidence, source)
        if en not in _all_en_names:
            _all_en_names.append(en)

    # 1. Caimogu skills
    skills_path = os.path.join(data_dir, "caimogu_skills.json")
    if os.path.exists(skills_path):
        with open(skills_path, "r", encoding="utf-8") as f:
            for s in json.load(f):
                _add(s.get("cn", "").strip(), s.get("en", "").strip(), "skill",
                     confidence=90, source="caimogu_skill")

    # 2. Curated item colloquial names (国服译名 + 社区俗称，见 entity_dict.ITEM_CN_ALIASES)
    from app.services.entity_dict import ITEM_CN_ALIASES
    for cn, en in ITEM_CN_ALIASES.items():
        _add(cn, en, "item", confidence=95, source="curated_item")

    # 3. Caimogu items (Tencent-aligned CN, loaded BEFORE poe2db)
    items_path = os.path.join(data_dir, "caimogu_items.json")
    if os.path.exists(items_path):
        with open(items_path, "r", encoding="utf-8") as f:
            for s in json.load(f):
                _add(s.get("cn", "").strip(), s.get("en", "").strip(), "item",
                     confidence=92, source="caimogu_item")

    _load_unique_cn_en(_add)

    # 4. game_aliases.json (poe2db items/mods — fallback)
    aliases_path = os.path.join(data_dir, "game_aliases.json")
    if os.path.exists(aliases_path):
        with open(aliases_path, "r", encoding="utf-8") as f:
            aliases = json.load(f)
        for cn, info in aliases.get("cn_to_en", {}).items():
            _add(cn, info.get("en", ""), info.get("type", "item"),
                 confidence=70, source="game_aliases")

    # 5. Ascendancy names
    from app.services.entity_dict import ASCENDANCY_CN_TO_EN as asc_en_map
    for cn, en in asc_en_map.items():
        _add(cn, en, "ascendancy", confidence=98, source="ascendancy")

    # 6. Class names
    from app.services.entity_dict import CLASS_CN_TO_EN as class_en_map
    for cn, en in class_en_map.items():
        _add(cn, en, "class", confidence=98, source="class")

    # 7. CraftofExile CN mod aliases (fallback, lowest priority)
    coe_path = os.path.join(data_dir, "coe_cn_aliases.json")
    if os.path.exists(coe_path):
        with open(coe_path, "r", encoding="utf-8") as f:
            coe = json.load(f)
        for en, cn in coe.items():
            _add(cn, en, "mod", confidence=60, source="craftofexile")

    # 5. Ascendancy notables — extract from DB (EN only, for spell-check)
    _load_notables()

    return _cn_to_en



def _load_unique_cn_en(_add) -> None:
    """Bundled + live jsonl CN→EN for all unique items."""
    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")

    # Live scrape file on NAS (highest for items)
    jsonl_path = os.path.join(data_dir, "poe2db_uniques.jsonl")
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    cn_raw = d.get("cn_data", "")
                    en = d.get("name_en", "")
                    if not cn_raw or not en:
                        continue
                    cn = json.loads(cn_raw).get("name", "").strip()
                    if cn:
                        _add(cn, en, "item", confidence=91, source="poe2db_jsonl")
                except Exception:
                    continue

    # Bundled index (ships with repo; always available)
    for rel in (
        os.path.join(data_dir, "unique_cn_en.json"),
        os.path.join(os.path.dirname(__file__), "..", "data", "unique_cn_en.json"),
    ):
        if not os.path.exists(rel):
            continue
        with open(rel, encoding="utf-8") as f:
            payload = json.load(f)
        for cn, info in payload.get("cn_to_en", {}).items():
            en = info.get("en", "") if isinstance(info, dict) else info
            if cn and en:
                _add(cn, en, "item", confidence=88, source="unique_cn_en")
        break


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
            en_name, etype, _, _ = aliases[cn_name]
            found[cn_name] = (en_name, cn_name, etype)

    # Strategy 2: CJK bigram scoring — require 2+ shared bigrams
    if not found:
        def _bigrams(s):
            result = set()
            for i in range(len(s) - 1):
                c1, c2 = s[i], s[i + 1]
                if "一" <= c1 <= "鿿" and "一" <= c2 <= "鿿":
                    result.add(c1 + c2)
            return result

        user_bigrams = _bigrams(text)
        if user_bigrams:
            scored: list[tuple[int, int, str]] = []
            for cn_name in sorted_cn:
                overlap = len(user_bigrams & _bigrams(cn_name))
                if overlap >= 2:
                    scored.append((overlap, len(cn_name), cn_name))
            if scored:
                scored.sort(reverse=True)
                best_overlap = scored[0][0]
                for overlap, _, cn_name in scored:
                    if overlap < best_overlap:
                        break
                    en_name, etype, _, _ = aliases[cn_name]
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


def resolve_entity(cn_name: str) -> tuple[str, str, int, str] | None:
    """Look up a single CN entity name. Returns (en_name, type) or None."""
    aliases = _load_aliases()
    hit = aliases.get(cn_name)
    if not hit:
        return None
    en_name, etype, _, _ = hit
    return en_name, etype


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
