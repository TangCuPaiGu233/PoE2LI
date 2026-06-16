"""Chat agent runtime — ClawCode-style ReAct loop: AI chooses tools, scripts execute."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import asyncio

from app.core.llm_config import LLM_MODEL, llm_thinking_extra_body
from app.core.llm_client import get_async_llm_client
from app.core.game_context import POE2_SITE_RULE
from app.orchestrator.session_context import build_session_context
from app.services.chat_multimodal import build_agent_messages, message_has_images, resolve_user_text
from app.services.follow_up_suggestions import generate_follow_up_questions

from app.services.chat_tools import (
    RAG_SOFT_LIMIT,
    TOOL_DEFINITIONS,
    TOOL_LABELS,
    ChatToolContext,
    detect_input_signals,
    execute_tool,
)
from app.services.observability import flush, trace_chat_turn

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
TRADE_SEARCH_MAX_PER_TURN = int(os.getenv("CHAT_TRADE_SEARCH_MAX", "8"))

AGENT_SYSTEM = """你是「流放漓」Path of Exile 2 智能助手。""" + POE2_SITE_RULE + """

## 工作方式（必须遵守）
0. 没有服务端强制路由或专用流水线；所有查价/搜索/检索都由你自主调用工具完成。
1. 你是编排者：先判断用户意图，再调用工具获取事实，最后基于工具结果用中文回答。
2. 不要在没有调用工具的情况下编造物品、技能数值、BD 数据或交易链接。
3. 用户消息若含 PoB 分享码(eN开头)、pobb.in 或 poe.ninja 或 wegame.com.cn/helper/poe2 分享链接 → 必须先调用 decode_pob。
4. 百科/机制/技能/物品问题 → 先 entity_resolve（如有中文专名），再 rag_search。rag_search 传入英文检索词，服务端会自动进行多角度并行检索，一次调用即可，不要重复调用。
5. 找装备/市价/交易 → trade_search（detail_count 1-10 控制返回前 N 条完整 listing；问价通常 1-3，对比可 2-5）。
6. 「哪个更好/推荐/对比」→ recommend。
7. **多物品市价列表**（用户一次问多个装备/暗金分别多少钱）：逐个调用 trade_search，每查完一个物品先输出该物品报价，全部完成后再给汇总；不要在一次 trade_search 里混查多个物品。
8. 可连续调用多个工具；当前问题与历史无关时（例如仅贴链接），不要沿用上一轮话题。
9. 工具失败时如实告知用户（例如 poe.ninja 角色不存在、链接失效）。
10. plan_and_search 的 subqueries 最多 3 个英文短语，从不同角度覆盖用户问题。如需先解析中文实体名，写入 entities 字段。大多数问题调用一次 plan_and_search 即可，不要重复调用。
11. **poe.ninja BD 造价（无链接）**：用户提到忍者网/poe.ninja 并询问 BD 造价，但消息里没有 poe.ninja 角色链接、PoB 码等可解析构建输入时，直接说明如何复制并粘贴链接，不要调用 decode_pob 或 BD 造价流水线。
12. **WeGame 分享链接**：`stats:` 行含 Life/FireRes/LightningRes 等时，即 WeGame 面板数据，**必须原样引用**（火/冰/闪抗即元素抗性，闪电抗勿改称「魔抗」）。仅当含 `data_limitation` 时才禁止编造面板数值。WeGame 无升华字段。
14. **用户附图**：消息可能含 PoE2 游戏截图（装备、天赋、技能、市集等）。先描述图中可见内容，再结合工具/知识库回答；看不清的数值如实说明，不要编造。
15. **估价/值多少钱**：只能引用 trade_search 返回的 `listing_price.display`；若无 listing_price 或 price_note 说无在售，必须明确「无法从市集估价」，**禁止**编造具体金额区间（如 3-8 崇高、建议挂 5E 等）。
16. **trade_search 的 query**：只写词缀/装备类型/暗金名；**不要**把截图里的物品等级(物等/ilvl)写进 query，除非用户原话明确要求物等条件。
17. **trade_search 次数**：多物品/多变体比价时逐项调用；同一件装备避免无意义重复搜索。
18. **暗金查价**（人格分裂、猎首等）：trade_search 的 query **只写暗金名**，不要加红玉/蓝玉基底或无关词缀描述。
19. **追问价格/其他变体词缀**：仍须 trade_search；结合对话里的物品名构造 query，禁止不查市集就报具体价格。
20. **多词条/多变体分别比价**（「不同词条分别多少钱」「各词缀价格对比」）：每条 query **只含一个词条或一种变体**，逐项调用 trade_search；全部搜完后用 markdown 表格或列表**汇总**，禁止把多个词条塞进一次搜索，禁止未搜索就报各词条价格。

