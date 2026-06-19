"""Multi-category price scanner — extends base_scanner to cover currency, uniques, gems, and bases.

Scans item prices via the GGG Trade API for filter generation.
Designed as the primary data source; poe.ninja integration reserved for future.

Categories:
  - Currency (orbs, essences, runes, catalysts, distillates, soul cores, omens)
  - Unique equipment (jewels, weapons, armours, accessories)
  - Skill gems & support gems
  - White equipment bases (delegates to base_scanner)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Protocol

from app.core.database import SessionLocal
from app.services.base_scanner import CURRENCY_TO_CHAOS, _to_chaos

logger = logging.getLogger(__name__)


# ── Hardcoded EN→CN currency names (bilingual index has many gaps) ──
_CURRENCY_CN_NAMES: dict[str, str] = {
    # Orbs
    "Divine Orb": "神圣石",
    "Chaos Orb": "混沌石",
    "Exalted Orb": "崇高石",
    "Orb of Alchemy": "点金石",
    "Orb of Chance": "蜕变石",
    "Orb of Transmutation": "改造石",
    "Orb of Augmentation": "增幅石",
    "Orb of Alteration": "重铸石",
    "Orb of Regret": "悔悟石",
    "Orb of Scouring": "洗点石",
    "Orb of Annulment": "撤销石",
    "Orb of Binding": "束缚石",
    "Orb of Unmaking": "拆解石",
    "Orb of Dominance": "统御石",
    "Orb of Fusing": "链接石",
    "Jeweller's Orb": "工匠石",
    "Chromatic Orb": "幻色石",
    "Gemcutter's Prism": "宝石匠之棱镜",
    "Vaal Orb": "瓦尔宝珠",
    "Regal Orb": "帝王石",
    "Blessed Orb": "祝福石",
    "Mirror of Kalandra": "卡兰德之镜",
    "Orb of Horizons": "地平石",
    "Harbinger's Orb": "先驱者之石",
    "Fracturing Orb": "裂变石",
    "Artificer's Orb": "工匠之宝珠",
    "Lesser Jeweller's Orb": "低级工匠宝珠",
    "Greater Jeweller's Orb": "高级工匠宝珠",
    "Perfect Jeweller's Orb": "完美工匠宝珠",
    "Greater Chaos Orb": "高级混沌石",
    "Perfect Chaos Orb": "完美混沌石",
    "Greater Exalted Orb": "高级崇高石",
    "Perfect Exalted Orb": "完美崇高石",
    "Greater Regal Orb": "高级帝王石",
    "Perfect Regal Orb": "完美帝王石",
    "Greater Orb of Augmentation": "高级增幅石",
    "Perfect Orb of Augmentation": "完美增幅石",
    "Greater Orb of Transmutation": "高级改造石",
    "Perfect Orb of Transmutation": "完美改造石",
    # Essences
    "Greater Essence of Haste": "高级急速精华",
    "Greater Essence of the Mind": "高级智慧精华",
    "Greater Essence of the Body": "高级体质精华",
    # Runes
    "Rune of Souls": "灵魂符文",
    "Rune of the Sky": "天空符文",
    "Rune of the Earth": "大地符文",
    "Rune of the Storm": "风暴符文",
    "Rune of the Flame": "烈焰符文",
    "Rune of the Ice": "寒冰符文",
    # Soul cores, catalysts, distillates, omens — add as discovered
}


# ═══════════════════════════════════════════════════════════
#  Data model
# ═══════════════════════════════════════════════════════════


@dataclass
class PriceSnapshot:
    """Price data for one item."""

    name_en: str
    name_cn: str | None
    category: str  # "currency_orb", "currency_essence", "currency_rune",
    # "currency_catalyst", "currency_distillate", "currency_soul_core",
    # "currency_omen", "currency_misc",
    # "unique_jewel", "unique_weapon", "unique_armour", "unique_accessory",
    # "skill_gem", "support_gem", "white_base"
    chaos_price: float | None = None
    divine_price: float | None = None  # chaos_price / divine_rate
    median_chaos: float | None = None
    listing_count: int = 0
    total_results: int = 0
    confidence: str = "low"  # "high" if listing_count >= 5
    prices_raw: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass
class ScanReport:
    """Summary of a multi-category scan run."""

    batch_id: str
    market: str
    league: str
    categories: list[str] = field(default_factory=list)
    total_items: int = 0
    scanned: int = 0
    priced: int = 0
    errors: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "market": self.market,
            "league": self.league,
            "categories": self.categories,
            "total_items": self.total_items,
            "scanned": self.scanned,
            "priced": self.priced,
            "errors": self.errors,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# ═══════════════════════════════════════════════════════════
#  Price source abstraction (for future poe.ninja switch)
# ═══════════════════════════════════════════════════════════


class PriceSource(Protocol):
    """Abstract price data source."""

    def fetch_prices(
        self, categories: list[str], market: str, league: str | None
    ) -> list[PriceSnapshot]: ...


# ═══════════════════════════════════════════════════════════
#  Currency item lists
# ═══════════════════════════════════════════════════════════


def _load_currency_items() -> dict[str, list[dict]]:
    """Load currency items grouped by sub-category from bilingual index.

    Returns:
        {"orb": [...], "essence": [...], "rune": [...], "catalyst": [...],
         "distillate": [...], "soul_core": [...], "omen": [...], "misc": [...]}
    """
    from app.services.trade_items_index import _load_bilingual

    data = _load_bilingual()
    groups: dict[str, list[dict]] = {
        "orb": [],
        "essence": [],
        "rune": [],
        "catalyst": [],
        "distillate": [],
        "soul_core": [],
        "omen": [],
        "misc": [],
    }

    for group in data.get("groups") or []:
        gid = group.get("id")
        if gid != "currency":
            continue
        for ent in group.get("entries") or []:
            en = (ent.get("text_en") or "").strip()
            cn = (ent.get("text_cn") or "").strip()
            if not en:
                continue
            # Use hardcoded CN name if bilingual index is empty
            if not cn:
                cn = _CURRENCY_CN_NAMES.get(en, "")

            lower = en.lower()
            if "essence" in lower:
                groups["essence"].append({"name_en": en, "name_cn": cn})
            elif "rune" in lower:
                groups["rune"].append({"name_en": en, "name_cn": cn})
            elif "catalyst" in lower:
                groups["catalyst"].append({"name_en": en, "name_cn": cn})
            elif "distillate" in lower or "distilled" in lower:
                groups["distillate"].append({"name_en": en, "name_cn": cn})
            elif "soul core" in lower:
                groups["soul_core"].append({"name_en": en, "name_cn": cn})
            elif "omen" in lower:
                groups["omen"].append({"name_en": en, "name_cn": cn})
            elif "orb" in lower or "shard" in lower or "scroll" in lower:
                groups["orb"].append({"name_en": en, "name_cn": cn})
            else:
                groups["misc"].append({"name_en": en, "name_cn": cn})

    return groups


# Category name → PoE2 filter Class condition
_CATEGORY_CLASS_MAP = {
    "orb": "Stackable Currency",
    "essence": "Stackable Currency",
    "rune": "Stackable Currency",
    "catalyst": "Stackable Currency",
    "distillate": "Stackable Currency",
    "soul_core": "Stackable Currency",
    "omen": "Stackable Currency",
    "misc": "Stackable Currency",
    "unique_jewel": "Jewel",
    "unique_weapon": None,  # multiple classes
    "unique_armour": None,  # multiple classes
    "unique_accessory": None,  # multiple classes
    "skill_gem": "Skill Gems",
    "support_gem": "Support Gems",
}


# ═══════════════════════════════════════════════════════════
#  Unique item lists
# ═══════════════════════════════════════════════════════════


def _load_unique_items() -> dict[str, list[dict]]:
    """Load unique items grouped by slot category from unique_cn_en.json.

    Returns:
        {"jewel": [...], "weapon": [...], "armour": [...], "accessory": [...]}
    """
    import os

    data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    if not os.path.isdir(data_dir):
        data_dir = "/app/data"

    path = os.path.join(data_dir, "unique_cn_en.json")
    if not os.path.isfile(path):
        logger.warning("unique_cn_en.json not found")
        return {"jewel": [], "weapon": [], "armour": [], "accessory": []}

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    cn_to_en = data.get("cn_to_en") or {}
    groups: dict[str, list[dict]] = {
        "jewel": [],
        "weapon": [],
        "armour": [],
        "accessory": [],
    }

    for cn_name, meta in cn_to_en.items():
        en_name = (meta.get("en") or meta.get("path") or "").strip()
        base_cn = (meta.get("base_cn") or "").strip()
        base_en = (meta.get("base_en") or "").strip()
        if not en_name:
            continue

        # Classify by base type keywords
        lower_base = (base_en or base_cn or "").lower()
        if any(kw in lower_base for kw in ("jewel", "珠宝", "宝石")):
            groups["jewel"].append(
                {"name_en": en_name, "name_cn": cn_name, "base_type": base_en}
            )
        elif any(kw in lower_base for kw in (
            "sword", "axe", "mace", "bow", "crossbow", "spear", "staff",
            "wand", "sceptre", "claw", "dagger", "flail", "quarterstaff",
            "剑", "斧", "锤", "弓", "弩", "矛", "杖", "魔杖", "权杖", "爪", "匕首",
        )):
            groups["weapon"].append(
                {"name_en": en_name, "name_cn": cn_name, "base_type": base_en}
            )
        elif any(kw in lower_base for kw in (
            "ring", "amulet", "belt", "talisman",
            "戒指", "护身符", "项链", "腰带",
        )):
            groups["accessory"].append(
                {"name_en": en_name, "name_cn": cn_name, "base_type": base_en}
            )
        else:
            groups["armour"].append(
                {"name_en": en_name, "name_cn": cn_name, "base_type": base_en}
            )

    return groups


# ═══════════════════════════════════════════════════════════
#  Skill gem list
# ═══════════════════════════════════════════════════════════


def _load_skill_gems() -> list[dict]:
    """Load skill/support gem base types from bilingual index."""
    from app.services.trade_items_index import _load_bilingual

    data = _load_bilingual()
    gems: list[dict] = []
    for group in data.get("groups") or []:
        gid = group.get("id")
        if gid not in ("gem",):
            continue
        for ent in group.get("entries") or []:
            en = (ent.get("text_en") or "").strip()
            cn = (ent.get("text_cn") or "").strip()
            if not en:
                continue
            gems.append({"name_en": en, "name_cn": cn, "group_id": gid})
    return gems


# ═══════════════════════════════════════════════════════════
#  Scanning functions
# ═══════════════════════════════════════════════════════════


def _get_divine_rate(market: str = "cn") -> float:
    """Get divine orb price in chaos. Uses poe.ninja as primary source."""
    # ── Primary: poe.ninja (always works, no auth needed) ──
    try:
        from app.services.poe_ninja_service import get_divine_chaos_rate
        rate = get_divine_chaos_rate()
        if rate and rate > 0:
            logger.info(f"Divine rate from poe.ninja: {rate:.2f}c")
            return rate
    except Exception as e:
        logger.debug(f"poe.ninja divine rate failed: {e}")

    # ── Fallback: hardcoded rate ──
    return CURRENCY_TO_CHAOS.get("divine", 150.0)


def scan_currency_from_ninja(
    market: str = "cn",
    league: str | None = None,
    divine_rate: float = 150.0,
    max_items: int | None = None,
) -> list[PriceSnapshot]:
    """Scan ALL economy prices from poe.ninja in batch.

    Covers 14 economy categories: Currency, Fragments, Abyss (Abyssal Bones),
    UncutGems, LineageSupportGems (Lineage Gems), Essences, SoulCores, Idols,
    Runes, Ritual (Omens), Expedition, Delirium (Liquid Emotions),
    Breach (Catalysts), Verisium — all fetched via poe.ninja's economy
    API (1 call per type, ~14 calls total).

    Returns:
        List of PriceSnapshot objects for all economy items found.
    """
    from app.services.poe_ninja_service import fetch_all_economy_prices

    prices = fetch_all_economy_prices(league=league)
    if not prices:
        logger.warning("poe.ninja returned no economy prices")
        return []

    if max_items:
        prices = prices[:max_items]

    snapshots: list[PriceSnapshot] = []
    for p in prices:
        chaos = p.get("chaos_price")
        divine_val = p.get("divine_price", 0) or 0
        category = p.get("category", "currency_orb")

        snap = PriceSnapshot(
            name_en=p.get("name_en", ""),
            name_cn=p.get("name_cn") or None,
            category=category,
            chaos_price=chaos,
            divine_price=divine_val,
            median_chaos=chaos,  # poe.ninja gives one price, use as median
            listing_count=0,
            total_results=0,
            confidence="high",
            prices_raw=[{
                "source": "poe.ninja",
                "ninja_type": p.get("ninja_type", ""),
                "divine_price": divine_val,
                "chaos_price": chaos,
            }],
        )
        snapshots.append(snap)

    logger.info(f"poe.ninja economy scan: {len(snapshots)} items across "
                f"{len(set(p.get('category', '') for p in prices))} categories, "
                f"divine rate={divine_rate:.2f}c")
    return snapshots


def scan_currency_item(
    name_en: str,
    name_cn: str,
    sub_category: str,
    market: str = "cn",
    league: str | None = None,
    divine_rate: float = 150.0,
) -> PriceSnapshot:
    """Scan one currency item's price."""
    from app.services.trade_service import search_trade, fetch_trade_listings

    snapshot = PriceSnapshot(
        name_en=name_en,
        name_cn=name_cn or None,
        category=f"currency_{sub_category}",
    )

    # CN Trade API requires CN item names for currency
    search_name = name_en
    if market == "cn":
        search_name = name_cn or _CURRENCY_CN_NAMES.get(name_en, name_en)

    intent = {
        "base_type": search_name,
        "stat_groups": [],
    }
    # Add Class filter for currency
    intent["item_type"] = None  # currency search doesn't need category filter

    search_result = search_trade(intent, league=league, market=market)
    if search_result.get("error"):
        snapshot.error = search_result["error"]
        return snapshot

    snapshot.total_results = search_result.get("total_results", 0)
    trade_url = search_result.get("trade_url", "")
    item_ids = search_result.get("item_ids", [])

    if snapshot.total_results == 0:
        return snapshot

    fetched = fetch_trade_listings(
        trade_url, market=market, league=league, item_ids=item_ids, count=5
    )

    listings = fetched.get("listings") or []
    chaos_prices: list[float] = []

    for listing in listings:
        price = listing.get("price") or {}
        amount = price.get("amount")
        currency = price.get("currency")
        if amount is None or not currency:
            continue
        chaos_eq = _to_chaos(amount, currency)
        if chaos_eq is not None:
            chaos_prices.append(chaos_eq)
            snapshot.prices_raw.append(
                {"amount": amount, "currency": currency, "chaos_eq": chaos_eq}
            )

    if chaos_prices:
        snapshot.chaos_price = min(chaos_prices)
        snapshot.median_chaos = median(chaos_prices)
        snapshot.divine_price = snapshot.chaos_price / divine_rate if divine_rate else None
        snapshot.listing_count = len(chaos_prices)
        snapshot.confidence = "high" if snapshot.listing_count >= 5 else "low"

    return snapshot


