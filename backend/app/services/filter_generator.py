"""Filter generator — inverted logic: show everything, hide confirmed-cheap items.

Strategy: the asmco template already has comprehensive Show rules for valuable
items (currency tiers, unique catch-all, gem sockets, ilvl≥82 white bases).
We only add Hide rules for items confirmed cheap via Trade API price scan
(price < threshold, default 2E ≈ 16c).  Items without price data or above
threshold follow template rules — no risk of hiding valuable items.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

# ── Template filter file paths ──
_FILTER_TEMPLATE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "filter_templates")
)
_USER_FILTER_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "generated_filters")
)

# Injection marker — we insert BEFORE this section header
_INJECT_MARKER = "#=========================全域隐藏========================="

# Output marker for the generated block
_GENERATED_HEADER = "#======[AI 自动更新] 高价值白装底材 ======#"
_GENERATED_PRICE_HEADER = "#======[AI 价格分级] 多品类价格 ======#"
_GENERATED_FALLBACK_HEADER = "#======[AI 保底高亮] 白底兜底 ======#"
_GENERATED_HIDE_HEADER = "#======[AI 智能隐藏] 确认低价物品 ======#"

# Hide threshold: items cheaper than this (in chaos) are hidden.
# PoE2 economy: 1D ≈ 8.5c, Chaos Orb = 1c (base unit).
# 0.5c ≈ 12E ≈ 0.06D — hides cheap junk while keeping most usable items visible.
_HIDE_PRICE_CHAOS_THRESHOLD = 0.5

# Currencies that must NEVER be hidden regardless of price.
# Chaos Orb is the base trading unit; Gemcutter's Prism and Vaal Orb
# are core crafting currencies — cheap in PoE2 but always relevant.
_NEVER_HIDE_CURRENCIES = frozenset({
    "Chaos Orb",
    "Gemcutter's Prism",
    "Vaal Orb",
    "Mirror of Kalandra",
    "Hinekora's Lock",
})

# ── Visual tier styles ──
# Follows asmco color hierarchy: 遗产>传奇>红色>粉色>黄色>绿色>蓝色>白色
_TIER_STYLES = {
    "top": {  # 极高价值 (≥5D = 750c)
        "text_color": "212 145 63",     # 遗产色
        "border_color": "212 145 63",
        "font_size": 50,
        "sound_file": "AlertSound_09.wav",
        "sound_volume": 300,
        "minimap": "0 Red Star",
        "beam": "Red",
        "label": "极高价值",
    },
    "high": {  # 高价值 (≥1D = 150c)
        "text_color": "255 0 255",      # 粉色
        "border_color": "255 0 255",
        "font_size": 45,
        "sound_file": "AlertSound_07.wav",
        "sound_volume": 200,
        "minimap": "1 Yellow Circle",
        "beam": "Yellow",
        "label": "高价值",
    },
    "mid": {  # 中等价值 (≥50c)
        "text_color": "74 230 58",      # 绿色
        "border_color": "74 230 58",
        "font_size": 40,
        "sound_file": "AlertSound_07.wav",
        "sound_volume": 200,
        "minimap": "2 Cyan Triangle",
        "beam": "Cyan",
        "label": "中等价值",
    },
}

# Price thresholds for tier classification (in chaos equivalent)
_TIER_THRESHOLDS = [
    (750.0, "top"),     # ≥5 divine
    (150.0, "high"),    # ≥1 divine
    (0.0, "mid"),       # anything above min_price_chaos
]

# ═══════════════════════════════════════════════════════════
#  Multi-category price tier system (S/A/B)
# ═══════════════════════════════════════════════════════════

_PRICE_TIER_STYLES = {
    "S": {  # 极高价值 (≥5D)
        "text_color": "212 145 63",     # 遗产金
        "border_color": "212 145 63",
        "font_size": 55,
        "sound_file": "AlertSound_09.wav",
        "sound_volume": 300,
        "minimap": "0 Red Star",
        "beam": "Red",
        "label": "S级",
    },
    "A": {  # 高价值 (≥1D)
        "text_color": "255 0 255",      # 粉色
        "border_color": "255 0 255",
        "font_size": 45,
        "sound_file": "AlertSound_07.wav",
        "sound_volume": 250,
        "minimap": "1 Yellow Circle",
        "beam": "Yellow",
        "label": "A级",
    },
    "B": {  # 中等价值 (≥0.3D)
        "text_color": "74 230 58",      # 绿色
        "border_color": "74 230 58",
        "font_size": 40,
        "sound_file": "AlertSound_07.wav",
        "sound_volume": 200,
        "minimap": "2 Cyan Triangle",
        "beam": "Cyan",
        "label": "B级",
    },
}

# Divine-based thresholds (1D = 1 divine orb)
_PRICE_TIER_THRESHOLDS = [
    (5.0, "S"),
    (1.0, "A"),
    (0.0, "B"),
]

# Per-category filter conditions and display metadata
_CATEGORY_CONFIG = {
    # Currency subcategories (all share Class "Stackable Currency")
    "currency_orb":         {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 宝珠"},
    "currency_essence":     {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 精华"},
    "currency_rune":        {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 符文"},
    "currency_catalyst":    {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 催化剂"},
    "currency_distillate":  {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 蒸馏液"},
    "currency_soul_core":   {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 灵魂核心"},
    "currency_omen":        {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 预兆"},
    "currency_misc":        {"class": '"Stackable Currency"', "display_group": "currency", "display_name": "通货 — 其他"},
    # Unique equipment
    "unique_jewel":         {"class": '"Jewel"',              "display_group": "unique_jewel",    "display_name": "暗金珠宝",   "rarity": "Unique"},
    "unique_weapon":        {"class": '"Weapons"',            "display_group": "unique_weapon",   "display_name": "暗金武器",   "rarity": "Unique"},
    "unique_armour":        {"class": '"Armour"',             "display_group": "unique_armour",   "display_name": "暗金护甲",   "rarity": "Unique"},
    "unique_accessory":     {"class": '"Accessories"',        "display_group": "unique_accessory","display_name": "暗金饰品",   "rarity": "Unique"},
    # Gems
    "skill_gem":            {"class": '"Skill Gems"',         "display_group": "gem",  "display_name": "技能宝石"},
    "support_gem":          {"class": '"Support Gems"',       "display_group": "gem",  "display_name": "辅助宝石"},
    # White bases
    "white_base":           {"display_group": "white_base",   "display_name": "高价值白装底材"},
}

# Display group ordering and labels (controls output section order)
_DISPLAY_GROUP_ORDER = [
    ("currency",         "通货 (精华/符文/催化剂/宝珠)"),
    ("unique_jewel",     "暗金珠宝"),
    ("unique_weapon",    "暗金武器"),
    ("unique_armour",    "暗金护甲"),
    ("unique_accessory", "暗金饰品"),
    ("gem",              "技能宝石 & 辅助宝石"),
    ("white_base",       "高价值白装底材"),
]


def _classify_tier(cheapest_chaos: float) -> str:
    """Classify a base into a visual tier based on cheapest price."""
    for threshold, tier in _TIER_THRESHOLDS:
        if cheapest_chaos >= threshold:
            return tier
    return "mid"


# BaseTypes that the CN PoE2 client cannot parse (item not in game or renamed).
# Items in this list are skipped during filter generation to avoid "BaseType 无法解析" errors.
_INVALID_BASETYPES = {
    "Undying Hate",       # 不朽之恨 — unique jewel not recognized by CN client
    "Runeseekers Call",   # 符文猎手的呼唤 — unique armour not recognized by CN client
    "Heroic Tragedy",     # 英雄的悲歌 — unique jewel not recognized by CN client
    "Periphery",          # 边缘 — unique weapon not recognized by CN client
    "The Hammer of Faith",# 信仰之锤 — unique weapon not recognized by CN filter parser
    "Guiding Palm of the Eye",  # 眼目之指引之掌 — unique weapon not recognized by CN filter parser
    "Spire of Ire",            # 怨怒塔矛 — unique weapon not recognized by CN filter parser
    "Doomfletch",              # 灭世 — unique weapon not recognized by CN filter parser
    "Sacred Flame",            # 神圣之火 — unique weapon not recognized by CN filter parser
    "The Last Lament",         # 末后哀歌 — unique weapon not recognized by CN filter parser
    "Tidebreaker",             # 局势逆转者 — unique weapon not recognized by CN filter parser
    "Guiding Palm of the Heart",# 心脏之指引之掌 — unique weapon not recognized by CN filter parser
    "Voltaxic Rift",           # 魔暴之痕 — unique weapon not recognized by CN filter parser
    "Collapsing Horizon",      # 崩塌视界 — unique weapon not recognized by CN filter parser
    "Split Personality",       # 人格分裂 — unique jewel not recognized by CN filter parser
}

# ── GGPK Words validation ──
# Load EN Words table from GGPK data to check if unique item names exist in game.
# Items not in Words are definitely not in the CN client (PoE1 leftovers, etc.).
_words_cache: set[str] | None = None


def _load_words_set() -> set[str]:
    """Load all English Text values from GGPK Words table (lazy, cached)."""
    global _words_cache
    if _words_cache is not None:
        return _words_cache
    words_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "poe2_data", "en", "Words.json"
    )
    if not os.path.exists(words_path):
        logger.warning(f"Words.json not found at {words_path}, skipping validation")
        _words_cache = set()
        return _words_cache
    try:
        with open(words_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _words_cache = {
            entry.get("Text", "").strip()
            for entry in data
            if entry.get("Text")
        }
        logger.info(f"Loaded {len(_words_cache)} entries from Words.json")
    except Exception as e:
        logger.warning(f"Failed to load Words.json: {e}")
        _words_cache = set()
    return _words_cache


def _is_valid_basetype(name_en: str) -> bool:
    """Check if a BaseType name is recognized by the CN client.

    Uses two checks:
    1. Not in _INVALID_BASETYPES (known failures)
    2. Present in GGPK Words table (PoE2 game data)
    """
    if name_en in _INVALID_BASETYPES:
        return False
    words = _load_words_set()
    if words and name_en not in words:
        return False
    return True

# Known low-value junk BaseTypes — always hide unless an earlier Show rule matched.
# Shards (currency fragments), common scrolls, and vendor trash.
_JUNK_BASETYPES = [
    # Currency shards (碎片)
    "Transmutation Shard",
    "Chance Shard",
    "Regal Shard",
    "Artificer's Shard",
    # Common scrolls (卷轴)
    "Scroll of Wisdom",
    "Portal Scroll",
    # Vendor trash
    "Blacksmith's Whetstone",
    "Armourer's Scrap",
]


def _generate_junk_hide_section() -> str:
    """Generate Hide rules for known low-value junk items.

    Appended at the very end of the filter so template Show rules take priority
    (first-match-wins). Only items NOT matched by any earlier Show rule reach here.
    """
    base_type_str = " ".join(f'"{bt}"' for bt in _JUNK_BASETYPES)
    return f"""
