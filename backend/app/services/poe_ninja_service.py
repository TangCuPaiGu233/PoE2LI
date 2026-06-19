"""poe.ninja PoE2 economy data source.

Fetches currency and exchange prices from poe.ninja's PoE2 API.
API discovered by reverse-engineering the JS bundles:
  GET https://poe.ninja/poe2/api/economy/exchange/{version}/overview
      ?league={display_name}&type={type}

  version  = "current" (latest snapshot)
  type     = "Currency" | "Expedition" | etc.
  league   = display name with spaces, e.g. "Runes of Aldur"

Response structure:
  core.rates    — exchange rates (e.g. chaos per divine)
  core.primary  — primary currency id ("divine")
  lines[]       — per-item prices (primaryValue = price in primary currency)
  items[]       — item metadata (id, name, image, category)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── Configuration ──
_BASE_URL = "https://poe.ninja/poe2/api/economy/exchange/current/overview"
_TIMEOUT = 15
_CACHE_TTL = 600  # 10 minutes

# Simple in-memory cache: {(league, type): (timestamp, data)}
_cache: dict[tuple[str, str], tuple[float, dict]] = {}

# Default PoE2 league (update when new league starts)
_DEFAULT_LEAGUE = "Runes of Aldur"

# ── Hardcoded EN→CN names for currency items ──
_CURRENCY_CN: dict[str, str] = {
    "Divine Orb": "神圣石",
    "Chaos Orb": "混沌石",
    "Exalted Orb": "崇高石",
    "Orb of Alchemy": "点金石",
    "Orb of Chance": "机会石",
    "Orb of Transmutation": "改造石",
    "Orb of Augmentation": "增幅石",
    "Orb of Annulment": "剥离石",
    "Artificer's Orb": "巧匠石",
    "Glassblower's Bauble": "玻璃弹珠",
    "Arcanist's Etcher": "奥术师的铭刻",
    "Gemcutter's Prism": "宝石匠的棱镜",
    "Vaal Orb": "瓦尔宝珠",
    "Regal Orb": "富豪石",
    "Mirror of Kalandra": "卡兰德的魔镜",
    "Hinekora's Lock": "辛格拉的发辫",
    "Cryptic Key": "神秘钥匙",
    "Fracturing Orb": "破溃宝珠",
    "Orb of Dominance": "统御石",
    "Architect's Orb": "建筑师之石",
    "Perfect Chaos Orb": "完美混沌石",
    "Perfect Exalted Orb": "完美崇高石",
    "Perfect Regal Orb": "完美富豪石",
    "Greater Chaos Orb": "高级混沌石",
    "Greater Exalted Orb": "高级崇高石",
    "Greater Regal Orb": "高级富豪石",
    "Greater Orb of Augmentation": "高级增幅石",
    "Perfect Orb of Augmentation": "完美增幅石",
    "Greater Orb of Transmutation": "高级改造石",
    "Perfect Orb of Transmutation": "完美改造石",
    "Greater Jeweller's Orb": "高等工匠石",
    "Lesser Jeweller's Orb": "低等工匠石",
    "Perfect Jeweller's Orb": "完美工匠石",
    "Blacksmith's Whetstone": "磨刀石",
    "Armourer's Scrap": "护甲片",
    "Transmutation Shard": "蜕变石碎片",
    "Chance Shard": "机会石碎片",
    "Regal Shard": "富豪石碎片",
    "Artificer's Shard": "巧匠石碎片",
    "Core Destabiliser": "核心失稳装置",
    "Crystallised Corruption": "结晶腐化",
    "Ancient Infuser": "远古注能装置",
    "Orb of Unmaking": "拆解石",
    "Vaal Cultivation Orb": "瓦尔培育宝珠",
    "Vaal Catalysing Infuser": "瓦尔催化注能装置",
    "Vaal Armourer's Infuser": "瓦尔护甲师注能装置",
    "Vaal Blacksmith's Infuser": "瓦尔铁匠注能装置",
    "Vaal Arcanist's Infuser": "瓦尔秘术师注能装置",
    "Orb of Extraction": "萃取石",
    "Vaal Siphoner": "瓦尔虹吸者",
}

# Session for connection pooling
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/137.0.0.0 Safari/537.36"
        )
    return _session


def _fetch_overview(
    league: str | None = None,
    overview_type: str = "Currency",
) -> dict[str, Any]:
    """Fetch economy overview from poe.ninja, with caching."""
    league = league or _DEFAULT_LEAGUE
    cache_key = (league, overview_type)

    # Check cache
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if time.time() - ts < _CACHE_TTL:
            logger.debug(f"poe.ninja cache hit: {cache_key}")
            return data

    params = {"league": league, "type": overview_type}
    try:
        resp = _get_session().get(_BASE_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"poe.ninja API error: {e}")
        # Return cached data if available, even if stale
        if cache_key in _cache:
            logger.info("Returning stale poe.ninja cache")
            return _cache[cache_key][1]
        return {}

    _cache[cache_key] = (time.time(), data)
    return data


def get_divine_chaos_rate(league: str | None = None) -> float:
    """Get divine orb price in chaos orbs from poe.ninja.

    Returns:
        Number of chaos orbs per divine orb (e.g. 8.71).
        Falls back to 8.73 if API fails.
    """
    data = _fetch_overview(league)
    core = data.get("core", {})
    rates = core.get("rates", {})

    # core.rates.chaos = chaos value of 1 divine (when primary=divine)
    if core.get("primary") == "divine" and "chaos" in rates:
        rate = float(rates["chaos"])
        if rate > 0:
            logger.info(f"poe.ninja divine rate: 1 divine = {rate:.2f} chaos")
            return rate

    # Fallback: derive from lines
    for line in data.get("lines", []):
        if line.get("id") == "chaos":
            # chaos line's primaryValue = divine price of 1 chaos
            divine_per_chaos = line.get("primaryValue", 0)
            if divine_per_chaos and divine_per_chaos > 0:
                rate = 1.0 / divine_per_chaos
                logger.info(f"poe.ninja divine rate (derived): 1 divine = {rate:.2f} chaos")
                return rate

    logger.warning("poe.ninja: falling back to hardcoded PoE2 divine rate 8.73c")
    return 8.73


def fetch_currency_prices(
    league: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all currency prices from poe.ninja.

    Returns:
        List of dicts: {name_en, name_cn, id, chaos_price, divine_price,
                        primary_value, volume, change_7d}
    """
    data = _fetch_overview(league)
    if not data:
        return []

    divine_rate = get_divine_chaos_rate(league)
    lines = data.get("lines", [])
    items = {it["id"]: it for it in data.get("items", [])}

    results: list[dict] = []
    for line in lines:
        item_id = line.get("id", "")
        meta = items.get(item_id, {})
        name_en = meta.get("name", item_id)
        name_cn = _CURRENCY_CN.get(name_en, "")

        # primaryValue is in the primary currency (divine)
        divine_value = line.get("primaryValue", 0) or 0
        chaos_price = divine_value * divine_rate if divine_value else None

        sparkline = line.get("sparkline", {})
        change_7d = sparkline.get("totalChange")

        results.append({
            "id": item_id,
            "name_en": name_en,
            "name_cn": name_cn,
            "divine_price": divine_value,
            "chaos_price": chaos_price,
            "volume": line.get("volumePrimaryValue", 0),
            "change_7d": change_7d,
        })

    logger.info(
        f"poe.ninja: fetched {len(results)} currency prices "
        f"(league={league or _DEFAULT_LEAGUE}, divine={divine_rate:.2f}c)"
    )
    return results


