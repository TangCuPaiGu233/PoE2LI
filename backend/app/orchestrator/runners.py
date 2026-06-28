"""Execute TaskSpec via existing chat_tools (stateless sub-agents)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.orchestrator.schemas import AgentName, SkillAgentResult, TaskSpec
from app.services.chat_tools import ChatToolContext, execute_tool

logger = logging.getLogger(__name__)


def _trade_match_quality(trade_data: dict[str, Any] | None) -> str:
    if not trade_data:
        return "failed"
    best = trade_data.get("best_match") or {}
    if best.get("empty"):
        return "failed"
    if best.get("degraded") or best.get("broad") or trade_data.get("degraded"):
        return "degraded"
    count = best.get("count", 0)
    if isinstance(count, int) and count > 5000:
        return "degraded"
    return "exact"


def _effective_user_msg(spec: TaskSpec, *, fallback: str) -> str:
    return str(spec.payload.get("effective_user_msg") or fallback or spec.user_phrase)


async def run_task(spec: TaskSpec, *, user_msg: str) -> SkillAgentResult:
    """Run a single sub-agent task."""
    started = time.perf_counter()
    effective = _effective_user_msg(spec, fallback=user_msg)
    ctx = ChatToolContext(user_msg=effective)
    agent = spec.agent

    try:
        if agent == "trade_search":
            return await _run_trade(spec, ctx, started)
        if agent == "encyclopedia":
            return await _run_encyclopedia(spec, ctx, started)
        if agent == "build_design":
            return await _run_build_design(spec, ctx, started)
        if agent == "recommend":
            return await _run_recommend(spec, ctx, started)
        if agent == "decode_pob":
            return await _run_decode_pob(spec, ctx, started)
        raise ValueError(f"unknown_agent:{agent}")
    except Exception as e:
        logger.exception("[ORCH] task %s agent=%s failed", spec.task_id, agent)
        return SkillAgentResult(
            task_id=spec.task_id,
            agent=agent,
            ok=False,
            match_quality="failed",
            error=str(e),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


async def _run_trade(
    spec: TaskSpec,
    ctx: ChatToolContext,
    started: float,
) -> SkillAgentResult:
    query = str(spec.payload.get("query") or spec.user_phrase)
    detail_count = int(spec.payload.get("detail_count") or 5)
    result = await execute_tool(
        "trade_search",
        {"query": query, "detail_count": detail_count},
        ctx,
    )
    trade_data = result.trade_result
    quality = _trade_match_quality(trade_data)
    warnings: list[str] = []
    if quality == "degraded":
        warnings.append("搜索结果较宽或降级，勿当作精确匹配")
    if trade_data and not trade_data.get("listing_price"):
        warnings.append("无在售标价样本，禁止编造具体价格")

    summary = ""
    if trade_data:
        exp = trade_data.get("explanation") or ""
        best = trade_data.get("best_match") or {}
        summary = f"trade: {best.get('label', '?')} count={best.get('count')} — {exp[:500]}"

    source_refs: list[dict[str, Any]] = []
    if trade_data:
        best = trade_data.get("best_match") or {}
        listing_price = trade_data.get("listing_price") or {}
        source_refs.append(
            {
                "type": "trade_listing",
                "url": listing_price.get("url"),
                "listing_price": listing_price.get("display"),
                "confidence": "high" if listing_price.get("url") else "low",
                "label": best.get("label"),
                "count": best.get("count"),
            }
        )

    return SkillAgentResult(
        task_id=spec.task_id,
        agent="trade_search",
        ok=trade_data is not None,
        match_quality=quality,  # type: ignore[arg-type]
        summary=summary,
        facts={"trade_payload": json.loads(result.content) if result.content else {}},
        warnings=warnings,
        sources=result.sources or [],
        source_refs=source_refs,
        trade_data=trade_data,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def _run_encyclopedia(
    spec: TaskSpec,
    ctx: ChatToolContext,
    started: float,
) -> SkillAgentResult:
    rag_query = str(spec.payload.get("query") or spec.user_phrase)
    result = await execute_tool(
        "rag_search",
        {"query": rag_query, "fast": True},
        ctx,
    )
    payload = json.loads(result.content) if result.content else {}
    rag_context = payload.get("context") or ""

    # Also query GameGraph for authoritative game data (Chinese names, relations)
    game_result = await execute_tool(
        "search_game",
        {"query": rag_query},
        ctx,
    )
    game_context = (game_result.content or "") if game_result else ""

    # Merge RAG + GameGraph contexts
    context = rag_context
    if game_context and not game_context.startswith("【游戏数据搜索结果】\n未找到"):
        context = f"{rag_context}\n\n{game_context}" if rag_context else game_context

    has_data = bool(context and context.strip())
    source_refs: list[dict[str, Any]] = []
    if result.sources:
        source_refs.extend(
            [
                {"type": s.get("source"), "preview": (s.get("preview") or "")[:120]}
                for s in result.sources[:5]
            ]
        )
    if game_result and game_result.content:
        source_refs.append(
            {
                "type": "game_graph",
                "preview": game_context[:120],
            }
        )

    return SkillAgentResult(
        task_id=spec.task_id,
        agent="encyclopedia",
        ok=has_data,
        match_quality="exact" if has_data else "failed",
        summary=context[:2000] if context else "未检索到相关资料",
        facts={
            "chunk_count": payload.get("chunk_count", 0),
            "context": context[:12000],
            "game_graph": game_context[:3000] if game_context else "",
        },
        sources=result.sources or [],
        source_refs=source_refs,
        warnings=[] if has_data else ["知识库与游戏数据均未命中"],
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def _run_build_design(
    spec: TaskSpec,
    ctx: ChatToolContext,
    started: float,
) -> SkillAgentResult:
    rag_query = str(spec.payload.get("query") or spec.user_phrase)
    result = await execute_tool(
        "rag_search",
        {"query": rag_query, "fast": True},
        ctx,
    )
    payload = json.loads(result.content) if result.content else {}
    rag_context = payload.get("context") or ""

    # Also query GameGraph for authoritative game data (classes, skills, passives)
    game_result = await execute_tool(
        "search_game",
        {"query": rag_query},
        ctx,
    )
    game_context = (game_result.content or "") if game_result else ""

    # Merge RAG + GameGraph contexts
    context = rag_context
    if game_context and not game_context.startswith("【游戏数据搜索结果】\n未找到"):
        context = f"{rag_context}\n\n{game_context}" if rag_context else game_context

    has_data = bool(context and context.strip())
    return SkillAgentResult(
        task_id=spec.task_id,
        agent="build_design",
        ok=has_data,
        match_quality="exact" if has_data else "failed",
        summary=context[:2000] if context else "未检索到 BD 相关资料",
        facts={
            "context": context[:12000],
            "game_graph": game_context[:3000] if game_context else "",
        },
        sources=result.sources or [],
        source_refs=[],
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def _run_recommend(
    spec: TaskSpec,
    ctx: ChatToolContext,
    started: float,
) -> SkillAgentResult:
    question = str(spec.payload.get("question") or spec.user_phrase)
    result = await execute_tool("recommend", {"question": question}, ctx)
    payload = json.loads(result.content) if result.content else {}
    structured = payload.get("structured") or {}
    return SkillAgentResult(
        task_id=spec.task_id,
        agent="recommend",
        ok=bool(structured),
        match_quality="exact" if structured else "failed",
        summary=payload.get("markdown") or structured.get("summary") or "",
        facts=structured,
        recommend_data=result.recommend_result,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def _run_decode_pob(
    spec: TaskSpec,
    ctx: ChatToolContext,
    started: float,
) -> SkillAgentResult:
    raw_input = str(spec.payload.get("input") or "")
    result = await execute_tool("decode_pob", {"input": raw_input}, ctx)
    payload = json.loads(result.content) if result.content else {}
    ok = bool(payload.get("ok"))
    summary = payload.get("summary") or ""
    return SkillAgentResult(
        task_id=spec.task_id,
        agent="decode_pob",
        ok=ok,
        match_quality="exact" if ok else "failed",
        summary=summary,
        facts=payload,
        error=None if ok else str(payload.get("error") or payload.get("reason")),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


RUNNERS: dict[AgentName, str] = {
    "trade_search": "trade_search",
    "encyclopedia": "encyclopedia",
    "build_design": "build_design",
    "recommend": "recommend",
    "decode_pob": "decode_pob",
}
