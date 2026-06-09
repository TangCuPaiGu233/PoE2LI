"""Trade Search Agent — multi-plan search with inspection and revision.

Architecture:
  User query
    → parse_intent: Chinese → DSL (concepts, not stat IDs)
    → resolve_concepts: dictionary lookup + vector fallback
    → build_plans: 2-3 search plans (core → broad → budget)
    → execute + inspect: run search, verify top items match
    → revise: retry with adjustments if inspection fails
    → return: best URL + alternatives + explanation
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


def _get_llm_client():
    from openai import OpenAI
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


# ── Step 1: Parse intent into DSL ──

PARSE_SYSTEM = """You convert Chinese PoE2 trade queries into a structured search intent.

Available concepts: {concept_list}

Item slot IDs:
  amulet=accessory.amulet ring=accessory.ring belt=accessory.belt
  sceptre=weapon.sceptre wand=weapon.wand staff=weapon.staff bow=weapon.bow
  spear=weapon.spear crossbow=weapon.crossbow
  onesword=weapon.onesword oneaxe=weapon.oneaxe onemace=weapon.onemace
  twosword=weapon.twosword twoaxe=weapon.twoaxe twomace=weapon.twomace
  chest=armour.chest helmet=armour.helmet gloves=armour.gloves boots=armour.boots
  shield=armour.shield quiver=armour.quiver

Output JSON:
{{
  "item_slot": "accessory.amulet",
  "must_have": [],
  "nice_to_have": [],
  "count_min": 1,
  "exclude": [],
  "sort": null,
  "sort_dir": "desc",
  "budget": null,
  "raw_summary": "short Chinese summary"
}}

CRITICAL RULES:
1. "最高/最大/最高伤害" → set sort="pdps" (NOT a stat! This is sorting, not filtering!)
   "元素伤害最高" → sort="edps"
   "最便宜/价格最低" → sort="price", sort_dir="asc"
2. "价格低于 X E/D/神" → budget={{"max": X, "currency": "exalted"/"divine"/"chaos"}}
   "价格低于 2E" → budget={{"max": 2, "currency": "exalted"}}
3. Item names (战猫, 猎首, 法血) → set item_slot to best guess, put name in raw_summary
4. must_have: stats the item MUST have. Use AND group.
5. nice_to_have: stats that are NICE to have. COUNT group with count_min.
6. "至少N条XX" → count_min=N
7. "存在/有XX" operator="exists"; "XX以上/至少XX" operator=">=" with value
8. If a user term doesn't match any concept, list it in unknown_terms"""


def _parse_intent(query: str) -> dict:
    """LLM parses Chinese query into Search Intent DSL."""
    from app.services.trade_concepts import list_all_concepts
    concepts = list_all_concepts()
    concept_list = "\n".join(f"  - {c}" for c in concepts)

    client = _get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": PARSE_SYSTEM.format(concept_list=concept_list)},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            content = m.group(0)
        parsed = json.loads(content)
        logger.info(f"Intent: slot={parsed.get('item_slot')}, "
                    f"must={len(parsed.get('must_have', []))}, "
                    f"nice={len(parsed.get('nice_to_have', []))}")
        return parsed
    except Exception as e:
        logger.error(f"Parse failed: {e}")
        return {"error": str(e)}


# ── Step 2: Resolve concepts to stat IDs ──

def _resolve_concept(db, concept_name: str, item_slot: str | None = None) -> list[dict]:
    """Resolve a concept name to candidate stat IDs.

    Resolution order:
      1. Known IDs from dictionary (direct use)
      2. Stat pattern match against full dictionary
      3. Vector search fallback
    """
    from app.services.trade_concepts import TRADE_CONCEPTS, is_concept_available, get_concept_ids
    from app.services.trade_stat_service import search_stats

    entry = TRADE_CONCEPTS.get(concept_name, {})

    # Check availability
    if item_slot and not is_concept_available(concept_name, item_slot):
        logger.info(f"Concept '{concept_name}' not available on {item_slot}, skipping")
        return []

    # Priority 1: Known IDs
    known = get_concept_ids(concept_name)
    if known:
        return [{"stat_id": sid, "ref_text": "known", "similarity": 1.0, "source": "dict"} for sid in known]

    # Priority 2: Regex match against stat dictionary
    patterns = entry.get("stat_patterns", [])
    if patterns:
        import os as _os
        dict_paths = [
            "/app/data/trade_stats_condensed.json",
            _os.path.join(_os.path.dirname(__file__), "..", "data", "trade_stats_condensed.json"),
        ]
        all_stats = {}
        for dp in dict_paths:
            if _os.path.exists(dp):
                with open(dp, "r") as f:
                    all_stats = json.load(f)
                break
        matches = []
        for sid, text in all_stats.items():
            if not sid.startswith("explicit."):
                continue
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    matches.append({"stat_id": sid, "ref_text": text, "similarity": 0.95, "source": "regex"})
                    break
        if matches:
            return matches[:10]

    # Priority 3: Vector search
    aliases = entry.get("aliases", [concept_name])
    query = " ".join(aliases[:3])
    results = search_stats(db, query, top_k=10, stat_type="explicit", min_similarity=0.35)
    if results:
        for r in results:
            r["source"] = "vector"
        return results

    return []


