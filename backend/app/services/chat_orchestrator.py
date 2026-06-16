"""Orchestrator chat runtime — plan → parallel sub-agents → synthesize."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from app.core.game_context import POE2_SITE_RULE
from app.orchestrator.dispatcher import dispatch_parallel
from app.orchestrator.planner import plan_dispatch
from app.orchestrator.schemas import SkillAgentResult
from app.orchestrator.session_context import build_session_context
from app.services.chat_agent import _emit_streamed_answer, _llm_client
from app.services.chat_multimodal import build_agent_messages, message_has_images, resolve_user_text
from app.services.chat_response_guard import strip_ungrounded_price_claims
from app.services.entity_validator import validate_answer
from app.services.follow_up_suggestions import generate_follow_up_questions
from app.services.observability import flush
from app.skills.router import get_skill

logger = logging.getLogger(__name__)

_AGENT_LABELS: dict[str, str] = {
    "trade_search": "交易搜索",
    "encyclopedia": "百科检索",
    "build_design": "BD 设计",
    "recommend": "对比推荐",
    "decode_pob": "PoB 解析",
}

SYNTHESIS_SYSTEM = (
    "你是「流放漓」Path of Exile 2 智能助手。"
    + POE2_SITE_RULE
    + """

## 编排模式（必须遵守）
1. 下方「子 Agent 结果」由专用子模块并行产出，是唯一事实来源。
2. 只综合这些结果回答，禁止编造子 Agent 未提供的物品、数值、价格或链接。
3. trade_search 的 match_quality=degraded 或 warnings 含「较宽」时，必须说明这是近似/宽泛匹配，勿称精确命中。
4. 无 listing_price 时禁止报具体金额；可说「暂无在售标价」并引导用户点市集链接。
5. decode_pob 的 summary 含 stats 行时原样引用抗性/DPS，闪电抗勿改称魔抗。
6. 多子 Agent 时按用户问题组织：先直接答核心，再分节补充交易/机制/BD 信息。
7. 使用清晰中文 markdown（### 小标题、列表、**关键数值**）。
"""
)


def _had_listing_price(results: list[SkillAgentResult]) -> bool:
    for r in results:
        if r.trade_data and r.trade_data.get("listing_price"):
            return True
    return False


def _build_synthesis_messages(
    user_msg: str,
    results: list[SkillAgentResult],
    *,
    has_images: bool,
    prior_snippet: str = "",
) -> list[dict[str, Any]]:
    blocks: list[str] = []
    for r in results:
        skill = get_skill(r.agent)
        if skill and r.ok:
            kwargs: dict[str, Any] = {"user_msg": user_msg}
            if r.agent == "trade_search" and r.trade_data:
                kwargs["trade_result"] = r.trade_data
            elif r.agent in ("encyclopedia", "build_design", "recommend"):
                kwargs["context"] = r.facts.get("context") or r.summary
            blocks.append(skill.system_prompt(**kwargs))
        blocks.append(r.to_synthesis_block())

    user_body = "用户问题:\n" + user_msg
    if prior_snippet.strip():
        user_body = (
            "对话上下文（供指代消解，勿重复无关历史）:\n"
            + prior_snippet.strip()
            + "\n\n"
            + user_body
        )
    if has_images:
        user_body += "\n\n(用户消息含游戏截图，请结合可见内容作答；看不清的如实说明)"
    user_body += "\n\n---\n子 Agent 结果:\n\n" + "\n\n---\n".join(blocks)

    return [
        {"role": "system", "content": SYNTHESIS_SYSTEM},
        {"role": "user", "content": user_body},
    ]


async def _follow_up_event(user_msg: str, answer: str) -> dict[str, Any] | None:
    questions = await generate_follow_up_questions(user_msg, answer)
    if questions:
        return {"type": "follow_ups", "content": questions}
    return None


async def stream_chat_orchestrator(messages: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """Plan tasks, dispatch sub-agents in parallel, synthesize SSE response."""
    user_msg = resolve_user_text(messages)
    last_msg = messages[-1] if messages else {}
    has_images = message_has_images(last_msg)

    if has_images:
        yield {"type": "thinking", "content": "已收到图片，正在分析…"}

    session = build_session_context(messages)
    plan = plan_dispatch(session=session)
    task_count = len(plan.tasks)
    agent_names = ", ".join(_AGENT_LABELS.get(t.agent, t.agent) for t in plan.tasks)
    yield {
        "type": "thinking",
        "content": f"AI 正在规划 {task_count} 个子任务: {agent_names}",
    }

    if plan.planning_note:
        logger.info("[ORCH] plan note=%s tasks=%s", plan.planning_note, [t.agent for t in plan.tasks])

    all_sources: list[dict] = []

    done_events: list[dict[str, Any]] = []

    async def _on_task_done(result: SkillAgentResult) -> None:
        label = _AGENT_LABELS.get(result.agent, result.agent)
        status = "完成" if result.ok else "失败"
        done_events.append(
            {
                "type": "sub_agent_done",
                "content": {
                    "agent": result.agent,
                    "task_id": result.task_id,
                    "ok": result.ok,
                    "match_quality": result.match_quality,
                    "latency_ms": result.latency_ms,
                    "label": f"{label}{status}",
                },
            },
        )

    results = await dispatch_parallel(
        plan.tasks,
        user_msg=user_msg,
        on_task_done=_on_task_done,
    )

    for ev in done_events:
        yield ev

    for r in results:
        if r.sources:
            all_sources.extend(r.sources)
        if r.trade_data:
            yield {"type": "trade_result", "content": r.trade_data}
        if r.recommend_data:
            yield {"type": "recommend_result", "content": r.recommend_data}

    failed = [r for r in results if not r.ok]
    if failed and all(not r.ok for r in results):
        err = "子任务均失败: " + "; ".join(f"{r.agent}: {r.error or 'unknown'}" for r in failed)
        yield {"type": "answer", "content": err}
        fu = await _follow_up_event(user_msg, err)
        if fu:
            yield fu
        flush()
        yield {"type": "done"}
        return

    yield {"type": "thinking", "content": "正在综合子 Agent 结果生成回答…"}

    synth_messages = _build_synthesis_messages(
        user_msg,
        results,
        has_images=has_images,
        prior_snippet=session.prior_snippet,
    )
    if has_images:
        synth_messages = build_agent_messages(messages, SYNTHESIS_SYSTEM)
        # Append sub-agent blocks as extra user context
        blocks = "\n\n".join(r.to_synthesis_block() for r in results)
        synth_messages.append(
            {
                "role": "user",
                "content": "子 Agent 结果:\n" + blocks,
            },
        )

    client = _llm_client()
    answer_acc = ""
    try:
        async for kind, text in _emit_streamed_answer(client, synth_messages):
            if kind == "reasoning":
                yield {"type": "reasoning", "content": text}
            else:
                answer_acc += text
                yield {"type": "answer", "content": text}
    except Exception as e:
        logger.error("[ORCH] synthesis failed: %s", e)
        err = f"生成失败: {e}"
        answer_acc += err
        yield {"type": "answer", "content": err}

    guarded = strip_ungrounded_price_claims(
        answer_acc,
        had_listing=_had_listing_price(results),
    )
    if guarded != answer_acc:
        extra = guarded[len(answer_acc) :]
        answer_acc = guarded
        yield {"type": "answer", "content": extra}

    if all_sources:
        seen: set[str] = set()
        unique_sources = []
        for s in all_sources:
            key = (s.get("source"), s.get("preview", "")[:50])
            if key not in seen:
                seen.add(key)
                unique_sources.append(s)
        yield {"type": "sources", "content": unique_sources[:8]}

    # Post-hoc entity validation
    if answer_acc:
        evidence = [r.summary for r in results if r.ok] if results else []
        suspicious = validate_answer(answer_acc, evidence_texts=evidence)
        if suspicious:
            yield {"type": "entity_warnings", "content": suspicious}

    fu = await _follow_up_event(user_msg, answer_acc)
    if fu:
        yield fu
    flush()
    yield {"type": "done"}


def chat_runtime_name() -> str:
    """Default: legacy ReAct agent (LLM chooses tools). Set CHAT_RUNTIME=orchestrator for parallel sub-agents."""
    return os.getenv("CHAT_RUNTIME", "legacy").strip().lower()


async def stream_chat(messages: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """Entry: orchestrator (default) or legacy ReAct agent."""
    runtime = chat_runtime_name()
    if runtime == "legacy":
        from app.services.chat_agent import stream_chat_agent

        async for event in stream_chat_agent(messages):
            yield event
        return

    async for event in stream_chat_orchestrator(messages):
        yield event
