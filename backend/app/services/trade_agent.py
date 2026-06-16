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
import time
from typing import Any

from app.core.llm_config import LLM_MODEL, llm_message_text
from app.core.llm_client import get_llm_client

logger = logging.getLogger(__name__)


def _get_llm_client():
    return get_llm_client()


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
  jewel=jewel (珠宝/宝石/蓝玉/日象之饰等)

Output JSON:
{{
  "item_slot": "jewel",
  "must_have": [{{"concept": "chaos_damage", "operator": ">=", "value": null}}],
  "nice_to_have": [{{"concept": "minion_damage", "operator": "exists"}}],
  "count_min": 1,
  "exclude": [],
  "sort": null,
  "sort_dir": "desc",
  "budget": null,
  "raw_summary": "short Chinese summary"
}}

must_have / nice_to_have entries MUST use concept names from the list above (English snake_case keys).

CRITICAL RULES:
1. "最高/最大/最高伤害" → set sort="pdps" (NOT a stat! This is sorting, not filtering!)
   "元素伤害最高" → sort="edps"
   "最便宜/价格最低" → sort="price", sort_dir="asc"
2. "价格低于 X E/D/神" → budget={{"max": X, "currency": "exalted"/"divine"/"chaos"}}
   "价格低于 2E" → budget={{"max": 2, "currency": "exalted"}}
