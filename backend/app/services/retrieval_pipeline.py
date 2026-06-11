"""Unified knowledge retrieval pipeline for RAG QA.

Consolidates vector search, intent routing, entity resolution, reverse lookup
(effect → equipment), and multi-hop concept expansion used by /ask, /chat,
and /recommend encyclopedia fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding

logger = logging.getLogger(__name__)

# ── Intent keywords ──

BD_KEYWORDS = [
    "bd", "build", "构建", "配装", "开荒", "转型", "升级", "加点",
    "天赋怎么点", "技能搭配", "装备搭配", "怎么玩", "设计", "配一套",
    "给我配", "帮我配", "怎么做", "玩法", "builds", "攻略",
]
RECOMMEND_KEYWORDS = ["推荐", "哪个好", "选哪个", "对比", "更适合", "最好"]
TRADE_KEYWORDS = ["搜", "找装备", "买", "卖", "价格", "交易"]
REVERSE_LOOKUP_KEYWORDS = [
    "什么装备", "哪件装备", "哪个装备", "哪些装备", "有什么装备",
    "什么物品", "哪个物品", "哪些物品", "什么词缀", "哪些词缀",
    "靠什么", "怎么获得", "哪里获得", "能提供", "提供", "带什么",
    "有哪些", "哪些可以", "什么可以",
]


@dataclass
class RetrievalOptions:
    top_k: int = 5
    classify_text: str | None = None
    league: str | None = None
    game_version: str | None = None
    q_embedding: list[float] | None = None
    expand_concepts: bool = True
    max_concept_chunks: int = 6
    multi_source: bool = False
    per_source: int = 5
    alias_keywords: list[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    chunks: list[dict]
    intent: str
    search_query: str
    matched_concepts: list[str] = field(default_factory=list)
    concept_chunks: list[dict] = field(default_factory=list)


def default_league() -> str | None:
    return os.getenv("DEFAULT_LEAGUE") or None


def default_game_version() -> str | None:
    return os.getenv("DEFAULT_GAME_VERSION") or None


def classify_intent(question: str) -> str:
    """Classify user intent for retrieval routing."""
    q = question.lower()
    if any(k in q for k in BD_KEYWORDS):
        return "build_design"
    if any(k in q for k in RECOMMEND_KEYWORDS):
        return "recommend"
    if any(k in q for k in TRADE_KEYWORDS):
        return "trade"
    if is_reverse_lookup(question):
        return "reverse_lookup"
    return "encyclopedia"


def classify_question(question: str) -> list[str] | None:
    """Keyword-based chunk_type pre-filter."""
    q = question.lower()
    types: list[str] = []
    if any(w in q for w in [
        "skill", "gem", "herald", "aura", "attack", "spell",
        "技能", "宝石", "光环", "攻击", "法术", "召唤",
    ]):
        types.extend(["skill", "gem", "wiki", "minion"])
    if any(w in q for w in [
        "minion", "召唤兽", "召唤物", "仆从", "魔像",
    ]):
        types.extend(["minion", "wiki", "skill"])
    if any(w in q for w in [
        "unique", "item", "weapon", "armour", "sword", "bow",
        "暗金", "装备", "武器", "防具", "传奇", "项链", "戒指",
    ]):
        types.extend(["item", "mod"])
    if any(w in q for w in [
        "mod", "affix", "prefix", "suffix", "enchant",
        "词缀", "前缀", "后缀", "附魔",
    ]):
        types.extend(["mod", "item"])
    if any(w in q for w in [
        "quest", "act", "boss", "map", "waystone",
        "任务", "章节", "首领", "地图",
    ]):
        types.extend(["quest", "map"])
    if any(w in q for w in [
        "passive", "ascendancy", "tree", "node",
        "天赋", "升华", "节点",
    ]):
        types.extend(["passive", "asc_nodes"])
    return list(dict.fromkeys(types)) or None


def is_reverse_lookup(question: str) -> bool:
    """Detect effect → equipment reverse lookup intent."""
    q = question.lower()
    if not any(k in q for k in REVERSE_LOOKUP_KEYWORDS):
        return False
    return bool(find_concepts_in_query(question))


def find_concepts_in_query(query: str) -> list[tuple[str, dict]]:
    """Match TRADE_CONCEPTS aliases present in the user query."""
    from app.services.trade_concepts import TRADE_CONCEPTS

    q_lower = query.lower()
    matches: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for name, entry in TRADE_CONCEPTS.items():
        if name in seen:
            continue
        for alias in entry.get("aliases", []):
            al = alias.lower()
            if len(al) >= 2 and al in q_lower:
                matches.append((name, entry))
                seen.add(name)
                break
    return matches


def _cosine_sim(a, b) -> float:
    if a is not None and not isinstance(a, (list, tuple)):
        a = list(a)
    if b is not None and not isinstance(b, (list, tuple)):
        b = list(b)
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def apply_version_filters(filters: list, league: str | None, game_version: str | None) -> None:
    """Restrict to league/version while still including NULL-version legacy chunks."""
    if league:
        filters.append(or_(KnowledgeChunk.league == league, KnowledgeChunk.league.is_(None)))
    if game_version:
        filters.append(or_(
            KnowledgeChunk.game_version == game_version,
            KnowledgeChunk.game_version.is_(None),
        ))


def vector_search(
    db: Session,
    q_embedding: list[float],
    filters: list,
    top_k: int,
    min_similarity: float = 0.3,
) -> list[dict]:
    """Run vector similarity search with the given SQLAlchemy filters."""
    db_url = str(db.get_bind().url)
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        chunks = db.query(KnowledgeChunk).filter(*filters).all()
        scored = []
        for c in chunks:
            emb = c.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            sim = _cosine_sim(q_embedding, emb)
            scored.append((sim, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            _chunk_row_to_dict(c, round(s, 3))
            for s, c in scored[:top_k] if s > min_similarity
        ]

    dist = KnowledgeChunk.embedding.cosine_distance(q_embedding).label("distance")
    rows = (
        db.query(KnowledgeChunk, dist)
        .filter(*filters)
        .order_by(dist)
        .limit(top_k)
        .all()
    )
    return [
        _chunk_row_to_dict(c, round(1.0 - d, 3))
        for c, d in rows if (1.0 - d) > min_similarity
    ]


def _chunk_row_to_dict(c: KnowledgeChunk, similarity: float, **extra) -> dict:
    row = {
        "content": c.content,
        "chunk_type": c.chunk_type,
        "source": c.source,
        "links": c.links,
        "similarity": similarity,
    }
    row.update(extra)
    return row


def chunk_to_dict(c: KnowledgeChunk, similarity: float = 1.0) -> dict:
    """Convert ORM row to retrieval dict (structured direct lookup)."""
    return _chunk_row_to_dict(c, similarity)


def _base_filters(league: str | None, game_version: str | None) -> list:
    filters = [
        KnowledgeChunk.embedding.isnot(None),
        KnowledgeChunk.stale == False,  # noqa: E712
    ]
    apply_version_filters(filters, league, game_version)
    return filters


def _pattern_to_keywords(pattern: str) -> str:
    """Turn trade stat pattern into searchable plain text."""
    return re.sub(r"[#%+?]", " ", pattern).strip()


def reverse_lookup_chunks(
    db: Session,
    question: str,
    concepts: list[tuple[str, dict]],
    league: str | None,
    game_version: str | None,
    top_k: int = 8,
) -> list[dict]:
    """Retrieve items/mods/skills that provide the requested effects."""
    results: list[dict] = []
    seen_previews: set[str] = set()

    for concept_name, entry in concepts:
        search_terms: list[str] = list(entry.get("aliases", [])[:3])
        for pattern in entry.get("stat_patterns", []):
            kw = _pattern_to_keywords(pattern)
            if kw:
                search_terms.append(kw)

        if not search_terms:
            continue

        # Text search on chunk content (catches mods/items with effect text)
        for term in search_terms[:4]:
            ilike_filters = [
                KnowledgeChunk.stale == False,  # noqa: E712
                KnowledgeChunk.chunk_type.in_(["item", "mod", "gem", "skill"]),
                KnowledgeChunk.content.ilike(f"%{term}%"),
            ]
            apply_version_filters(ilike_filters, league, game_version)
            rows = db.query(KnowledgeChunk).filter(*ilike_filters).limit(3).all()
            for c in rows:
                preview = (c.content or "")[:100]
                if preview in seen_previews:
                    continue
                seen_previews.add(preview)
                results.append(_chunk_row_to_dict(
                    c, 0.95, via_concept=concept_name, match_type="text",
                ))

        # Vector search with effect-focused query
        effect_query = " ".join(search_terms[:5])
        emb = get_embedding(effect_query)
        if emb:
            vec_filters = list(_base_filters(league, game_version))
            vec_filters.append(KnowledgeChunk.chunk_type.in_(["item", "mod", "gem", "skill"]))
            for c in vector_search(db, emb, vec_filters, top_k=4, min_similarity=0.25):
                preview = c.get("content", "")[:100]
                if preview in seen_previews:
                    continue
                seen_previews.add(preview)
                c["via_concept"] = concept_name
                c["match_type"] = "vector"
                results.append(c)

    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return results[:top_k]


def structured_entity_lookup(
    db: Session,
    entities: list[tuple[str, str, str]],
    league: str | None = None,
    game_version: str | None = None,
) -> list[dict]:
    """Direct DB fetch for resolved entity names (ascendancy / item / skill)."""
    direct_chunks: list[dict] = []
    for etype, en_name, chunk_type_filter in entities:
        filters = [
            KnowledgeChunk.stale == False,  # noqa: E712
            KnowledgeChunk.content.ilike(f"%{en_name}%"),
        ]
        if chunk_type_filter == "asc_nodes":
            filters.append(KnowledgeChunk.chunk_type == "asc_nodes")
        apply_version_filters(filters, league, game_version)
        direct = db.query(KnowledgeChunk).filter(*filters).first()
        if direct:
            logger.info("structured_lookup: found %s for %s", etype, en_name)
            direct_chunks.append(chunk_to_dict(direct))
    return direct_chunks


def expand_concepts(
    chunks: list[dict],
    max_new: int = 6,
    league: str | None = None,
    game_version: str | None = None,
) -> list[dict]:
    """Follow concept links from retrieved chunks for multi-hop context."""
    from app.services.concept_links import parse_link, expand_query_for_link

    all_links: list[str] = []
    seen_links: set[str] = set()
    for c in chunks:
        raw = c.get("links", "")
        if not raw:
            continue
        try:
            link_list = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        for link in link_list:
            if link not in seen_links:
                seen_links.add(link)
                all_links.append(link)

    if not all_links:
        return []

    db = SessionLocal()
    try:
        all_new: list[dict] = []
        seen_contents = {c.get("content", "")[:100] for c in chunks}

        for link in all_links[:6]:
            if len(all_new) >= max_new:
                break
            ctype_filter, search_kw = expand_query_for_link(link)
            if not search_kw:
                continue

            filters = list(_base_filters(league, game_version))
            if ctype_filter:
                filters.append(KnowledgeChunk.chunk_type == ctype_filter)

            concept_emb = get_embedding(search_kw)
            if not concept_emb:
                continue

            for c in vector_search(db, concept_emb, filters, top_k=2, min_similarity=0.25):
                if len(all_new) >= max_new:
                    break
                content_preview = c.get("content", "")[:100]
                if content_preview in seen_contents:
                    continue
                seen_contents.add(content_preview)
                info = parse_link(link)
                c["via_link"] = info.get("key", link)
                all_new.append(c)

        return all_new[:max_new]
    finally:
        db.close()


def retrieve_multi_source(
    question: str,
    q_embedding: list[float] | None = None,
    per_source: int = 5,
    league: str | None = None,
    game_version: str | None = None,
) -> list[dict]:
    """Retrieve from each knowledge source separately (build design)."""
    db = SessionLocal()
    try:
        if q_embedding is None:
            q_embedding = get_embedding(question)
        if not q_embedding:
            return []

        sources = [
            row[0] for row in db.query(KnowledgeChunk.source)
            .filter(KnowledgeChunk.stale == False)  # noqa: E712
            .distinct().all() if row[0]
        ] or ["homework", "pob", "poe2db", "poe2wiki"]

        all_chunks: list[dict] = []
        for source in sources:
            filters = list(_base_filters(league, game_version))
            filters.append(KnowledgeChunk.source == source)
            all_chunks.extend(vector_search(db, q_embedding, filters, per_source))

        if not all_chunks:
            all_chunks = vector_search(db, q_embedding, _base_filters(league, game_version), 10)

        all_chunks.sort(key=lambda x: x["similarity"], reverse=True)
        return all_chunks[:20]
    finally:
        db.close()


def retrieve_knowledge(
    question: str,
    options: RetrievalOptions | None = None,
) -> RetrievalResult:
    """Main retrieval entry: vector search + optional reverse lookup + expansion."""
    opts = options or RetrievalOptions()
    cls_text = opts.classify_text if opts.classify_text is not None else question
    league = opts.league if opts.league is not None else default_league()
    game_version = opts.game_version if opts.game_version is not None else default_game_version()

    search_query = question
    if opts.alias_keywords:
        search_query = question + " " + " ".join(opts.alias_keywords)

    intent = classify_intent(cls_text)
    matched_concepts = find_concepts_in_query(cls_text)

    db = SessionLocal()
    try:
        q_embedding = opts.q_embedding or get_embedding(search_query)
        if not q_embedding:
            logger.error("Retrieval aborted: embedding unavailable")
            return RetrievalResult(chunks=[], intent=intent, search_query=search_query)

        # Reverse lookup path
        if intent == "reverse_lookup" and matched_concepts:
            chunks = reverse_lookup_chunks(
                db, cls_text, matched_concepts, league, game_version, top_k=opts.top_k,
            )
            concept_chunks: list[dict] = []
            if opts.expand_concepts and chunks:
                concept_chunks = expand_concepts(
                    chunks, max_new=opts.max_concept_chunks, league=league, game_version=game_version,
                )
                chunks = chunks + concept_chunks
            return RetrievalResult(
                chunks=chunks,
                intent=intent,
                search_query=search_query,
                matched_concepts=[n for n, _ in matched_concepts],
                concept_chunks=concept_chunks,
            )

        # Multi-source (build design)
        if opts.multi_source:
            chunks = retrieve_multi_source(
                search_query, q_embedding=q_embedding,
                per_source=opts.per_source, league=league, game_version=game_version,
            )
        else:
            base = _base_filters(league, game_version)
            filters = list(base)

            if intent == "recommend":
                filters.append(KnowledgeChunk.chunk_type.in_(["item", "skill", "gem", "mod"]))

            content_types = classify_question(cls_text)
            if content_types:
                filters.append(KnowledgeChunk.chunk_type.in_(content_types))

            chunks = vector_search(db, q_embedding, filters, opts.top_k)
            if not chunks and len(filters) > len(base):
                logger.info("Pre-filter empty, retrying without chunk_type filter")
                chunks = vector_search(db, q_embedding, base, opts.top_k)

        concept_chunks = []
        if opts.expand_concepts and chunks:
            concept_chunks = expand_concepts(
                chunks, max_new=opts.max_concept_chunks, league=league, game_version=game_version,
            )
            chunks = chunks + concept_chunks

        return RetrievalResult(
            chunks=chunks,
            intent=intent,
            search_query=search_query,
            matched_concepts=[n for n, _ in matched_concepts],
            concept_chunks=concept_chunks,
        )
    finally:
        db.close()


def build_search_query(
    user_msg: str,
    alias_keywords: list[str] | None = None,
    search_keywords: list[str] | None = None,
) -> str:
    """Combine user text with resolved aliases and LLM keywords."""
    parts = [user_msg]
    if alias_keywords:
        parts.extend(alias_keywords)
    if search_keywords:
        parts.extend(search_keywords)
    return " ".join(parts)


def extract_alias_keywords(user_msg: str) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Resolve class/ascendancy/item/skill entities from user message."""
    from app.services.entity_dict import normalize_class, normalize_ascendancy, resolve_ascendancy_en
    from app.services.entity_resolver import resolve_all_entities

    alias_keywords: list[str] = []
    resolved_entities: list[tuple[str, str, str]] = []

    class_en = normalize_class(user_msg)
    asc_cn = normalize_ascendancy(user_msg)
    asc_en = resolve_ascendancy_en(asc_cn) if asc_cn else None

    if class_en:
        alias_keywords.append(class_en)
    if asc_en:
        alias_keywords.append(asc_en)
    if asc_cn:
        alias_keywords.append(asc_cn)

    for en_name, cn_name, etype in resolve_all_entities(user_msg):
        alias_keywords.extend([en_name, cn_name])
        if etype in ("item", "skill", "ascendancy") and en_name != asc_en:
            chunk_filter = "asc_nodes" if etype == "ascendancy" else etype
            resolved_entities.append((etype, en_name, chunk_filter))

    if asc_en:
        resolved_entities.insert(0, ("ascendancy", asc_en, "asc_nodes"))

    return alias_keywords, resolved_entities


def chunk_text_for_context(c: dict, default_limit: int = 800) -> str:
    """Extract display text from a retrieved chunk."""
    try:
        data = json.loads(c["content"])
        text = data.get("search_text", c["content"])
    except Exception:
        text = c["content"]
    limit = 3000 if c.get("chunk_type") in ("asc_nodes", "build_summary", "minion") else default_limit
    prefix = f"[{c.get('source', '?')}/{c.get('chunk_type', '?')}]"
    if c.get("via_link"):
        prefix += f" (关联:{c['via_link']})"
    if c.get("via_concept"):
        prefix += f" (效果:{c['via_concept']})"
    return prefix + " " + text[:limit]


def build_context(chunks: list[dict]) -> str:
    """Build LLM context string from retrieved chunks."""
    return "\n\n".join(chunk_text_for_context(c) for c in chunks)
