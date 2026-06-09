"""Trade Search Agent — multi-turn LLM agent with tool calling.

Architecture:
  LLM Agent (loop, max 5 turns)
    ├─ search_stats(query, top_k) → stat ID + English text candidates
    ├─ execute_search(stat_groups) → total_results + URL
    └─ final_answer(summary, url, total) → return to user

No pseudo item-type validation. Agent sees results and adapts.
"""

import json
import re
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

# ── Agent tool definitions (OpenAI function-calling format) ──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_stats",
            "description": "搜索 PoE2 交易站的词缀数据库。输入中文或英文关键词，返回最匹配的词缀 ID 和英文文本。可以多次调用，用不同的关键词组合来找到最准确的词缀。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，可以是中文或英文。例如 '召唤伤害'、'Minions deal Damage'、'火焰抗性'",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回多少条结果，默认 10，最多 20",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_search",
            "description": "向 PoE2 官方交易站发起实际搜索，返回结果的条数和链接。如果返回 0 条，说明当前词缀组合没有匹配装备，需要调整词缀或放宽条件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_type": {
                        "type": "string",
                        "description": "装备类型 ID，如 accessory.amulet, weapon.sceptre, armour.boots 等。不填则不限类型",
                    },
                    "stat_groups": {
                        "type": "array",
                        "description": "词缀分组列表。每组的 type: and(全部必须)/count(至少匹配 count_min 条)/not(排除)/weight2(加权)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["and", "count", "not", "weight2"]},
                                "count_min": {"type": "integer", "description": "仅 count 类型需要"},
                                "stats": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string", "description": "词缀 ID，如 explicit.stat_2162097452"},
                                            "min": {"type": "number", "description": "数值最小值，不指定则为 null"},
                                            "max": {"type": "number", "description": "数值最大值，不指定则为 null"},
                                        },
                                        "required": ["id"],
                                    },
                                },
                            },
                            "required": ["type", "stats"],
                        },
                    },
                    "rarity": {
                        "type": "string",
                        "enum": ["normal", "magic", "rare", "unique"],
                        "description": "稀有度限制，不填则不限",
                    },
                    "league": {
                        "type": "string",
                        "description": "赛季，默认 Standard",
                        "default": "Standard",
                    },
                },
                "required": ["stat_groups"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "搜索完成，返回最终结果给用户。当找到结果或确认无法找到时调用此工具结束搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "PoE2 交易站链接",
                    },
                    "summary": {
                        "type": "string",
                        "description": "给用户的中文总结说明",
                    },
                    "total_results": {
                        "type": "integer",
                        "description": "搜索结果总数",
                    },
                },
                "required": ["summary", "total_results"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是 PoE2（流放之路2）交易搜索助手。用户用中文描述想找的装备，你通过工具搜索词缀并执行交易站查询。

## 严格流程（必须按顺序执行！）

### 阶段1：理解需求（1次思考）
识别装备类型、核心需求词缀、辅助词缀。

### 阶段2：搜索核心词缀（1-3次 search_stats）
对每个需求，调 search_stats 找词缀 ID。
- 核心需求（如"+2召唤等级"）：搜 1 次就够了
- 模糊需求（如"召唤光环"）：最多搜 3 次，用不同关键词
- ⚠️ 搜到足够候选后立刻进入阶段3，不要无限搜！

### 阶段3：执行搜索（调 execute_search）
把选好的词缀组成 stat_groups，调 execute_search。
- 第1次搜索：用最匹配的词缀
- 如果结果 0：分析原因，调整后重试（最多重试 2 次）
  - 加通用词缀（最大生命、三种抗性、护盾）到 count 池子
  - 降 count_min 到 1
  - 去掉可能太稀有的词缀
- 如果结果 > 0：立刻调 final_answer

### 阶段4：结束（调 final_answer）
- 有结果 → 返回链接和数量
- 重试3次仍为0 → 告知用户建议调整方向

## ⚠️ 重要规则
- search_stats 最多调 5 次！超过 5 次还没找到，也要强行进入 execute_search
- 必须在第 8 轮之前调 final_answer
- count 组里必须加通用词缀（最大生命 + 三种抗性）作为兜底
- 搜到 0 结果时：先加通用词缀，再降 count_min，不要反复搜词

## 装备类型 ID
项链: accessory.amulet | 戒指: accessory.ring | 腰带: accessory.belt
权杖: weapon.sceptre | 魔杖: weapon.wand | 弓: weapon.bow
胸甲: armour.chest | 头盔: armour.helmet | 手套: armour.gloves | 鞋子: armour.boots
"""


def _get_llm_client():
    from openai import OpenAI
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


# ── Tool implementations ──

def _tool_search_stats(db, args: dict) -> str:
    """Execute search_stats tool and return JSON result."""
    from app.services.trade_stat_service import search_stats

    query = args.get("query", "")
    top_k = min(args.get("top_k", 10), 20)

    matches = search_stats(db, query, top_k=top_k, stat_type="explicit", min_similarity=0.35)
    if not matches:
        matches = search_stats(db, query, top_k=top_k, min_similarity=0.35)

    results = []
    for m in matches:
        results.append({
            "id": m["stat_id"],
            "text": m["ref_text"],
            "similarity": round(m["similarity"], 3),
        })

    return json.dumps({
        "query": query,
        "count": len(results),
        "results": results,
    }, ensure_ascii=False)


def _tool_execute_search(db, intent_ctx: dict, args: dict) -> str:
    """Execute execute_search tool and return JSON result."""
    from app.services.trade_service import build_trade_query, search_trade

    item_type = args.get("item_type")
    stat_groups = args.get("stat_groups", [])
    rarity = args.get("rarity")
    league = args.get("league", "Standard")

    # No universal injection — let agent handle 0 results by retrying with different stats
    # Future: inject context-appropriate stats based on user's build/class
    intent = {
        "item_type": item_type,
        "item_type_name": None,
        "rarity": rarity,
        "stat_groups": stat_groups,
        "summary": intent_ctx.get("summary", ""),
    }

    result = search_trade(intent, league)

    if result.get("error"):
        return json.dumps({"error": result["error"]}, ensure_ascii=False)

    url = result.get("trade_url", "")
    total = result.get("total_results", 0)

    # Store for fallback if LLM forgets to pass url to final_answer
    if url:
        intent_ctx["last_url"] = url
        intent_ctx["last_total"] = total

    return json.dumps({
        "total_results": total,
        "url": url,
        "search_id": result.get("search_id", ""),
        "hint": f"搜索完成，{total} 条结果。如果结果 > 0，立即调 final_answer 并把 url 参数设为 '{url}'！",
    }, ensure_ascii=False)


def _tool_final_answer(args: dict, messages: list, intent_ctx: dict) -> dict:
    """Complete the agent loop and return final result.

    Falls back to intent_ctx['last_url'] if LLM doesn't pass url.
    """
    url = args.get("url", "") or intent_ctx.get("last_url", "")
    total = args.get("total_results", 0) or intent_ctx.get("last_total", 0)
    return {
        "done": True,
        "trade_url": url,
        "total_results": total,
        "intent_summary": args.get("summary", ""),
    }


# ── Agent loop ──

MAX_TURNS = 10


def run_agent(query: str, league: str = "Standard") -> dict:
    """Run the trade search agent for a user query.

    LLM Agent with tools: search_stats → execute_search → final_answer.
    Multi-turn: can retry with different strategies if search returns 0.

    Returns: dict with trade_url, total_results, intent_summary, error
    """
    from app.core.database import SessionLocal
    from openai import OpenAI

    client = _get_llm_client()
    db = SessionLocal()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"搜索：{query}\n赛季：{league}"},
    ]

    intent_ctx = {"summary": query}
    stats_call_count = 0
    search_call_count = 0  # execute_search count
    MAX_STATS_CALLS = 4
    MAX_SEARCH_CALLS = 3

    try:
        for turn in range(MAX_TURNS):
            logger.info(f"Agent turn {turn + 1}/{MAX_TURNS} (stats={stats_call_count}, search={search_call_count})")

            # Force progression: if too many search_stats, block further calls
            if stats_call_count >= MAX_STATS_CALLS:
                messages.append({
                    "role": "system",
                    "content": "⚠️ 已经搜了足够多次词缀。现在必须调 execute_search 执行实际搜索！不要再搜词缀了。",
                })

            # Force final_answer after enough search attempts
            if search_call_count >= MAX_SEARCH_CALLS:
                messages.append({
                    "role": "system",
                    "content": "⚠️ 已经搜了多次，现在必须调 final_answer 结束。告知用户找到了多少结果，或建议调整搜索条件。不要再调其他工具了。",
                })

            try:
                resp = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2048,
                )
            except Exception as e:
                logger.error(f"LLM call failed at turn {turn + 1}: {e}")
                return {
                    "error": f"AI 服务调用失败: {e}",
                    "total_results": 0,
                    "trade_url": "",
                    "intent_summary": query,
                }

            msg = resp.choices[0].message

            # If LLM responds with text (no tool call), add to messages
            if msg.content and not msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content})
                # If it seems like a final answer, break
                if "找到" in msg.content or "没有" in msg.content or "抱歉" in msg.content:
                    return {
                        "trade_url": "",
                        "total_results": 0,
                        "intent_summary": msg.content[:200],
                        "error": None,
                    }
                continue

            # If no tool calls, ask LLM to continue or stop
            if not msg.tool_calls:
                logger.info(f"Agent stopped at turn {turn + 1} (no tool call)")
                return {
                    "trade_url": "",
                    "total_results": 0,
                    "intent_summary": msg.content or query,
                    "error": None,
                }

            # Process tool calls
            tool_call = msg.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # Block search_stats if limit reached
            if tool_name == "search_stats" and stats_call_count >= MAX_STATS_CALLS:
                result_str = json.dumps({"error": "已超过 search_stats 调用上限，请直接调 execute_search"})
            elif tool_name == "search_stats":
                stats_call_count += 1
                result_str = _tool_search_stats(db, tool_args)
            elif tool_name == "execute_search" and search_call_count >= MAX_SEARCH_CALLS:
                result_str = json.dumps({"error": "已超过 execute_search 调用上限，请调 final_answer 结束"})
            elif tool_name == "execute_search":
                search_call_count += 1
                result_str = _tool_execute_search(db, intent_ctx, tool_args)
                # Auto-transition to final_answer after last search attempt
                if search_call_count >= MAX_SEARCH_CALLS:
                    d = json.loads(result_str)
                    if d.get("total_results", 0) > 0:
                        result_str = json.dumps({**d, "hint": "找到结果了！现在必须调 final_answer 返回给用户。"})
                    else:
                        result_str = json.dumps({**d, "hint": "多次搜索均为0结果。现在必须调 final_answer 告知用户建议调整条件。"})
                result_str = _tool_execute_search(db, intent_ctx, tool_args)
            elif tool_name == "final_answer":
                final = _tool_final_answer(tool_args, messages, intent_ctx)
                db.close()
                return final
            else:
                result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})

            # Add assistant message + tool result to conversation
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": tool_call.function.arguments,
                        },
                    },
                ],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_str,
            })

        # Max turns reached
        logger.warning(f"Agent reached max turns ({MAX_TURNS})")
        return {
            "trade_url": "",
            "total_results": 0,
            "intent_summary": "搜索超时，请简化查询条件后重试",
            "error": "搜索步骤过多，请尝试更简洁的描述",
        }

    finally:
        db.close()
