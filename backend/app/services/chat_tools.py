"""Chat tool registry — deterministic executors invoked by the AI agent (ClawCode-style)."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.chat_async_util import run_sync_with_timeout, TRADE_SEARCH_TIMEOUT_SEC

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.models.knowledge_graph import KbEntity
from app.models.schemas import DecodeResponse, ErrorResponse
from app.services.embedding_service import get_embedding
from app.services.pob_service import decode_pob
from app.services.rag_retrieval_policy import build_rag_options, classify_retrieval_intent
from app.services.retrieval_pipeline import (
    build_context,
    build_search_query,
    default_game_version,
    default_league,
    expand_concepts,
    extract_alias_keywords,
    retrieve_dual_path,
    structured_entity_lookup,
)

logger = logging.getLogger(__name__)

TRADE_SEARCH_MAX_PER_TURN = int(os.getenv("CHAT_TRADE_SEARCH_MAX", "8"))


POB_INPUT_RE = re.compile(
    r"(https?://(?:pobb\.in|poe\.ninja|(?:www\.)?wegame\.com\.cn/helper/poe2)[^\s]*|[A-Za-z0-9_-]{40,}|eN[a-zA-Z0-9+/_-]{20,})",
    re.IGNORECASE,
)


@dataclass
class ChatToolContext:
    league: str = field(default_factory=default_league)
    game_version: str = field(default_factory=default_game_version)
    user_msg: str = ""
    last_sources: list[dict] = field(default_factory=list)
    last_trade: dict | None = None
    last_recommend: dict | None = None
    rag_search_calls: int = 0
    trade_search_calls: int = 0
    search_game_calls: int = 0
    last_build_summary: str | None = None
    rag_queries: list[str] = field(default_factory=list)  # dedup: track all rag queries this turn
    last_chunks: list[str] = field(default_factory=list)  # evidence for entity validation
    last_game_searches: list[dict] = field(default_factory=list)  # game graph searches for validation
    consecutive_failures: int = 0
    tool_call_history: list[dict] = field(default_factory=list)


@dataclass
class ToolRunResult:
    """Result returned to the agent loop and optional SSE side-effects."""
    content: str
    trade_result: dict | None = None
    sources: list[dict] | None = None
    recommend_result: dict | None = None


# ── Dedup helpers ──────────────────────────────────────────────

def _query_jaccard(a: str, b: str) -> float:
    """Jaccard similarity on word sets — fast, no dependencies."""
    if not a or not b:
        return 0.0
    sa, sb = set(a.lower().split()), set(b.lower().split())
    union = len(sa | sb)
    return len(sa & sb) / union if union > 0 else 0.0


_RAG_DEDUP_THRESHOLD = 0.50
RAG_SOFT_LIMIT = 6  # total RAG search budget per turn
SEARCH_GAME_MAX_PER_TURN = 5  # max search_game calls per turn


def _check_rag_dedup(query: str, ctx: ChatToolContext) -> str | None:
    """Return a warning message if this query is too similar to a previous one, else None."""
    if not ctx.rag_queries:
        return None
    for prev in reversed(ctx.rag_queries[-5:]):  # only check last 5
        if _query_jaccard(query, prev) > _RAG_DEDUP_THRESHOLD:
            return (
                f"检索去重：当前 query 「{query}」与已搜过的 「{prev}」高度相似（Jaccard={_query_jaccard(query, prev):.2f}）。"
                "请基于已有检索结果回答，不要再搜相同内容。"
            )
    return None


# ── Tool definitions ───────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "entity_resolve",
            "description": (
                "Resolve Chinese PoE2 names (items, skills, ascendancies) to official EN names "
                "using alias tables. Call before rag_search when the query contains CN game terms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "User text or phrase containing entity names",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": (
                "Search the PoE2 knowledge base (poe2db, wiki, PoB data, homework). "
                "Call once per topic — the system will automatically expand into multi-angle "
                "parallel retrieval internally. Do not call multiple times for the same question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Self-contained search query (English preferred)",
                    },
                    "expand_concepts": {
                        "type": "boolean",
                        "description": "Follow concept links for broader context (default true)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decode_pob",
            "description": (
                "Fetch and parse a Path of Building share code, pobb.in URL, poe.ninja character URL, or WeGame PoE2 share link "
                "into structured build data (class, skills, items, stats). "
                "Required when user shares a build link or PoB code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "PoB code (eN...), pobb.in URL, poe.ninja build URL, or WeGame share URL/token",
                    },
                },
                "required": ["input"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_trade_stat",
            "description": (
                "Resolve a normalized Chinese affix label to official Trade API stat_id. "
                "You MUST interpret user intent and pass standard Chinese mod text as canonical_label "
                "(not raw slang). Call BEFORE trade_search when query mentions specific mods. "
                "Returns best (exact only), need_disambiguation, and suggestions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "canonical_label": {
                        "type": "string",
                        "description": "Standard Chinese mod label (normalized from user intent)",
                    },
                    "user_phrase": {
                        "type": "string",
                        "description": "Optional original user wording for context/suggestions",
                    },
                    "query": {
                        "type": "string",
                        "description": "Deprecated alias for canonical_label",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max suggestion rows (default 8)",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["canonical_label"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trade_search",
            "description": (
                "Search the official PoE2 trade market. Returns trade URLs, match counts, "
                "listings[] (full item+listing details for top N results), listing_price (cheapest sample), "
                "and price_note. Set detail_count to control how many top results to fetch (1-10). "
                "When describing items, quote fields from listings[] verbatim — do not guess stats/mods. "
                "Do NOT put item level (物等/ilvl) in query unless the user explicitly requires it. "
                "When comparing many affixes/variants, call once per affix with a single-mod query, then summarize."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Chinese trade search request",
                    },
                    "detail_count": {
                        "type": "integer",
                        "description": (
                            "How many top search hits to fetch with full item details (1-10). "
                            "Use 1 for quick price check; 3-5 to compare mods/stats on similar listings; "
                            "up to 10 for market overview."
                        ),
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend",
            "description": (
                "Compare multiple items/skills/options and rank them for the user's build context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Comparison / recommendation question",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_game",
            "description": (
                "Search PoE2 official game data (GGPK): classes, ascendancies, passive skills, "
                "items, mods, skills, gems, monsters, stats. Returns Chinese + English names and "
                "related entities from the authoritative game database. "
                "MUST be called for ANY question about game mechanics, entities, or data — "
                "your training data about PoE2 is unreliable (PoE1 vs PoE2 confusion). "
                "IMPORTANT: Use the SAME LANGUAGE as the user. Current user is on Chinese server — "
                "search with Chinese terms (e.g. '光环' not 'aura', '野兽' not 'beast')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Entity name to search. MUST match the user's language: "
                            "for Chinese users, use Chinese terms like '光环', '野兽光环', '扭曲项链'. "
                            "English fallback only when Chinese yields no results. "
                            "Examples: '灵魂行者', '光环', '扭曲项链', 'Spirit Walker', 'Distorted Amulet'"
                        ),
                    },
                    "table_filter": {
                        "type": "string",
                        "description": (
                            "Optional — OMIT unless user explicitly asks about a specific table. "
                            "Valid values: Ascendancy, PassiveSkills, ActiveSkills, BaseItemTypes, Mods, SkillGems, Stats, MonsterVarieties. "
                            "WARNING: filtering too narrowly may miss valid results spread across multiple tables."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_LABELS: dict[str, str] = {
    "entity_resolve": "解析游戏实体别名",
    "rag_search": "检索知识库",
    "decode_pob": "解析 PoB / 链接 BD",
    "resolve_trade_stat": "解析交易词条",
    "trade_search": "搜索交易市场",
    "recommend": "对比推荐分析",
    "search_game": "搜索游戏数据",
}


def find_build_input(text: str) -> str | None:
    """Extract PoB code or build share URL/token from a user message."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = POB_INPUT_RE.search(raw)
    if m:
        return m.group(1)
    from app.services.wegame_service import extract_wegame_share_id

    share_id = extract_wegame_share_id(raw)
    if share_id:
        return share_id
    return None