def scan_unique_item(
    name_en: str,
    name_cn: str,
    sub_category: str,
    market: str = "cn",
    league: str | None = None,
    divine_rate: float = 150.0,
) -> PriceSnapshot:
    """Scan one unique item's price via search_unique_by_name.

    If CN market yields no price, falls back to global (international) market.
    """
    from app.services.trade_service import (
        search_unique_by_name,
        fetch_cheapest_listing,
    )

    snapshot = PriceSnapshot(
        name_en=name_en,
        name_cn=name_cn or None,
        category=f"unique_{sub_category}",
    )

    # Use the Chinese name if available for CN market, else English
    search_label = name_cn if (name_cn and market == "cn") else name_en

    result = search_unique_by_name(search_label, market=market, league=league)
    if result.get("error"):
        snapshot.error = result["error"]
    else:
        snapshot.total_results = result.get("total_results", 0)
        trade_url = result.get("trade_url", "")
        item_ids = result.get("item_ids", [])

        if trade_url and snapshot.total_results > 0:
            cheapest = fetch_cheapest_listing(
                trade_url, market=market, league=league, item_ids=item_ids
            )
            if not cheapest.get("error"):
                amount = cheapest.get("amount")
                currency = cheapest.get("currency", "")
                if amount is not None and currency:
                    chaos_eq = _to_chaos(amount, currency)
                    if chaos_eq is not None:
                        snapshot.chaos_price = chaos_eq
                        snapshot.divine_price = chaos_eq / divine_rate if divine_rate else None
                        snapshot.listing_count = 1
                        snapshot.prices_raw = [
                            {"amount": amount, "currency": currency, "chaos_eq": chaos_eq}
                        ]
            else:
                snapshot.error = cheapest["error"]

    # ── Global market fallback ──
    if snapshot.chaos_price is None and market == "cn":
        logger.info(f"CN no price for {name_en} ({name_cn or '?'}), trying global market")
        try:
            global_result = search_unique_by_name(
                name_en, market="global", league="Runes of Aldur"
            )
            if not global_result.get("error"):
                global_url = global_result.get("trade_url", "")
                global_ids = global_result.get("item_ids", [])
                if global_url and global_result.get("total_results", 0) > 0:
                    cheapest_g = fetch_cheapest_listing(
                        global_url, market="global", league="Runes of Aldur",
                        item_ids=global_ids,
                    )
                    if not cheapest_g.get("error"):
                        amount = cheapest_g.get("amount")
                        currency = cheapest_g.get("currency", "")
                        if amount is not None and currency:
                            chaos_eq = _to_chaos(amount, currency)
                            if chaos_eq is not None:
                                snapshot.chaos_price = chaos_eq
                                snapshot.divine_price = chaos_eq / divine_rate if divine_rate else None
                                snapshot.listing_count = 1
                                snapshot.prices_raw = [
                                    {"amount": amount, "currency": currency,
                                     "chaos_eq": chaos_eq, "source": "global"}
                                ]
                                snapshot.total_results = global_result.get("total_results", 0)
                                snapshot.error = None
                                logger.info(f"  → global fallback: {chaos_eq:.1f}c")
        except Exception as e:
            logger.debug(f"Global fallback failed for {name_en}: {e}")

    return snapshot


