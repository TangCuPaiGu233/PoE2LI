"""Base item price scanner — scans normal-rarity equipment bases via Trade API."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median

from app.core.database import SessionLocal
from app.models.base_price import BasePriceSnapshot

logger = logging.getLogger(__name__)

# ── Currency → chaos equivalent (PoE2 rates, fallback when poe.ninja unavailable) ──
# Primary lookup uses poe.ninja live rates via get_currency_chaos_rates().
# These hardcoded values are a LAST RESORT fallback for when the API is down.
# Updated 2026-06-19 for PoE2 economy (1D ≈ 8.5c, NOT PoE1's 150c).
CURRENCY_TO_CHAOS: dict[str, float] = {
    # Base unit
    "chaos": 1.0,
    "chaos orb": 1.0,
    # Major currencies (PoE2 rates)
    "divine": 8.5,
    "divine orb": 8.5,
    "exalted": 0.04,
    "exalted orb": 0.04,
    "greater exalted orb": 0.14,
    "perfect exalted orb": 24.3,
    "mirror": 34000.0,
    "mirror of kalandra": 34000.0,
    "vaal orb": 0.13,
    "gemcutter's prism": 0.06,
    "regal": 0.014,
    "regal orb": 0.014,
    "orb of alchemy": 0.026,
    "alchemy": 0.026,
    "orb of chance": 0.4,
    "chance": 0.4,
    "orb of augmentation": 0.009,
    "augmentation": 0.009,
    "orb of transmutation": 0.003,
    "transmutation": 0.003,
    "wisdom": 0.001,
    "scroll of wisdom": 0.001,
    # PoE2 crafting currencies
    "artificer's orb": 0.05,
    "artificer's shard": 0.02,
    "greater jeweller's orb": 0.02,
    "lesser jeweller's orb": 0.002,
    "blacksmith's whetstone": 0.001,
    "armourer's scrap": 0.001,
    "glassblower's bauble": 0.003,
    "orb of annulment": 0.3,
    "annul": 0.3,
    "fracturing orb": 5.0,
    "orb of dominance": 1.0,
}

# ── Variant prefixes to skip (these are upgraded versions of plain bases) ──
_VARIANT_PREFIXES = (
    "Runeforged ",
    "Runemastered ",
    "Runed ",
    "Foil ",
)

# Equipment groups to scan
_EQUIPMENT_GROUPS = {"accessory", "armour", "weapon"}


@dataclass
class BasePriceResult:
    """Result of scanning one base type."""
    base_name_en: str
    base_name_cn: str
    item_category: str
    group_id: str
    total_results: int = 0
    prices: list[dict] = field(default_factory=list)  # [{amount, currency, chaos_eq}]
    cheapest_chaos: float | None = None
    median_chaos: float | None = None
    is_high_value: bool = False
    error: str | None = None


@dataclass
class ScanReport:
    """Summary of a full scan run."""
    batch_id: str
    market: str
    league: str
    total_bases: int = 0
    scanned: int = 0
    high_value_count: int = 0
    errors: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    high_value_bases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "market": self.market,
            "league": self.league,
            "total_bases": self.total_bases,
            "scanned": self.scanned,
            "high_value_count": self.high_value_count,
            "errors": self.errors,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "high_value_bases": self.high_value_bases,
        }


def _to_chaos(amount: float, currency: str) -> float | None:
    """Convert a price to chaos equivalent.

    Lookup order:
    1. poe.ninja live rates (covers all ~50 PoE2 currencies, 10min cache)
    2. Hardcoded CURRENCY_TO_CHAOS fallback (legacy/static rates)
    """
    key = currency.lower().strip()

    # 1. Try live rates from poe.ninja
    try:
        from app.services.poe_ninja_service import get_currency_chaos_rates
        live_rates = get_currency_chaos_rates()
        if key in live_rates:
            return amount * live_rates[key]
    except Exception:
        pass  # poe.ninja unavailable, fall through to hardcoded

    # 2. Fallback to hardcoded table
    rate = CURRENCY_TO_CHAOS.get(key)
    if rate is None:
        return None
    return amount * rate


def deduplicate_base_types(entries: list[dict]) -> list[dict]:
    """Filter out variant/upgraded base types, keeping only plain bases."""
    result = []
    seen_names: set[str] = set()
    for entry in entries:
        en = (entry.get("text_en") or "").strip()
        if not en:
            continue
        # Skip variants
        if any(en.startswith(prefix) for prefix in _VARIANT_PREFIXES):
            continue
        # Deduplicate by EN name
        if en in seen_names:
            continue
        seen_names.add(en)
        result.append(entry)
    return result


def load_equipment_bases() -> list[dict]:
    """Load all plain (non-variant) equipment base types from bilingual index."""
    from app.services.trade_items_index import _load_bilingual

    data = _load_bilingual()
    all_entries = []
    for group in data.get("groups") or []:
        gid = group.get("id")
        if gid not in _EQUIPMENT_GROUPS:
            continue
        for ent in group.get("entries") or []:
            ent["_group_id"] = gid
            all_entries.append(ent)

    return deduplicate_base_types(all_entries)


def scan_single_base(
    base_en: str,
    base_cn: str,
    item_category: str,
    group_id: str,
    market: str = "cn",
    league: str | None = None,
) -> BasePriceResult:
    """Scan one base type on the Trade API (normal rarity)."""
    from app.services.trade_service import search_trade, fetch_trade_listings
    from app.services.trade_items_index import trade_category_for_base

    result = BasePriceResult(
        base_name_en=base_en,
        base_name_cn=base_cn,
        item_category=item_category or trade_category_for_base(base_en) or "",
        group_id=group_id,
    )

    # Build intent for white-base search with anti-manipulation filters:
    # - listed_days=3: only items listed within 3 days (stale = likely fake price)
    # - online=True: forces status=online even for CN market (instant buyout only)
    intent = {
        "base_type": base_en,
        "rarity": "normal",
        "stat_groups": [],
        "listed_days": 3,
        "online": True,
    }

    # Step 1: Search
    search_result = search_trade(intent, league=league, market=market)
    if search_result.get("error"):
        result.error = search_result["error"]
        logger.warning(f"Scan {base_en}: search failed — {result.error}")
        return result

    result.total_results = search_result.get("total_results", 0)
    trade_url = search_result.get("trade_url", "")
    item_ids = search_result.get("item_ids", [])

    if result.total_results == 0:
        logger.debug(f"Scan {base_en}: 0 results on market")
        return result

    # Step 2: Fetch up to 10 cheapest listings
    fetched = fetch_trade_listings(
        trade_url,
        market=market,
        league=league,
        item_ids=item_ids,
        count=10,
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
        if chaos_eq is None:
            # Unknown currency — record but skip for chaos calculation
            result.prices.append({"amount": amount, "currency": currency, "chaos_eq": None})
            continue
        result.prices.append({"amount": amount, "currency": currency, "chaos_eq": chaos_eq})
        chaos_prices.append(chaos_eq)

    if chaos_prices:
        result.cheapest_chaos = min(chaos_prices)
        result.median_chaos = median(chaos_prices)

    logger.info(
        f"Scan {base_en}: total={result.total_results}, "
        f"fetched={len(listings)}, priced={len(chaos_prices)}, "
        f"cheapest={result.cheapest_chaos}, median={result.median_chaos}"
    )
    return result


def scan_all_bases(
    market: str = "cn",
    league: str | None = None,
    min_price_chaos: float = 50.0,
    min_results: int = 3,
    max_bases: int | None = None,
    callback=None,
) -> ScanReport:
    """Scan all equipment base types and write results to DB.

    Args:
        market: "cn" or "global"
        league: league name (None = market default)
        min_price_chaos: cheapest listing must exceed this (in chaos eq)
        min_results: must have at least this many trade results
        max_bases: limit scan count (for testing)
        callback: optional callable(scanned, total, result) for progress reporting
    """
    from app.services.trade_realm import resolve_league

    batch_id = uuid.uuid4().hex[:12]
    resolved_league = resolve_league(market, league)
    bases = load_equipment_bases()

    if max_bases:
        bases = bases[:max_bases]

    report = ScanReport(
        batch_id=batch_id,
        market=market,
        league=resolved_league,
        total_bases=len(bases),
    )

    logger.info(
        f"Starting base scan batch={batch_id}: {len(bases)} bases, "
        f"market={market}, league={resolved_league}, "
        f"min_price={min_price_chaos}c, min_results={min_results}"
    )

    db = SessionLocal()
    try:
        for i, entry in enumerate(bases):
            en = (entry.get("text_en") or "").strip()
            cn = (entry.get("text_cn") or "").strip()
            gid = entry.get("_group_id", entry.get("group_id", ""))
            cat = entry.get("_category", "")

            result = scan_single_base(en, cn, cat, gid, market=market, league=league)

            # Determine high-value
            is_hv = (
                result.total_results >= min_results
                and result.cheapest_chaos is not None
                and result.cheapest_chaos >= min_price_chaos
            )
            result.is_high_value = is_hv

            # Write to DB
            snapshot = BasePriceSnapshot(
                base_name_en=result.base_name_en,
                base_name_cn=result.base_name_cn,
                item_category=result.item_category,
                group_id=result.group_id,
                market=market,
                league=resolved_league,
                total_results=result.total_results,
                cheapest_price_chaos=result.cheapest_chaos,
                median_price_chaos=result.median_chaos,
                prices_raw=result.prices,
                is_high_value=is_hv,
                scan_batch=batch_id,
            )
            db.add(snapshot)
            db.commit()

            report.scanned += 1
            if result.error:
                report.errors += 1
            if is_hv:
                report.high_value_count += 1
                report.high_value_bases.append(en)

            if callback:
                callback(report.scanned, report.total_bases, result)

            if report.scanned % 10 == 0:
                logger.info(
                    f"Scan progress: {report.scanned}/{report.total_bases} "
                    f"(high_value={report.high_value_count}, errors={report.errors})"
                )

    except Exception:
        logger.exception("Base scan interrupted")
        raise
    finally:
        db.close()
        report.finished_at = datetime.now(timezone.utc)

    logger.info(
        f"Scan complete: batch={batch_id}, scanned={report.scanned}, "
        f"high_value={report.high_value_count}, errors={report.errors}, "
        f"duration={report.finished_at - report.started_at}"
    )
    return report


def get_latest_high_value_bases(
    market: str = "cn",
    league: str | None = None,
) -> list[dict]:
    """Return the most recent high-value base list from DB."""
    from app.services.trade_realm import resolve_league

    resolved_league = resolve_league(market, league)
    db = SessionLocal()
    try:
        # Find the latest scan batch
        latest = (
            db.query(BasePriceSnapshot)
            .filter(
                BasePriceSnapshot.market == market,
                BasePriceSnapshot.league == resolved_league,
            )
            .order_by(BasePriceSnapshot.scanned_at.desc())
            .first()
        )
        if not latest:
            return []

        batch_id = latest.scan_batch

        # Fetch all high-value bases from that batch
        rows = (
            db.query(BasePriceSnapshot)
            .filter(
                BasePriceSnapshot.scan_batch == batch_id,
                BasePriceSnapshot.is_high_value == True,
            )
            .order_by(BasePriceSnapshot.cheapest_price_chaos.desc())
            .all()
        )
        return [
            {
                "name_en": r.base_name_en,
                "name_cn": r.base_name_cn,
                "category": r.item_category,
                "group_id": r.group_id,
                "cheapest_chaos": r.cheapest_price_chaos,
                "median_chaos": r.median_price_chaos,
                "total_results": r.total_results,
            }
            for r in rows
        ]
    finally:
        db.close()