#======[AI 定向隐藏] 已知垃圾物品 ======
#碎片、卷轴、磨刀石等低价值杂物 — 仅隐藏未被模板Show规则匹配的物品
Hide
    BaseType {base_type_str}

#======[AI 定向隐藏] 已知垃圾物品 ======
"""


# ── Equipment classes for white base fallback ──
_EQUIPMENT_CLASSES = (
    '"Gloves" "Boots" "Body Armours" "Helmets" '
    '"Shields" "Bucklers" "Foci" "Quivers" '
    '"Rings" "Amulets" "Belts" '
    '"Claws" "Daggers" "Wands" "One Hand Swords" "One Hand Axes" "One Hand Maces" '
    '"Sceptres" "Spears" "Flails" '
    '"Bows" "Staves" "Two Hand Swords" "Two Hand Axes" "Two Hand Maces" '
    '"Quarterstaves" "Crossbows"'
)


def _generate_fallback_section() -> str:
    """Generate fallback Show rules for white equipment bases.

    Only white (Normal) equipment items get a fallback highlight for
    crafting base identification. Unique items are NOT given a blanket
    fallback — only items with confirmed prices from the Trade API are
    shown (via AI price blocks). This avoids including PoE1 unique items
    whose BaseTypes the CN filter parser cannot resolve.

    First-match-wins: specific AI price rules above will match first for priced items.
    """
    return f"""
{_GENERATED_FALLBACK_HEADER}
#白底保底: 所有普通(白底)装备 — 用于Crafting基底识别
Show
    Rarity = Normal
    Class {_EQUIPMENT_CLASSES}
    SetTextColor 255 255 255
    SetBorderColor 200 200 200
    SetFontSize 38
    MinimapIcon 2 White Circle