def detect_input_signals(text: str) -> list[str]:
    """Factual hints for the agent (not routing decisions)."""
    signals: list[str] = []
    if POB_INPUT_RE.search(text):
        signals.append("message_contains_pob_code_or_build_url")
    if "pobb.in" in text.lower():
        signals.append("pobb_in_url")
    if "poe.ninja" in text.lower():
        signals.append("poe_ninja_url")
    if "wegame.com.cn/helper/poe2" in text.lower():
        signals.append("wegame_url")
    if text.strip().startswith("eN"):
        signals.append("pob_share_code")
    if re.search(r"https?://", text):
        signals.append("contains_http_url")

    from app.services.trade_items_index import match_base_type_in_text

    base_hit = match_base_type_in_text(text)
    if base_hit:
        cn, en = base_hit
        signals.append(f"trade_base_type:{cn}={en}")

    affix_ask = re.search(
        r"(词条|词缀|能提供|出什么|什么属性|基底|介绍|是什么|有什么用|属性)",
        text,
    )
    trade_ask = re.search(
        r"(搜|找|买|卖|多少钱|市价|查价|价格|trade|集市|值多少)",
        text,
    )
    if base_hit and affix_ask:
        signals.append("item_knowledge_query:use_entity_resolve_and_rag_not_trade")
    elif base_hit and not trade_ask and len(text.strip()) <= 24:
        signals.append("bare_item_name:use_entity_resolve_and_rag_not_trade")

    return signals