def scan_skill_gem(
    name_en: str,
    name_cn: str,
    market: str = "cn",
    league: str | None = None,
    divine_rate: float = 150.0,
) -> PriceSnapshot:
    """Scan one skill gem's price.

    If CN market yields no price, falls back to global (international) market.
    """
    from app.services.trade_service import search_trade, fetch_trade_listings

    snapshot = PriceSnapshot(
        name_en=name_en,
        name_cn=name_cn or None,
        category="skill_gem",
    )

    intent = {
        "base_type": name_en,
        "stat_groups": [],
    }

    # ── Try primary market ──
    search_result = search_trade(intent, league=league, market=market)
    if not search_result.get("error"):
        snapshot.total_results = search_result.get("total_results", 0)
        trade_url = search_result.get("trade_url", "")
        item_ids = search_result.get("item_ids", [])

        if snapshot.total_results > 0 and trade_url:
            fetched = fetch_trade_listings(
                trade_url, market=market, league=league, item_ids=item_ids, count=5
            )
            listings = fetched.get("listings") or []
            chaos_prices: list[float] = []
            for listing in listings:
                price = listing.get("price") or {}
                amount = price.get("amount")
                currency = price.get("currency")
                if amount is None or not currency:
                    continue
                chaos_eq = _to_chaos(amount, currency)
                if chaos_eq is not None:
                    chaos_prices.append(chaos_eq)
                    snapshot.prices_raw.append(
                        {"amount": amount, "currency": currency, "chaos_eq": chaos_eq}
                    )
            if chaos_prices:
                snapshot.chaos_price = min(chaos_prices)
                snapshot.median_chaos = median(chaos_prices)
                snapshot.divine_price = snapshot.chaos_price / divine_rate if divine_rate else None
                snapshot.listing_count = len(chaos_prices)
                snapshot.confidence = "high" if snapshot.listing_count >= 5 else "low"
    else:
        snapshot.error = search_result["error"]

    # ── Global market fallback ──
    if snapshot.chaos_price is None and market == "cn":
        logger.info(f"CN no price for gem {name_en}, trying global market")
        try:
            global_result = search_trade(
                intent, league="Runes of Aldur", market="global"
            )
            if not global_result.get("error"):
                global_url = global_result.get("trade_url", "")
                global_ids = global_result.get("item_ids", [])
                if global_url and global_result.get("total_results", 0) > 0:
                    fetched_g = fetch_trade_listings(
                        global_url, market="global", league="Runes of Aldur",
                        item_ids=global_ids, count=5,
                    )
                    listings_g = fetched_g.get("listings") or []
                    chaos_prices_g: list[float] = []
                    for listing in listings_g:
                        price = listing.get("price") or {}
                        amount = price.get("amount")
                        currency = price.get("currency")
                        if amount is None or not currency:
                            continue
                        chaos_eq = _to_chaos(amount, currency)
                        if chaos_eq is not None:
                            chaos_prices_g.append(chaos_eq)
                            snapshot.prices_raw.append(
                                {"amount": amount, "currency": currency,
                                 "chaos_eq": chaos_eq, "source": "global"}
                            )
                    if chaos_prices_g:
                        snapshot.chaos_price = min(chaos_prices_g)
                        snapshot.median_chaos = median(chaos_prices_g)
                        snapshot.divine_price = snapshot.chaos_price / divine_rate if divine_rate else None
                        snapshot.listing_count = len(chaos_prices_g)
                        snapshot.confidence = "high" if snapshot.listing_count >= 5 else "low"
                        snapshot.total_results = global_result.get("total_results", 0)
                        snapshot.error = None
                        logger.info(f"  → global fallback: {snapshot.chaos_price:.1f}c")
        except Exception as e:
            logger.debug(f"Global fallback failed for gem {name_en}: {e}")

    return snapshot