{_GENERATED_FALLBACK_HEADER}
"""


def generate_cheap_hide_blocks(
    snapshots: list[dict],
    hide_threshold_chaos: float = _HIDE_PRICE_CHAOS_THRESHOLD,
    item_level_min: int = 82,
) -> str:
    """Generate Hide rules for items confirmed cheap (price < threshold).

    Strategy: default-show, only hide items with confirmed low prices.
    - Economy items (currency, fragments, essences, runes, etc.) grouped by
      category sub-type → separate Hide blocks per group, each with BaseType
    - Gems (skill/support) → Hide by BaseType + Class
    - White bases → Hide by Rarity + Class + ItemLevel
    - Unique equipment → skipped (template handles via Rarity = Unique)

    These Hide blocks are injected BEFORE the template's Show rules so that
    first-match-wins catches cheap items here, while valuable items pass
    through to the template's styled Show rules below.
    """
    cheap = [
        s for s in snapshots
        if (s.get("chaos_price") or s.get("cheapest_chaos") or 0) > 0
        and (s.get("chaos_price") or s.get("cheapest_chaos") or 0) < hide_threshold_chaos
        and s.get("name_en", "") not in _NEVER_HIDE_CURRENCIES
    ]
    if not cheap:
        return ""

    # Group by high-level category
    economy_groups: dict[str, list[dict]] = {}
    gem_items: list[dict] = []
    white_base_items: list[dict] = []

    # Display names for category groups
    _CAT_LABELS = {
        "currency_orb": "通货",
        "currency_fragment": "碎片",
        "currency_abyssal_bone": "深渊骸骨",
        "currency_uncut_gem": "未切割宝石",
        "currency_lineage_gem": "传承宝石",
        "currency_essence": "精华",
        "currency_soul_core": "灵魂核心",
        "currency_idol": "神像",
        "currency_rune": "符文",
        "currency_omen": "预兆",
        "currency_expedition": "远征",
        "currency_liquid_emotion": "蒸馏情绪",
        "currency_catalyst": "催化剂",
        "currency_verisium": "矿合金",
    }

    for s in cheap:
        cat = s.get("category", "")
        if cat.startswith("currency_"):
            economy_groups.setdefault(cat, []).append(s)
        elif cat in ("skill_gem", "support_gem"):
            gem_items.append(s)
        elif cat == "white_base":
            white_base_items.append(s)
        # unique_* skipped — cannot target individual items without class data

    total = sum(len(v) for v in economy_groups.values()) + len(gem_items) + len(white_base_items)

    blocks: list[str] = [f"\n{_GENERATED_HIDE_HEADER}"]
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    blocks.append(f"#扫描时间: {scan_date}")
    # Use live divine rate for accurate comment display
    _divine_rate = 8.5
    try:
        from app.services.poe_ninja_service import get_divine_chaos_rate
        _r = get_divine_chaos_rate()
        if _r and _r > 0:
            _divine_rate = _r
    except Exception:
        pass
    blocks.append(f"#隐藏确认低价物品 (<{hide_threshold_chaos:g}c ≈ {hide_threshold_chaos/_divine_rate:.1f}D)")
    blocks.append(f"#共 {total} 个低价物品被隐藏\n")

    # ── Economy groups (currency, fragments, essences, runes, etc.) ──
    # Each group gets its own Hide block with BaseType only.
    # BaseType names from poe.ninja are standard PoE2 items — always valid
    # in the CN filter parser. No Class restriction (different item types
    # may use different Class values).
    for cat_key in sorted(economy_groups.keys()):
        items = economy_groups[cat_key]
        items.sort(key=lambda x: x.get("chaos_price") or x.get("cheapest_chaos") or 0)
        label = _CAT_LABELS.get(cat_key, cat_key.replace("currency_", ""))

        names = " ".join(f'"{it["name_en"]}"' for it in items)
        cn_parts = [
            f'{(it.get("name_cn") or it["name_en"])}({it.get("chaos_price") or it.get("cheapest_chaos") or 0:.0f}c)'
            for it in items
        ]
        blocks.append(f"#── 低价{label} ({len(items)}个) ──")
        blocks.append(f"# {', '.join(cn_parts)}")
        blocks.append(f"""Hide
    BaseType {names}
