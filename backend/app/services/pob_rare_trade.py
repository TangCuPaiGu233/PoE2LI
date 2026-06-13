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
