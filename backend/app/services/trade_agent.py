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

PARSE_SYSTEM_PROMPT = """You parse Chinese PoE2 trade search queries. Output JSON with:
- item_type: Trade API category ID (accessory.amulet, weapon.sceptre, armour.boots, etc.)
- requirements: list of search requirements, each with:
  - raw: the original Chinese phrase
  - kind: "required" (must have this stat) or "count" (match at least count_min of the listed stats)
  - count_min: (only for count kind) minimum number of matching stats
  - meaning_hint: English paraphrase of what this requirement means in PoE2 terms
  - search_queries: list of 2-4 search queries (Chinese and English) to find matching stat IDs

Item type IDs:
  necklace/amulet = accessory.amulet
  ring = accessory.ring
  belt = accessory.belt
  sceptre = weapon.sceptre
  wand = weapon.wand
  bow = weapon.bow
  staff = weapon.staff
  chest/body armour = armour.chest
  helmet = armour.helmet
  gloves = armour.gloves
  boots/shoes = armour.boots
  shield = armour.shield

Example:
User: 加2召唤技能等级的项链，至少2条召唤光环
Output:
{
  "item_type": "accessory.amulet",
  "requirements": [
    {
      "raw": "召唤技能等级+2",
      "kind": "required",
      "meaning_hint": "+2 to Level of all Minion Skills",
      "search_queries": ["+2 to Level of all Minion Skills", "# to Level of all Minion Skills", "召唤技能等级"]
    },
    {
      "raw": "召唤光环",
      "kind": "count",
      "count_min": 2,
      "meaning_hint": "minion aura mods: Spirit, nearby allies buffs",
      "search_queries": ["Spirit", "Allies in your Presence", "召唤光环", "nearby allies damage speed"]
    }
  ]
}

Output ONLY valid JSON, no markdown, no explanation."""


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

# ── Step 3: LLM selects from candidates ──

SELECT_SYSTEM_PROMPT = """You select the most relevant PoE2 trade stat IDs from a candidate list.

The user wants: {user_raw}
Meaning: {meaning_hint}
Target item: {item_type}

Candidate stats (pick the best matches for the user's intent):
{candidates_text}

Output ONLY JSON:
{{
  "selected_ids": ["explicit.stat_xxx", "explicit.stat_yyy", ...],
  "reason": "Brief reasoning in Chinese"
}}

Rules:
- Select ALL stats that match the user's intent, not just the top one
- For a "count" requirement, select 5-10 stats to create a large pool
- For a "required" requirement, select 1-3 stats
- Do NOT select stats that are clearly unrelated"""


def _select_from_candidates(requirement: dict, candidates: list[dict], item_type: str | None) -> list[dict]:
    """LLM selects the best stat IDs from candidate list."""
    if len(candidates) <= 3:
        return candidates  # few enough, just use all

    # Build candidate text for LLM
    lines = []
    id_to_candidate = {}
    for i, c in enumerate(candidates):
        lines.append(f"{i+1}. {c['stat_id']}: \"{c['ref_text']}\" (sim={c['similarity']:.2f})")
        id_to_candidate[c["stat_id"]] = c
    candidates_text = "\n".join(lines)

    prompt = SELECT_SYSTEM_PROMPT.format(
        user_raw=requirement.get("raw", ""),
        meaning_hint=requirement.get("meaning_hint", ""),
        item_type=item_type or "unknown",
        candidates_text=candidates_text,
    )

    client = _get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Select the matching stat IDs."},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)

        selection = json.loads(content)
        selected_ids = selection.get("selected_ids", [])
        reason = selection.get("reason", "")

        result = []
        for sid in selected_ids:
            sid = sid.split(".")[-1] if "." in sid else sid
            full_id = f"explicit.{sid}" if not sid.startswith("explicit.") else sid
            if full_id in id_to_candidate:
                result.append(id_to_candidate[full_id])
            else:
                # Try fuzzy match
                for cid, c in id_to_candidate.items():
                    if sid in cid or cid.endswith(sid):
                        result.append(c)
                        break

        logger.info(f"LLM selected {len(result)}/{len(candidates)} candidates for "
                    f"'{requirement.get('raw', '?')}': {reason[:80]}")
        return result if result else candidates[:5]
    except Exception as e:
        logger.error(f"Candidate selection failed: {e}, using top-5")
        return candidates[:5]


# ── Step 4: Build and execute search ──

def _build_search_query(intent: dict, requirements: list[dict]) -> dict:
    """Build Trade API query from requirements."""
    from app.services.trade_service import build_trade_query

    stat_groups = []
    for req in requirements:
        kind = req.get("kind", "required")
        selected = req.get("_selected_stats", [])

        if not selected:
            continue

        stats = []
        for s in selected:
            entry = {"id": s["stat_id"]}
            val = req.get("value")
            if val is not None:
                entry["min"] = val
            stats.append(entry)

        if kind == "required":
            stat_groups.append({"type": "and", "stats": stats})
        elif kind == "count":
            count_min = req.get("count_min", 1)
            stat_groups.append({"type": "count", "count_min": count_min, "stats": stats})

    trade_intent = {
        "item_type": intent.get("item_type"),
        "item_type_name": None,
        "rarity": intent.get("rarity"),
        "stat_groups": stat_groups,
        "summary": intent.get("summary", ""),
    }

    return build_trade_query(trade_intent)