""")

    # ── Gems ──
    if gem_items:
        gem_items.sort(key=lambda x: x.get("chaos_price") or x.get("cheapest_chaos") or 0)
        names = " ".join(f'"{it["name_en"]}"' for it in gem_items)
        cn_parts = [
            f'{(it.get("name_cn") or it["name_en"])}({it.get("chaos_price") or it.get("cheapest_chaos") or 0:.0f}c)'
            for it in gem_items
        ]
        blocks.append(f"#── 低价宝石 ({len(gem_items)}个) ──")
        blocks.append(f"# {', '.join(cn_parts)}")
        blocks.append(f"""Hide
    BaseType {names}
    Class "Skill Gems" "Support Gems"
""")

    # ── White bases ──
    if white_base_items:
        white_base_items.sort(key=lambda x: x.get("chaos_price") or x.get("cheapest_chaos") or 0)
        cn_parts = [
            f'{(it.get("name_cn") or it["name_en"])}({it.get("chaos_price") or it.get("cheapest_chaos") or 0:.0f}c)'
            for it in white_base_items
        ]
        blocks.append(f"#── 低价白装底材 ({len(white_base_items)}个) ──")
        blocks.append(f"# {', '.join(cn_parts)}")
        blocks.append(f"""Hide
    Rarity = Normal
    Class {_EQUIPMENT_CLASSES}
    ItemLevel >= {item_level_min}
""")

    blocks.append(_GENERATED_HIDE_HEADER)
    blocks.append("")
    return "\n".join(blocks)


def _load_filter_template(template_path: str) -> str:
    """Load a filter template file."""
    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Filter template not found: {template_path}")
    with open(template_path, encoding="utf-8") as f:
        return f.read()


def _find_inject_point(lines: list[str]) -> int:
    """Find the line index just before the 全域隐藏 section."""
    for i, line in enumerate(lines):
        if _INJECT_MARKER in line:
            return i
    # Fallback: insert before the last 20 lines
    return max(0, len(lines) - 20)


def _find_price_inject_point(lines: list[str]) -> int:
    """Find the line just before the first Show block that matches currency/uniques/gems.

    PoE2 filter uses first-match-wins, so our AI price rules must appear BEFORE
    the template's own currency/unique/gem rules to take effect.
    """
    # Look for the first Show block containing Stackable Currency, Unique, or Gem conditions
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Show" and i > 0:
            # Peek ahead up to 15 lines for relevant conditions
            for j in range(i + 1, min(i + 16, len(lines))):
                peek = lines[j].strip()
                if peek.startswith("Show") or peek.startswith("Hide"):
                    break  # end of this block
                if any(kw in peek for kw in (
                    'Class "Stackable Currency"',
                    'Rarity = Unique',
                    'Class "Skill Gems"',
                    'Class "Support Gems"',
                    'Class "Jewel"',
                )):
                    return i
    # Fallback: after comments, before first Show
    for i, line in enumerate(lines):
        if line.strip() == "Show":
            return i
    return 0


def _remove_previous_generated_block(content: str) -> str:
    """Remove any previously generated blocks (white bases + multi-category prices + fallback + hide)."""
    # Remove white-base block
    content = re.sub(
        rf"\n?{re.escape(_GENERATED_HEADER)}.*?{re.escape(_GENERATED_HEADER)}\s*\n",
        "\n", content, flags=re.DOTALL,
    )
    # Remove multi-category price block
    content = re.sub(
        rf"\n?{re.escape(_GENERATED_PRICE_HEADER)}.*?{re.escape(_GENERATED_PRICE_HEADER)}\s*\n",
        "\n", content, flags=re.DOTALL,
    )
    # Remove fallback block (current + old header formats)
    content = re.sub(
        rf"\n?{re.escape(_GENERATED_FALLBACK_HEADER)}.*?{re.escape(_GENERATED_FALLBACK_HEADER)}\s*\n",
        "\n", content, flags=re.DOTALL,
    )
    # Remove cheap-hide block
    content = re.sub(
        rf"\n?{re.escape(_GENERATED_HIDE_HEADER)}.*?{re.escape(_GENERATED_HIDE_HEADER)}\s*\n",
        "\n", content, flags=re.DOTALL,
    )
    # Remove junk-hide block
    content = re.sub(
        r"\n?#======\[AI 定向隐藏\] 已知垃圾物品 ======.*?#======\[AI 定向隐藏\] 已知垃圾物品 ======\s*\n",
        "\n", content, flags=re.DOTALL,
    )
    # Also remove old fallback header format (暗金/白底兜底)
    content = re.sub(
        r"\n?#======\[AI 保底高亮\] 暗金/白底兜底 ======#.*?#======\[AI 保底高亮\] 暗金/白底兜底 ======#\s*\n",
        "\n", content, flags=re.DOTALL,
    )
    # Also remove the old hand-added fallback section (before markers were introduced)
    content = re.sub(
        r"\n?#=========================\[AI 保底高亮\]=========================.*?(?=#=========================全域隐藏=========================)",
        "\n", content, flags=re.DOTALL,
    )
    return content


def generate_show_block(bases: list[dict], item_level_min: int = 82) -> str:
    """Generate Show rule blocks for high-value bases, grouped by tier.

    Args:
        bases: list of {name_en, name_cn, cheapest_chaos, ...} dicts
        item_level_min: minimum item level filter (default 82 for endgame)
    """
    if not bases:
        return ""

    # Group bases by tier
    tier_groups: dict[str, list[dict]] = {"top": [], "high": [], "mid": []}
    for base in bases:
        price = base.get("cheapest_chaos") or base.get("chaos_price") or 0
        tier = _classify_tier(price)
        tier_groups[tier].append(base)

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks = [f"\n{_GENERATED_HEADER}"]
    blocks.append(f"#扫描时间: {scan_date}")
    blocks.append(f"#共计 {len(bases)} 个高价值白装底材，按价格分为 {sum(1 for v in tier_groups.values() if v)} 档\n")

    for tier_name in ("top", "high", "mid"):
        tier_bases = tier_groups[tier_name]
        if not tier_bases:
            continue

        style = _TIER_STYLES[tier_name]
        # Sort by price descending within tier
        tier_bases.sort(key=lambda b: b.get("cheapest_chaos") or b.get("chaos_price") or 0, reverse=True)

        # Build BaseType string
        base_type_str = " ".join(f'"{b["name_en"]}"' for b in tier_bases)

        # Build CN comment
        cn_names = ", ".join(
            f'{b["name_cn"]}({b.get("cheapest_chaos") or b.get("chaos_price") or 0:.0f}c)'
            for b in tier_bases
            if b.get("name_cn")
        )

        block = f"""#── {style['label']}底材 ({len(tier_bases)}个) ──
