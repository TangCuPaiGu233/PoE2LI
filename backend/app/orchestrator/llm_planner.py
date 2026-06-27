"""LLM orchestrator planner — AI reads full conversation and decides sub-agents."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from app.core.llm_config import LLM_MODEL, llm_message_text
from app.core.llm_client import get_llm_client
from app.orchestrator.schemas import AgentName, DispatchPlan, SkillAgentResult, TaskSpec
from app.services.session_context import SessionContext, build_session_context
from app.services.chat_multimodal import extract_text, message_has_images
from app.services.chat_tools import find_build_input

logger = logging.getLogger(__name__)

# ── R-01：三级截断策略 ──────────────────────────────────────────

# Token budget thresholds
_PLANNER_INPUT_BUDGET = 6000          # Planner 输入 token 预算
_SYNTHESIS_TOKEN_BUDGET = 80000       # Synthesis token 预算
_SUB_AGENT_RESULT_BUDGET = 4000       # 单个子 Agent 结果 token 预算
_PLANNER_SNIPPET_CHARS = 1200         # 上下文摘要最大字符数


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 1.5 UTF-8 chars for CJK/EN mix."""
    if not text:
        return 0
    return max(1, int(len(text) / 1.5))


def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
    """Truncate text to fit within token budget, preserving complete lines."""
    if not text or max_tokens <= 0:
        return text or ""
    tokens = _estimate_tokens(text)
    if tokens <= max_tokens:
        return text
    # Binary search for optimal truncation point
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _estimate_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    truncated = text[:lo]
    # Cut at last newline to avoid mid-line truncation
    last_nl = truncated.rfind('\n')
    if last_nl > 0:
        truncated = truncated[:last_nl]
    return truncated + "\n...[truncated]"


def _truncate_sub_agent_results(results: list[SkillAgentResult]) -> list[SkillAgentResult]:
    """R-01 Level 2: Truncate sub-agent result summaries to fit budget."""
    truncated = []
    for r in results:
        if r.summary and _estimate_tokens(r.summary) > _SUB_AGENT_RESULT_BUDGET:
            r.summary = _truncate_to_token_budget(r.summary, _SUB_AGENT_RESULT_BUDGET)
        if r.facts:
            facts_str = json.dumps(r.facts, ensure_ascii=False)
            if _estimate_tokens(facts_str) > _SUB_AGENT_RESULT_BUDGET:
                r.facts = {}  # Drop oversized facts to prevent context bloat
        truncated.append(r)
    return truncated


def _prior_snippet_for_synthesis(messages: list[dict[str, Any]]) -> str:
    """R-01 Level 1: Build compact prior snippet for synthesis context."""
    if not messages:
        return ""
    # Take last 6 turns, heavily compressed
    tail = messages[-6:]
    parts: list[str] = []
    for msg in tail:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = extract_text(msg).strip()
        if not text:
            continue
        label = "用户" if role == "user" else "助手"
        parts.append(f"{label}: {text[:200]}")
    snippet = "\n".join(parts)
    return _truncate_to_token_budget(snippet, _PLANNER_SNIPPET_CHARS)


_VALID_AGENTS: set[str] = {
    "trade_search",
    "encyclopedia",
    "build_design",
    "recommend",
    "decode_pob",
}

PLANNER_SYSTEM = """你是「流放漓」聊天编排器的规划模块。根据**完整对话**决定本轮要并行调用哪些子 Agent。

## 子 Agent（你只做选择 + 写 query，不回答问题）

|| agent | 何时用 | payload 字段 |
|-------|--------|--------------|
| decode_pob | 本轮有可解析的 PoB 码/链接 | input |
| trade_search | 查价、搜装备、市集 | query, detail_count(1-5) |
| encyclopedia | 机制、技能、词缀、有哪些、百科（子 Agent 自动搜索游戏数据图谱）| query |
| build_design | BD、配装、**如何搭配**、装备选择思路 | query |
| recommend | **仅**用户明确对比 2+ 个具名装备「哪个更好」 | question |

## 规划原则（模糊判断由你完成，不要用死板关键词）

1. **读全对话**：当前句可能是追问（「这个值多少钱」「不是珠宝」「搜差不多强度的」）→ query 必须来自**历史里描述的那件装备**，不要把抱怨/纠正句当 trade query。
2. **trade_search 的 query**：只写装备类型、词缀、暗金名；追问价格时从上一轮用户描述或截图语境还原物品。
3. **搭配/配装/怎么配** → build_design 或 encyclopedia，**不是** recommend（recommend 只用于多物品二选一/对比）。
4. 机制 + 搜装备可**同时**派 trade_search + encyclopedia。
5. 有 PoB 码时加 decode_pob；若还有文字问题，可同时派 encyclopedia/build_design。
6. query/question 用自洽中文或英文检索词，可引用对话中的升华/技能/词缀名。

## 输出格式（仅 JSON，无 markdown）

{
  "tasks": [
    {"agent": "trade_search", "query": "稀有项链 +2召唤技能等级", "detail_count": 3},
    {"agent": "encyclopedia", "query": "Spirit Walker ascendancy skills"}
  ],
  "reasoning": "一句话说明规划理由"
}
"""


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _conversation_for_planner_original(messages: list[dict[str, Any]], *, max_turns: int = 8) -> str:
    """Original planner input formatter (kept for reference/tests)."""
    tail = messages[-max_turns:] if messages else []
    lines: list[str] = []
    for msg in tail:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = extract_text(msg).strip()
        if not text and role == "user" and message_has_images(msg):
            text = "(用户发送了游戏截图)"
        if not text:
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {text[:600]}")
    return "\n".join(lines)


