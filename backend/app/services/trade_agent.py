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
            "name": "inspect_results",
            "description": "抽查搜索结果中的实际装备。拿到 search_id 后，取前几条装备查看它们的词缀，验证是否真的匹配用户需求。如果不匹配，说明词缀选错了，需要换词重新搜。",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_id": {
                        "type": "string",
                        "description": "execute_search 返回的 search_id",
                    },
                    "count": {
                        "type": "integer",
                        "description": "抽查几条，默认 3",
                        "default": 3,
                    },
                },
                "required": ["search_id"],
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

SYSTEM_PROMPT = """You are a PoE2 trade search agent. Follow these rules EXACTLY:

STEP 1: Parse the user's Chinese query. Identify item_type, core requirement (use "and" group), and optional requirements (use "count" group).

STEP 2: Call search_stats for each requirement. Use the user's original Chinese words and English paraphrases. Max 3 search_stats calls total, then STOP searching and move on.

STEP 3: Call execute_search with the stat IDs you found. Use the exact IDs from search_stats results. For count groups, include ALL candidate stats you found — do not filter.

STEP 4: If execute_search returns total_results > 0, you MUST call inspect_results to verify the items actually match. If they don't match, reconsider your stat choices and go back to STEP 2.

STEP 5: Call final_answer with the trade URL from the LAST successful execute_search. Include in summary: what was searched, how many results, and the URL.

CRITICAL RULES:
- You CANNOT call search_stats more than 3 times.
- You MUST call execute_search after finding stats.
- You MUST call inspect_results before final_answer when results > 0.
- You MUST call final_answer by turn 8.
- NEVER hallucinate stat IDs — only use IDs returned by search_stats.
- If execute_search returns 0, try again with count_min lowered to 1. If still 0, call final_answer and tell the user the stats may not exist on that item type.

Item type IDs:
necklace/amulet=accessory.amulet ring=accessory.ring belt=accessory.belt
sceptre=weapon.sceptre wand=weapon.wand bow=weapon.bow staff=weapon.staff
chest=armour.chest helmet=armour.helmet gloves=armour.gloves boots=armour.boots
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


def _tool_inspect_results(db, args: dict, intent_ctx: dict) -> str:
    """Fetch actual items from a search result and show their mods."""
    import cloudscraper

    search_id = args.get("search_id", "")
    count = min(args.get("count", 3), 5)
    league = intent_ctx.get("league", "Standard")

    if not search_id:
        return json.dumps({"error": "缺少 search_id，请先调 execute_search"})

    # Step 1: fetch item IDs from the search
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    fetch_url = f"https://www.pathofexile.com/api/trade2/fetch/{','.join([search_id])}?query={search_id}&limit={count}"
    # Actually the correct endpoint is:
    # GET /api/trade2/search/<league>/<search_id> first to get item IDs
    # Then POST /api/trade2/fetch/<item_ids>
    search_url = f"https://www.pathofexile.com/api/trade2/search/{league}/{search_id}"
    try:
        resp = scraper.get(search_url, timeout=15)
        if resp.status_code != 200:
            return json.dumps({"error": f"获取搜索结果失败 (HTTP {resp.status_code})"})
        search_data = resp.json()
        item_ids = search_data.get("result", [])[:count]
        if not item_ids:
            return json.dumps({"error": "搜索结果中没有装备"})
    except Exception as e:
        return json.dumps({"error": f"获取搜索结果失败: {e}"})

    # Step 2: fetch item details
    fetch_detail_url = f"https://www.pathofexile.com/api/trade2/fetch/{','.join(item_ids)}?query={search_id}"
    try:
        resp2 = scraper.get(fetch_detail_url, timeout=15)
        if resp2.status_code != 200:
            return json.dumps({"error": f"获取装备详情失败 (HTTP {resp2.status_code})"})
        items = resp2.json().get("result", [])
    except Exception as e:
        return json.dumps({"error": f"获取装备详情失败: {e}"})

    # Step 3: extract mods from each item
    samples = []
    for item in items[:count]:
        name = item.get("name", "?")
        item_type = item.get("typeLine", "?")
        # Extract explicit mods
        mods = []
        for mod in item.get("explicitMods", []):
            mods.append(mod)
        samples.append({
            "name": name,
            "type": item_type,
            "mods": mods[:10],  # first 10 explicit mods
        })

    intent_ctx["last_search_id"] = search_id
    return json.dumps({
        "search_id": search_id,
        "samples": samples,
        "hint": "检查这些装备的词缀是否匹配用户需求。如果不匹配，需要重新 search_stats 换词，或调整 stat_groups 去掉错误的词缀 ID。",
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
    stats_call_count = 0
    search_call_count = 0  # execute_search count
    MAX_STATS_CALLS = 3
    MAX_SEARCH_CALLS = 2

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
            elif tool_name == "inspect_results":
                result_str = _tool_inspect_results(db, tool_args, intent_ctx)
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