# ═══════════════════════════════════════════════════════════
#  Batch scanning orchestrator
# ═══════════════════════════════════════════════════════════


def scan_all_categories(
    categories: list[str] | None = None,
    market: str = "cn",
    league: str | None = None,
    max_items_per_category: int | None = None,
    callback=None,
) -> tuple[ScanReport, list[PriceSnapshot]]:
    """Scan prices across all requested categories.

    Args:
        categories: list of category keys to scan.
            Available: "currency", "unique", "skill_gem", "white_base"
            Default: all four.
        market: "cn" or "global"
        league: league name (None = market default)
        max_items_per_category: limit items per category (for testing)
        callback: optional callable(scanned, total, snapshot) for progress

    Returns:
        (ScanReport, list[PriceSnapshot])
    """
    from app.services.trade_realm import resolve_league
    from app.services.base_scanner import scan_all_bases, get_latest_high_value_bases

    if categories is None:
        categories = ["currency", "unique", "skill_gem", "white_base"]

    batch_id = uuid.uuid4().hex[:12]
    resolved_league = resolve_league(market, league)

    report = ScanReport(
        batch_id=batch_id,
        market=market,
        league=resolved_league,
        categories=categories,
    )

    # Get dynamic divine rate
    divine_rate = _get_divine_rate(market=market)
    logger.info(f"Batch {batch_id}: divine rate = {divine_rate}c")

    all_snapshots: list[PriceSnapshot] = []

    # ── Count total items for progress ──
    total_est = 0
    if "currency" in categories:
        total_est += 50  # poe.ninja returns ~49 currency items
    if "unique" in categories:
        unique_items = _load_unique_items()
        total_est += sum(len(v) for v in unique_items.values())
    if "skill_gem" in categories:
        gem_items = _load_skill_gems()
        total_est += len(gem_items)
    report.total_items = total_est

    logger.info(
        f"Starting price scan batch={batch_id}: "
        f"categories={categories}, ~{total_est} items, "
        f"market={market}, league={resolved_league}"
    )

    # ── Currency (poe.ninja — one API call gets all prices) ──
    if "currency" in categories:
        try:
            ninja_snaps = scan_currency_from_ninja(
                market=market,
                league=league,
                divine_rate=divine_rate,
                max_items=max_items_per_category,
            )
            for snap in ninja_snaps:
                all_snapshots.append(snap)
                report.scanned += 1
                if snap.chaos_price is not None:
                    report.priced += 1
                if snap.error:
                    report.errors += 1
            logger.info(f"Currency scan complete: {len(ninja_snaps)} items from poe.ninja")
        except Exception as e:
            logger.exception("poe.ninja currency scan failed")
            report.errors += 1

    # ── Uniques ──
    if "unique" in categories:
        unique_items = _load_unique_items()
        for sub_cat, items in unique_items.items():
            if max_items_per_category:
                items = items[:max_items_per_category]
            for item in items:
                snap = scan_unique_item(
                    item["name_en"],
                    item.get("name_cn", ""),
                    sub_cat,
                    market=market,
                    league=league,
                    divine_rate=divine_rate,
                )
                all_snapshots.append(snap)
                report.scanned += 1
                if snap.chaos_price is not None:
                    report.priced += 1
                if snap.error:
                    report.errors += 1
                if callback:
                    callback(report.scanned, report.total_items, snap)
                _log_progress(report, snap.name_en)

    # ── Skill gems ──
    if "skill_gem" in categories:
        gem_items = _load_skill_gems()
        if max_items_per_category:
            gem_items = gem_items[:max_items_per_category]
        for item in gem_items:
            snap = scan_skill_gem(
                item["name_en"],
                item.get("name_cn", ""),
                market=market,
                league=league,
                divine_rate=divine_rate,
            )
            all_snapshots.append(snap)
            report.scanned += 1
            if snap.chaos_price is not None:
                report.priced += 1
            if snap.error:
                report.errors += 1
            if callback:
                callback(report.scanned, report.total_items, snap)
            _log_progress(report, snap.name_en)

    # ── White bases (delegate to existing scanner) ──
    if "white_base" in categories:
        try:
            base_report = scan_all_bases(
                market=market,
                league=league,
                min_price_chaos=0,  # capture all priced bases
                min_results=1,
            )
            # Convert base results to PriceSnapshots
            bases = get_latest_high_value_bases(market=market, league=league)
            for b in bases:
                snap = PriceSnapshot(
                    name_en=b["name_en"],
                    name_cn=b.get("name_cn"),
                    category="white_base",
                    chaos_price=b.get("cheapest_chaos"),
                    median_chaos=b.get("median_chaos"),
                    listing_count=b.get("total_results", 0),
                    total_results=b.get("total_results", 0),
                )
                if snap.chaos_price is not None:
                    snap.divine_price = snap.chaos_price / divine_rate if divine_rate else None
                all_snapshots.append(snap)
                report.scanned += 1
                if snap.chaos_price is not None:
                    report.priced += 1
        except Exception as e:
            logger.exception("White base scan failed")
            report.errors += 1

    report.finished_at = datetime.now(timezone.utc)
    logger.info(
        f"Price scan complete: batch={batch_id}, "
        f"scanned={report.scanned}, priced={report.priced}, "
        f"errors={report.errors}, "
        f"duration={report.finished_at - report.started_at}"
    )

    # Persist to DB
    if all_snapshots:
        written = save_snapshots_to_db(all_snapshots, batch_id, market, resolved_league)
        logger.info(f"Saved {written} price snapshots to DB (batch={batch_id})")

    return report, all_snapshots