def _resolve_all_concepts(db, intent: dict) -> dict:
    """Resolve all concepts in the intent to stat IDs.

    Returns: dict with resolved must_have_stats, nice_to_have_stats
    """
    item_slot = intent.get("item_slot")

    must_have_stats = []
    for req in intent.get("must_have", []):
        concept = req.get("concept", "")
        if not concept:
            continue
        candidates = _resolve_concept(db, concept, item_slot)
        if candidates:
            # For must_have, take only the first (best) match
            best = candidates[0]
            stat_entry = {"id": best["stat_id"], "source": best.get("source", "?")}
            val = req.get("value")
            if val is not None and req.get("operator") in (">=", "="):
                stat_entry["min"] = val
            must_have_stats.append(stat_entry)
            logger.info(f"  must_have '{concept}' → {best['stat_id']} ({best.get('source', '?')})")
        else:
            logger.warning(f"  must_have '{concept}' → NO MATCH FOUND")

    nice_to_have_stats = []
    for req in intent.get("nice_to_have", []):
        concept = req.get("concept", "")
        if not concept:
            continue
        candidates = _resolve_concept(db, concept, item_slot)
        for c in candidates[:3]:  # take top 3 per concept
            nice_to_have_stats.append({
                "id": c["stat_id"],
                "source": c.get("source", "?"),
                "concept": concept,
            })

    return {
        "must_have": must_have_stats,
        "nice_to_have": nice_to_have_stats,
        "count_min": intent.get("count_min", 1),
    }


# ── Step 3: Build search plans ──

def _build_plans(resolved: dict, item_slot: str | None) -> list[dict]:
    """Generate 2-3 search plans from narrow to broad.

    Plan 1 (core): must_have only (AND group)
    Plan 2 (full): must_have (AND) + nice_to_have (COUNT, original count_min)
    Plan 3 (relaxed): must_have (AND) + nice_to_have (COUNT, count_min=1)
    """
    must = resolved.get("must_have", [])
    nice = resolved.get("nice_to_have", [])
    count_min = resolved.get("count_min", 1)

    plans = []

    # If no stat filters at all, create minimal plan (just item_type + sort/budget)
    if not must and not nice:
        return [{
            "name": "core",
            "stat_groups": [{"type": "and", "filters": []}],
            "count_min": 0,
        }]

    # Plan 1: Core only
    if must:
        plans.append({
            "name": "core",
            "stat_groups": [{"type": "and", "stats": list(must)}],
            "count_min": 0,
        })

    # Plan 2: Full (AND + COUNT)
    if must and nice:
        plans.append({
            "name": "full",
            "stat_groups": [
                {"type": "and", "stats": list(must)},
                {"type": "count", "count_min": count_min, "stats": list(nice)},
            ],
            "count_min": count_min,
        })
    elif nice:
        plans.append({
            "name": "full",
            "stat_groups": [
                {"type": "count", "count_min": count_min, "stats": list(nice)},
            ],
            "count_min": count_min,
        })

    # Plan 3: Relaxed (count_min=1)
    if must and nice and count_min > 1:
        plans.append({
            "name": "relaxed",
            "stat_groups": [
                {"type": "and", "stats": list(must)},
                {"type": "count", "count_min": 1, "stats": list(nice)},
            ],
            "count_min": 1,
        })

    logger.info(f"Generated {len(plans)} search plans: {[p['name'] for p in plans]}")
    return plans


# ── Step 4: Execute search ──

