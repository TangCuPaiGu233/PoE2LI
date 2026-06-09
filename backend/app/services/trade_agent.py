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

## 工作流程

1. 理解用户需求：识别装备类型、核心需求词缀、辅助词缀（count 组）
2. 调用 search_stats 找每个需求的候选词缀 ID
3. 如果有疑问，多调几次 search_stats 用不同关键词，确认选对了
4. 调用 execute_search 执行搜索
5. 如果结果 > 0：调 final_answer 返回链接
6. 如果结果 = 0：分析原因，调整策略重试（最多 3 次）：
   - count 组池子太小？加更多候选词缀（生命、抗性等通用词缀）
   - count_min 太高？降到 1
   - 某些词缀在该装备上可能极稀有？去掉它们，换通用词缀
7. 如果 3 次重试都是 0：调 final_answer，告知用户哪些词缀可能不存在于该装备上，建议怎么改

## 装备类型 ID 对照
- 项链: accessory.amulet
- 戒指: accessory.ring
- 腰带: accessory.belt
- 权杖: weapon.sceptre
- 魔杖: weapon.wand
- 长杖: weapon.staff
- 弓: weapon.bow
- 弩: weapon.crossbow
- 单手剑/斧/锤: weapon.onesword / weapon.oneaxe / weapon.onemace
- 双手剑/斧/锤: weapon.twosword / weapon.twoaxe / weapon.twomace
- 胸甲: armour.chest
- 头盔: armour.helmet
- 手套: armour.gloves
- 鞋子: armour.boots
- 盾牌: armour.shield

## 搜索技巧
- count 组的池子要大（8-12 条），既包含主题词缀也包含通用词缀（最大生命、三种抗性、护盾）
- 「召唤光环」类的需求，用多个关键词搜索：raw 中文 + English paraphrase
- 执行 execute_search 之前，count 组里至少有 count_min + 2 条候选词缀
- 不要把明显属于其他装备的词缀放进池子（如武器上的附加伤害不在项链上）
- 如果搜索结果 0：先检查是不是 count_min 太高，再检查是不是有词缀太稀有

## 输出要求
- 每次只调用一个工具
- 收到工具结果后，分析并决定下一步
- 完成搜索后调 final_answer
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

    # Build intent from args
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

    return json.dumps({
        "total_results": result.get("total_results", 0),
        "url": result.get("trade_url", ""),
        "search_id": result.get("search_id", ""),
    }, ensure_ascii=False)


def _tool_final_answer(args: dict, messages: list) -> dict:
    """Complete the agent loop and return final result."""
    return {
        "done": True,
        "trade_url": args.get("url", ""),
        "total_results": args.get("total_results", 0),
        "intent_summary": args.get("summary", ""),
    }


# ── Agent loop ──

MAX_TURNS = 8


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

    try:
        for turn in range(MAX_TURNS):
            logger.info(f"Agent turn {turn + 1}/{MAX_TURNS}")

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

            logger.info(f"Agent calls {tool_name}: {json.dumps(tool_args, ensure_ascii=False)[:200]}")

            # Execute tool
            if tool_name == "search_stats":
                result_str = _tool_search_stats(db, tool_args)
            elif tool_name == "execute_search":
                result_str = _tool_execute_search(db, intent_ctx, tool_args)
            elif tool_name == "final_answer":
                final = _tool_final_answer(tool_args, messages)
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