def _log_progress(report: ScanReport, item_name: str):
    """Log scan progress every 10 items."""
    if report.scanned % 10 == 0:
        logger.info(
            f"Price scan progress: {report.scanned}/{report.total_items} "
            f"(priced={report.priced}, errors={report.errors}) "
            f"last={item_name}"
        )


# ═══════════════════════════════════════════════════════════
#  DB persistence
# ═══════════════════════════════════════════════════════════


def save_snapshots_to_db(
    snapshots: list[PriceSnapshot],
    batch_id: str,
    market: str,
    league: str,
) -> int:
    """Write price snapshots to the item_price_snapshots table.

    Returns number of rows written.
    """
    from app.models.item_price_snapshot import ItemPriceSnapshot

    db = SessionLocal()
    count = 0
    try:
        for snap in snapshots:
            row = ItemPriceSnapshot(
                name_en=snap.name_en,
                name_cn=snap.name_cn,
                category=snap.category,
                chaos_price=snap.chaos_price,
                divine_price=snap.divine_price,
                median_chaos=snap.median_chaos,
                listing_count=snap.listing_count,
                total_results=snap.total_results,
                confidence=snap.confidence,
                prices_raw=snap.prices_raw,
                market=market,
                league=league,
                scan_batch=batch_id,
            )
            db.add(row)
            count += 1
        db.commit()
        logger.info(f"Saved {count} price snapshots (batch={batch_id})")
    except Exception:
        db.rollback()
        logger.exception("Failed to save price snapshots")
        raise
    finally:
        db.close()
    return count