def fetch_currency_item_price(
    item_id: str,
    league: str | None = None,
) -> dict[str, Any] | None:
    """Fetch price for a single currency item by its poe.ninja id.

    Args:
        item_id: poe.ninja item id (e.g. "divine", "chaos", "exalted")
        league: league display name

    Returns:
        dict with name_en, chaos_price, divine_price, or None if not found
    """
    data = _fetch_overview(league)
    if not data:
        return None

    divine_rate = get_divine_chaos_rate(league)

    for line in data.get("lines", []):
        if line.get("id") == item_id:
            meta = next(
                (it for it in data.get("items", []) if it["id"] == item_id),
                {},
            )
            name_en = meta.get("name", item_id)
            divine_value = line.get("primaryValue", 0) or 0
            return {
                "id": item_id,
                "name_en": name_en,
                "name_cn": _CURRENCY_CN.get(name_en, ""),
                "divine_price": divine_value,
                "chaos_price": divine_value * divine_rate if divine_value else None,
            }
    return None


def get_available_types(league: str | None = None) -> list[str]:
    """Return economy types that have data (non-empty lines)."""
    league = league or _DEFAULT_LEAGUE
    types_with_data = []
    for t in _ECONOMY_TYPES:
        data = _fetch_overview(league, t)
        if data.get("lines"):
            types_with_data.append(t)
    return types_with_data


# ── Economy types that return data from poe.ninja PoE2 API ──
# Discovered by reverse-engineering poe.ninja's Astro JS bundles (2026-06-19).
# API type names do NOT always match display names:
#   LineageSupportGems → "Lineage Gems" (skill/support lineage gems)
#   Abyss             → "Abyssal Bones"
#   Ritual            → "Omens"
#   Breach            → "Catalysts" (breach catalysts + splinters + stones)
#   Delirium          → "Liquid Emotions" (distilled emotions)
#   Verisium          → "Verisium" (alloys / ores)
_ECONOMY_TYPES = [
    "Currency", "Fragments", "Abyss", "UncutGems", "LineageSupportGems",
    "Essences", "SoulCores", "Idols", "Runes", "Ritual",
    "Expedition", "Delirium", "Breach", "Verisium",
]