def _execute_search(db, trade_query: dict, league: str) -> dict:
    """Execute a single trade search."""
    from app.services.trade_service import search_trade

    intent = {
        "item_type": None,
        "stat_groups": [],
        "summary": "",
    }
    # Reconstruct intent from trade_query for search_trade
    q = trade_query.get("query", {})
    stats = q.get("stats", [])
    filters = q.get("filters", {})

    # Extract item_type from type_filters
    type_f = filters.get("type_filters", {}).get("filters", {})
    item_type = type_f.get("category", {}).get("option")
    rarity = type_f.get("rarity", {}).get("option")

    intent["item_type"] = item_type
    intent["rarity"] = rarity
    intent["stat_groups"] = stats

    return search_trade(intent, league)


# ── Main pipeline ──

def run_agent(query: str, league: str = "Standard") -> dict:
    """Run the trade search pipeline.

    Flow:
      1. LLM parses intent → requirements
      2. Code does multi-query vector retrieval for each requirement
      3. LLM selects best stat IDs from candidates (for ambiguous reqs)
      4. Code builds and executes Trade API query
      5. If 0 results, retry with relaxed count_min
      6. Return result to user
    """
    from app.core.database import SessionLocal

    t_start = time.time()
    db = SessionLocal()

    try:
        # Step 1: Parse intent
        logger.info("Step 1: Parsing intent...")
        intent = _parse_intent(query)
        requirements = intent.get("requirements", [])
        item_type = intent.get("item_type")

        if not requirements:
            return {
                "trade_url": "",
                "total_results": 0,
                "intent_summary": "无法理解搜索意图，请描述具体的装备类型和属性要求",
                "error": "无法解析搜索意图",
            }

        # Step 2+3: Retrieve + select stats for each requirement
        all_resolved = True
        for req in requirements:
            logger.info(f"Step 2: Retrieving stats for '{req.get('raw', '?')}'...")
            candidates = _retrieve_stats(db, req)

            if not candidates:
                logger.warning(f"No stats found for '{req.get('raw', '?')}'")
                all_resolved = False
                continue

            # For count groups with many candidates, use LLM to select
            # For required (single stat) groups, just use top match
            if req.get("kind") == "count" and len(candidates) > 3:
                logger.info(f"Step 3: LLM selecting from {len(candidates)} candidates...")
                selected = _select_from_candidates(req, candidates, item_type)
            else:
                selected = candidates[:5]

            req["_selected_stats"] = selected

        if not all_resolved and not any(r.get("_selected_stats") for r in requirements):
            return {
                "trade_url": "",
                "total_results": 0,
                "intent_summary": "未找到匹配的词缀，请尝试用不同的关键词描述",
                "error": "向量搜索未找到匹配词缀",
            }

        # Step 4: Build and execute search
        logger.info("Step 4: Building and executing search...")
        trade_query = _build_search_query(intent, requirements)
        result = _execute_search(db, trade_query, league)

        if result.get("error"):
            return {
                "trade_url": "",
                "total_results": 0,
                "intent_summary": result["error"],
                "error": result["error"],
            }

        total = result.get("total_results", 0)
        url = result.get("trade_url", "")

        # Step 5: If 0 results, retry with relaxed count_min
        if total == 0:
            logger.info("Step 5: 0 results, retrying with relaxed conditions...")
            # Reduce count_min to 1 for all count groups
            for req in requirements:
                if req.get("kind") == "count":
                    req["count_min"] = 1

            trade_query = _build_search_query(intent, requirements)
            result = _execute_search(db, trade_query, league)

            if result.get("error"):
                return {
                    "trade_url": url or "",
                    "total_results": 0,
                    "intent_summary": f"未找到匹配装备。当前词缀组合可能在该装备类型上极稀有。建议：放宽 count 条件或去掉部分词缀。",
                    "error": None,
                }

            total = result.get("total_results", 0)
            url = result.get("trade_url", url)

            if total > 0:
                summary = f"放宽条件后找到 {total} 件装备（原条件过于严格，已将 count 降为 1）"
            else:
                summary = f"未找到匹配装备。这些词缀组合在该装备类型上可能不存在，建议调整搜索条件。"

            elapsed = time.time() - t_start
            logger.info(f"Pipeline complete in {elapsed:.1f}s: {total} results")
            return {
                "trade_url": url,
                "total_results": total,
                "intent_summary": summary,
                "error": None,
            }

        # Build summary
        parts = []
        for r in requirements:
            kind = r.get('kind', 'required')
            if kind == 'required':
                parts.append(f"{r.get('raw', '?')}(必须)")
            else:
                cm = r.get('count_min', 1)
                parts.append(f"{r.get('raw', '?')}(至少{cm}条)")
        req_summary = ", ".join(parts)
        summary = f"搜索 {req_summary}，找到 {total} 件装备"

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