def get_latest_snapshots(
    market: str = "cn",
    league: str | None = None,
    category: str | None = None,
    min_price_chaos: float = 0.0,
) -> list[PriceSnapshot]:
    """Load the latest price snapshots from DB.

    Args:
        market: "cn" or "global"
        league: league name (None = resolve from market)
        category: filter by category prefix (e.g. "currency", "unique")
        min_price_chaos: minimum price filter
    """
    from app.services.trade_realm import resolve_league
    from app.models.item_price_snapshot import ItemPriceSnapshot

    resolved_league = resolve_league(market, league)
    db = SessionLocal()
    try:
        # Find latest batch
        latest = (
            db.query(ItemPriceSnapshot)
            .filter(
                ItemPriceSnapshot.market == market,
                ItemPriceSnapshot.league == resolved_league,
            )
            .order_by(ItemPriceSnapshot.scanned_at.desc())
            .first()
        )
        if not latest:
            return []

        batch_id = latest.scan_batch
        query = db.query(ItemPriceSnapshot).filter(
            ItemPriceSnapshot.scan_batch == batch_id,
        )
        if category:
            query = query.filter(
                ItemPriceSnapshot.category.like(f"{category}%")
            )
        if min_price_chaos > 0:
            query = query.filter(
                ItemPriceSnapshot.chaos_price >= min_price_chaos
            )

        rows = query.order_by(
            ItemPriceSnapshot.chaos_price.desc().nullslast()
        ).all()

        return [
            PriceSnapshot(
                name_en=r.name_en,
                name_cn=r.name_cn,
                category=r.category,
                chaos_price=r.chaos_price,
                divine_price=r.divine_price,
                median_chaos=r.median_chaos,
                listing_count=r.listing_count,
                total_results=r.total_results,
                confidence=r.confidence,
            )
            for r in rows
        ]
    finally:
        db.close()
