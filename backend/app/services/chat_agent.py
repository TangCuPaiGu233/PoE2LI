"""Chat agent runtime — ClawCode-style ReAct loop: AI chooses tools, scripts execute."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import asyncio

from openai import AsyncOpenAI

from app.services.chat_tools import (
    TOOL_DEFINITIONS,
    TOOL_LABELS,
    ChatToolContext,
    detect_input_signals,
    execute_tool,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8

AGENT_SYSTEM = """你是「流放漓」Path of Exile 2 智能助手。

## 工作方式（必须遵守）
1. 你是编排者：先判断用户意图，再调用工具获取事实，最后基于工具结果用中文回答。
2. 不要在没有调用工具的情况下编造物品、技能数值、BD 数据或交易链接。
3. 用户消息若含 PoB 分享码(eN开头)、pobb.in 或 poe.ninja 或 wegame.com.cn/helper/poe2 分享链接 → 必须先调用 decode_pob。
4. 百科/机制/技能/物品问题 → 先 entity_resolve（如有中文专名），再 rag_search。
5. 找装备/市价/交易 → trade_search。
6. 「哪个更好/推荐/对比」→ recommend。
7. **多物品市价列表**（用户一次问多个装备/暗金分别多少钱）：逐个调用 trade_search，每查完一个物品先输出该物品报价，全部完成后再给汇总；不要在一次 trade_search 里混查多个物品。
8. 可连续调用多个工具；当前问题与历史无关时（例如仅贴链接），不要沿用上一轮话题。
9. 工具失败时如实告知用户（例如 poe.ninja 角色不存在、链接失效）。
10. rag_search 必须传入非空 query（英文检索词）；若未提供则服务端会用用户原话前 200 字兜底。同一轮对话最多调用 3 次 rag_search。
11. **WeGame 分享链接**：`stats:` 行含 Life/FireRes/LightningRes 等时，即 WeGame 面板数据，**必须原样引用**（火/冰/闪抗即元素抗性，闪电抗勿改称「魔抗」）。仅当含 `data_limitation` 时才禁止编造面板数值。WeGame 无升华字段。

## 回答格式
- 使用清晰的中文 markdown（### 小标题、列表、**关键数值**）
- 资料不足就说明不足，标注 [推测] 仅限合理推断
- 交易搜索结果需在正文中解释最佳匹配含义
"""


def _llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
    )


def _model() -> str:
    return os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")


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


async def stream_chat_agent(messages: list[dict]) -> AsyncIterator[dict[str, Any]]:
    """Run the agent loop and yield SSE event dicts."""
    from app.services.multi_item_price import is_multi_item_price_query, stream_multi_item_prices, is_build_cost_query, stream_build_cost

    user_msg = (messages[-1].get("content") if messages else "") or ""

    if is_build_cost_query(user_msg):
        yield {"type": "thinking", "content": "检测到 BD 造价查询，进入专用流水线…"}
        async for event in stream_build_cost(user_msg, market="cn"):
            if event.get("type") == "route" and event.get("content") == "default_agent":
                break
            yield event
            if event.get("type") == "done":
                return
        else:
            return

    if is_multi_item_price_query(user_msg):
        yield {"type": "thinking", "content": "检测到多件查价，进入市价流水线…"}
        async for event in stream_multi_item_prices(user_msg, market="cn"):
            if event.get("type") == "route" and event.get("content") == "default_agent":
                break
            yield event
            if event.get("type") == "done":
                return
        else:
            return

    ctx = ChatToolContext(user_msg=user_msg)
    client = _llm_client()

    agent_messages: list[dict[str, Any]] = [
        {"role": "system", "content": _build_system_message(user_msg)},
    ]
    for m in messages[-8:]:
        role = m.get("role", "user")
        content = m.get("content") or ""
        if role in ("user", "assistant") and content:
            agent_messages.append({"role": role, "content": content})

    yield {"type": "thinking", "content": "AI 正在分析意图并规划工具..."}

    used_tools = False
    tool_round = 0
    while tool_round < MAX_TOOL_ROUNDS:
        tool_round += 1
        try:
            response = await client.chat.completions.create(
                model=_model(),
                messages=agent_messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error("[CHAT] agent plan failed: %s", e)
            yield {"type": "answer", "content": f"AI 规划失败: {e}"}
            yield {"type": "done"}
            return

        choice = response.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            # Final text from model (non-streaming fallback)
            if msg.content:
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
        yield {"type": "done"}
        return

    # Stream final synthesis after tool rounds
    yield {"type": "thinking", "content": "正在综合工具结果生成回答..."}

    try:
        stream = await client.chat.completions.create(
            model=_model(),
            messages=agent_messages,
            temperature=0.3,
            max_tokens=2048,
            stream=True,
            extra_body={"thinking": {"type": "enabled"}},
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None) or (
                delta.model_extra.get("reasoning_content")
                if hasattr(delta, "model_extra") and delta.model_extra
                else None
            )
            if reasoning:
                yield {"type": "reasoning", "content": reasoning}
            if delta.content:
                yield {"type": "answer", "content": delta.content}
    except Exception as e:
        logger.error("[CHAT] agent stream failed: %s", e)
        yield {"type": "answer", "content": f"生成失败: {e}"}

    if ctx.last_sources:
        yield {"type": "sources", "content": ctx.last_sources}

    yield {"type": "done"}
