"""PoB rare-item trade search: parse mods and build relaxed stat groups.

Pricing policy (BD cost from user PoB):
- Keep the same number of affixes (count_min == resolved mod count; never drop mods).
- Numeric thresholds may be lowered for non-skill mods (default 85% floor).
- Skill level mods: min must stay at PoB value (never lower; same or higher only).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

# PoB item text mods appear after the first "--------" separator.
_MOD_SEP = re.compile(r"^-{4,}\s*$", re.MULTILINE)
# +120 to maximum Life / 45% increased Fire Damage / +2 to Level of all Minion Skills
_MOD_NUM = re.compile(
    r"^([+\-]?\d+(?:\.\d+)?)\s*(?:to|%)\s*(.+)$|^(.+?)\s*([+\-]?\d+(?:\.\d+)?)\s*$"
)

_SKILL_LEVEL_MOD = re.compile(
    r"to Level of (?:all )?(?:\w+\s+)*Skills?",
    re.IGNORECASE,
)
_SKILL_LEVEL_STAT_IDS: frozenset[str] = frozenset(
    {
        "explicit.stat_2162097452",  # minion skills
        "explicit.stat_1428232057",  # spell skills
        "explicit.stat_4283407333",  # all skills
    }
)


@dataclass(frozen=True)
class PobMod:
    line: str
    value: float | None = None
    is_percent: bool = False


def parse_pob_item_mods(raw: str) -> list[PobMod]:
    """Extract explicit mod lines from PoB item raw text."""
    if not raw:
        return []
    parts = _MOD_SEP.split(raw, maxsplit=1)
    body = parts[1] if len(parts) > 1 else raw
    mods: list[PobMod] = []
    for line in body.splitlines():
        text = line.strip()
        if not text:
            continue
        low = text.lower()
        if low.startswith("item level:") or low.startswith("quality:"):
            continue
        if low.startswith("requirements:"):
            break
        value: float | None = None
        is_pct = "%" in text
        m = re.match(r"^([+\-]?\d+(?:\.\d+)?)\s*(?:to|%)\s*(.+)$", text)
        if m:
            value = float(m.group(1))
        else:
            m2 = re.match(r"^(\d+(?:\.\d+)?)%\s+", text)
            if m2:
                value = float(m2.group(1))
        mods.append(PobMod(line=text, value=value, is_percent=is_pct))
    return mods


def is_skill_level_mod(mod_line: str, stat_id: str | None = None) -> bool:
    if stat_id and stat_id in _SKILL_LEVEL_STAT_IDS:
        return True
    return bool(_SKILL_LEVEL_MOD.search(mod_line or ""))


def relax_mod_min(
    original_min: int | float | None,
    mod_line: str,
    stat_id: str | None = None,
    *,
    relax_ratio: float = 0.85,
) -> int | None:
    """Return Trade API min for one mod under BD pricing policy."""
    if original_min is None:
        return None
    orig = int(original_min)
    if is_skill_level_mod(mod_line, stat_id):
        return orig
    if orig <= 0:
        return orig
    relaxed = max(1, math.floor(orig * relax_ratio))
    return relaxed


def build_pob_rare_stat_groups(
    resolved_stats: list[dict[str, Any]],
    *,
    relax_ratio: float = 0.85,
) -> list[dict[str, Any]]:
    """Build stat_groups: COUNT with full mod count; per-mod relaxed mins."""
    stats: list[dict[str, Any]] = []
    for row in resolved_stats:
        stat_id = row.get("id")
        if not stat_id:
            continue
        mod_line = str(row.get("mod_line") or row.get("desc_en") or "")
        orig_min = row.get("min")
        min_val = relax_mod_min(orig_min, mod_line, stat_id, relax_ratio=relax_ratio)
        entry: dict[str, Any] = {"id": stat_id}
        if min_val is not None:
            entry["min"] = min_val
        if row.get("max") is not None:
            entry["max"] = row["max"]
        stats.append(entry)

    if not stats:
        return []

    return [
        {
            "type": "count",
            "count_min": len(stats),
            "stats": stats,
        }
    ]

POB_SLOT_TO_ITEM_TYPE: dict[str, str] = {
    "Amulet": "accessory.amulet",
    "Ring 1": "accessory.ring",
    "Ring 2": "accessory.ring",
    "Belt": "accessory.belt",
    "Body Armour": "armour.chest",
    "Helmet": "armour.helmet",
    "Gloves": "armour.gloves",
    "Boots": "armour.boots",
    "Shield": "armour.shield",
    "Quiver": "armour.quiver",
    "Flask 1": "flask",
    "Flask 2": "flask",
    "Flask 3": "flask",
    "Flask 4": "flask",
    "Flask 5": "flask",
}


def item_type_for_pob_item(slot: str | None, base_name: str) -> str | None:
    from app.services.trade_stats_index import ITEM_TYPES_EN

    if slot:
        s = slot.strip()
        if s in POB_SLOT_TO_ITEM_TYPE:
            return POB_SLOT_TO_ITEM_TYPE[s]
    base_lower = (base_name or "").lower()
    for keyword, (item_type, _name) in ITEM_TYPES_EN.items():
        if keyword in base_lower:
            return item_type
    if slot:
        sl = slot.lower()
        for keyword, (item_type, _name) in ITEM_TYPES_EN.items():
            if keyword in sl:
                return item_type
    return None


def _mod_min_value(mod: PobMod) -> int | float | None:
    if mod.value is not None:
        return int(mod.value) if mod.value == int(mod.value) else mod.value
    m = re.match(r"^(\d+(?:\.\d+)?)%\s+", mod.line)
    if m:
        return int(float(m.group(1)))
    return None


def resolve_pob_mods_to_stats(mods: list[PobMod]) -> tuple[list[dict[str, Any]], list[str]]:
    from app.core.database import SessionLocal
    from app.services.trade_service import _resolve_stat
    from app.services.trade_stats_index import find_stat_id

    db = SessionLocal()
    resolved: list[dict[str, Any]] = []
    missed: list[str] = []
    try:
        for mod in mods:
            line = mod.line.strip()
            if not line:
                continue
            stat_id = find_stat_id(line)
            row: dict[str, Any] = {"mod_line": line}
            min_val = _mod_min_value(mod)
            if min_val is not None:
                row["min"] = min_val
            if stat_id:
                row["id"] = stat_id if stat_id.startswith("explicit.") else f"explicit.{stat_id.split('.')[-1]}"
            else:
                matched = _resolve_stat(db, {"desc_en": line, **({"min": min_val} if min_val is not None else {})})
                if matched:
                    row["id"] = matched["id"]
                    if matched.get("min") is not None and "min" not in row:
                        row["min"] = matched["min"]
            if row.get("id"):
                resolved.append(row)
            else:
                missed.append(line)
    finally:
        db.close()
    return resolved, missed


def quote_pob_rare_sync(
    label: str,
    raw: str,
    slot: str | None,
    base_name: str,
    market: str = "cn",
    league: str | None = None,
) -> dict[str, Any]:
    from app.services.trade_service import fetch_cheapest_listing, search_trade

    mods = parse_pob_item_mods(raw)
    if not mods:
        return {"item": label, "error": "未解析到词缀"}

    resolved, missed = resolve_pob_mods_to_stats(mods)
    if not resolved:
        return {"item": label, "error": "词缀无法映射到 Trade stat_id"}

    stat_groups = build_pob_rare_stat_groups(resolved)
    item_type = item_type_for_pob_item(slot, base_name)
    intent: dict[str, Any] = {
        "rarity": "rare",
        "stat_groups": stat_groups,
        "summary": f"rare {label} ({base_name})",
    }
    if item_type:
        intent["item_type"] = item_type
    if base_name:
        intent["base_type"] = base_name

    search = search_trade(intent, league=league, market=market)
    trade_data = {
        "best_match": (
            {
                "label": f"{label} ({search.get('total_results', 0)} 条)",
                "url": search.get("trade_url"),
                "count": search.get("total_results", 0),
            }
            if search.get("trade_url")
            else None
        ),
        "alternatives": [],
        "explanation": search.get("intent_summary") or intent["summary"],
    }
    base: dict[str, Any] = {
        "item": label,
        "trade_result": trade_data,
        "mods_total": len(mods),
        "mods_matched": len(resolved),
        "mods_missed": missed[:3],
    }
    if search.get("error"):
        base["error"] = search["error"]
        return base
    if not search.get("trade_url"):
        base["error"] = "未找到交易结果"
        return base

    listing = fetch_cheapest_listing(
        search["trade_url"],
        market=market,
        league=league,
        skip_rate_limit=True,
        item_ids=search.get("item_ids"),
    )
    if listing.get("error"):
        base["error"] = listing["error"]
        return base
    base.update(
        {
            "amount": listing.get("amount"),
            "currency": listing.get("currency"),
            "item_name": listing.get("item_name"),
        }
    )
    return base