#中文: {cn_names}
Show
    BaseType {base_type_str}
    ItemLevel >= {item_level_min}
    Rarity < Magic
    Mirrored False
    Corrupted False
    SetTextColor {style['text_color']}
    SetBorderColor {style['border_color']}
    SetFontSize {style['font_size']}
    CustomAlertSound "{style['sound_file']}" {style['sound_volume']}
    MinimapIcon {style['minimap']}
    PlayEffect {style['beam']}
    DisableDropSound
"""
        blocks.append(block)

    blocks.append(_GENERATED_HEADER)
    blocks.append("")
    return "\n".join(blocks)


def generate_hide_block(items: list[dict]) -> str:
    """Generate Hide rule blocks for deprecated items.

    Args:
        items: list of {base_name_en, reason} dicts to hide
    """
    if not items:
        return ""

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_names = " ".join(f'"{item["base_name_en"]}"' for item in items)

    return f"""
#======[AI 自动更新] 已贬值物品 ({scan_date})======#
#这些物品市场价极低，自动隐藏以减少视觉干扰
Hide
    BaseType {base_names}
    DisableDropSound
"""


# ═══════════════════════════════════════════════════════════
#  Multi-category price-tier block generation
# ═══════════════════════════════════════════════════════════


def _classify_price_tier(divine_price: float | None) -> str:
    """Classify an item into S / A / B tier based on divine orb price."""
    price = divine_price or 0
    for threshold, tier in _PRICE_TIER_THRESHOLDS:
        if price >= threshold:
            return tier
    return "B"


def generate_price_tier_blocks(
    snapshots: list[dict],
    min_price_divine: float = 0.3,
    item_level_min: int = 82,
) -> str:
    """Generate Show blocks for multi-category priced items, grouped by display_group and S/A/B tier.

    Prices are classified in divine orbs (D). Chaos prices are converted via
    poe.ninja live rate at generation time.

    Args:
        snapshots: list of dicts with keys: name_en, name_cn, category, chaos_price (or cheapest_chaos)
        min_price_divine: minimum divine price to include an item (default 0.3D = B-tier floor)
        item_level_min: minimum item level for white base rules (default 82)
    """
    if not snapshots:
        return ""

    # Get live divine rate to convert chaos → divine
    divine_rate = 8.73  # fallback
    try:
        from app.services.poe_ninja_service import get_divine_chaos_rate
        rate = get_divine_chaos_rate()
        if rate and rate > 0:
            divine_rate = rate
    except Exception:
        pass

    # Convert chaos_price → divine_price for each snapshot
    for s in snapshots:
        chaos = s.get("chaos_price") or s.get("cheapest_chaos") or 0
        s["_divine_price"] = chaos / divine_rate if chaos > 0 else 0

    def _price(s: dict) -> float:
        return s.get("_divine_price", 0)

    qualified = [s for s in snapshots if _price(s) >= min_price_divine]
    # Skip items whose BaseType the CN client cannot parse.
    # Unique equipment is exempt — we use Rarity = Unique (WeGame pattern)
    # which does not reference specific BaseType names.
    before = len(qualified)
    qualified = [
        s for s in qualified
        if s.get("category", "").startswith("unique_")
        or _is_valid_basetype(s.get("name_en", ""))
    ]
    skipped = before - len(qualified)
    if skipped:
        invalid_names = [
            s["name_en"] for s in snapshots
            if not s.get("category", "").startswith("unique_")
            and not _is_valid_basetype(s.get("name_en", ""))
        ]
        logger.info(f"Skipped {skipped} items with invalid BaseTypes: {invalid_names}")
    if not qualified:
        return ""

    # Group by display_group
    groups: dict[str, list[dict]] = {}
    for s in qualified:
        cat = s.get("category", "")
        cfg = _CATEGORY_CONFIG.get(cat, {})
        dg = cfg.get("display_group", "other")
        groups.setdefault(dg, []).append(s)

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    blocks: list[str] = [f"\n{_GENERATED_PRICE_HEADER}"]
    blocks.append(f"#扫描时间: {scan_date}")
    blocks.append(f"#共计 {len(qualified)} 个有价值物品")
    blocks.append("#价格分级: S级(≥5D) A级(≥1D) B级(≥0.3D)")
    blocks.append(f"#汇率: 1D = {divine_rate:.2f}c | 价格信息见注释，游戏内仅显示颜色/特效\n")

    # Generate sections per display group, in defined order
    for dg_key, dg_label in _DISPLAY_GROUP_ORDER:
        if dg_key not in groups:
            continue
        # unique_jewel: skip per-group blocks — the generic jewel catch-all
        # at the end provides highlighting.  Without Class constraints,
        # per-group blocks would steal matches from generic blocks below.
        if dg_key == "unique_jewel":
            continue
        dg_items = groups[dg_key]

        # Classify items within this group into tiers
        tier_groups: dict[str, list[dict]] = {"S": [], "A": [], "B": []}
        for item in dg_items:
            tier = _classify_price_tier(_price(item))
            tier_groups[tier].append(item)

        for tier_name in ("S", "A", "B"):
            tier_items = tier_groups[tier_name]
            if not tier_items:
                continue

            style = _PRICE_TIER_STYLES[tier_name]
            tier_items.sort(key=_price, reverse=True)

            # Build filter conditions based on group type
            if dg_key.startswith("unique_"):
                # ── WeGame pattern for unique equipment ──
                # CN filter parser cannot reliably parse unique item English
                # BaseTypes (many are PoE1 leftovers or not synced to CN).
                # WeGame official CN filters use Rarity = Unique WITHOUT
                # specific BaseType names.  First-match-wins ensures
                # higher-tier blocks grab items before lower-tier ones.
                cn_parts = []
                for it in tier_items:
                    label = it.get("name_cn") or it["name_en"]
                    p = _price(it)
                    cn_parts.append(f"{label}({p:.1f}D)")
                cn_comment = ", ".join(cn_parts)

                blocks.append(f"#── {dg_label} · {style['label']} ({len(tier_items)}个) ──")
                blocks.append(f"#价格: {cn_comment}")
                blocks.append(f"""Show
    Rarity = Unique
    SetTextColor {style['text_color']}
    SetBorderColor {style['border_color']}
    SetFontSize {style['font_size']}
    CustomAlertSound "{style['sound_file']}" {style['sound_volume']}
    MinimapIcon {style['minimap']}
    PlayEffect {style['beam']}
    DisableDropSound
