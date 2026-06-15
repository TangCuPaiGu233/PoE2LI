"""TradeConcept Dictionary — curated concept→stat_id mappings.

Instead of relying purely on vector search (which can't distinguish
"Minion Skills" from "Melee Skills"), this dictionary provides
pre-verified mappings for the 60 most common search concepts.

Resolution order:
  1. Alias match (exact or fuzzy)
  2. English stat text pattern match (regex against stat dictionary)
  3. Vector search for candidates (only if dict misses)
  4. LLM selects from candidates (last resort)

Each concept also has item_slots — an allowlist of which equipment
slots this mod can appear on. Empty = assume all slots.
"""

import re
import logging

logger = logging.getLogger(__name__)

# ── Concept definitions ──
# aliases: Chinese terms users might type
# stat_patterns: regex patterns to match against stat ref_text (English game text)
# item_slots: which equipment slots this mod appears on (empty = anywhere)
# known_ids: verified-good stat IDs (from empirical testing on PoE2 Trade API)
# kind: "required" (core stat) or "optional" (nice to have)

TRADE_CONCEPTS = {
    # ═══ Skill Levels ═══
    "minion_skill_level": {
        "aliases": ["召唤等级", "召唤技能等级", "召唤物等级", "召唤兽等级",
                     "+1召唤", "+2召唤", "+3召唤", "minion level", "minion skill"],
        "stat_patterns": [r"# to Level of all Minion Skills"],
        "item_slots": ["accessory.amulet", "weapon.sceptre", "weapon.wand", "armour.helmet"],
        "known_ids": ["explicit.stat_2162097452"],
    },
    "spell_skill_level": {
        "aliases": ["法术等级", "法术技能等级", "+1法术", "+2法术", "+3法术",
                     "spell level", "spell skill"],
        "stat_patterns": [r"# to Level of all Spell Skills"],
        "item_slots": ["accessory.amulet", "weapon.sceptre", "weapon.wand", "weapon.staff"],
        "known_ids": ["explicit.stat_1428232057"],
    },
    "all_skill_level": {
        "aliases": ["全技能等级", "所有技能等级", "+1全技能", "+1所有技能"],
        "stat_patterns": [r"# to Level of all Skills"],
        "item_slots": [],  # very rare, can appear anywhere
        "known_ids": ["explicit.stat_4283407333"],
    },

    # ═══ Spirit ═══
    "spirit": {
        "aliases": ["精魂", "精魄", "spirit", "光环"],
        "stat_patterns": [r"# to Spirit", r"increased Spirit"],
        "item_slots": ["accessory.amulet", "armour.chest", "weapon.sceptre"],
        "known_ids": ["explicit.stat_3981240776", "explicit.stat_2704225257"],
    },

    # ═══ Life / ES / Mana ═══
    "maximum_life": {
        "aliases": ["最大生命", "生命值", "生命", "血量", "hp", "life"],
        "stat_patterns": [r"\+?# to maximum Life"],
        "item_slots": [],  # almost all equipment
        "known_ids": ["explicit.stat_3299347043"],
    },
    "energy_shield": {
        "aliases": ["护盾", "能量护盾", "能盾", "es", "能量盾"],
        "stat_patterns": [r"\+?# to maximum Energy Shield"],
        "item_slots": ["accessory.amulet", "accessory.ring", "armour.chest",
                        "armour.helmet", "armour.gloves", "armour.boots"],
        "known_ids": ["explicit.stat_4225203927"],
    },
    "maximum_mana": {
        "aliases": ["最大魔力", "魔力值", "魔力", "mana", "蓝量"],
        "stat_patterns": [r"\+?# to maximum Mana"],
        "item_slots": [],  # most equipment
        "known_ids": ["explicit.stat_1050105434"],
    },

    # ═══ Resistances ═══
    "fire_resistance": {
        "aliases": ["火焰抗性", "火抗", "火炕", "fire res", "火防"],
        "stat_patterns": [r"\+?#% to Fire Resistance"],
        "item_slots": [],  # almost all equipment (except weapons)
        "known_ids": ["explicit.stat_3372524247"],
    },
    "cold_resistance": {
        "aliases": ["冰霜抗性", "冰抗", "cold res", "冰防"],
        "stat_patterns": [r"\+?#% to Cold Resistance"],
        "item_slots": [],
        "known_ids": ["explicit.stat_4220027924"],
    },
    "lightning_resistance": {
        "aliases": ["闪电抗性", "电抗", "lightning res", "电防"],
        "stat_patterns": [r"\+?#% to Lightning Resistance"],
        "item_slots": [],
        "known_ids": ["explicit.stat_1671376347"],
    },
    "chaos_resistance": {
        "aliases": ["混沌抗性", "混抗", "chaos res", "混沌防"],
        "stat_patterns": [r"\+?#% to Chaos Resistance"],
        "item_slots": [],
        "known_ids": ["explicit.stat_2923486259"],
    },
    "all_elemental_resistance": {
        "aliases": ["全元素抗性", "全抗", "三抗", "all res", "元素抗性"],
        "stat_patterns": [r"\+?#% to all Elemental Resistances"],
        "item_slots": [],
        "known_ids": ["explicit.stat_2901986750"],
    },

    # ═══ Attributes ═══
    "strength": {
        "aliases": ["力量", "str", "strength"],
        "stat_patterns": [r"\+?# to Strength"],
        "item_slots": [],
        "known_ids": ["explicit.stat_4080412365"],
    },
    "dexterity": {
        "aliases": ["敏捷", "dex", "dexterity"],
        "stat_patterns": [r"\+?# to Dexterity"],
        "item_slots": [],
        "known_ids": ["explicit.stat_3261801346"],
    },
    "intelligence": {
        "aliases": ["智慧", "智力", "int", "intelligence"],
        "stat_patterns": [r"\+?# to Intelligence"],
        "item_slots": [],
        "known_ids": ["explicit.stat_328968392"],
    },
    "all_attributes": {
        "aliases": ["全属性", "所有属性", "all attr", "全能力"],
        "stat_patterns": [r"\+?# to all Attributes"],
        "item_slots": [],
        "known_ids": ["explicit.stat_1379411915"],
    },

    # ═══ Speed ═══
    "movement_speed": {
        "aliases": ["移动速度", "移速", "跑速", "move speed", "ms"],
        "stat_patterns": [r"#% increased Movement Speed"],
        "item_slots": ["armour.boots"],
        "known_ids": ["explicit.stat_2250533757"],
    },
    "cast_speed": {
        "aliases": ["施法速度", "法速", "cast speed", "cs"],
        "stat_patterns": [r"#% increased Cast Speed"],
        "item_slots": ["accessory.amulet", "accessory.ring", "weapon.sceptre",
                        "weapon.wand", "weapon.staff", "armour.gloves"],
        "known_ids": ["explicit.stat_2891184298"],
    },
    "attack_speed": {
        "aliases": ["攻击速度", "攻速", "attack speed", "as"],
        "stat_patterns": [r"#% increased Attack Speed"],
        "item_slots": ["weapon.bow", "weapon.claw", "weapon.dagger",
                        "armour.gloves"],
        "known_ids": ["explicit.stat_2100673559"],
    },

    # ═══ Minion Mods ═══
    "minion_damage": {
        "aliases": ["召唤伤害", "召唤物伤害", "召唤兽伤害", "minion damage",
                     "召唤增伤"],
        "stat_patterns": [r"Minions deal #% increased Damage"],
        "item_slots": ["weapon.sceptre", "weapon.wand", "armour.helmet"],
        "known_ids": ["explicit.stat_1589917703"],
    },
    "minion_attack_cast_speed": {
        "aliases": ["召唤攻速", "召唤施法速度", "召唤物攻速", "minion speed",
                     "召唤物施法", "召唤攻击和施法速度", "召唤生物攻击和施法速度",
                     "召唤生物攻击施法速度"],
        "stat_patterns": [r"Minions have #% increased Attack and Cast Speed"],
        "item_slots": ["weapon.sceptre", "weapon.wand"],
        "known_ids": ["explicit.stat_3091578504"],
    },
    "minion_critical_damage": {
        "aliases": ["召唤暴击伤害", "召唤物暴击伤害", "召唤生物暴击伤害", "召唤生物暴击伤害加成",
                     "召唤暴伤", "minion crit damage", "minion critical"],
        "stat_patterns": [r"Minions have #% increased Critical Damage Bonus"],
        "item_slots": [],
        "known_ids": ["explicit.stat_1854213750"],
    },
    "minion_life": {
        "aliases": ["召唤生命", "召唤物生命", "召唤兽生命", "minion life"],
        "stat_patterns": [r"Minions have #% increased maximum Life"],
        "item_slots": ["weapon.sceptre", "armour.helmet"],
        "known_ids": ["explicit.stat_770672621"],
    },
    "minion_resistance": {
        "aliases": ["召唤抗性", "召唤物抗性", "召唤全抗", "minion res"],
        "stat_patterns": [r"Minions have \+?#% to all Elemental Resistances"],
        "item_slots": ["weapon.sceptre", "armour.helmet"],
        "known_ids": ["explicit.stat_1423639565"],
    },
    "minion_movement_speed": {
        "aliases": ["召唤移速", "召唤物移速", "minion move speed"],
        "stat_patterns": [r"Minions have #% increased Movement Speed"],
        "item_slots": ["weapon.sceptre"],
        "known_ids": ["explicit.stat_174664100"],
    },

    # ═══ Allies (Aura) Mods ═══
    "allies_attack_speed": {
        "aliases": ["友军攻速", "友方攻速", "光环攻速", "allies attack speed"],
        "stat_patterns": [r"Allies in your Presence have #% increased Attack Speed"],
        "item_slots": ["accessory.amulet", "weapon.sceptre"],
        "known_ids": ["explicit.stat_1998951374"],
    },
    "allies_cast_speed": {
        "aliases": ["友军施法速度", "友方施法", "光环施法", "allies cast speed"],
        "stat_patterns": [r"Allies in your Presence have #% increased Cast Speed"],
        "item_slots": ["accessory.amulet", "weapon.sceptre"],
        "known_ids": ["explicit.stat_289128254"],
    },
    "allies_damage": {
        "aliases": ["友军伤害", "友方伤害", "光环伤害", "allies damage"],
        "stat_patterns": [r"Allies in your Presence deal #% increased Damage"],
        "item_slots": ["weapon.sceptre"],
        "known_ids": ["explicit.stat_1798257884"],
    },
    "allies_added_fire_damage": {
        "aliases": ["友军附加火焰伤害", "光环火伤", "在场友军火焰", "allies fire"],
        "stat_patterns": [r"Allies in your Presence deal # to # added Attack Fire Damage"],
        "item_slots": ["weapon.sceptre"],
        "known_ids": ["explicit.stat_849987426"],
    },
    "allies_added_lightning_damage": {
        "aliases": ["友军附加闪电伤害", "光环电伤", "在场友军闪电", "allies lightning"],
        "stat_patterns": [r"Allies in your Presence deal # to # added Attack Lightning Damage"],
        "item_slots": ["weapon.sceptre"],
        "known_ids": ["explicit.stat_2854751904"],
    },
    "allies_added_cold_damage": {
        "aliases": ["友军附加冰霜伤害", "光环冰伤", "在场友军冰霜", "allies cold"],
        "stat_patterns": [r"Allies in your Presence deal # to # added Attack Cold Damage"],
        "item_slots": ["weapon.sceptre"],
        "known_ids": ["explicit.stat_2347036682"],
    },
    "allies_added_physical_damage": {
        "aliases": ["友军附加物理伤害", "光环物伤", "在场友军物理", "allies physical"],
        "stat_patterns": [r"Allies in your Presence deal # to # added Attack Physical Damage"],
        "item_slots": ["weapon.sceptre"],
        "known_ids": ["explicit.stat_1574590649"],
    },

    # ═══ Damage ═══
    "fire_damage": {
        "aliases": ["火焰伤害", "火伤", "fire damage"],
        "stat_patterns": [r"#% increased Fire Damage", r"adds # to # Fire Damage"],
        "item_slots": ["weapon.sceptre", "weapon.wand", "weapon.staff", "accessory.ring"],
        "known_ids": [],  # too many variants, use vector search
    },
    "cold_damage": {
        "aliases": ["冰霜伤害", "冰伤", "cold damage"],
        "stat_patterns": [r"#% increased Cold Damage", r"adds # to # Cold Damage"],
        "item_slots": ["weapon.sceptre", "weapon.wand", "weapon.staff", "accessory.ring"],
        "known_ids": [],
    },
    "lightning_damage": {
        "aliases": ["闪电伤害", "电伤", "lightning damage"],
        "stat_patterns": [r"#% increased Lightning Damage", r"adds # to # Lightning Damage"],
        "item_slots": ["weapon.sceptre", "weapon.wand", "weapon.staff", "accessory.ring"],
        "known_ids": [],
    },
    "chaos_damage": {
        "aliases": ["混沌伤害", "混伤", "chaos damage", "混沌伤害提高"],
        "stat_patterns": [r"#% increased Chaos Damage", r"adds # to # Chaos Damage"],
        "item_slots": ["weapon.sceptre", "weapon.wand", "weapon.staff"],
        "known_ids": [],
    },
    "cold_penetration": {
        "aliases": ["冰霜穿透", "冰穿透", "穿透冰霜抗性", "伤害穿透冰霜抗性",
                     "cold penetration", "cold pen"],
        "stat_patterns": [r"Penetrates #% Cold Resistance"],
        "item_slots": [],
        "known_ids": [],
    },
    "physical_damage": {
        "aliases": ["物理伤害", "物伤", "physical damage", "物理点伤"],
        "stat_patterns": [
            r"#% increased Physical Damage",
            r"adds # to # Physical Damage to Attacks",
        ],
        "item_slots": ["weapon.bow", "weapon.claw", "weapon.dagger",
                        "weapon.onesword", "weapon.oneaxe", "weapon.onemace",
                        "weapon.twosword", "weapon.twoaxe", "weapon.twomace",
                        "weapon.spear", "weapon.crossbow",
                        "accessory.ring"],
        "known_ids": [
            "explicit.stat_3967918456",  # % increased Physical Damage
        ],
    },
    "spell_damage": {
        "aliases": ["法术伤害", "法伤", "spell damage"],
        "stat_patterns": [r"#% increased Spell Damage"],
        "item_slots": ["weapon.sceptre", "weapon.wand", "weapon.staff", "armour.shield"],
        "known_ids": [],
    },

    # ═══ Utility ═══
    "rarity": {
        "aliases": ["稀有度", "物品稀有度", "打宝", "iir", "rarity", "mf"],
        "stat_patterns": [r"#% increased Rarity of Items found"],
        "item_slots": ["accessory.amulet", "accessory.ring", "armour.helmet",
                        "armour.gloves", "armour.boots"],
        "known_ids": ["explicit.stat_3917489142"],
    },
    "item_level": {
        "aliases": ["物品等级", "ilvl", "装备等级", "物等"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "type_filter_ilvl",  # handled by type_filters, not stats
    },
    "quality": {
        "aliases": ["品质", "quality", "q20", "满品质"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "type_filter_quality",
    },
    "sockets": {
        "aliases": ["孔数", "孔", "sockets", "洞"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "socket_filters",
    },
    "links": {
        "aliases": ["链接", "连", "links", "6连", "5连"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "socket_filters",
    },

    # ═══ Weapon Stats ═══
    "physical_dps": {
        "aliases": ["物理DPS", "pdps", "物理秒伤", "phys dps", "物理伤害最高",
                     "最高物理伤害", "高物理伤害", "大物理"],
        "stat_patterns": [],
        "item_slots": [],  # handled by equipment_filters, not stats
        "known_ids": [],
        "special": "sort_pdps",  # SORT by pdps, NOT a stat filter!
    },
    "elemental_dps": {
        "aliases": ["元素DPS", "edps", "元素秒伤", "ele dps"],
        "stat_patterns": [],
        "item_slots": [],  # all weapons
        "known_ids": [],
        "special": "equipment_filter_edps",
    },
    "critical_strike_chance": {
        "aliases": ["暴击率", "暴率", "crit chance", "暴击几率"],
        "stat_patterns": [r"#% to Critical Hit Chance", r"#% increased Critical Hit Chance"],
        "item_slots": [],  # weapons and some accessories
        "known_ids": [],
    },
    "critical_damage_bonus": {
        "aliases": ["暴击伤害", "暴伤", "crit damage", "crit multi", "爆伤"],
        "stat_patterns": [r"#% increased Critical Damage Bonus",
                          r"\+#% to Critical Damage Multiplier"],
        "item_slots": [],
        "known_ids": [],
    },

    # ═══ Special Flags ═══
    "corrupted": {
        "aliases": ["腐化", "已腐化", "corrupted", "瓦过的", "瓦"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "misc_filter_corrupted",
    },
    "identified": {
        "aliases": ["已鉴定", "鉴定", "identified"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "misc_filter_identified",
    },
    "unidentified": {
        "aliases": ["未鉴定", "未鉴定", "unidentified"],
        "stat_patterns": [],
        "item_slots": [],
        "known_ids": [],
        "special": "misc_filter_identified",
    },
}


# ── Lookup functions ──

def find_concept(term: str) -> tuple[str | None, dict | None]:
    """Find a concept by Chinese alias or concept name.

    Returns (concept_name, concept_entry) or (None, None).
    """
    term_lower = term.lower().strip()

    # Exact match on concept name
    if term_lower in TRADE_CONCEPTS:
        return term_lower, TRADE_CONCEPTS[term_lower]

    # Search aliases
    for name, entry in TRADE_CONCEPTS.items():
        for alias in entry.get("aliases", []):
            if term_lower == alias.lower():
                return name, entry
            # Partial match for multi-word terms
            if len(term_lower) >= 3 and term_lower in alias.lower():
                return name, entry

    return None, None


def match_concept_by_text(stat_text: str) -> str | None:
    """Match a stat ref_text against concept patterns. Returns concept name or None."""
    for name, entry in TRADE_CONCEPTS.items():
        for pattern in entry.get("stat_patterns", []):
            if re.search(pattern, stat_text, re.IGNORECASE):
                return name
    return None


def is_concept_available(concept_name: str, item_slot: str | None) -> bool:
    """Check if a concept is available on a specific item slot.

    If no item_slot specified, assume available.
    If concept has empty item_slots, assume available everywhere.
    """
    if not item_slot:
        return True
    from app.services.trade_service import normalize_trade_item_slot

    item_slot = normalize_trade_item_slot(item_slot) or item_slot
    # Jewels roll many affix families — slot allowlists target weapons/armour only.
    if item_slot == "jewel":
        return True
    entry = TRADE_CONCEPTS.get(concept_name)
    if not entry:
        return True  # unknown concept, don't block
    slots = entry.get("item_slots", [])
    if not slots:
        return True  # no restrictions = available everywhere
    return item_slot in slots


def get_concept_ids(concept_name: str) -> list[str]:
    """Get known-good stat IDs for a concept."""
    entry = TRADE_CONCEPTS.get(concept_name, {})
    return entry.get("known_ids", [])


def get_concept_aliases(concept_name: str) -> list[str]:
    """Get all Chinese aliases for a concept."""
    entry = TRADE_CONCEPTS.get(concept_name, {})
    return entry.get("aliases", [])


def list_all_concepts() -> list[str]:
    """List all available concept names."""
    return sorted(TRADE_CONCEPTS.keys())


def list_concepts_for_slot(item_slot: str) -> list[str]:
    """List concepts available for a specific equipment slot."""
    result = []
    for name, entry in TRADE_CONCEPTS.items():
        slots = entry.get("item_slots", [])
        if not slots or item_slot in slots:
            result.append(name)
    return sorted(result)