21. **词缀解析/归一化**：装备或词缀搜索前，先理解用户提到的抗性/伤害/召唤等级/移速等，写成标准中文词缀名，再 `resolve_trade_stat(canonical_label=...)`；`canonical_label` **不得**包含数值后缀（如 +4、15% 等），数值只写在 operator/value 或用户说明中；禁止把口语/缩写原样传入。
22. **歧义处理**：若 `need_disambiguation` 为 true，结合 suggestions 与上下文选定 stat_id 并说明理由，再调用 `trade_search`。
23. **trade_search query 用词**：`trade_search` 的 query 必须使用已确认的 `text_cn`（来自 resolve 的 best 或你选定的那条 suggestion）。

## 多轮对话（必读历史，工具参数由你构造）
24. 当前句很短或含「这个/这件/上面/差不多/同款」而**未重复描述装备** → 必须从对话历史还原物品再 `trade_search`，禁止用「值多少钱」等当 query。
25. 用户纠正搜索（「不是珠宝」「别搜蓝玉」）→ 根据历史中真实装备类型/词缀**重新** `trade_search`；纠正句只作说明，不要当搜索词。
26. 「如何搭配/配装/怎么配/装备选择」→ `entity_resolve` + `rag_search`，由你分析配装；**不要**用 `recommend`（`recommend` 仅用于用户明确对比多个具名装备「哪个更好」）。
27. 附图 + 问价：先描述图中装备，再 `trade_search`；query 写词缀/类型，不要把纠正或情绪句塞进 query。
28. 规划工具时默认**已阅读**上方完整对话；同一轮可先 `rag_search` 再 `trade_search`，顺序由你决定。
29. **扭曲项链 vs 畸变项链**：国服 Trade 译名中 **扭曲项链=Distorted Amulet**（普通基底词缀池），**畸变项链=Twisted Amulet**（Delirium 涂油/Instilled 底）。用户说「扭曲项链」且未提涂油时，按 Distorted Amulet 检索；涂油/Instilled/扭曲护身符才指 Twisted Amulet。
30. **物品百科 vs 市集**：仅物品/基底名、或问「词条/词缀/能出什么/介绍/是什么」→ **必须** `entity_resolve` + `rag_search`；**禁止** `trade_search`（除非用户明确要搜装备/查价/多少钱）。检测信号含 `bare_item_name` 或 `item_knowledge_query` 时遵守本条。
31. 若仍调用 `trade_search` 且 query 含基底名，query **只写基底 CN 名**（如「扭曲项链」），服务端会自动加 `type` 过滤；不要对百科问题返回泛类目搜索结果。
## 回答格式
- 使用清晰的中文 markdown（### 小标题、列表、**关键数值**）
- 资料不足就说明不足，标注 [推测] 仅限合理推断
- 交易搜索结果需在正文中解释最佳匹配含义；有 listing_price 时写「市集参考价：XXX」，并说明是近似匹配最低价
"""


def _active_tools(ctx: ChatToolContext) -> list[dict[str, Any]]:
    """Return available tools for this turn, removing exhausted ones."""
    active = list(TOOL_DEFINITIONS)
    if ctx.trade_search_calls >= TRADE_SEARCH_MAX_PER_TURN:
        active = [t for t in active if t["function"]["name"] != "trade_search"]
    if ctx.rag_search_calls >= RAG_SOFT_LIMIT:
        active = [t for t in active if t["function"]["name"] != "rag_search"]
        # If no rag_search, entity_resolve by itself is less useful — keep it but hint
    return active


def _llm_client():
    return get_async_llm_client()


def _model() -> str:
    return LLM_MODEL


def _build_system_message(user_msg: str) -> str:
    signals = detect_input_signals(user_msg)
    extra = ""
    if signals:
        extra = "\n\n## 检测信号（供你决策，非强制路由）\n" + ", ".join(signals)
    return AGENT_SYSTEM + extra


def _parse_tool_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _first_choice(obj: Any) -> Any | None:
    choices = getattr(obj, "choices", None) or []
    return choices[0] if choices else None


async def _emit_streamed_answer(
    client: AsyncOpenAI,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event_type, text) for answer/reasoning. Falls back to non-stream if needed."""
    stream_kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    thinking = llm_thinking_extra_body()
    if thinking:
        stream_kwargs["extra_body"] = thinking

    answer_parts: list[str] = []
    try:
        stream = await client.chat.completions.create(**stream_kwargs)
        async for chunk in stream:
            choice = _first_choice(chunk)
            if choice is None:
                continue
            delta = choice.delta
            reasoning = getattr(delta, "reasoning_content", None) or (
                delta.model_extra.get("reasoning_content")
                if hasattr(delta, "model_extra") and delta.model_extra
                else None
            )
            if reasoning:
                yield ("reasoning", reasoning)
            if delta.content:
                answer_parts.append(delta.content)
                yield ("answer", delta.content)
    except Exception as e:
        logger.warning("[CHAT] stream synthesis failed, fallback: %s", e)

    if answer_parts:
        return

    # MiMo sometimes returns empty stream chunks — non-stream fallback
    fb_kwargs = dict(stream_kwargs)
    fb_kwargs.pop("stream", None)
    fb_kwargs.pop("extra_body", None)
    if thinking:
        fb_kwargs["extra_body"] = thinking
    resp = await client.chat.completions.create(**fb_kwargs)
    choice = _first_choice(resp)
    if choice is None:
        raise RuntimeError("LLM returned no choices")
    msg = choice.message
    reasoning = getattr(msg, "reasoning_content", None) or ""
    if reasoning:
        yield ("reasoning", reasoning)
    text = msg.content or ""
    if text:
        yield ("answer", text)