# Map poe.ninja API type → our category key (used by filter_generator)
_NINJA_TYPE_TO_CATEGORY = {
    "Currency": "currency_orb",
    "Fragments": "currency_fragment",
    "Abyss": "currency_abyssal_bone",
    "UncutGems": "currency_uncut_gem",
    "LineageSupportGems": "currency_lineage_gem",
    "Essences": "currency_essence",
    "SoulCores": "currency_soul_core",
    "Idols": "currency_idol",
    "Runes": "currency_rune",
    "Ritual": "currency_omen",
    "Expedition": "currency_expedition",
    "Delirium": "currency_liquid_emotion",
    "Breach": "currency_catalyst",
    "Verisium": "currency_verisium",
}


def fetch_all_economy_prices(
    league: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all economy item prices from poe.ninja (batch, 1 call per type).

    Covers 14 economy categories: Currency, Fragments, Abyss (Abyssal Bones),
    UncutGems, LineageSupportGems (Lineage Gems), Essences, SoulCores, Idols,
    Runes, Ritual (Omens), Expedition, Delirium (Liquid Emotions),
    Breach (Catalysts), Verisium.

    Returns:
        List of dicts: {name_en, name_cn, ninja_type, category,
                        chaos_price, divine_price}
    """
    league = league or _DEFAULT_LEAGUE
    divine_rate = get_divine_chaos_rate(league)
    all_results: list[dict] = []

    for ninja_type in _ECONOMY_TYPES:
        data = _fetch_overview(league, ninja_type)
        if not data:
            continue

        lines = data.get("lines", [])
        items_map = {it["id"]: it for it in data.get("items", [])}
        category = _NINJA_TYPE_TO_CATEGORY.get(ninja_type, f"currency_{ninja_type.lower()}")

        for line in lines:
            item_id = line.get("id", "")
            meta = items_map.get(item_id, {})
            name_en = meta.get("name", item_id)
            name_cn = _CURRENCY_CN.get(name_en, "")

            divine_value = line.get("primaryValue", 0) or 0
            chaos_price = divine_value * divine_rate if divine_value else None

            all_results.append({
                "id": item_id,
                "name_en": name_en,
                "name_cn": name_cn,
                "ninja_type": ninja_type,
                "category": category,
                "divine_price": divine_value,
                "chaos_price": chaos_price,
            })

        if lines:
            logger.info(f"poe.ninja: {ninja_type} → {len(lines)} items")

    logger.info(
        f"poe.ninja: fetched {len(all_results)} total economy prices "
        f"(league={league})"
    )
    return all_results


# ── Live currency→chaos rate lookup ──
_live_rates_cache: dict[str, tuple[float, dict[str, float]]] = {}
_LIVE_RATES_TTL = 600  # 10 minutes, same as _CACHE_TTL


def get_currency_chaos_rates(league: str | None = None) -> dict[str, float]:
    """Build a complete {currency_key_lower: chaos_price} lookup from poe.ninja.

    Returns a dict keyed by multiple name variants for flexible matching:
      - poe.ninja id (e.g. "divine", "chaos")
      - full display name (e.g. "divine orb", "chaos orb")
      - short aliases (e.g. "exalted" → also maps "exalted orb")

    Used by _to_chaos() as primary lookup; CURRENCY_TO_CHAOS is fallback.
    Cached for 10 minutes.
    """
    league = league or _DEFAULT_LEAGUE
    cache_key = league

    # Check cache
    if cache_key in _live_rates_cache:
        ts, rates = _live_rates_cache[cache_key]
        if time.time() - ts < _LIVE_RATES_TTL:
            return rates

    prices = fetch_currency_prices(league)
    if not prices:
        # Return cached stale data if available
        if cache_key in _live_rates_cache:
            return _live_rates_cache[cache_key][1]
        return {}

    rates: dict[str, float] = {}
    for item in prices:
        chaos = item.get("chaos_price")
        if not chaos or chaos <= 0:
            continue

        # Map by id (e.g. "divine", "chaos", "exalted")
        item_id = item.get("id", "").lower().strip()
        if item_id:
            rates[item_id] = chaos

        # Map by full display name (e.g. "divine orb", "chaos orb")
        name = item.get("name_en", "").lower().strip()
        if name:
            rates[name] = chaos

    _live_rates_cache[cache_key] = (time.time(), rates)
    logger.info(f"poe.ninja: built live rates table with {len(rates)} currency keys")
    return rates