def _execute_plan(plan: dict, item_slot: str | None, league: str,
                  sort: str | None = None, sort_dir: str = "desc",
                  budget: dict | None = None) -> dict:
    """Execute a single search plan against the Trade API."""
    from app.services.trade_service import search_trade

    intent = {
        "item_type": item_slot,
        "stat_groups": plan["stat_groups"],
        "summary": "",
    }

    # Apply price filter
    if budget:
        intent["price"] = {
            "currency": budget.get("currency", "chaos"),
            "max": budget.get("max"),
        }

    # Apply weapon DPS filter
    if sort in ("pdps", "edps"):
        if sort == "pdps":
            intent["weapon"] = {"pdps": {"min": 1}}
        else:
            intent["weapon"] = {"edps": {"min": 1}}

    result = search_trade(intent, league)
    return {
        "plan_name": plan["name"],
        "total": result.get("total_results", 0),
        "url": result.get("trade_url", ""),
        "error": result.get("error"),
        "count_min": plan.get("count_min", 0),
    }


# ── Step 5: Inspect results ──

def _inspect_results(url: str, intent: dict, count: int = 3) -> dict:
    """Fetch top N items from a search and verify they match the intent."""
    import cloudscraper

    # Extract search_id from URL
    search_id = url.split("/")[-1] if url else ""
    if not search_id:
        return {"passed": False, "reason": "no search_id"}

    league = intent.get("league", "Standard")
    item_slot = intent.get("item_slot")
    must_have_concepts = [r.get("concept") for r in intent.get("must_have", [])]

    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )

        # Get item IDs from search
        search_url = f"https://www.pathofexile.com/api/trade2/search/{league}/{search_id}"
        resp = scraper.get(search_url, timeout=15)
        if resp.status_code != 200:
            return {"passed": False, "reason": f"search fetch failed: HTTP {resp.status_code}"}
        item_ids = resp.json().get("result", [])[:count]
        if not item_ids:
            return {"passed": False, "reason": "no items in result"}

        # Fetch item details
        fetch_url = f"https://www.pathofexile.com/api/trade2/fetch/{','.join(item_ids)}?query={search_id}"
        resp2 = scraper.get(fetch_url, timeout=15)
        if resp2.status_code != 200:
            return {"passed": False, "reason": f"item fetch failed: HTTP {resp2.status_code}"}

        items = resp2.json().get("result", [])

        # Check each item
        checks = []
        for item in items:
            mods = [m.lower() for m in item.get("explicitMods", [])]
            mods_text = " ".join(mods)

            # Check item type
            item_type_line = item.get("typeLine", "").lower()
            slot_ok = True
            if item_slot == "accessory.amulet" and "amulet" not in item_type_line:
                slot_ok = False

            # Check must_have concepts
            must_ok = True
            for concept in must_have_concepts:
                if not _concept_in_mods(concept, mods_text):
                    must_ok = False
                    break

            checks.append({
                "name": item.get("name", "?"),
                "type": item_type_line,
                "slot_ok": slot_ok,
                "must_ok": must_ok,
                "mod_count": len(mods),
            })

        passed = all(c["must_ok"] and c["slot_ok"] for c in checks) if checks else False
        logger.info(f"Inspection: {len(checks)} items, passed={passed}, "
                    f"must_ok={sum(c['must_ok'] for c in checks)}/{len(checks)}")
        return {
            "passed": passed,
            "checks": checks,
            "reason": "all items match" if passed else f"{sum(not c['must_ok'] for c in checks)} items missing must_have mods",
        }

    except Exception as e:
        logger.warning(f"Inspection error: {e}")
        return {"passed": False, "reason": str(e)}


def _concept_in_mods(concept_name: str, mods_text: str) -> bool:
    """Check if a concept's known patterns appear in item mods."""
    from app.services.trade_concepts import TRADE_CONCEPTS

    entry = TRADE_CONCEPTS.get(concept_name, {})
    for pat in entry.get("stat_patterns", []):
        # Simplify pattern for matching: remove regex anchors and quantifiers
        simple = pat.replace(r"#", "").replace(r"+", "").replace(r"\%", "%").replace("\\", "")
        # Extract key words
        words = re.findall(r'[a-zA-Z]+', simple)
        if len(words) >= 2 and all(w.lower() in mods_text for w in words):
            return True
    return False


# ── Agent loop ──