async def _follow_up_event(user_msg: str, answer: str) -> dict[str, Any] | None:
    questions = await generate_follow_up_questions(user_msg, answer)
    if questions:
        return {"type": "follow_ups", "content": questions}
    return None


async def _stream_with_follow_ups(
    user_msg: str,
    source: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    answer_acc = ""
    async for event in source:
        if event.get("type") == "answer":
            chunk = event.get("content") or ""
            if isinstance(chunk, str):
                answer_acc += chunk
        if event.get("type") == "done":
            fu = await _follow_up_event(user_msg, answer_acc)
            if fu:
                yield fu
        yield event
        if event.get("type") == "done":
            return


async def _yield_done_with_follow_ups(
    user_msg: str,
    answer: str,
) -> AsyncIterator[dict[str, Any]]:
    fu = await _follow_up_event(user_msg, answer)
    if fu:
        yield fu
    yield {"type": "done"}



async def stream_chat_agent(messages: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """Run the agent loop and yield SSE event dicts."""

    user_msg = resolve_user_text(messages)
    last_msg = messages[-1] if messages else {}
    has_images = message_has_images(last_msg)

    if has_images:
        yield {"type": "thinking", "content": "已收到图片，正在视觉分析…"}

    session = build_session_context(messages)
    ctx = ChatToolContext(user_msg=session.effective_user_msg())
    client = _llm_client()

    agent_messages = build_agent_messages(messages, _build_system_message(user_msg))

    yield {"type": "thinking", "content": "AI 正在分析意图并规划工具..."}

    used_tools = False
    answer_acc = ""
    tool_round = 0
    while tool_round < MAX_TOOL_ROUNDS:
        tool_round += 1
        try:
            response = await client.chat.completions.create(
                model=_model(),
                messages=agent_messages,
                tools=_active_tools(ctx),
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error("[CHAT] agent plan failed: %s", e)
            err = f"AI 规划失败: {e}"
            yield {"type": "answer", "content": err}
            async for ev in _yield_done_with_follow_ups(user_msg, err):
                yield ev
            flush()
            return

        choice = _first_choice(response)
        if choice is None:
            err = "AI 规划失败: LLM 未返回有效结果"
            logger.error("[CHAT] agent plan empty choices")
            yield {"type": "answer", "content": err}
            async for ev in _yield_done_with_follow_ups(user_msg, err):
                yield ev
            flush()
            return
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            if msg.content:
                answer_acc += msg.content
                yield {"type": "answer", "content": msg.content}
            break

        # Append assistant message with tool calls
        assistant_entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        assistant_entry["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tool_calls
        ]
        agent_messages.append(assistant_entry)
        used_tools = True

        for tc in tool_calls:
            fn = tc.function.name
            args = _parse_tool_args(tc.function.arguments)
            label = TOOL_LABELS.get(fn, fn)
            yield {"type": "thinking", "content": f"调用工具: {label}..."}
            yield {
                "type": "tool_use",
                "content": {"name": fn, "arguments": args},
            }

            try:
                result = await execute_tool(fn, args, ctx)
            except Exception as e:
                logger.error("[CHAT] tool %s failed: %s", fn, e)
                result_content = json.dumps({"error": str(e)}, ensure_ascii=False)
                yield {
                    "type": "tool_result",
                    "content": {"name": fn, "ok": False, "preview": str(e)[:200]},
                }
                agent_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    },
                )
                continue

            preview = result.content[:240] + ("..." if len(result.content) > 240 else "")
            yield {
                "type": "tool_result",
                "content": {"name": fn, "ok": True, "preview": preview},
            }

            if result.trade_result:
                yield {"type": "trade_result", "content": result.trade_result}
            if result.recommend_result:
                yield {"type": "recommend_result", "content": result.recommend_result}

            agent_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result.content,
                },
            )


    if not used_tools:
        if ctx.last_sources:
            yield {"type": "sources", "content": ctx.last_sources}
        async for ev in _yield_done_with_follow_ups(user_msg, answer_acc):
            yield ev
        flush()
        return


    # Stream final synthesis after tool rounds
    yield {"type": "thinking", "content": "正在综合工具结果生成回答..."}

    try:
        async for kind, text in _emit_streamed_answer(client, agent_messages):
            if kind == "reasoning":
                yield {"type": "reasoning", "content": text}
            else:
                answer_acc += text
                yield {"type": "answer", "content": text}
    except Exception as e:
        logger.error("[CHAT] agent stream failed: %s", e)
        err = f"生成失败: {e}"
        answer_acc += err
        yield {"type": "answer", "content": err}

    if ctx.last_sources:
        yield {"type": "sources", "content": ctx.last_sources}

    async for ev in _yield_done_with_follow_ups(user_msg, answer_acc):
        yield ev

    flush()
