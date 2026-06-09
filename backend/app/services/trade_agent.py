"""Trade Agent — code-driven pipeline with LLM at decision points.

Architecture (inspired by Claw Code):
  Code controls the loop. LLM is called for specific intelligence tasks:
  1. Parse user query → requirements (one LLM call)
  2. Vector search for each requirement (code)
  3. LLM selects best stat IDs from candidates (one LLM call per ambiguous req)
  4. Build and execute Trade API query (code)
  5. If 0 results, retry with relaxed constraints (code + optional LLM advice)
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

# ── LLM: Parse user query into structured requirements ──

PARSE_SYSTEM_PROMPT = """You parse Chinese PoE2 trade search queries.

RULES:
- The user lists multiple requirements for ONE item (e.g. "+2召唤 且 2条光环")
- ALL requirements go into a SINGLE count group with ONE combined pool of candidate stats
- count_min = total number of requirements (1 for each "must have" + N for "at least N")
- Each requirement gets search_queries to find matching stat IDs
- The stats from all requirements are merged into one pool, and the item just needs to match count_min of them

Item type IDs:
  necklace = accessory.amulet
  ring = accessory.ring
  sceptre = weapon.sceptre
  wand = weapon.wand
  bow = weapon.bow
  chest = armour.chest
  helmet = armour.helmet
  gloves = armour.gloves
  boots = armour.boots

Example:
User: 加2召唤等级的项链，至少2条召唤光环
Output:
{
  "item_type": "accessory.amulet",
  "count_min": 3,
  "requirements": [
    {
      "raw": "召唤技能等级+2",
      "meaning_hint": "+2 Level of all Minion Skills",
      "search_queries": ["# to Level of all Minion Skills", "Minion Skills level", "召唤技能等级"]
    },
    {
      "raw": "召唤光环",
      "meaning_hint": "minion-related aura/buff mods",
      "search_queries": ["Spirit", "Allies in your Presence", "Minions deal increased Damage", "Minions have increased Attack Speed", "召唤光环 友军 附近"]
    }
  ]
}
Explanation: count_min=3 because user wants 1 (Minion Skills) + 2 (aura mods) = 3 total matches.

Another example:
User: 生命80以上，火抗30以上的戒指
Output:
{
  "item_type": "accessory.ring",
  "count_min": 2,
  "requirements": [
    {
      "raw": "生命80以上",
      "meaning_hint": "maximum Life at least 80",
      "search_queries": ["+# to maximum Life", "maximum Life", "生命"]
    },
    {
      "raw": "火抗30以上",
      "meaning_hint": "Fire Resistance at least 30",
      "search_queries": ["+#% to Fire Resistance", "Fire Resistance", "火抗 火焰抗性"]
    }
  ]
}