def run_agent(query: str, league: str = "Standard") -> dict:
    """Run the Trade Search Agent.

    Flow:
      1. Parse intent (LLM → DSL)
      2. Resolve concepts (dict + vector)
      3. Build plans (2-3 tiers)
      4. Execute core plan → inspect → if fails, try next plan
      5. Return best results + explanation
    """
    from app.core.database import SessionLocal

    t_start = time.time()
    db = SessionLocal()

    try:
        # Step 1: Parse intent
        logger.info("=== Step 1: Parse intent ===")
        intent = _parse_intent(query)
        if "error" in intent:
            return {
                "best_match": None,
                "alternatives": [],
                "explanation": f"无法理解搜索意图: {intent['error']}",
                "need_user_input": True,
            }

        item_slot = intent.get("item_slot")
        sort = intent.get("sort")
        sort_dir = intent.get("sort_dir", "desc")
        budget = intent.get("budget")
        raw_summary = intent.get("raw_summary", query)

        # Step 2: Resolve concepts to stat IDs (or handle sort-only searches)
        logger.info("=== Step 2: Resolve concepts ===")
        resolved = _resolve_all_concepts(db, intent)

        # Allow sort/budget-only searches (no stat filters needed)
        if not resolved["must_have"] and not resolved["nice_to_have"]:
            if not item_slot:
                return {
                    "best_match": None,
                    "alternatives": [],
                    "explanation": "请指定装备类型（如'矛'、'权杖'、'项链'）",
                    "need_user_input": True,
                }
            resolved["must_have"] = []  # empty = just sort/budget on item type

        # Step 3: Build plans
        logger.info("=== Step 3: Build plans ===")
        plans = _build_plans(resolved, item_slot)

        # Step 4-5: Execute plans + inspect
        logger.info("=== Step 4: Execute + Inspect ===")
        results = []
        for plan in plans:
            result = _execute_plan(plan, item_slot, league, sort, sort_dir, budget)
            logger.info(f"  Plan '{plan['name']}': {result['total']} results")

            inspection = None
            if result["total"] > 0 and result["url"]:
                inspection = _inspect_results(result["url"], intent, count=3)

            results.append({
                "plan": plan["name"],
                "result": result,
                "inspection": inspection,
                "stats": {
                    "must_have_count": len(resolved["must_have"]),
                    "nice_to_have_count": len(resolved["nice_to_have"]),
                    "count_min": plan.get("count_min", 0),
                },
            })

            # If this plan passed inspection, we can stop
            if inspection and inspection.get("passed"):
                logger.info(f"  Plan '{plan['name']}' passed inspection, stopping")
                break

        # Step 6: Build response
        logger.info("=== Step 6: Build response ===")
        best = results[0] if results else None
        alternatives = results[1:] if len(results) > 1 else []

        # Find the best plan with results > 0
        best_with_results = None
        for r in results:
            if r["result"]["total"] > 0:
                best_with_results = r
                break

        response = {
            "best_match": {
                "label": f"{best['plan']}版",
                "url": best["result"]["url"],
                "count": best["result"]["total"],
                "reason": raw_summary,
            } if best_with_results else None,
            "alternatives": [
                {
                    "label": f"{a['plan']}版",
                    "url": a["result"]["url"],
                    "count": a["result"]["total"],
                    "reason": f"放宽条件版 (count_min={a['stats']['count_min']})",
                }
                for a in alternatives if a["result"]["total"] > 0 and a["result"]["url"]
            ],
            "explanation": _build_explanation(results, resolved, raw_summary),
            "need_user_input": False,
        }

        elapsed = time.time() - t_start
        logger.info(f"Agent complete in {elapsed:.1f}s: "
                    f"best={best_with_results['result']['total'] if best_with_results else 0} results")
        return response

    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        return {
            "best_match": None,
            "alternatives": [],
            "explanation": f"搜索出错: {str(e)[:100]}",
            "need_user_input": False,
        }
    finally:
        db.close()


def _build_explanation(results: list, resolved: dict, raw_summary: str) -> str:
    """Build a human-readable explanation of the search results."""
    parts = [raw_summary]

    if not results:
        return raw_summary

    best = results[0]
    total = best["result"]["total"]
    inspection = best.get("inspection", {})

    if total == 0:
        parts.append("未找到匹配装备。")
        parts.append(f"核心条件: {resolved['must_have']} 条词缀")
        parts.append(f"辅助条件: {resolved['nice_to_have']} 条候选词缀")
        parts.append("建议: 放宽条件或去掉部分词缀重试")
    elif total < 10:
        parts.append(f"仅找到 {total} 件，条件较严格。")
        if inspection and inspection.get("passed"):
            parts.append("已验证结果包含所需词缀。")
    else:
        parts.append(f"找到 {total} 件装备。")
        if inspection and inspection.get("passed"):
            parts.append("已验证前几件装备符合条件。")

    # Mention alternatives
    alt_results = [r for r in results[1:] if r["result"]["total"] > 0]
    if alt_results:
        parts.append(f"另有 {len(alt_results)} 个放宽条件的备选方案。")

    return " | ".join(parts)