""")
            else:
                # Currency / gem / white_base — use specific BaseType names
                base_type_str = " ".join(f'"{it["name_en"]}"' for it in tier_items)

                # Price annotation comment
                cn_parts = []
                for it in tier_items:
                    label = it.get("name_cn") or it["name_en"]
                    p = _price(it)
                    cn_parts.append(f"{label}({p:.1f}D)")
                cn_comment = ", ".join(cn_parts)

                conditions: list[str] = [f"    BaseType {base_type_str}"]

                if dg_key == "currency":
                    conditions.append('    Class "Stackable Currency"')
                elif dg_key == "gem":
                    conditions.append('    Class "Skill Gems" "Support Gems"')
                elif dg_key == "white_base":
                    conditions.append(f"    ItemLevel >= {item_level_min}")
                    conditions.append("    Rarity < Magic")

                cond_block = "\n".join(conditions)
                blocks.append(f"#── {dg_label} · {style['label']} ({len(tier_items)}个) ──")
                blocks.append(f"#价格: {cn_comment}")
                blocks.append(f"""Show
{cond_block}
    SetTextColor {style['text_color']}
    SetBorderColor {style['border_color']}
    SetFontSize {style['font_size']}
    CustomAlertSound "{style['sound_file']}" {style['sound_volume']}
    MinimapIcon {style['minimap']}
    PlayEffect {style['beam']}
    DisableDropSound