3. item_slot MUST use full Trade category IDs (e.g. accessory.amulet, NOT amulet); unique/item names go in raw_summary
4. must_have: stats the item MUST have. Use AND group.
5. nice_to_have: stats that are NICE to have. COUNT group with count_min.
6. "至少N条XX" → count_min=N
7. "存在/有XX" operator="exists"; "XX以上/至少XX" operator=">=" with value
8. If a user term doesn't match any concept, list it in unknown_terms
9. Output JSON only — no markdown fences, no reasoning text outside the JSON object
10. **物等/物品等级/ilvl**：仅当用户明确要求（如「物等81以上」「至少80物等」）时才写入 must_have 或 item_level；截图/描述里出现的等级数字默认**不要**作为搜索条件
11. **召唤物词缀**：query 含「召唤/召唤物/召唤生物/minion」+ 暴击伤害 → 必须用 `minion_critical_damage`，禁止用 `critical_damage_bonus`（后者是角色暴击，不是召唤物）
12. **暗金/唯一物品**（人格分裂、猎首、法血等）：must_have/nice_to_have 留空，把名称写入 raw_summary；不要当成稀有蓝玉/红玉去搜词缀
"""


_ILVL_USER_ASKS = re.compile(
    r"(?:物等|物品等级|ilvl)\s*(?:至少|不低于|以上|大于|>=|≥|要|得|需要)?\s*\d+"
    r"|\d+\s*(?:以上)?\s*(?:物等|物品等级)",
    re.I,
)


def sanitize_trade_query(query: str, user_msg: str = "") -> str:
    """Drop ilvl from trade query unless the user explicitly asked for it."""
    if _ILVL_USER_ASKS.search(user_msg or ""):
        return re.sub(r"\s+", " ", (query or "").strip())
    q = query or ""
    for pat in (
        r"物品等级\s*\d+\+?",
        r"物等\s*\d+\+?",
        r"\bilvl\s*\d+\+?",
    ):
        q = re.sub(pat, "", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip()


def _apply_ilvl_policy(intent: dict, user_msg: str, query: str) -> dict:
    if _ILVL_USER_ASKS.search(user_msg or ""):
        return intent
    for key in ("must_have", "nice_to_have"):
        intent[key] = [
            r for r in intent.get(key, [])
            if (r.get("concept") or "") != "item_level"
        ]
    intent.pop("item_level", None)
    return intent


def _currency_cn(currency: str) -> str:
    return {
        "chaos": "混沌石",
        "divine": "神圣石",
        "exalted": "崇高石",
        "exalt": "崇高石",
        "alch": "点金石",
        "alchemy": "点金石",
        "mirror": "镜子",
    }.get((currency or "").lower(), currency or "?")


def _listing_matches_variant(listing, variant_hint):
    if not variant_hint:
        return True
    vl=(listing.get(chr(118)+chr(97)+chr(114)+chr(105)+chr(97)+chr(110)+chr(116)+chr(95)+chr(108)+chr(97)+chr(98)+chr(101)+chr(108)) or chr(32)).strip()
    if vl==variant_hint:
        return True
    core=variant_hint.replace(chr(36215)+chr(28857), chr(32)).strip()
    if not core:
        return False
    if core in vl:
        return True
    blob=chr(32).join(listing.get(chr(101)+chr(120)+chr(112)+chr(108)+chr(105)+chr(99)+chr(105)+chr(116)+chr(95)+chr(109)+chr(111)+chr(100)+chr(115)) or [])
    return core in blob

def _attach_market_price(
    response: dict,
    *,
    url: str | None,
    total: int,
    market: str,
    league: str,
    item_ids: list | None = None,
    detail_count: int = 1,
    variant_hint=None,
) -> dict:
    """Attach listing details from Trade API; forbid LLM from guessing."""
    detail_count = max(1, min(int(detail_count or 1), 10))
    fetch_count = max(detail_count, 10) if variant_hint else detail_count
    if not url or total <= 0:
        response["listing_price"] = None
        response["listings"] = []
        response["price_note"] = "市集无符合当前搜索条件的在售物品，无法给出真实市价。"
        return response
    from app.services.trade_service import fetch_trade_listings

    fetched = fetch_trade_listings(
        url,
        market=market,
        league=league,
        item_ids=item_ids,
        count=fetch_count,
        skip_rate_limit=True,
    )
    listings = fetched.get("listings") or []
    response["listings"] = listings
    response["listings_fetched"] = len(listings)

    if not listings:
        response["listing_price"] = None
        err = fetched.get("error") or "无法读取 listing"
        if total > 0 and err == "no listings":
            response["price_note"] = (
                f"搜索到 {total} 条在售，但无法读取 listing 详情，请直接打开市集链接查看"
            )
        else:
            response["price_note"] = err
        return response

    cheapest = None
    if variant_hint:
        for listing in listings:
            price = listing.get("price") or {}
            if price.get("amount") is None or not price.get("currency"):
                continue
            if _listing_matches_variant(listing, variant_hint):
                cheapest = listing
                break
    if cheapest is None:
        for listing in listings:
            price = listing.get("price") or {}
            if price.get("amount") is not None and price.get("currency"):
                cheapest = listing
                break

    if cheapest:
        price = cheapest["price"]
        explicit_mods = cheapest.get("explicit_mods") or []
        variant_label = cheapest.get("variant_label")
        response["listing_price"] = {
            "amount": price["amount"],
            "currency": price["currency"],
            "item_name": cheapest.get("display_name") or "",
            "display": price.get("display") or f"{price['amount']} {_currency_cn(price['currency'])}",
            "explicit_mods": explicit_mods,
            "implicit_mods": cheapest.get("implicit_mods") or [],
            "variant_label": variant_label,
            "properties": cheapest.get("properties") or [],
            "requirements": cheapest.get("requirements") or [],
        }
        note = (
            f"已返回前 {len(listings)} 条在售详情（共 {total} 条匹配）；"
            "listing_price 为其中首个有标价的条目"
        )
        if detail_count == 1:
            note = "以下为市集在售最低价样本（按当前搜索排序）"
        if explicit_mods:
            note += "；描述装备属性须基于 listings[] / listing_price，禁止从百科猜测"
        if variant_label:
            note += f"；该件变体：{variant_label}"
        response["price_note"] = note
    else:
        response["listing_price"] = None
        response["price_note"] = (
            f"搜索到 {total} 条在售，已返回 {len(listings)} 条物品详情，但未读到标价"
        )
    return response


def _normalize_stat_reqs(items: list) -> list[dict]:
    """Coerce LLM must_have/nice_to_have entries to {concept, operator, value}."""
    from app.services.trade_concepts import find_concept

    out: list[dict] = []
    for req in items or []:
        if isinstance(req, str):
            term = req.strip()
            if not term:
                continue
            canonical, _ = find_concept(term)
            out.append({"concept": canonical or term, "operator": "exists", "value": None})
        elif isinstance(req, dict):
            concept = req.get("concept") or req.get("name") or ""
            if isinstance(concept, str) and concept.strip():
                canonical, _ = find_concept(concept.strip())
                req = dict(req)
                req["concept"] = canonical or concept.strip()
                out.append(req)
    return out


_MINION_CTX = re.compile(r"召唤|minion|Minion|仆从|魔卫|图腾兽", re.I)




def _normalize_intent_slots_and_concepts(intent: dict, query: str) -> dict:
    from app.services.trade_service import normalize_trade_item_slot

    slot = intent.get("item_slot")
    if slot:
        intent["item_slot"] = normalize_trade_item_slot(slot)
    if _MINION_CTX.search(query or ""):
        for key in ("must_have", "nice_to_have"):
            for req in intent.get(key, []) or []:
                if req.get("concept") == "all_skill_level":
                    req["concept"] = "minion_skill_level"
    return intent

def _remap_concepts_from_query(intent: dict, query: str) -> dict:
    """Fix LLM mis-labeling minion mods as player crit."""
    if not _MINION_CTX.search(query or ""):
        return intent
    for key in ("must_have", "nice_to_have"):
        for req in intent.get(key, []) or []:
            if req.get("concept") == "critical_damage_bonus":
                req["concept"] = "minion_critical_damage"
    return intent


def _try_unique_trade(
    query: str,
    league: str,
    market: str,
    user_msg: str = "",
    detail_count: int = 1,
) -> dict | None:
    """Fast-path: recognized unique name -> search by name, skip rare+mod parse."""
    from app.services.trade_service import resolve_trade_unique_name, search_unique_by_name

    resolved = resolve_trade_unique_name(query)
    if not resolved or not resolved.get("unique_name"):
        return None

    # Rare jewel mod search on a base type — don't hijack when unique is incidental
    if re.search(r"日象之饰|蓝玉|钴蓝|Cobalt", query, re.I):
        matched = resolved.get("matched") or ""
        if matched and matched not in query[: max(len(matched) + 2, 8)]:
            return None

    from app.services.chat_item_profile import extract_class_variant_hint
    from app.services.trade_stats_index import class_start_stat_id

    user_variant = extract_class_variant_hint(query + chr(10) + user_msg)
    stat_id = class_start_stat_id(user_variant) if user_variant else None
    label = resolved.get("trade_name_cn") or resolved.get("unique_name") or query
    result = search_unique_by_name(
        resolved.get("matched") or query,
        market=market,
        league=league,
        required_stat_ids=[stat_id] if stat_id else None,
    )
    if result.get("error"):
        logger.warning("Unique fast-path failed: %s", result.get("error"))
        return None
    url = result.get("trade_url")
    if not url:
        return None

    total = int(result.get("total_results") or 0)
    link = {
        "url": url,
        "total": total,
        "label": f"暗金·{label}",
        "degraded": False,
        "note": f"按暗金「{label}」搜索",
    }
    logger.info("Unique fast-path: %s → %d results", resolved.get("unique_name"), total)
    eff_detail = max(detail_count, 10) if user_variant else detail_count
    resp = _response_from_link(
        link,
        explanation=link["note"],
        market=market,
        league=league,
        item_ids=result.get("item_ids"),
        detail_count=eff_detail,
        variant_hint=user_variant,
    )
    if user_variant:
        resp["user_variant_hint"] = user_variant
    return resp


def _extract_json_object(text: str) -> str:
    text = re.sub(r"^```\w*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def _parse_intent(query: str, user_msg: str = "") -> dict:
    """LLM parses Chinese query into Search Intent DSL."""
    query = sanitize_trade_query(query, user_msg)
    from app.services.trade_concepts import list_all_concepts
    concepts = list_all_concepts()
    concept_list = "\n".join(f"  - {c}" for c in concepts)

    client = _get_llm_client()
    messages = [
        {"role": "system", "content": PARSE_SYSTEM.format(concept_list=concept_list)},
        {"role": "user", "content": query},
    ]
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        content = ""
        if resp.choices:
            content = llm_message_text(resp.choices[0].message)
        if not content:
            logger.error("Parse failed: empty LLM response for query=%s", query[:80])
            return {"error": "empty_llm_response"}
        parsed = json.loads(_extract_json_object(content))
        parsed["must_have"] = _normalize_stat_reqs(parsed.get("must_have"))
        parsed["nice_to_have"] = _normalize_stat_reqs(parsed.get("nice_to_have"))
        parsed = _remap_concepts_from_query(parsed, query)
        parsed = _apply_ilvl_policy(parsed, user_msg, query)
        parsed = _normalize_intent_slots_and_concepts(parsed, query)
        logger.info(
            "Intent: slot=%s, must=%s, nice=%s",
            parsed.get("item_slot"),
            len(parsed.get("must_have", [])),
            len(parsed.get("nice_to_have", [])),
        )
        return parsed
    except Exception as e:
        logger.error("Parse failed: %s", e)
        return {"error": str(e)}


# ── Step 2: Resolve concepts to stat IDs ──



def _direct_stats_from_query(query: str) -> list[dict]:
    from app.services.trade_stats_index import (
        _normalize_stat_search_query,
        resolve_stat_query_exact,
        stat_id_to_cn,
    )

    q = _normalize_stat_search_query((query or "").strip())
    if not q:
        return []
    found: list[dict] = []
    seen: set[str] = set()

    for chunk in re.split(r"[、,;；\n]+", q):
        chunk = chunk.strip()
        if len(chunk) < 2:
            continue
        sid = resolve_stat_query_exact(chunk, apply_slang=False)
        if sid and sid not in seen and len(found) < 6:
            seen.add(sid)
            found.append({"id": sid, "source": "chunk_exact", "label_cn": stat_id_to_cn(sid) or chunk})
    return found


def _resolve_concept(db, concept_name: str, item_slot: str | None = None) -> list[dict]:
    """Resolve a concept name to candidate stat IDs.

    Resolution order:
      1. Known IDs from dictionary (direct use)
      2. Stat pattern match against full dictionary
      3. Vector search fallback
    """
    from app.services.trade_concepts import (
        TRADE_CONCEPTS,
        find_concept,
        is_concept_available,
        get_concept_ids,
    )
    from app.services.trade_stat_service import search_stats

    canonical, entry = find_concept(concept_name)
    if canonical:
        concept_name = canonical
    else:
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
            return _filter_concept_candidates(concept_name, matches[:10])

    # Priority 3: Vector search
    aliases = entry.get("aliases", [concept_name])
    query = " ".join(aliases[:3])
    results = search_stats(db, query, top_k=10, stat_type="explicit", min_similarity=0.35)
    if results:
        for r in results:
            r["source"] = "vector"
        filtered = _filter_concept_candidates(concept_name, results)
        if filtered:
            return filtered

    return []


def _filter_concept_candidates(concept_name: str, candidates: list[dict]) -> list[dict]:
    """Drop vector false-positives (e.g. minion crit → bleeding on hit)."""
    if concept_name.startswith("minion_"):
        kept = [
            c for c in candidates
            if "minion" in (c.get("ref_text") or "").lower()
        ]
        if kept:
            return kept
    return candidates


def _resolve_all_concepts(db, intent: dict, query: str = "") -> dict:
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
            op = (req.get("operator") or "exists").lower()
            val = req.get("value")
            # min=1 on exists-style mods breaks CN trade filters → treat as exists-only
            if val is not None and op in (">=", "=") and isinstance(val, (int, float)) and val > 1:
                stat_entry["min"] = val
            must_have_stats.append(stat_entry)
            logger.info(f"  must_have '{concept}' → {best['stat_id']} ({best.get('source', '?')})")
        else:
            logger.warning(f"  must_have '{concept}' → NO MATCH FOUND")


    direct = _direct_stats_from_query(query)
    existing_ids = {s.get("id") for s in must_have_stats if s.get("id")}
    for d in direct:
        sid = d.get("id")
        if sid and sid not in existing_ids:
            must_have_stats.append({"id": sid, "source": "direct_cn"})
            existing_ids.add(sid)
            logger.info("  direct_cn '%s' -> %s", d.get("label_cn"), sid)

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
            "stat_groups": [{"type": "and", "stats": []}],
            "count_min": 0,
        }]

    # Plan 1: Core only
    if must:
        plans.append({
            "name": "core",
            "stat_groups": [{"type": "and", "stats": list(must)}],
            "count_min": 0,
        })
        # When many must-have mods, add COUNT fallback (partial match)
        if len(must) >= 2 and not nice:
            plans.append({
                "name": "relaxed",
                "stat_groups": [{
                    "type": "count",
                    "count_min": max(1, len(must) - 1),
                    "stats": list(must),
                }],
                "count_min": max(1, len(must) - 1),
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


def _plan_specificity(stats: dict) -> int:
    return stats.get("must_have_count", 0) * 10 + stats.get("nice_to_have_count", 0)


def _plan_display_label(plan_name: str, stats: dict) -> str:
    """Human-readable plan title."""
    must_n = stats.get("must_have_count", 0)
    nice_n = stats.get("nice_to_have_count", 0)
    count_min = stats.get("count_min", 0)
    if plan_name == "core":
        if must_n:
            return f"全部 {must_n} 条词缀"
        return "基础筛选"
    if plan_name == "full":
        if must_n and nice_n:
            return f"{must_n} 必选 + {nice_n} 条至少 {count_min or 1}"
        if nice_n:
            return f"{nice_n} 条词缀至少 {count_min or 1}"
    if plan_name == "relaxed":
        return "放宽词缀（至少 1 条）"
    if plan_name == "fallback":
        return "参考搜索"
    return "市集搜索"


def _format_plan_match(
    plan_name: str,
    url: str,
    total: int,
    stats: dict,
    *,
    degraded: bool = False,
) -> dict:
    return {
        "label": _plan_display_label(plan_name, stats),
        "url": url,
        "count": total,
        "degraded": degraded or total == 0,
        "empty": total == 0,
        "broad": total >= 5000 and _plan_specificity(stats) == 0,
    }


def _pick_best_plan(results: list) -> dict | None:
    """Prefer the most specific search URL; tie-break by having listings."""
    candidates = [
        r for r in results
        if r["result"].get("url") and not r["result"].get("error")
    ]
    if not candidates:
        return results[0] if results else None

    def rank(r: dict) -> tuple:
        spec = _plan_specificity(r.get("stats", {}))
        total = r["result"].get("total", 0)
        has_listings = 1 if 0 < total < 5000 else 0
        narrow_total = total if total < 5000 else 0
        return (spec, has_listings, narrow_total)

    return max(candidates, key=rank)


def _build_trade_matches(results: list, best_plan: dict) -> tuple[dict, list[dict]]:
    """Primary link + alternatives that have listings (skip 0-hit duplicates)."""
    total = best_plan["result"]["total"]
    primary = _format_plan_match(
        best_plan["plan"],
        best_plan["result"]["url"],
        total,
        best_plan.get("stats", {}),
        degraded=total == 0,
    )
    alts: list[dict] = []
    for r in results:
        if r is best_plan:
            continue
        if not r["result"].get("url") or r["result"].get("error"):
            continue
        alt_total = r["result"].get("total", 0)
        if alt_total <= 0:
            continue
        alts.append(
            _format_plan_match(
                r["plan"],
                r["result"]["url"],
                alt_total,
                r.get("stats", {}),
            )
        )
    alts.sort(key=lambda x: -x["count"])
    return primary, alts[:2]


# ── Step 4: Execute search ──

def _execute_plan(plan: dict, item_slot: str | None, league: str,
                  market: str = "cn",
                  sort: str | None = None, sort_dir: str = "desc",
                  budget: dict | None = None,
                  base_type: str | None = None,
                  rarity: str | None = None) -> dict:
    """Execute a single search plan against the Trade API."""
    from app.services.trade_service import search_trade

    intent = _search_intent(
        item_slot,
        plan["stat_groups"],
        base_type=base_type,
        rarity=rarity,
        budget=budget,
        sort=sort,
    )

    result = search_trade(intent, league, market)
    return {
        "plan_name": plan["name"],
        "total": result.get("total_results", 0),
        "url": result.get("trade_url", ""),
        "error": result.get("error"),
        "rate_limited": bool(result.get("rate_limited")),
        "item_ids": result.get("item_ids"),
        "count_min": plan.get("count_min", 0),
    }


# ── Step 5: Inspect results ──

def _inspect_results(url: str, intent: dict, market: str = "cn", league: str | None = None, count: int = 3) -> dict:
    """Fetch top N items from a search and verify they match the intent."""
    from app.services.trade_realm import search_result_api_url, fetch_api_url, resolve_league
    from app.services.trade_service import _get_scraper

    # Extract search_id from URL
    search_id = url.split("/")[-1] if url else ""
    if not search_id:
        return {"passed": False, "reason": "no search_id"}

    resolved_league = resolve_league(market, league)
    item_slot = intent.get("item_slot")
    must_have_concepts = [r.get("concept") for r in intent.get("must_have", [])]

    try:
        scraper = _get_scraper(market)

        # Get item IDs from search
        search_url = search_result_api_url(market, resolved_league, search_id)
        resp = scraper.get(search_url, timeout=15)
        if resp.status_code != 200:
            return {"passed": False, "reason": f"search fetch failed: HTTP {resp.status_code}"}
        item_ids = resp.json().get("result", [])[:count]
        if not item_ids:
            return {"passed": False, "reason": "no items in result"}

        # Fetch item details
        fetch_url = fetch_api_url(market, item_ids, search_id)
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


# ── Fallback: always return a usable trade link ──

_MOD_SKIP_TERMS = frozenset({
    "珠宝", "宝石", "蓝玉", "召唤", "混沌", "冰霜", "闪电", "火焰", "物理",
    "穿透", "伤害", "暴击", "攻速", "施法", "生物", "提高", "加成", "抗性",
    "物品等级", "稀有", "魔法", "传奇", "暗金", "装备", "武器", "护甲",
    "项链", "戒指", "腰带", "手套", "鞋子", "头盔", "胸甲", "市集", "价格",
})


def _infer_item_slot(query: str) -> str | None:
    """Heuristic item slot from Chinese query text."""
    from app.services.trade_service import ITEM_TYPES_ZH

    for zh in sorted(ITEM_TYPES_ZH.keys(), key=len, reverse=True):
        if zh in query:
            return ITEM_TYPES_ZH[zh][0]
    if any(k in query for k in ("蓝玉", "日象", "珠宝", "宝石", "jewel", "Jewel")):
        return "jewel"
    return None


def _infer_base_type(query: str, item_slot: str | None, market: str = "cn") -> str | None:
    """Infer Trade API base type from query (all slots, via official trade index)."""
    from app.services.trade_items_index import infer_base_type_label

    hit = infer_base_type_label(query, market=market)
    if hit:
        return hit

    if item_slot != "jewel" and "jewel" not in (item_slot or ""):
        return None

    from app.services.pob_rare_trade import resolve_base_type_cn

    cn_bases = (
        ("蓝玉", "蓝玉", "Cobalt Jewel"),
        ("红玉", "红玉", "Ruby"),
        ("绿玉", "绿玉", "Emerald"),
        ("宝钻", "宝钻", "Diamond"),
    )
    for token, cn, en in cn_bases:
        if token in query:
            return cn if market == "cn" else (resolve_base_type_cn(en) or en)
    return None


def _search_intent(
    item_slot: str | None,
    stat_groups: list,
    *,
    base_type: str | None = None,
    rarity: str | None = None,
    budget: dict | None = None,
    sort: str | None = None,
) -> dict:
    intent: dict = {
        "item_type": item_slot,
        "stat_groups": stat_groups,
        "summary": "",
    }
    if base_type:
        intent["base_type"] = base_type
    if rarity:
        intent["rarity"] = rarity
    if budget:
        intent["price"] = {
            "currency": budget.get("currency", "chaos"),
            "max": budget.get("max"),
        }
    if sort in ("pdps", "edps"):
        if sort == "pdps":
            intent["weapon"] = {"pdps": {"min": 1}}
        else:
            intent["weapon"] = {"edps": {"min": 1}}
    return intent


def _candidate_unique_labels(query: str) -> list[str]:
    """Extract possible unique item names from a free-text query."""
    labels: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"[\u4e00-\u9fff]{2,10}", query):
        term = m.group().strip()
        if term in _MOD_SKIP_TERMS or term in seen:
            continue
        seen.add(term)
        labels.append(term)
    return labels[:5]


def _fallback_trade_link(
    query: str,
    league: str,
    market: str = "cn",
    reason: str = "",
    *,
    resolved: dict | None = None,
    item_slot: str | None = None,
    base_type: str | None = None,
) -> dict:
    """Best-effort trade URL — always POST a real search (never bare market home)."""
    from app.services.trade_service import search_trade, search_unique_by_name

    note = reason or "已降级为参考链接"
    slot = item_slot or _infer_item_slot(query)
    base = base_type or _infer_base_type(query, slot, market)

    if resolved and slot and (resolved.get("must_have") or resolved.get("nice_to_have")):
        for plan in _build_plans(resolved, slot):
            intent = _search_intent(
                slot,
                plan["stat_groups"],
                base_type=base,
                rarity="rare" if slot == "jewel" else None,
            )
            result = search_trade(intent, league, market)
            url = result.get("trade_url")
            if url:
                return {
                    "url": url,
                    "total": result.get("total_results", 0),
                    "label": f"{_plan_display_label(plan['name'], {'must_have_count': len(resolved.get('must_have', [])), 'nice_to_have_count': len(resolved.get('nice_to_have', [])), 'count_min': plan.get('count_min', 0)})}（降级）",
                    "degraded": True,
                    "note": f"{note}（保留词缀搜索条件）",
                }

    for label in _candidate_unique_labels(query):
        unique = search_unique_by_name(label, market=market, league=league)
        url = unique.get("trade_url")
        if url:
            return {
                "url": url,
                "total": unique.get("total_results", 0),
                "label": "暗金参考",
                "degraded": True,
                "note": f"{note}（按暗金「{label}」）",
            }

    if slot:
        intent = _search_intent(
            slot,
            [{"type": "and", "stats": []}],
            base_type=base,
            rarity="rare" if slot == "jewel" else None,
        )
        slot_result = search_trade(intent, league, market)
        url = slot_result.get("trade_url")
        if url:
            label = "品类浏览"
            detail = "装备类型"
            if base:
                label = f"{base}浏览"
                detail = f"基底 {base}"
            return {
                "url": url,
                "total": slot_result.get("total_results", 0),
                "label": label,
                "degraded": True,
                "note": f"{note}（仅按{detail}筛选）",
            }
        if slot_result.get("error"):
            note = f"{note}；{slot_result['error']}"

    # Last resort: still POST category search — never return home page without search_id
    intent = _search_intent("jewel", [{"type": "and", "stats": []}])
    slot_result = search_trade(intent, league, market)
    url = slot_result.get("trade_url") or ""
    return {
        "url": url,
        "total": slot_result.get("total_results", 0),
        "label": "珠宝浏览",
        "degraded": True,
        "note": f"{note}（最宽珠宝搜索）",
    }


def _response_from_link(
    link: dict,
    *,
    alternatives: list | None = None,
    explanation: str = "",
    need_user_input: bool = False,
    market: str = "cn",
    league: str = "",
    item_ids: list | None = None,
    detail_count: int = 1,
    variant_hint=None,
) -> dict:
    resp = {
        "best_match": {
            "label": link.get("label", "市集链接"),
            "url": link["url"],
            "count": link.get("total", 0),
            "reason": link.get("note", ""),
            "degraded": link.get("degraded", False),
        },
        "alternatives": alternatives or [],
        "explanation": explanation or link.get("note", ""),
        "need_user_input": need_user_input,
    }
    return _attach_market_price(
        resp,
        url=link.get("url"),
        total=int(link.get("total") or 0),
        market=market,
        league=league,
        item_ids=item_ids,
        detail_count=detail_count,
        variant_hint=variant_hint,
    )


# ── Agent loop ──

def run_agent(
    query: str,
    league: str | None = None,
    market: str = "cn",
    user_msg: str = "",
    detail_count: int = 1,
) -> dict:
    """Run the Trade Search Agent.

    Flow:
      1. Parse intent (LLM → DSL)
      2. Resolve concepts (dict + vector)
      3. Build plans (2-3 tiers)
      4. Execute core plan → inspect → if fails, try next plan
      5. Return best results + explanation
    """
    from app.core.database import SessionLocal
    from app.services.trade_realm import resolve_league

    t_start = time.time()
    db = SessionLocal()
    resolved_league = resolve_league(market, league)
    query = sanitize_trade_query(query, user_msg)

    try:
        unique_resp = _try_unique_trade(
            query, resolved_league, market, user_msg=user_msg, detail_count=detail_count,
        )
        if unique_resp:
            logger.info("Agent complete in %.1fs: unique fast-path", time.time() - t_start)
            return unique_resp

        # Step 1: Parse intent
        logger.info("=== Step 1: Parse intent ===")
        intent = _parse_intent(query, user_msg=user_msg)
        if "error" in intent:
            logger.warning("Intent parse failed, using fallback link: %s", intent["error"])
            slot = _infer_item_slot(query)
            base = _infer_base_type(query, slot, market)
            fb = _fallback_trade_link(
                query, resolved_league, market,
                reason=f"无法精确解析搜索条件（{intent['error']}）",
                item_slot=slot,
                base_type=base,
            )
            return _response_from_link(
                fb,
                explanation=fb.get("note", ""),
                need_user_input=False,
                market=market,
                league=resolved_league,
                detail_count=detail_count,
            )

        from app.services.trade_service import normalize_trade_item_slot

        item_slot = normalize_trade_item_slot(intent.get("item_slot") or _infer_item_slot(query))
        base_type = _infer_base_type(query, item_slot, market)
        item_rarity = "rare" if item_slot == "jewel" else None
        sort = intent.get("sort")
        sort_dir = intent.get("sort_dir", "desc")
        budget = intent.get("budget")
        raw_summary = intent.get("raw_summary", query)

        # Step 2: Resolve concepts to stat IDs (or handle sort-only searches)
        logger.info("=== Step 2: Resolve concepts ===")
        resolved = _resolve_all_concepts(db, intent, query=query)

        # Allow sort/budget-only searches (no stat filters needed)
        if not resolved["must_have"] and not resolved["nice_to_have"]:
            if not item_slot:
                fb = _fallback_trade_link(
                    query, resolved_league, market,
                    reason="未能识别装备类型",
                    item_slot=item_slot,
                    base_type=base_type,
                )
                return _response_from_link(
                    fb,
                    explanation=fb.get("note", ""),
                    need_user_input=False,
                    market=market,
                    league=resolved_league,
                    detail_count=detail_count,
                )

        # Step 3: Build plans
        logger.info("=== Step 3: Build plans ===")
        plans = _build_plans(resolved, item_slot)

        # Step 4-5: Execute plans + inspect
        logger.info("=== Step 4: Execute + Inspect ===")
        results = []
        for plan in plans:
            result = _execute_plan(
                plan, item_slot, resolved_league, market, sort, sort_dir, budget,
                base_type=base_type, rarity=item_rarity,
            )
            logger.info(f"  Plan '{plan['name']}': {result['total']} results")

            inspection = None
            if result["total"] > 0 and result["url"]:
                inspection = _inspect_results(result["url"], intent, market=market, league=resolved_league, count=3)

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

            if result.get("rate_limited"):
                logger.warning("  Plan '%s' hit rate limit, stopping plan loop", plan["name"])
                break

            # If this plan passed inspection, we can stop
            if inspection and inspection.get("passed"):
                logger.info(f"  Plan '{plan['name']}' passed inspection, stopping")
                break

        # Step 6: Build response — always try to include a link
        logger.info("=== Step 6: Build response ===")
        best_plan = _pick_best_plan(results)

        if not best_plan or not best_plan["result"].get("url"):
            fb = _fallback_trade_link(
                query, resolved_league, market,
                reason="精确搜索未生成有效链接",
                resolved=resolved,
                item_slot=item_slot,
                base_type=base_type,
            )
            return _response_from_link(
                fb,
                explanation=_build_explanation(results, resolved, raw_summary)
                + " | "
                + fb.get("note", ""),
                market=market,
                league=resolved_league,
                detail_count=detail_count,
            )

        primary, alt_matches = _build_trade_matches(results, best_plan)

        response = {
            "best_match": primary,
            "alternatives": alt_matches,
            "explanation": _build_explanation(results, resolved, raw_summary),
            "need_user_input": False,
        }

        response = _attach_market_price(
            response,
            url=primary["url"],
            total=primary["count"],
            market=market,
            league=resolved_league,
            item_ids=best_plan["result"].get("item_ids"),
            detail_count=detail_count,
        )

        elapsed = time.time() - t_start
        logger.info(
            "Agent complete in %.1fs: best=%s results url=%s",
            elapsed,
            primary["count"],
            bool(primary.get("url")),
        )
        return response

    except Exception as e:
        logger.error("Agent error: %s", e, exc_info=True)
        try:
            fb = _fallback_trade_link(
                query, resolved_league, market,
                reason=f"搜索异常（{str(e)[:80]}）",
                resolved=locals().get("resolved"),
                item_slot=locals().get("item_slot"),
                base_type=locals().get("base_type"),
            )
            return _response_from_link(
                fb,
                explanation=fb.get("note", ""),
                market=market,
                league=resolved_league,
                detail_count=detail_count,
            )
        except Exception as fb_err:
            logger.error("Fallback link failed: %s", fb_err)
            fb = _fallback_trade_link(
                query, resolved_league, market,
                reason=f"搜索出错: {str(e)[:80]}",
            )
            return _response_from_link(
                fb,
                market=market,
                league=resolved_league,
                detail_count=detail_count,
            )
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
        err = best.get("result", {}).get("error")
        if err:
            parts.append(err)
            return " | ".join(parts)
        if best["result"].get("url"):
            parts.append("市集暂无完全匹配（0 件），可点击上方链接在国服市集查看或调整筛选。")
        else:
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