def format_build_summary(data: DecodeResponse) -> str:
    """Compact build summary for LLM tool results."""
    b = data.build
    cfg = data.config or {}
    lines = [
        f"class: {b.className or '?'}",
        f"ascendancy: {b.ascendClassName or '?'}",
        f"level: {b.level or '?'}",
    ]
    if cfg.get("bd_title"):
        lines.append(f"bd_title: {cfg['bd_title']}")
    if cfg.get("role_name"):
        lines.append(f"character: {cfg['role_name']}")
    stats = data.playerStats or {}
    stat_bits = []
    for label, key in [
        ("Life", "Life"),
        ("Mana", "Mana"),
        ("ES", "EnergyShield"),
        ("FireRes", "FireResist"),
        ("ColdRes", "ColdResist"),
        ("LightningRes", "LightningResist"),
        ("ChaosRes", "ChaosResist"),
        ("DPS", "TotalDPS"),
        ("EHP", "TotalEHP"),
    ]:
        if stats.get(key):
            stat_bits.append(f"{label}={stats[key]}")
    if stat_bits:
        lines.append("stats: " + ", ".join(stat_bits))

    skills: list[str] = []
    for ss in data.skillSets or []:
        for g in ss.gems or []:
            if g.nameSpec and g.enabled:
                skills.append(g.nameSpec)
    if skills:
        lines.append("skills: " + ", ".join(list(dict.fromkeys(skills))[:12]))

    uniques = [
        f"{i.name}({i.baseName or ''})"
        for i in (data.items or [])
        if i.rarity == "UNIQUE" and i.name
    ]
    if uniques:
        lines.append("unique_items: " + ", ".join(uniques[:10]))

    return "\n".join(lines)