# Backward compatibility: tests import this name from llm_planner
_conversation_for_planner = _conversation_for_planner_original


def _task_from_entry(entry: dict[str, Any], ctx: SessionContext) -> TaskSpec | None:
    agent = str(entry.get("agent") or "").strip()
    if agent not in _VALID_AGENTS:
        return None

    effective = ctx.effective_user_msg()
    payload: dict[str, Any] = {"effective_user_msg": effective}

    if agent == "decode_pob":
        inp = str(entry.get("input") or ctx.pob_input or "").strip()
        if not inp:
            return None
        payload["input"] = inp
    elif agent == "trade_search":
        query = str(entry.get("query") or "").strip()
        if not query:
            query = ctx.trade_search_query()
        payload["query"] = query[:500]
        try:
            payload["detail_count"] = max(1, min(int(entry.get("detail_count") or 3), 10))
        except (TypeError, ValueError):
            payload["detail_count"] = 3
    elif agent == "recommend":
        payload["question"] = str(entry.get("question") or effective)[:2000]
    else:
        query = str(entry.get("query") or ctx.rag_query_text()).strip()
        if not query:
            return None
        payload["query"] = query[:500]

    return TaskSpec(
        task_id=_new_task_id(),
        agent=agent,  # type: ignore[arg-type]
        user_phrase=ctx.current_user_text,
        payload=payload,
        priority=10 if agent == "decode_pob" else 0,
    )


def _merge_pob_task(tasks: list[TaskSpec], ctx: SessionContext) -> list[TaskSpec]:
    """Deterministic: PoB code detection is code's job, not LLM's."""
    if not ctx.pob_input:
        return tasks
    if any(t.agent == "decode_pob" for t in tasks):
        return tasks
    pob_task = TaskSpec(
        task_id=_new_task_id(),
        agent="decode_pob",
        user_phrase=ctx.current_user_text,
        payload={"input": ctx.pob_input, "effective_user_msg": ctx.effective_user_msg()},
        priority=10,
    )
    return [pob_task, *tasks]


def _fallback_plan(ctx: SessionContext) -> DispatchPlan:
    """Minimal fallback when LLM planner fails — encyclopedia with full context."""
    return DispatchPlan(
        tasks=[
            TaskSpec(
                task_id=_new_task_id(),
                agent="encyclopedia",
                user_phrase=ctx.current_user_text,
                payload={
                    "query": ctx.rag_query_text(),
                    "effective_user_msg": ctx.effective_user_msg(),
                },
            ),
        ],
        planning_note="llm_planner_fallback",
    )


def llm_plan_dispatch(messages: list[dict[str, Any]]) -> DispatchPlan:
    """AI planner: read conversation → parallel sub-agent tasks."""
    ctx = build_session_context(messages)
    text = (ctx.current_user_text or "").strip()
    if not text and not ctx.has_images_current:
        return _merge_pob_task(_fallback_plan(SessionContext(current_user_text="你好")).tasks, ctx)

    # R-01: use budget-controlled conversation for planner input
    convo = _conversation_for_planner(messages)
    user_block = f"## 对话记录\n{convo}\n\n## 当前轮\n用户: {text or '(截图)'}"
    if ctx.has_images_current:
        user_block += "\n(本轮含截图，若需查价/识装请派 trade_search，query 写从对话推断的装备描述)"

    try:
        client = get_llm_client()
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": user_block},
            ],
            temperature=0.1,
            max_tokens=800,
        )
        msg = resp.choices[0].message if resp.choices else None
        parsed = _extract_json(llm_message_text(msg) if msg else "")
    except Exception as e:
        logger.warning("[ORCH] LLM planner failed: %s", e)
        return DispatchPlan(
            tasks=_merge_pob_task(_fallback_plan(ctx).tasks, ctx),
            planning_note="llm_planner_error",
        )

    if not parsed or not isinstance(parsed.get("tasks"), list):
        logger.warning("[ORCH] LLM planner invalid JSON")
        return DispatchPlan(
            tasks=_merge_pob_task(_fallback_plan(ctx).tasks, ctx),
            planning_note="llm_planner_invalid_json",
        )

    tasks: list[TaskSpec] = []
    for entry in parsed["tasks"]:
        if not isinstance(entry, dict):
            continue
        spec = _task_from_entry(entry, ctx)
        if spec:
            tasks.append(spec)

    if not tasks:
        tasks = _fallback_plan(ctx).tasks

    tasks = _merge_pob_task(tasks, ctx)
    note = str(parsed.get("reasoning") or "llm_plan")[:200]
    tasks.sort(key=lambda t: -t.priority)
    return DispatchPlan(tasks=tasks, planning_note=f"llm:{note}")
