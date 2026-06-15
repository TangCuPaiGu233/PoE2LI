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
    last_build_summary: str | None = None


@dataclass
class ToolRunResult:
    """Result returned to the agent loop and optional SSE side-effects."""
    content: str
    trade_result: dict | None = None
    sources: list[dict] | None = None
    recommend_result: dict | None = None


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
                "Use for mechanics, skills, items, mods, ascendancy questions."
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
]

TOOL_LABELS: dict[str, str] = {
    "entity_resolve": "解析游戏实体别名",
    "rag_search": "检索知识库",
    "decode_pob": "解析 PoB / 链接 BD",
    "resolve_trade_stat": "解析交易词条",
    "trade_search": "搜索交易市场",
    "recommend": "对比推荐分析",
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
    sources = [
        {
            "type": c.get("chunk_type", "?"),
            "source": c.get("source", "?"),
            "preview": (c.get("content") or "")[:100],
        }
        for c in chunks[:5]
    ]
    ctx.last_sources = sources
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
    timeout = float(os.getenv("CHAT_TOOL_TIMEOUT_SEC", "45"))
    if name == "entity_resolve":
        return _run_entity_resolve(args, ctx)
    if name == "rag_search":
        if ctx.rag_search_calls >= 3:
            return ToolRunResult(
                content=json.dumps(
                    {"error": "rag_search_limit", "message": "max 3 rag_search per turn"},
                    ensure_ascii=False,
                ),
            )
        ctx.rag_search_calls += 1
        return await run_sync_with_timeout(_run_rag_search, args, ctx, timeout=timeout)
    if name == "decode_pob":
        return await run_sync_with_timeout(_run_decode_pob, args, ctx, timeout=timeout)
    if name == "resolve_trade_stat":
        return await run_sync_with_timeout(_run_resolve_trade_stat, args, ctx, timeout=timeout)
    if name == "trade_search":
        return await run_sync_with_timeout(_run_trade_search, args, ctx, timeout=TRADE_SEARCH_TIMEOUT_SEC)
    if name == "recommend":
        return await _run_recommend(args, ctx)
    return ToolRunResult(content=json.dumps({"error": f"unknown_tool:{name}"}))