def _run_entity_resolve(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    text = (args.get("text") or ctx.user_msg or "").strip()
    aliases, entities = extract_alias_keywords(text)
    payload = {
        "aliases": aliases[:12],
        "entities": [
            {"type": et, "name_en": en, "chunk_filter": cf}
            for et, en, cf in (entities or [])[:8]
        ],
    }
    return ToolRunResult(content=json.dumps(payload, ensure_ascii=False))


def _run_search_game(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    """Execute search_game tool — queries GameGraph for authoritative game data."""
    from app.services.game_graph_service import search_game

    query = (args.get("query") or "").strip()
    table_filter = args.get("table_filter")
    result = search_game(query, table_filter=table_filter)

    # Track for post-validation
    ctx.last_game_searches.append({"query": query, "result": result[:500]})

    return ToolRunResult(content=result)


# ── Entity grounding ──────────────────────────────────────────

# Chunk types that contain definitive entity facts (not user-submitted builds)
_FACT_CHUNK_TYPES = {"item", "skill", "gem", "mod", "mechanic", "wiki", "ascendancy", "quest"}


def _collect_entity_facts(
    chunks: list[dict],
    league: str | None = None,
    game_version: str | None = None,
) -> str:
    """Extract entity names from chunk metadata and cross-reference kb_entities for authoritative facts.

    Returns a markdown block of verified entity info to inject before the RAG context,
    or an empty string if no entities found.
    """
    # Collect (entity_type, en_name) pairs from chunk metadata
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for c in chunks:
        ctype = (c.get("chunk_type") or "").strip()
        if ctype not in _FACT_CHUNK_TYPES:
            continue
        content = c.get("content") or ""
        try:
            data = json.loads(content) if isinstance(content, str) and content.startswith("{") else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        for field in ("name_en", "name", "title", "skill_name", "item_name"):
            val = (data.get(field) or "").strip()
            if val and val.lower() not in seen and len(val) > 2:
                seen.add(val.lower())
                candidates.append((ctype, val))

    if not candidates:
        return ""

    # Query kb_entities for matches
    db = SessionLocal()
    try:
        entity_map: dict[str, dict] = {}
        for ctype, en_name in candidates[:10]:  # cap at 10 to keep prompt lean
            row = (
                db.query(KbEntity)
                .filter(
                    KbEntity.name_en.ilike(en_name),
                    KbEntity.entity_type == ctype,
                )
                .first()
            )
            if row:
                key = f"{ctype}:{en_name}"
                entity_map[key] = {
                    "type": row.entity_type,
                    "name_en": row.name_en or en_name,
                    "name_cn": row.name_cn or "",
                    "aliases": json.loads(row.aliases) if row.aliases else [],
                    "chunk_id": row.chunk_id,
                }
                # Fetch linked detailed chunk for rich description
                if row.chunk_id:
                    chunk_row = db.query(KnowledgeChunk).filter(
                        KnowledgeChunk.id == row.chunk_id
                    ).first()
                    if chunk_row and chunk_row.content:
                        entity_map[key]["detail"] = (chunk_row.content or "")[:800]
    finally:
        db.close()

    if not entity_map:
        return ""

    lines = [
        "## 权威实体信息（回答时只能引用下方列出的实体属性，禁止推测未提供的技能效果或装备词缀）",
        "",
    ]
    for key, info in entity_map.items():
        cn = info["name_cn"]
        en = info["name_en"]
        et = info["type"]
        label = f"{cn}（{en}）" if cn else en
        lines.append(f"### [{et}] {label}")
        if info.get("detail"):
            detail = info["detail"]
            try:
                d = json.loads(detail) if isinstance(detail, str) else detail
                if isinstance(d, dict):
                    # poe2db data: extract key fields
                    desc = d.get("cn_description") or d.get("description") or ""
                    if desc:
                        lines.append(f"  - {desc[:300]}")
                    stats = d.get("stats") or d.get("cn_stats") or ""
                    if stats:
                        lines.append(f"  - 属性: {str(stats)[:200]}")
                    search = d.get("search_text") or ""
                    if search and search != en:
                        lines.append(f"  - {search[:200]}")
                elif isinstance(detail, str):
                    # wiki data: clean up and truncate
                    clean = detail[:400].replace("\n", " ")
                    lines.append(f"  - {clean}")
            except (json.JSONDecodeError, TypeError):
                lines.append(f"  - {detail[:300]}")
        lines.append("")

    return "\n".join(lines) if len(lines) > 2 else ""


def _run_plan_and_search(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    """One-shot multi-query retrieval: plan first, search all subqueries in parallel, merge."""
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    t0 = _time.perf_counter()
    subqueries: list[str] = args.get("subqueries") or []
    entities: list[str] = args.get("entities") or []
    intent_hint: str = args.get("intent_hint", "general")

    if not subqueries:
        subqueries = [ctx.user_msg[:200]]

    # Cap at 3
    subqueries = subqueries[:3]
    entities = entities[:5]

    # 1. Resolve entities
    entity_results: list[dict] = []
    if entities:
        resolved = _run_entity_resolve({"text": " ".join(entities)}, ctx)
        entity_results.append(resolved)
        aliases, resolved_entities = extract_alias_keywords(ctx.user_msg)
    else:
        aliases, resolved_entities = extract_alias_keywords(ctx.user_msg)

    # 2. Parallel subquery retrieval
    all_chunks: list[dict] = []
    seen_keys: set[str] = set()

    def _search_one(query: str) -> list[dict]:
        """Run one subquery retrieval, returning chunks."""
        search_aliases, search_entities = extract_alias_keywords(query)
        # Merge with top-level aliases/entities
        all_aliases = list(set(aliases + search_aliases))[:10]
        all_entities = list({(e[0], e[1], e[2]) for e in resolved_entities + search_entities})[:8]

        embedding = get_embedding(build_search_query(query, all_aliases, [query]))
        if not embedding:
            return []
        rag_opts, _ = build_rag_options(
            user_msg=query,
            query=query,
            entities=all_entities,
            fast=False,
            q_embedding=embedding,
            league=ctx.league,
            game_version=ctx.game_version,
            alias_keywords=all_aliases,
        )
        retrieval = retrieve_dual_path(query, query, rag_opts)
        return list(retrieval.chunks)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_search_one, q): q for q in subqueries}
        for future in as_completed(futures):
            try:
                chunks = future.result()
                for c in chunks:
                    key = c.get("content", "")[:120]
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_chunks.append(c)
            except Exception as e:
                logger.warning("[CHAT] plan_and_search subquery failed: %s", e)

    # 3. Structured entity lookup for resolved entities
    if resolved_entities:
        db = SessionLocal()
        try:
            direct = structured_entity_lookup(
                db, resolved_entities,
                league=ctx.league, game_version=ctx.game_version,
                intent=classify_retrieval_intent(ctx.user_msg),
            )
            for dc in direct:
                key = dc["content"][:120]
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_chunks.insert(0, dc)
        finally:
            db.close()

    # 4. Dedup & sort (prefer poe2db/wiki over pob)
    def _chunk_priority(c: dict) -> int:
        src = c.get("source", "")
        if src in ("poe2db", "poe2wiki"):
            return 0
        if src == "homework":
            return 1
        return 2  # pob

    all_chunks.sort(key=_chunk_priority)
    top_chunks = all_chunks[:12]

    # 5. Entity grounding
    entity_facts = _collect_entity_facts(top_chunks, ctx.league, ctx.game_version)

    # 6. Build context
    context = build_context(top_chunks[:10])
    if entity_facts:
        context = entity_facts + "\n\n" + context

    sources = [
        {"type": c.get("chunk_type", "?"), "source": c.get("source", "?"),
         "preview": (c.get("content") or "")[:100]}
        for c in top_chunks[:5]
    ]
    ctx.last_sources = sources
    ctx.last_chunks = [c.get("content") or "" for c in top_chunks]
    elapsed = (_time.perf_counter() - t0) * 1000
    logger.info(
        "[CHAT] tool plan_and_search subqueries=%d entities=%d chunks=%d %.0fms",
        len(subqueries), len(entities), len(top_chunks), elapsed,
    )
    return ToolRunResult(content=context, sources=sources)


def _run_rag_search(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    import time as _time

    t0 = _time.perf_counter()
    query = (args.get("query") or "").strip()
    if not query:
        query = (ctx.user_msg or "")[:200]
    fast = bool(args.get("fast"))
    expand = bool(args.get("expand_concepts", True)) and not fast
    aliases, entities = extract_alias_keywords(ctx.user_msg)
    search_query = build_search_query(ctx.user_msg, aliases, [query])
    rag_intent = classify_retrieval_intent(ctx.user_msg)

    embedding = get_embedding(search_query)
    if not embedding:
        return ToolRunResult(content=json.dumps({"error": "embedding_unavailable"}, ensure_ascii=False))

    rag_opts, _ = build_rag_options(
        user_msg=ctx.user_msg,
        query=query,
        entities=entities,
        fast=fast,
        q_embedding=embedding,
        league=ctx.league,
        game_version=ctx.game_version,
        alias_keywords=aliases,
    )
    retrieval = retrieve_dual_path(ctx.user_msg, query, rag_opts)
    chunks = list(retrieval.chunks)

    if entities:
        db = SessionLocal()
        try:
            direct = structured_entity_lookup(
                db,
                entities,
                league=ctx.league,
                game_version=ctx.game_version,
                intent=rag_intent,
            )
            seen = {c.get("content", "")[:100] for c in chunks}
            for dc in direct:
                key = dc["content"][:100]
                if key not in seen:
                    seen.add(key)
                    chunks.insert(0, dc)
        finally:
            db.close()

    if expand and chunks:
        extra = expand_concepts(chunks, max_new=4, league=ctx.league, game_version=ctx.game_version)
        chunks.extend(extra)

    context = build_context(chunks[:10])

    # ── Entity grounding: inject verified facts for entities found in chunks ──
    entity_facts = _collect_entity_facts(chunks, ctx.league, ctx.game_version)
    if entity_facts:
        context = entity_facts + "\n\n" + context

    sources = [
        {
            "type": c.get("chunk_type", "?"),
            "source": c.get("source", "?"),
            "preview": (c.get("content") or "")[:100],
        }
        for c in chunks[:5]
    ]
    ctx.last_sources = sources
    ctx.last_chunks = [c.get("content") or "" for c in chunks[:10]]
    elapsed = (_time.perf_counter() - t0) * 1000
    logger.info(
        "[CHAT] tool rag_search chunks=%d fast=%s %.0fms",
        len(chunks),
        fast,
        elapsed,
    )
    payload = {
        "chunk_count": len(chunks),
        "context": context[:12000],
        "fast": fast,
    }
    return ToolRunResult(content=json.dumps(payload, ensure_ascii=False), sources=sources)


def _run_decode_pob(args: dict[str, Any], _ctx: ChatToolContext) -> ToolRunResult:
    raw_input = (args.get("input") or "").strip()
    if not raw_input:
        return ToolRunResult(content=json.dumps({"error": "empty_input"}, ensure_ascii=False))

    result = decode_pob(raw_input)
    if isinstance(result, ErrorResponse):
        return ToolRunResult(
            content=json.dumps(
                {"ok": False, "error": result.error, "reason": result.reason},
                ensure_ascii=False,
            ),
        )

    summary = format_build_summary(result)
    _ctx.last_build_summary = summary
    payload = {
        "ok": True,
        "summary": summary,
        "build": result.model_dump(),
    }
    # Keep tool payload bounded — full build JSON can be huge
    content = json.dumps(
        {"ok": True, "summary": summary, "build_meta": result.build.model_dump()},
        ensure_ascii=False,
    )
    if len(content) > 14000:
        content = json.dumps({"ok": True, "summary": summary}, ensure_ascii=False)
    if (result.config or {}).get("source") == "wegame":
        logger.info(
            "[CHAT] tool decode_pob ok wegame share=%s class=%s",
            (result.config or {}).get("share_id", "")[:16],
            result.build.className,
        )
    else:
        logger.info("[CHAT] tool decode_pob ok class=%s", result.build.className)
    return ToolRunResult(content=content)


def _run_trade_search(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    from app.services.trade_agent import run_agent as trade_run_agent, sanitize_trade_query

    if ctx.trade_search_calls >= TRADE_SEARCH_MAX_PER_TURN:
        prev = ctx.last_trade or {}
        return ToolRunResult(
            content=json.dumps(
                {
                    "error": "trade_search_limit",
                    "message": "本轮trade_search 已达上限，请基于已有结果汇总作答",
                    "previous": prev,
                },
                ensure_ascii=False,
            ),
            trade_result=prev or None,
        )
    ctx.trade_search_calls += 1
    query = (args.get("query") or "").strip()
    if not query:
        query = (ctx.user_msg or "")[:200]
    query = sanitize_trade_query(query, ctx.user_msg or "")
    raw_detail = args.get("detail_count")
    try:
        detail_count = max(1, min(int(raw_detail if raw_detail is not None else 3), 10))
    except (TypeError, ValueError):
        detail_count = 3
    trade_result = trade_run_agent(
        query,
        market="cn",
        user_msg=ctx.user_msg or "",
        detail_count=detail_count,
    )
    best = trade_result.get("best_match")
    alts = trade_result.get("alternatives", [])
    trade_data = {
        "best_match": (
            {
                "label": best["label"],
                "url": best["url"],
                "count": best.get("count", 0),
                "degraded": best.get("degraded", False),
                "empty": best.get("empty", best.get("count", 0) == 0),
                "broad": best.get("broad", False),
            }
            if best
            else None
        ),
        "alternatives": [
            {
                "label": a["label"],
                "url": a["url"],
                "count": a.get("count", 0),
                "empty": a.get("empty", False),
                "broad": a.get("broad", False),
                "degraded": a.get("degraded", False),
            }
            for a in alts[:3]
        ],
        "explanation": trade_result.get("explanation", ""),
        "degraded": bool(best and best.get("degraded")),
        "listing_price": trade_result.get("listing_price"),
        "listings": trade_result.get("listings") or [],
        "listings_fetched": trade_result.get("listings_fetched", 0),
        "detail_count": detail_count,
        "price_note": trade_result.get("price_note"),
        "user_variant_hint": trade_result.get("user_variant_hint"),
    }
    ctx.last_trade = trade_data
    payload = json.dumps(trade_data, ensure_ascii=False)
    if len(payload) > 28000:
        trade_data["listings"] = (trade_data.get("listings") or [])[: max(1, detail_count // 2)]
        trade_data["truncated"] = True
        payload = json.dumps(trade_data, ensure_ascii=False)
    return ToolRunResult(
        content=payload[:28000],
        trade_result=trade_data,
    )


async def _run_recommend(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    from app.services.recommend_runtime import format_recommend_markdown, get_recommend_agent

    question = (args.get("question") or ctx.user_msg or "").strip()
    agent = get_recommend_agent()
    result = await agent.run(
        question=question,
        league=ctx.league,
        game_version=ctx.game_version,
    )
    recommend_data = {
        "best_pick": result.best_pick,
        "ranking": result.ranking[:5],
        "summary": result.summary,
        "resolved": result.resolved,
    }
    ctx.last_recommend = recommend_data
    markdown = format_recommend_markdown(result)
    payload = {"structured": recommend_data, "markdown": markdown}
    return ToolRunResult(
        content=json.dumps(payload, ensure_ascii=False)[:12000],
        recommend_result=recommend_data,
    )




def _run_resolve_trade_stat(args: dict[str, Any], ctx: ChatToolContext) -> ToolRunResult:
    from app.services.trade_service import resolve_trade_stat

    canonical = str(args.get("canonical_label") or args.get("query") or "").strip()
    user_phrase = str(args.get("user_phrase") or "").strip()
    limit = int(args.get("limit") or 8)
    if not canonical:
        return ToolRunResult(content=json.dumps({"error": "empty_canonical_label"}, ensure_ascii=False))
    payload = resolve_trade_stat(
        canonical,
        user_phrase=user_phrase,
        suggest_limit=limit,
    )
    return ToolRunResult(content=json.dumps(payload, ensure_ascii=False)[:12000])


async def execute_tool(
    name: str,
    args: dict[str, Any],
    ctx: ChatToolContext,
) -> ToolRunResult:
    """Dispatch a tool call from the agent loop."""
    logger.info("[CHAT] tool_call name=%s args=%s", name, str(args)[:200])
    ctx.tool_call_history.append({"name": name, "args": args})
    timeout = float(os.getenv("CHAT_TOOL_TIMEOUT_SEC", "45"))
    recent = [entry for entry in ctx.tool_call_history[-6:] if entry.get("name") == name]
    if len(recent) >= 3:
        seen = [tuple(sorted((entry.get("args") or {}).items())) for entry in recent]
        if seen[0] and all(s == seen[0] for s in seen):
            return ToolRunResult(
                content=json.dumps(
                    {
                        "status": "blocked",
                        "reason": "repeated_tool_loop",
                        "hint": f"{name} 已在近期重复调用且参数完全相同，已跳过。请基于已有结果综合回答。",
                    },
                    ensure_ascii=False,
                ),
            )
    if name == "trade_search":
        query = str(args.get("query") or "").strip()
        prev_queries = [str(entry.get("args", {}).get("query") or "") for entry in ctx.tool_call_history[-6:] if entry.get("name") == "trade_search"]
        prev_queries = [q for q in prev_queries if q]
        if prev_queries:
            def _jw(a: str, b: str) -> float:
                sa, sb = set(a.lower().split()), set(b.lower().split())
                u = len(sa | sb)
                return len(sa & sb) / u if u else 0.0
            if any(_jw(query, q) > 0.72 for q in prev_queries[:-1]):
                return ToolRunResult(
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "reason": "similar_trade_query",
                            "hint": "当前 trade_search query 与近期搜索过于相似，已跳过。请尝试不同角度或词缀。",
                        },
                        ensure_ascii=False,
                    ),
                )
    if name == "entity_resolve":
        return _run_entity_resolve(args, ctx)
    if name == "rag_search":
        query = (args.get("query") or "").strip()

        # Dedup: block near-duplicate queries
        dup_msg = _check_rag_dedup(query, ctx)
        if dup_msg:
            logger.info("[CHAT] tool rag_search DUPLICATE query=%s", query[:100])
            return ToolRunResult(
                content=json.dumps(
                    {"status": "blocked", "reason": "duplicate", "hint": dup_msg},
                    ensure_ascii=False,
                ),
            )

        # Rich single-call batch: on first call, internally run batch retrieval for broader coverage.
        # Subsequent calls fall through to normal single-query path.
        if ctx.rag_search_calls == 0:
            ctx.rag_search_calls = 2  # batch consumes 2 slots
            ctx.rag_queries.append(query)
            # Convert to batch: use the LLM's query as primary, add auto expansions
            batch_args = {
                "subqueries": [query],
                "intent_hint": classify_retrieval_intent(ctx.user_msg),
            }
            if args.get("expand_concepts", True):
                # Generate a couple of variant queries from aliases
                aliases, _ = extract_alias_keywords(ctx.user_msg)
                if aliases:
                    batch_args["subqueries"].append(" ".join(aliases[:4]))
            batch_args["subqueries"] = batch_args["subqueries"][:3]
            return await run_sync_with_timeout(_run_plan_and_search, batch_args, ctx, timeout=timeout)

        # Soft limit: block when budget exhausted
        if ctx.rag_search_calls >= RAG_SOFT_LIMIT:
            logger.info("[CHAT] tool rag_search LIMIT reached (%d)", ctx.rag_search_calls)
            return ToolRunResult(
                content=json.dumps(
                    {
                        "status": "budget_exhausted",
                        "reason": f"本轮已检索 {RAG_SOFT_LIMIT} 次，预算耗尽。",
                        "hint": "请基于已有的检索结果综合回答，不要再次检索。",
                    },
                    ensure_ascii=False,
                ),
            )

        ctx.rag_search_calls += 1
        ctx.rag_queries.append(query)
        result = await run_sync_with_timeout(_run_rag_search, args, ctx, timeout=timeout)

        # Countdown hint from 3rd search onward
        remaining = RAG_SOFT_LIMIT - ctx.rag_search_calls
        if ctx.rag_search_calls >= 3 and remaining > 0:
            result.content += f"\n\n[检索预算还剩 {remaining}/{RAG_SOFT_LIMIT} 次]"

        return result
    if name == "decode_pob":
        return await run_sync_with_timeout(_run_decode_pob, args, ctx, timeout=timeout)
    if name == "resolve_trade_stat":
        return await run_sync_with_timeout(_run_resolve_trade_stat, args, ctx, timeout=timeout)
    if name == "trade_search":
        return await run_sync_with_timeout(_run_trade_search, args, ctx, timeout=TRADE_SEARCH_TIMEOUT_SEC)
    if name == "recommend":
        return await _run_recommend(args, ctx)
    if name == "search_game":
        ctx.search_game_calls += 1
        if ctx.search_game_calls > SEARCH_GAME_MAX_PER_TURN:
            return ToolRunResult(content=json.dumps({
                "status": "blocked",
                "reason": f"本轮已调用 {SEARCH_GAME_MAX_PER_TURN} 次 search_game，预算耗尽。请基于已有搜索结果组织回答，不要再搜索。",
            }, ensure_ascii=False))
        result = _run_search_game(args, ctx)
        if ctx.search_game_calls >= 3:
            # Append plain-text warning (search_game returns text, not JSON)
            hint = (
                f"\n\n⚠️ 这是本轮第 {ctx.search_game_calls} 次 search_game 调用。"
                f"请优先基于已有搜索结果组织回答，避免继续搜索。"
            )
            result.content = (result.content + hint)[:12000]
        return result
    return ToolRunResult(content=json.dumps({"error": f"unknown_tool:{name}"}))