""")

    # ── Generic catch-all blocks for unique weapons & jewels ──
    # Uses WeGame pattern (Rarity = Unique + specific Class names) so the CN
    # filter parser never has to resolve unique item English BaseTypes.
    # First-match-wins: priced unique items matched above get premium styling;
    # these catch-alls provide a basic highlight for everything else.
    _GENERIC_UNIQUE_STYLE = {
        "text_color": "175 96 37",    # 传奇色 (orange, same as template unique catch-all)
        "border_color": "175 96 37",
        "font_size": 40,
        "sound_file": "AlertSound_04.wav",
        "sound_volume": 200,
        "minimap": "1 Orange Star",
        "beam": "Red",
    }
    gs = _GENERIC_UNIQUE_STYLE

    # Unique weapons — all weapon sub-classes (specific names, not meta-class)
    _WEAPON_CLASSES = (
        '"Claws" "Daggers" "Wands" "One Hand Swords" "One Hand Axes" '
        '"One Hand Maces" "Sceptres" "Spears" "Flails" '
        '"Bows" "Staves" "Two Hand Swords" "Two Hand Axes" "Two Hand Maces" '
        '"Quarterstaves" "Crossbows"'
    )
    blocks.append(f"#── 暗金武器 · 通用 [WeGame模式: 其他未具名暗金武器] ──")
    blocks.append(f"""Show
    Rarity = Unique
    Class {_WEAPON_CLASSES}
    SetTextColor {gs['text_color']}
    SetBorderColor {gs['border_color']}
    SetFontSize {gs['font_size']}
    CustomAlertSound "{gs['sound_file']}" {gs['sound_volume']}
    MinimapIcon {gs['minimap']}
    PlayEffect {gs['beam']}
    DisableDropSound
""")

    # Unique jewels
    blocks.append(f"#── 暗金珠宝 · 通用 [WeGame模式] ──")
    blocks.append(f"""Show
    Rarity = Unique
    Class "Jewel"
    SetTextColor {gs['text_color']}
    SetBorderColor {gs['border_color']}
    SetFontSize {gs['font_size']}
    CustomAlertSound "{gs['sound_file']}" {gs['sound_volume']}
    MinimapIcon {gs['minimap']}
    PlayEffect {gs['beam']}
    DisableDropSound
