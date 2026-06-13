"""Apply PoB rare mod parsing fixes for BD cost (v2)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POB = ROOT / "app/services/pob_rare_trade.py"
MIP = ROOT / "app/services/multi_item_price.py"
TEST = ROOT / "tests/test_pob_rare_trade.py"


def patch_pob_rare_trade() -> list[str]:
    changes: list[str] = []
    text = POB.read_text(encoding="utf-8")

    extra_imports = ""
    if "_RARE_SEARCH_RELAX_RATIOS" not in text:
        anchor = "_MOD_SEP = re.compile"
        insert = textwrap_dedent = None
        block = '''

_IMPLICIT_LINE_RE = re.compile(r"^Implicits:\\s*(\\d+)\\s*$", re.IGNORECASE)
_CRAFTED_PREFIX_RE = re.compile(
    r"^\\{(crafted|fractured|enchant|crucible|mutated)\\}\\s*",
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
_RARE_SEARCH_RELAX_RATIOS: tuple[float, ...] = (0.85, 0.65, 0.45)
'''
        if anchor in text and "_IMPLICIT_LINE_RE" not in text:
            idx = text.index(anchor)
            end = text.index("\n", idx)
            text = text[: end + 1] + block + text[end + 1 :]
            changes.append("added rare-parse regex constants")

    new_parse = '''
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

        text = _CRAFTED_PREFIX_RE.sub("", text).strip()
        if not text:
            continue

        value: float | None = None
        is_pct = "%" in text
        m = re.match(r"^([+\\-]?\\d+(?:\\.\\d+)?)\\s*(?:to|%)\\s*(.+)$", text)
        if m:
            value = float(m.group(1))
        else:
            m2 = re.match(r"^(\\d+(?:\\.\\d+)?)%\\s+", text)
            if m2:
                value = float(m2.group(1))
        mods.append(PobMod(line=text, value=value, is_percent=is_pct))
    return mods
'''.strip("\n")

    m_parse = re.search(
        r"def parse_pob_item_mods\(raw: str\) -> list\[PobMod\]:[\s\S]*?\n    return mods\n",
        text,
    )
    n = 0
    if m_parse:
        text = text[: m_parse.start()] + new_parse + "\n" + text[m_parse.end() :]
        n = 1
        changes.append("replaced parse_pob_item_mods")

    helpers = '''

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
    for ratio in _RARE_SEARCH_RELAX_RATIOS:
        stat_groups = build_pob_rare_stat_groups(resolved, relax_ratio=ratio)
        if not stat_groups:
            continue
        attempts = (True, False) if base_type else (False,)
        for with_base in attempts:
            attempt = dict(intent)
            attempt["stat_groups"] = stat_groups
            if with_base and base_type:
                attempt["base_type"] = base_type
            else:
                attempt.pop("base_type", None)
            search = search_trade(attempt, league=league, market=market)
            last = search
            if search.get("error"):
                continue
            total = int(search.get("total_results") or 0)
            if total > 0 and search.get("trade_url"):
                return search
    return last
'''.lstrip("\n")

    if "_search_rare_with_fallback" not in text:
        marker = "\n\n\ndef _has_cjk(text: str) -> bool:"
        if marker in text:
            text = text.replace(marker, "\n\n" + helpers + "\n\ndef _has_cjk(text: str) -> bool:", 1)
            changes.append("added dedupe + rare search fallback helpers")

    text, n = re.subn(
        r"    return resolved, missed\n",
        "    return _dedupe_resolved_stats(resolved), missed\n",
        text,
        count=1,
    )
    if n:
        changes.append("resolve_pob_mods_to_stats returns deduped stats")

    old_quote_chunk = """    stat_groups = build_pob_rare_stat_groups(resolved)
    item_type = item_type_for_pob_item(slot, base_name)
    intent: dict[str, Any] = {
        \"rarity\": \"rare\",
        \"stat_groups\": stat_groups,
        \"summary\": f\"rare {label} ({base_name})\",
    }"""
    new_quote_chunk = """    item_type = item_type_for_pob_item(slot, base_name)
    intent: dict[str, Any] = {
        \"rarity\": \"rare\",
        \"summary\": f\"rare {label} ({base_name})\",
    }"""
    if old_quote_chunk in text:
        text = text.replace(old_quote_chunk, new_quote_chunk, 1)
        changes.append("quote intent no longer pins first relax tier")

    text, n = re.subn(
        r"    search = search_trade\(intent, league=league, market=market\)\n",
        "    search = _search_rare_with_fallback(resolved, intent, league=league, market=market)\n",
        text,
        count=1,
    )
    if n:
        changes.append("quote_pob_rare_sync uses fallback search")

    POB.write_text(text, encoding="utf-8")
    return changes


def patch_multi_item_price() -> list[str]:
    changes: list[str] = []
    text = MIP.read_text(encoding="utf-8")
    old = """    for item in data.items or []:
        if (item.rarity or "").upper() != "RARE":
            continue
        raw = (item.raw or "").strip()"""
    new = """    for item in data.items or []:
        if (item.rarity or "").upper() != "RARE":
            continue
        slot = (item.slot or "").strip()
        if not slot:
            continue
        raw = (item.raw or "").strip()"""
    if old in text and "if not slot:" not in text.split("_extract_rare_items")[1][:400]:
        text = text.replace(old, new, 1)
        changes.append("_extract_rare_items requires equipped slot")
        MIP.write_text(text, encoding="utf-8")
    elif "if not slot:" in text:
        changes.append("_extract_rare_items slot filter already present")
    else:
        changes.append("WARN: _extract_rare_items pattern not found")
    return changes


def patch_tests() -> list[str]:
    changes: list[str] = []
    text = TEST.read_text(encoding="utf-8")
    if "test_parse_pob_native_format_skips_header_and_implicit" in text:
        return ["test already present"]

    extra = '''

def test_parse_pob_native_format_skips_header_and_implicit():
    raw = """Rarity: RARE
Bramble Grip
Suede Bracers
Unique ID: 1
Item Level: 84
Quality: 0
Sockets: G-G-G
LevelReq: 52
Implicits: 1
+12% to Chaos Resistance
+88 to maximum Life
+42% to Fire Resistance
+36% to Lightning Resistance
+18% increased Attack Speed
+35% increased Critical Damage Bonus
Armour: 45
Evasion: 45
"""
    mods = parse_pob_item_mods(raw)
    assert len(mods) == 5
    lines = [m.line for m in mods]
    assert "+88 to maximum Life" in lines
    assert all("Chaos Resistance" not in ln for ln in lines)
    assert all(not ln.lower().startswith("armour:") for ln in lines)
'''
    TEST.write_text(text.rstrip() + extra + "\n", encoding="utf-8")
    changes.append("added Bramble Grip native-format parse test")
    return changes


def main() -> None:
    report: list[str] = []
    report.extend(patch_pob_rare_trade())
    report.extend(patch_multi_item_price())
    report.extend(patch_tests())
    print("apply_rare_parse_fix_v2:")
    for line in report:
        print(" -", line)


if __name__ == "__main__":
    main()
