"""PoB rare-item trade search: parse mods and build relaxed stat groups.

Pricing policy (BD cost from user PoB):
- Keep the same number of affixes (count_min == resolved mod count; never drop mods).
- Numeric thresholds may be lowered for non-skill mods (default 85% floor).
- Skill level mods: min must stay at PoB value (never lower; same or higher only).
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any

# PoB item text mods appear after the first "--------" separator.
_MOD_SEP = re.compile(r"^-{4,}\s*$", re.MULTILINE)


_IMPLICIT_LINE_RE = re.compile(r"^Implicits:\s*(\d+)\s*$", re.IGNORECASE)
_CRAFTED_PREFIX_RE = re.compile(
    r"^\{(crafted|fractured|enchant|crucible|mutated|desecrated)\}\s*",
    re.IGNORECASE,
)
_POB_META_LINE_RE = re.compile(
    r"^(unique id|item level|quality|sockets|levelreq|link count|colour|corrupted|mirrored|split|fractured item|influences|note):",
    re.IGNORECASE,
)
_BASE_STAT_LINE_RE = re.compile(
    r"^(armour|evasion|energy shield|ward|block|spirit|attacks per second|physical damage|elemental damage|critical hit chance|chance to block):",
    re.IGNORECASE,
)
_RARE_SEARCH_PLANS: tuple[tuple[float, bool], ...] = (
    (0.85, True),
    (0.65, False),
)
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
    if len(parts) > 1:
        lines = parts[1].splitlines()
        start = 0
    else:
        lines = raw.splitlines()
        start = min(3, len(lines))

    mods: list[PobMod] = []
    skip_implicit = 0
    for line in lines[start:]:
        text = line.strip()
        if not text:
            continue
        low = text.lower()
        if low.startswith("requirements:"):
            break

        implicit_m = _IMPLICIT_LINE_RE.match(text)
        if implicit_m:
            skip_implicit = int(implicit_m.group(1))
            continue
        if skip_implicit > 0:
            skip_implicit -= 1
            continue

        if _POB_META_LINE_RE.match(text):
            continue
        if _BASE_STAT_LINE_RE.match(text):
            continue
        if low.startswith("rune:") or low.startswith("charm slots:"):
            continue

        text = _CRAFTED_PREFIX_RE.sub("", text).strip()
        if not text:
            continue

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


def _dedupe_resolved_stats(stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in stats:
        stat_id = row.get("id")
        if not stat_id:
            continue
        if stat_id not in by_id:
            by_id[stat_id] = dict(row)
            order.append(stat_id)
            continue
        prev = by_id[stat_id]
        prev_min = prev.get("min")
        new_min = row.get("min")
        if new_min is not None and (prev_min is None or new_min > prev_min):
            prev["min"] = new_min
        if row.get("mod_line"):
            prev["mod_line"] = row["mod_line"]
    return [by_id[sid] for sid in order]


def _search_rare_with_fallback(
    resolved: list[dict[str, Any]],
    intent: dict[str, Any],
    *,
    league: str | None,
    market: str,
) -> dict[str, Any]:
    from app.services.trade_service import search_trade

    base_type = intent.get("base_type")
    last: dict[str, Any] = {}
    for relax_ratio, use_base in _RARE_SEARCH_PLANS:
        if use_base and not base_type:
            continue
        stat_groups = build_pob_rare_stat_groups(resolved, relax_ratio=relax_ratio)
        if not stat_groups:
            continue
        attempt = dict(intent)
        attempt["stat_groups"] = stat_groups
        if use_base and base_type:
            attempt["base_type"] = base_type
        else:
            attempt.pop("base_type", None)
        search = search_trade(attempt, league=league, market=market)
        last = search
        if search.get("rate_limited"):
            return search
        if search.get("error"):
            continue
        total = int(search.get("total_results") or 0)
        if total > 0 and search.get("trade_url"):
            return search
    return last


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def _data_dir() -> str:
    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    return data_dir


_base_en_cn_cache: dict[str, str] | None = None


def _load_base_en_cn_map() -> dict[str, str]:
    global _base_en_cn_cache
    if _base_en_cn_cache is not None:
        return _base_en_cn_cache
    mapping: dict[str, str] = {}
    here = os.path.dirname(__file__)
    candidates = [
        os.path.join(_data_dir(), "base_en_cn.json"),
        os.path.join(here, "..", "data", "base_en_cn.json"),
        os.path.join(here, "..", "..", "data", "base_en_cn.json"),
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        raw = payload.get("en_to_cn") if isinstance(payload, dict) else None
        if isinstance(raw, dict):
            mapping = {str(k).strip(): str(v).strip() for k, v in raw.items() if k and v}
            break
    _base_en_cn_cache = mapping
    return mapping


def resolve_base_type_cn(en_base: str) -> str | None:
    """Map PoB/Trade EN base type to CN realm trade type string."""
    raw = (en_base or "").strip()
    if not raw:
        return None
    if _has_cjk(raw):
        return raw
    hit = _load_base_en_cn_map().get(raw)
    if hit:
        return hit
    lower = raw.lower()
    for key, val in _load_base_en_cn_map().items():
        if key.lower() == lower:
            return val
    return None

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
    return _dedupe_resolved_stats(resolved), missed


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

    item_type = item_type_for_pob_item(slot, base_name)
    intent: dict[str, Any] = {
        "rarity": "rare",
        "summary": f"rare {label} ({base_name})",
    }
    if item_type:
        intent["item_type"] = item_type
    if base_name:
        if market == "cn":
            cn_base = resolve_base_type_cn(base_name)
            if cn_base:
                intent["base_type"] = cn_base
        else:
            intent["base_type"] = base_name

    search = _search_rare_with_fallback(resolved, intent, league=league, market=market)
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
        if search.get("rate_limited"):
            base["rate_limited"] = True
        return base
    if not search.get("trade_url"):
        base["error"] = "未找到交易结果"
        return base

    total_results = int(search.get("total_results") or 0)
    item_ids = search.get("item_ids") or []
    if total_results == 0 or not item_ids:
        base["no_listing"] = True
        base["note"] = "市集中暂无完全匹配的在售物品"
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
        if listing.get("rate_limited"):
            base["rate_limited"] = True
        return base
    base.update(
        {
            "amount": listing.get("amount"),
            "currency": listing.get("currency"),
            "item_name": listing.get("item_name"),
        }
    )
    return base