""")

    blocks.append(_GENERATED_PRICE_HEADER)
    blocks.append("")
    return "\n".join(blocks)


def generate_filter_with_prices(
    template_path: str,
    price_snapshots: list[dict],
    deprecated_items: list[dict] | None = None,
    hide_threshold_chaos: float = _HIDE_PRICE_CHAOS_THRESHOLD,
    item_level_min: int = 82,
    output_path: str | None = None,
) -> str:
    """Generate a complete filter using inverted logic: show-everything, hide-cheap.

    Instead of explicitly showing valuable items (old approach), this function
    only generates Hide rules for items confirmed cheap (price < threshold).
    The template's own Show rules provide visual styling for known valuable
    items.  Items not matched by any rule follow PoE2 filter default behavior.

    Benefits:
    - No risk of accidentally hiding valuable items
    - No BaseType parsing errors for unique equipment (no unique-specific rules)
    - Template's generic unique catch-all (Rarity = Unique) handles all uniques
    """
    content = _load_filter_template(template_path)
    content = _remove_previous_generated_block(content)

    lines = content.split("\n")

    # Generate Hide blocks for confirmed-cheap items (< threshold)
    cheap_hide_block = generate_cheap_hide_blocks(
        price_snapshots, hide_threshold_chaos, item_level_min,
    )

    # Insert cheap-hide blocks BEFORE the template's first Show rule for
    # currency/uniques/gems.  First-match-wins: cheap items are caught by
    # these Hide blocks before the template's Show rules can match them.
    # Valuable items (not in any Hide block) pass through to template Show
    # rules below and get their styled highlighting.
    if cheap_hide_block.strip():
        inject_idx = _find_price_inject_point(lines)
        hide_lines = cheap_hide_block.split("\n")
        lines = lines[:inject_idx] + hide_lines + lines[inject_idx:]

    result = "\n".join(lines)

    # Append targeted junk-hide rules at the very end (safety net for
    # shards/scrolls not covered by price scan)
    result += _generate_junk_hide_section()

    if not cheap_hide_block.strip():
        logger.info("No cheap items found, returning template with junk-hide only")
        result = content + _generate_junk_hide_section()
        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(result)
        return result

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)
        logger.info(f"Generated inverted filter (hide-cheap) written to: {output_path}")

    return result


def generate_from_latest_prices(
    market: str = "cn",
    league: str | None = None,
    template_path: str | None = None,
    hide_threshold_chaos: float = _HIDE_PRICE_CHAOS_THRESHOLD,
    item_level_min: int = 82,
    output_dir: str | None = None,
) -> dict:
    """Convenience: generate filter from the latest multi-category price scan in DB.

    Returns:
        {output_path, total_count, category_counts, template}
    """
    from app.models.item_price_snapshot import ItemPriceSnapshot

    db = SessionLocal()
    try:
        # Find latest batch
        latest = (
            db.query(ItemPriceSnapshot)
            .filter(
                ItemPriceSnapshot.market == market,
                ItemPriceSnapshot.league == (league or _resolve_default_league(market)),
            )
            .order_by(ItemPriceSnapshot.scanned_at.desc())
            .first()
        )
        if not latest:
            return {"error": "没有可用的价格扫描数据，请先运行多品类价格扫描", "output_path": None}

        batch_id = latest.scan_batch
        rows = (
            db.query(ItemPriceSnapshot)
            .filter(ItemPriceSnapshot.scan_batch == batch_id)
            .all()
        )

        snapshots = [
            {
                "name_en": r.name_en,
                "name_cn": r.name_cn,
                "category": r.category,
                "chaos_price": r.chaos_price,
                "median_chaos": r.median_chaos,
            }
            for r in rows
        ]
    finally:
        db.close()

    if not snapshots:
        return {"error": "该批次无数据", "output_path": None}

    if not template_path:
        template_path = _find_default_template()
    if not output_dir:
        output_dir = _USER_FILTER_DIR

    template_name = os.path.splitext(os.path.basename(template_path))[0]
    output_path = os.path.join(output_dir, f"{template_name}_AI价格过滤器.filter")

    result = generate_filter_with_prices(
        template_path=template_path,
        price_snapshots=snapshots,
        hide_threshold_chaos=hide_threshold_chaos,
        item_level_min=item_level_min,
        output_path=output_path,
    )

    # Compute summary
    cat_counts: dict[str, int] = {}
    for s in snapshots:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1

    return {
        "output_path": output_path,
        "total_count": len(snapshots),
        "category_counts": cat_counts,
        "template": template_path,
        "content_lines": len(result.split("\n")),
    }


def _resolve_default_league(market: str) -> str:
    """Resolve the current league name for filter generation."""
    try:
        from app.services.trade_realm import resolve_league
        return resolve_league(market, None)
    except Exception:
        return "Standard" if market == "global" else "奥术秘符"


def generate_filter(
    template_path: str,
    high_value_bases: list[dict],
    deprecated_items: list[dict] | None = None,
    item_level_min: int = 82,
    output_path: str | None = None,
) -> str:
    """Generate a complete filter file from template + scanned data.

    Args:
        template_path: path to the asmco .filter template
        high_value_bases: list of high-value base dicts from scanner
        deprecated_items: optional list of items to hide
        item_level_min: minimum item level for base Show rules
        output_path: optional path to write the generated filter

    Returns:
        The full generated filter content as a string
    """
    # Load template
    content = _load_filter_template(template_path)

    # Remove any previously generated block
    content = _remove_previous_generated_block(content)

    # Generate new blocks
    show_block = generate_show_block(high_value_bases, item_level_min)
    hide_block = generate_hide_block(deprecated_items or [])
    generated_section = show_block + hide_block

    if not generated_section.strip():
        logger.info("No high-value bases found, returning template as-is")
        return content

    # Inject before 全域隐藏
    lines = content.split("\n")
    inject_idx = _find_inject_point(lines)

    new_lines = lines[:inject_idx] + generated_section.split("\n") + lines[inject_idx:]
    result = "\n".join(new_lines)

    # Write to file if output path specified
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)
        logger.info(f"Generated filter written to: {output_path}")

    return result


def generate_from_latest_scan(
    market: str = "cn",
    league: str | None = None,
    template_path: str | None = None,
    item_level_min: int = 82,
    output_dir: str | None = None,
) -> dict:
    """Convenience: generate filter from the latest scan results in DB.

    Returns:
        {output_path, high_value_count, deprecated_count, template}
    """
    from app.services.base_scanner import get_latest_high_value_bases

    bases = get_latest_high_value_bases(market=market, league=league)
    if not bases:
        return {"error": "没有可用的扫描数据，请先运行底材扫描", "output_path": None}

    # Determine template path
    if not template_path:
        template_path = _find_default_template()

    # Determine output path
    if not output_dir:
        output_dir = _USER_FILTER_DIR
    template_name = os.path.splitext(os.path.basename(template_path))[0]
    output_path = os.path.join(output_dir, f"{template_name}_AI高价值底材.filter")

    result = generate_filter(
        template_path=template_path,
        high_value_bases=bases,
        item_level_min=item_level_min,
        output_path=output_path,
    )

    return {
        "output_path": output_path,
        "high_value_count": len(bases),
        "deprecated_count": 0,
        "template": template_path,
        "content_lines": len(result.split("\n")),
    }


def _find_default_template() -> str:
    """Find the default asmco filter template (4后期)."""
    # Look in the filter_templates directory first
    if os.path.isdir(_FILTER_TEMPLATE_DIR):
        for f in os.listdir(_FILTER_TEMPLATE_DIR):
            if "4后期" in f and f.endswith(".filter"):
                return os.path.join(_FILTER_TEMPLATE_DIR, f)
        # Fallback: any .filter in templates
        for f in os.listdir(_FILTER_TEMPLATE_DIR):
            if f.endswith(".filter"):
                return os.path.join(_FILTER_TEMPLATE_DIR, f)

    # Fallback: look in user's PoE2 directory (Windows)
    user_dir = os.path.expanduser(
        os.path.join("~", "Documents", "My Games", "Path of Exile 2")
    )
    if os.path.isdir(user_dir):
        for f in sorted(os.listdir(user_dir)):
            if "4后期" in f and f.endswith(".filter"):
                return os.path.join(user_dir, f)

    raise FileNotFoundError(
        "找不到过滤器模板。请将 asmco 的 .filter 文件放入 "
        f"{_FILTER_TEMPLATE_DIR} 或 {user_dir}"
    )