Output ONLY valid JSON, no markdown."""


def _get_llm_client():
    from openai import OpenAI
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


# ── Step 1: Parse intent ──

def _parse_intent(query: str) -> dict:
    """One LLM call: parse Chinese query into structured requirements."""
    client = _get_llm_client()

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        content = resp.choices[0].message.content.strip()

        # Extract JSON
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        parsed = json.loads(content)
        logger.info(f"Intent parsed: item_type={parsed.get('item_type')}, "
                    f"requirements={len(parsed.get('requirements', []))}")
        return parsed
    except Exception as e:
        logger.error(f"Intent parsing failed: {e}")
        return {"item_type": None, "requirements": []}


# ── Step 2: Multi-query vector retrieval ──

def _retrieve_stats(db, requirement: dict, top_k: int = 15) -> list[dict]:
    """For each search_query in the requirement, search vector DB and merge results."""
    from app.services.trade_stat_service import search_stats

    seen_ids = set()
    all_matches = []

    for query in requirement.get("search_queries", []):
        matches = search_stats(db, query, top_k=8, stat_type="explicit", min_similarity=0.35)
        if not matches:
            matches = search_stats(db, query, top_k=8, min_similarity=0.35)
        for m in matches:
            if m["stat_id"] not in seen_ids:
                seen_ids.add(m["stat_id"])
                all_matches.append(m)

    all_matches.sort(key=lambda x: x["similarity"], reverse=True)
    result = all_matches[:top_k]
    logger.info(f"Retrieved {len(result)} candidates for '{requirement.get('raw', '?')}' "
                f"from {len(requirement.get('search_queries', []))} queries")
    return result

# ── Step 3: Build and execute search ──

def _build_intent(intent: dict, all_stats: list[dict], count_min: int) -> dict:
    """Build a single COUNT group intent from merged stats."""
    stats = [{"id": s["stat_id"]} for s in all_stats]

    logger.info(f"Built intent: 1 count group, {len(stats)} stats, count_min={count_min}")

    return {
        "item_type": intent.get("item_type"),
        "item_type_name": None,
        "rarity": intent.get("rarity"),
        "stat_groups": [{"type": "count", "count_min": count_min, "stats": stats}],
        "summary": intent.get("summary", ""),
    }


def _execute_search(intent: dict, league: str) -> dict:
    """Execute a single trade search from intent dict."""
    from app.services.trade_service import search_trade
    return search_trade(intent, league)


# ── Main pipeline ──

def run_agent(query: str, league: str = "Standard") -> dict:
    """Run the trade search pipeline.

    ONE count group — all stats in one pool, item just needs to match count_min.
    """
    from app.core.database import SessionLocal

    t_start = time.time()
    db = SessionLocal()

    try:
        # Step 1: LLM parses intent
        logger.info("Step 1: Parsing intent...")
        intent = _parse_intent(query)
        requirements = intent.get("requirements", [])
        item_type = intent.get("item_type")
        count_min = intent.get("count_min", 2)

        if not requirements:
            return {
                "trade_url": "",
                "total_results": 0,
                "intent_summary": "无法理解搜索意图",
                "error": "无法解析搜索意图",
            }

        # Step 2: Retrieve stats
        # First requirement = core (goes in AND group — must have)
        # Remaining requirements = broad (go in COUNT group — at least count_min)
        core_stats = []
        broad_stats = []
        seen_ids = set()

        for i, req in enumerate(requirements):
            limit = 1 if i == 0 else 10
            logger.info(f"Retrieving stats for '{req.get('raw', '?')}' (keep top {limit})...")
            candidates = _retrieve_stats(db, req)
            kept = 0
            for c in candidates:
                if c["stat_id"] not in seen_ids:
                    seen_ids.add(c["stat_id"])
                    if i == 0:
                        core_stats.append(c)
                    else:
                        broad_stats.append(c)
                    kept += 1
                    if kept >= limit:
                        break

        if not core_stats:
            return {
                "trade_url": "",
                "total_results": 0,
                "intent_summary": "未找到匹配的核心词缀",
                "error": "向量搜索未找到匹配词缀",
            }

        logger.info(f"Core: {len(core_stats)} stats, Broad: {len(broad_stats)} stats")

        # Step 3: Build AND + COUNT groups
        # AND group: core stats (must match all)
        # COUNT group: broad stats (match count_min of these)
        # count_min = total_requirements - 1 (minus the core requirement)
        broad_count_min = max(1, count_min - len(core_stats))
        if broad_count_min < 1:
            broad_count_min = 1

        search_intent = {
            "item_type": intent.get("item_type"),
            "item_type_name": None,
            "rarity": intent.get("rarity"),
            "stat_groups": [
                {"type": "and", "stats": [{"id": s["stat_id"]} for s in core_stats]},
                {"type": "count", "count_min": broad_count_min, "stats": [{"id": s["stat_id"]} for s in broad_stats]},
            ],
            "summary": intent.get("summary", ""),
        }
        logger.info(f"Built: AND({len(core_stats)}) + COUNT({len(broad_stats)}, min={broad_count_min})")

        result = _execute_search(search_intent, league)
        total = result.get("total_results", 0)
        url = result.get("trade_url", "")

        # Step 4: If 0 results, retry with count_min=1
        if total == 0:
            logger.info(f"0 results, retrying with count_min=1...")
            search_intent["stat_groups"][1]["count_min"] = 1
            result = _execute_search(search_intent, league)
            total = result.get("total_results", 0)
            url = result.get("trade_url", url)
            summary = f"放宽条件后找到 {total} 件" if total > 0 else "未找到匹配装备，建议调整搜索条件"
        else:
            req_names = ", ".join(r.get("raw", "?") for r in requirements)
            summary = f"搜索 {req_names}(合计{count_min}条)，找到 {total} 件"

        elapsed = time.time() - t_start
        logger.info(f"Pipeline complete in {elapsed:.1f}s: {total} results, {url}")
        return {
            "trade_url": url,
            "total_results": total,
            "intent_summary": summary,
            "error": None,
        }

    except Exception as e:
        logger.error(f"Agent pipeline error: {e}", exc_info=True)
        return {
            "trade_url": "",
            "total_results": 0,
            "intent_summary": f"搜索出错: {str(e)[:100]}",
            "error": str(e),
        }
    finally:
        db.close()
