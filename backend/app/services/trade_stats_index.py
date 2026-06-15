"""
PoE2 Trade Stat Search Index

Two-tier architecture:
- COMMON_STATS: ~150 curated common stats with Chinese labels, used in LLM prompt
- FULL_INDEX: Full stat dictionary loaded from JSON, used for fuzzy fallback matching

The LLM parses user queries using the common stats reference. If a stat isn't in
the common list, the LLM returns an English description which is fuzzy-matched
against the full index.
"""

import json
import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  Item type mappings (Chinese → Trade API category)
# ═══════════════════════════════════════════════════════════


_STAT_LOOKUP_PATHS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "trade_stats_en_cn.json"),
    os.path.join(os.path.dirname(__file__), "data", "trade_stats_en_cn.json"),
    "/app/data/trade_stats_en_cn.json",
]

_CLASS_START_CN: dict[str, str] = {
    "佣兵": "explicit.stat_738592688",
    "魔巫": "explicit.stat_3359496001",
    "战士": "explicit.stat_1359862146",
    "游侠": "explicit.stat_3116298775",
    "暗影": "explicit.stat_2218479786",
    "圣堂武僧": "explicit.stat_1688294122",
}

_VARIANT_ALIASES: dict[str, str] = {
    "女巫": "魔巫",
    "行者": "圣堂武僧",
    "圣堂": "圣堂武僧",
}

_stat_lookup_cache: dict | None = None


def _load_stat_lookup() -> dict:
    global _stat_lookup_cache
    if _stat_lookup_cache is not None:
        return _stat_lookup_cache
    data: dict = {}
    for path in _STAT_LOOKUP_PATHS:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            break
    if not data:
        logger.warning("trade_stats_en_cn.json not found; CN stat lookup disabled")
    _stat_lookup_cache = data
    return data


def normalize_variant_label(label: str) -> str:
    s = (label or "").strip().replace("起点", "").strip()
    return _VARIANT_ALIASES.get(s, s)


def class_start_stat_id(variant: str | None) -> str | None:
    key = normalize_variant_label(variant or "")
    if not key:
        return None
    return _CLASS_START_CN.get(key)


def stat_id_to_cn(stat_id: str) -> str | None:
    lookup = _load_stat_lookup()
    return (lookup.get("id_to_cn") or {}).get(stat_id)




def normalize_canonical_stat_label(label: str) -> str:
    """Strip numeric suffixes (+4 etc.) from AI canonical labels."""
    s = (label or "").strip()
    if not s:
        return s
    s = re.sub(r"[+＋]\s*\d+(?:\.\d+)?\s*$", "", s).strip()
    s = re.sub(r"\s*\d+(?:\.\d+)?\s*$", "", s).strip()
    return s


def resolve_stat_query_exact(query: str, apply_slang: bool = False) -> str | None:
    """Exact CN/EN label match only (no substring or fuzzy)."""
    q = (query or "").strip()
    if not q:
        return None
    if apply_slang:
        q = _normalize_stat_search_query(q)
    lookup = _load_stat_lookup()
    cn_to_id: dict = lookup.get("cn_to_id") or {}
    if q in cn_to_id:
        return cn_to_id[q]
    for cn, sid in cn_to_id.items():
        if not cn:
            continue
        cn_plain = cn.replace("#%", "").strip()
        if cn_plain == q or cn == q:
            return sid
    _load_full_index()
    if _full_stat_dict:
        ql = q.lower()
        for sid, ref in _full_stat_dict.items():
            if ref and ref.lower() == ql:
                return sid
    return None


def resolve_stat_query(query: str) -> str | None:
    exact = resolve_stat_query_exact(query, apply_slang=True)
    if exact:
        return exact
    q = _normalize_stat_search_query((query or "").strip())
    if not q:
        return None
    lookup = _load_stat_lookup()
    cn_to_id: dict = lookup.get("cn_to_id") or {}
    if q in cn_to_id:
        return cn_to_id[q]
    for cn, sid in cn_to_id.items():
        if cn and cn.replace("#%", "").strip() == q:
            return sid
    best_key: str | None = None
    best_len = 0
    for cn, sid in cn_to_id.items():
        if not cn:
            continue
        cn_plain = cn.replace("#%", "").strip()
        if cn == q or cn_plain == q:
            return sid
        if cn in q or q in cn or cn_plain in q or q in cn_plain:
            if len(cn) > best_len:
                best_len = len(cn)
                best_key = cn
    if best_key:
        return cn_to_id[best_key]
    _load_full_index()
    if not _full_stat_dict:
        return None
    ql = q.lower()
    for sid, ref in _full_stat_dict.items():
        if ref and ref.lower() == ql:
            return sid
    return find_stat_id(q, stat_type="explicit")


_STAT_SLANG_HINTS: dict[str, str] = {
    "火抗": "火焰抗性",
    "火抗性": "火焰抗性",
    "冰抗": "冰霜抗性",
    "冰抗性": "冰霜抗性",
    "闪抗": "闪电抗性",
    "雷抗": "闪电抗性",
    "电抗": "闪电抗性",
    "全元素抗": "元素抗性",
    "全抗": "元素抗性",
    "三抗": "元素抗性",
    "召唤等级": "召唤技能等级",
    "召唤兽等级": "召唤技能等级",
    "佣兵起点": "佣兵",
    "总生命": "最大生命",
    "生命": "最大生命",
    "跑速": "移动速度",
    "移速": "移动速度",
}

def _normalize_stat_search_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return q
    for slang in sorted(_STAT_SLANG_HINTS.keys(), key=len, reverse=True):
        if slang in q:
            q = q.replace(slang, _STAT_SLANG_HINTS[slang])
    return q


def resolve_stat_detail(stat_id: str) -> dict | None:
    sid = (stat_id or "").strip()
    if not sid:
        return None
    lookup = _load_stat_lookup()
    id_to_cn: dict = lookup.get("id_to_cn") or {}
    en_to_cn: dict = lookup.get("en_to_cn_by_id") or {}
    _load_full_index()
    text_cn = id_to_cn.get(sid) or en_to_cn.get(sid) or ""
    text_en = (_full_stat_dict or {}).get(sid) or ""
    stat_type = sid.split(".", 1)[0] if "." in sid else "explicit"
    return {
        "stat_id": sid,
        "text_en": text_en,
        "text_cn": text_cn,
        "stat_type": stat_type,
    }


def search_stat_suggestions(query: str, limit: int = 15) -> list[dict]:
    q = _normalize_stat_search_query(query)
    if not q:
        return []
    ql = q.lower()
    lookup = _load_stat_lookup()
    cn_to_id: dict = lookup.get("cn_to_id") or {}
    scores: dict[str, float] = {}

    for cn, sid in cn_to_id.items():
        if not cn or not sid:
            continue
        cn_plain = cn.replace("#%", "").strip()
        score = 0.0
        if cn == q or cn_plain == q:
            score = 100.0
        elif cn.startswith(q) or cn_plain.startswith(q):
            score = 85.0 + min(len(q), 10) * 0.1
        elif q.startswith(cn_plain) and len(cn_plain) >= 2:
            score = 75.0
        elif q in cn:
            score = 60.0 + min(len(q), 15) * 0.2
        elif len(cn_plain) >= 3 and cn_plain in q:
            score = 55.0 + len(cn_plain) * 0.5
        if score > 0:
            scores[sid] = max(scores.get(sid, 0.0), score)

    for sid, ref in (_full_stat_dict or {}).items():
        if not ref or not sid:
            continue
        ref_l = ref.lower()
        if ref_l == ql:
            scores[sid] = max(scores.get(sid, 0.0), 90.0)
        elif ref_l.startswith(ql):
            scores[sid] = max(scores.get(sid, 0.0), 70.0 + min(len(ql), 12) * 0.2)
        elif ql in ref_l and len(ql) >= 3:
            scores[sid] = max(scores.get(sid, 0.0), 45.0)

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    out: list[dict] = []
    for sid, score in ranked:
        detail = resolve_stat_detail(sid)
        if not detail:
            continue
        detail["score"] = round(score, 2)
        out.append(detail)
        if len(out) >= max(1, int(limit or 15)):
            break
    return out


ITEM_TYPES_ZH = {
    # 饰品
    "项链": ("accessory.amulet", "Amulet"),
    "护身符": ("accessory.amulet", "Amulet"),
    "戒指": ("accessory.ring", "Ring"),
    "腰带": ("accessory.belt", "Belt"),
    # 护甲
    "胸甲": ("armour.chest", "Body Armour"),
    "衣服": ("armour.chest", "Body Armour"),
    "铠甲": ("armour.chest", "Body Armour"),
    "头盔": ("armour.helmet", "Helmet"),
    "帽子": ("armour.helmet", "Helmet"),
    "手套": ("armour.gloves", "Gloves"),
    "鞋子": ("armour.boots", "Boots"),
    "靴子": ("armour.boots", "Boots"),
    "盾牌": ("armour.shield", "Shield"),
    "箭袋": ("armour.quiver", "Quiver"),
    # 武器
    "弓": ("weapon.bow", "Bow"),
    "爪": ("weapon.claw", "Claw"),
    "匕首": ("weapon.dagger", "Dagger"),
    "权杖": ("weapon.sceptre", "Sceptre"),
    "魔杖": ("weapon.wand", "Wand"),
    "长杖": ("weapon.staff", "Staff"),
    "法杖": ("weapon.wand", "Wand"),
    "单手剑": ("weapon.onesword", "One Hand Sword"),
    "单手斧": ("weapon.oneaxe", "One Hand Axe"),
    "单手锤": ("weapon.onemace", "One Hand Mace"),
    "双手剑": ("weapon.twosword", "Two Hand Sword"),
    "双手斧": ("weapon.twoaxe", "Two Hand Axe"),
    "双手锤": ("weapon.twomace", "Two Hand Mace"),
    "战杖": ("weapon.warstaff", "Warstaff"),
    "弩": ("weapon.crossbow", "Crossbow"),
    "十字弩": ("weapon.crossbow", "Crossbow"),
    "长矛": ("weapon.spear", "Spear"),
    "标枪": ("weapon.javelin", "Javelin"),
    # 药剂
    "药剂": ("flask", "Flask"),
    "生命药剂": ("flask.life", "Life Flask"),
    "魔力药剂": ("flask.mana", "Mana Flask"),
    # 珠宝
    "珠宝": ("jewel", "Jewel"),
    "宝石": ("jewel", "Jewel"),
}

ITEM_TYPES_EN = {
    "amulet": ("accessory.amulet", "Amulet"),
    "necklace": ("accessory.amulet", "Amulet"),
    "ring": ("accessory.ring", "Ring"),
    "belt": ("accessory.belt", "Belt"),
    "body armour": ("armour.chest", "Body Armour"),
    "body": ("armour.chest", "Body Armour"),
    "chest": ("armour.chest", "Body Armour"),
    "armour": ("armour.chest", "Body Armour"),
    "helmet": ("armour.helmet", "Helmet"),
    "helm": ("armour.helmet", "Helmet"),
    "gloves": ("armour.gloves", "Gloves"),
    "boots": ("armour.boots", "Boots"),
    "shield": ("armour.shield", "Shield"),
    "quiver": ("armour.quiver", "Quiver"),
    "bow": ("weapon.bow", "Bow"),
    "wand": ("weapon.wand", "Wand"),
    "sceptre": ("weapon.sceptre", "Sceptre"),
    "staff": ("weapon.staff", "Staff"),
    "dagger": ("weapon.dagger", "Dagger"),
    "claw": ("weapon.claw", "Claw"),
    "sword": ("weapon.onesword", "One Hand Sword"),
    "axe": ("weapon.oneaxe", "One Hand Axe"),
    "mace": ("weapon.onemace", "One Hand Mace"),
    "crossbow": ("weapon.crossbow", "Crossbow"),
    "spear": ("weapon.spear", "Spear"),
    "javelin": ("weapon.javelin", "Javelin"),
    "flask": ("flask", "Flask"),
    "jewel": ("jewel", "Jewel"),
}


# ═══════════════════════════════════════════════════════════
#  Common Stats Reference — curated for LLM prompt inclusion
#  Each entry: { "id": stat_id, "zh": Chinese name, "ref": English ref }
# ═══════════════════════════════════════════════════════════

COMMON_STATS = [
    # ── 生命 / Life ──
    {"id": "explicit.stat_3299347043", "zh": "最大生命", "ref": "+# to maximum Life"},
    {"id": "explicit.stat_983749596", "zh": "百分比生命", "ref": "#% increased maximum Life"},
    {"id": "explicit.stat_3325883026", "zh": "生命回复", "ref": "Regenerate #% of Life per second"},
    {"id": "explicit.stat_3299347043", "zh": "生命", "ref": "+# to maximum Life"},

    # ── 魔力 / Mana ──
    {"id": "explicit.stat_1050105434", "zh": "最大魔力", "ref": "+# to maximum Mana"},
    {"id": "explicit.stat_2748665614", "zh": "百分比魔力", "ref": "#% increased maximum Mana"},
    {"id": "explicit.stat_789117908", "zh": "魔力回复", "ref": "#% increased Mana Regeneration Rate"},

    # ── 能量护盾 / Energy Shield ──
    {"id": "explicit.stat_4082111882", "zh": "能量护盾", "ref": "+# to maximum Energy Shield"},
    {"id": "explicit.stat_2482852589", "zh": "百分比能量护盾", "ref": "#% increased maximum Energy Shield"},
    {"id": "explicit.stat_3489782002", "zh": "能量护盾回复", "ref": "#% increased Energy Shield Recharge Rate"},

    # ── 护甲 / Armour ──
    {"id": "explicit.stat_3484657501", "zh": "护甲", "ref": "+# to Armour"},
    {"id": "explicit.stat_124859000", "zh": "百分比护甲", "ref": "#% increased Armour"},
    {"id": "explicit.stat_2866327818", "zh": "闪避与护甲", "ref": "#% increased Armour and Evasion"},

    # ── 闪避 / Evasion ──
    {"id": "explicit.stat_2144192055", "zh": "闪避值", "ref": "+# to Evasion Rating"},
    {"id": "explicit.stat_53650340", "zh": "百分比闪避", "ref": "#% increased Evasion Rating"},

    # ── 格挡 / Block ──
    {"id": "explicit.stat_3556824919", "zh": "格挡", "ref": "#% Chance to Block Attack Damage"},

    # ── 抗性 / Resistances ──
    {"id": "explicit.stat_3372524247", "zh": "火焰抗性", "ref": "+#% to Fire Resistance"},
    {"id": "explicit.stat_4220027924", "zh": "冰冷抗性", "ref": "+#% to Cold Resistance"},
    {"id": "explicit.stat_1671376347", "zh": "闪电抗性", "ref": "+#% to Lightning Resistance"},
    {"id": "explicit.stat_2923486259", "zh": "混沌抗性", "ref": "+#% to Chaos Resistance"},
    {"id": "explicit.stat_2901986750", "zh": "全元素抗性", "ref": "+#% to all Elemental Resistances"},

    # ── 属性 / Attributes ──
    {"id": "explicit.stat_4080418644", "zh": "力量", "ref": "+# to Strength"},
    {"id": "explicit.stat_3261801346", "zh": "敏捷", "ref": "+# to Dexterity"},
    {"id": "explicit.stat_328541901", "zh": "智慧", "ref": "+# to Intelligence"},
    {"id": "explicit.stat_1379411836", "zh": "全属性", "ref": "+# to all Attributes"},

    # ── 技能等级 / Skill Gem Levels ──
    {"id": "explicit.stat_4283407333", "zh": "全技能等级", "ref": "+# to Level of all Skill Gems"},
    {"id": "explicit.stat_124131830", "zh": "法术技能等级", "ref": "+# to Level of all Spell Skill Gems"},
    {"id": "explicit.stat_2162097452", "zh": "召唤技能等级", "ref": "+# to Level of all Minion Skill Gems"},
    {"id": "explicit.stat_599749213", "zh": "火焰技能等级", "ref": "+# to Level of all Fire Skill Gems"},
    {"id": "explicit.stat_1078455967", "zh": "冰冷技能等级", "ref": "+# to Level of all Cold Skill Gems"},
    {"id": "explicit.stat_1147690586", "zh": "闪电技能等级", "ref": "+# to Level of all Lightning Skill Gems"},
    {"id": "explicit.stat_67169579", "zh": "混沌技能等级", "ref": "+# to Level of all Chaos Skill Gems"},
    {"id": "explicit.stat_619213329", "zh": "物理技能等级", "ref": "+# to Level of all Physical Skill Gems"},
    {"id": "explicit.stat_9187492", "zh": "近战技能等级", "ref": "+# to Level of all Melee Skill Gems"},

    # ── 召唤物 / Minion stats ──
    {"id": "explicit.stat_770672621", "zh": "召唤物生命", "ref": "Minions have #% increased maximum Life"},
    {"id": "explicit.stat_1589917703", "zh": "召唤物伤害", "ref": "Minions deal #% increased Damage"},
    {"id": "explicit.stat_2479683456", "zh": "召唤物生命回复", "ref": "Minions Regenerate #% of Life per second"},
    {"id": "explicit.stat_3523867985", "zh": "召唤物攻速", "ref": "Minions have #% increased Attack Speed"},
    {"id": "explicit.stat_2974417149", "zh": "召唤物暴击", "ref": "Minions have #% increased Critical Strike Chance"},

    # ── 伤害 / Damage ──
    {"id": "explicit.stat_2974417149", "zh": "法术伤害", "ref": "#% increased Spell Damage"},
    {"id": "explicit.stat_1509134228", "zh": "物理伤害", "ref": "#% increased Physical Damage"},
    {"id": "explicit.stat_3291658075", "zh": "冰冷伤害", "ref": "#% increased Cold Damage"},
    {"id": "explicit.stat_3299347043", "zh": "火焰伤害", "ref": "#% increased Fire Damage"},
    {"id": "explicit.stat_2891184298", "zh": "闪电伤害", "ref": "#% increased Lightning Damage"},
    {"id": "explicit.stat_1050105434", "zh": "混沌伤害", "ref": "#% increased Chaos Damage"},

    # ── 攻击 / Attack ──
    {"id": "explicit.stat_2672805335", "zh": "攻击速度", "ref": "#% increased Attack Speed"},
    {"id": "explicit.stat_691932474", "zh": "攻击伤害", "ref": "#% increased Attack Damage"},

    # ── 施法 / Cast ──
    {"id": "explicit.stat_2891184298", "zh": "施法速度", "ref": "#% increased Cast Speed"},

    # ── 移动速度 / Movement Speed ──
    {"id": "pseudo.pseudo_increased_movement_speed", "zh": "移动速度", "ref": "#% increased Movement Speed"},
    {"id": "explicit.stat_2250533757", "zh": "移动速度(explicit)", "ref": "#% increased Movement Speed"},

    # ── 暴击 / Critical ──
    {"id": "explicit.stat_587431675", "zh": "暴击率", "ref": "#% increased Global Critical Strike Chance"},
    {"id": "explicit.stat_3556824919", "zh": "暴击伤害", "ref": "+#% to Global Critical Strike Multiplier"},
    {"id": "explicit.stat_737908626", "zh": "法术暴击", "ref": "#% increased Critical Strike Chance for Spells"},

    # ── 其他常用 / Other common ──
    {"id": "pseudo.pseudo_increased_rarity", "zh": "物品稀有度", "ref": "#% increased Rarity of Items found"},
    {"id": "explicit.stat_280731498", "zh": "范围效果", "ref": "#% increased Area of Effect"},
    {"id": "explicit.stat_2067062068", "zh": "穿透", "ref": "Projectiles Pierce # additional Targets"},
    {"id": "explicit.stat_1256719186", "zh": "持续时间", "ref": "#% increased Duration"},
    {"id": "explicit.stat_3981238845", "zh": "精神", "ref": "+# to Spirit"},
    {"id": "explicit.stat_3981238845", "zh": "精魂", "ref": "+# to Spirit"},

    # ── 偷取 / Leech ──
    {"id": "explicit.stat_3556824919", "zh": "生命偷取", "ref": "#% of Physical Attack Damage Leeched as Life"},
    {"id": "explicit.stat_3556824919", "zh": "魔力偷取", "ref": "#% of Physical Attack Damage Leeched as Mana"},

    # ── 元素伤害加点 / Added Elemental Damage ──
    {"id": "explicit.stat_3032590688", "zh": "附加火焰伤害", "ref": "Adds # to # Fire Damage to Attacks"},
    {"id": "explicit.stat_1037193709", "zh": "附加冰冷伤害", "ref": "Adds # to # Cold Damage to Attacks"},
    {"id": "explicit.stat_3371854518", "zh": "附加闪电伤害", "ref": "Adds # to # Lightning Damage to Attacks"},

    # ── 宝石插槽 / Sockets ──
    {"id": "explicit.stat_1573130764", "zh": "技能插槽", "ref": "Has # Sockets"},

    # ── 抗性上限 / Max Resistances ──
    {"id": "explicit.stat_1011760251", "zh": "最大火焰抗性", "ref": "+#% to maximum Fire Resistance"},
    {"id": "explicit.stat_1011760251", "zh": "最大冰冷抗性", "ref": "+#% to maximum Cold Resistance"},

    # ── 其他 / Misc ──
    {"id": "explicit.stat_2230687504", "zh": "力量百分比", "ref": "#% increased Strength"},
    {"id": "explicit.stat_2974417149", "zh": "敏捷百分比", "ref": "#% increased Dexterity"},
    {"id": "explicit.stat_2230687504", "zh": "智慧百分比", "ref": "#% increased Intelligence"},
    {"id": "explicit.stat_3695891184", "zh": "伤害", "ref": "#% increased Damage"},
    {"id": "explicit.stat_3556824919", "zh": "击晕", "ref": "#% chance to gain an Endurance Charge when you Stun an Enemy"},

    # ── Pseudo totals (very important for trade) ──
    {"id": "pseudo.pseudo_total_life", "zh": "总生命", "ref": "+# total to maximum Life"},
    {"id": "pseudo.pseudo_total_mana", "zh": "总魔力", "ref": "+# total to maximum Mana"},
    {"id": "pseudo.pseudo_total_energy_shield", "zh": "总能量护盾", "ref": "+# total to maximum Energy Shield"},
    {"id": "pseudo.pseudo_total_fire_resistance", "zh": "总火焰抗性", "ref": "+#% total to Fire Resistance"},
    {"id": "pseudo.pseudo_total_cold_resistance", "zh": "总冰冷抗性", "ref": "+#% total to Cold Resistance"},
    {"id": "pseudo.pseudo_total_lightning_resistance", "zh": "总闪电抗性", "ref": "+#% total to Lightning Resistance"},
    {"id": "pseudo.pseudo_total_chaos_resistance", "zh": "总混沌抗性", "ref": "+#% total to Chaos Resistance"},
    {"id": "pseudo.pseudo_total_elemental_resistance", "zh": "总元素抗性", "ref": "+#% total Elemental Resistance"},
    {"id": "pseudo.pseudo_total_strength", "zh": "总力量", "ref": "+# total to Strength"},
    {"id": "pseudo.pseudo_total_dexterity", "zh": "总敏捷", "ref": "+# total to Dexterity"},
    {"id": "pseudo.pseudo_total_intelligence", "zh": "总智慧", "ref": "+# total to Intelligence"},
    {"id": "pseudo.pseudo_total_all_elemental_resistances", "zh": "总全元素抗性", "ref": "+#% total to all Elemental Resistances"},
    {"id": "pseudo.pseudo_total_life_regen", "zh": "总生命回复", "ref": "Regenerate # Life per second"},
]

# Deduplicate by ID
_seen_ids = set()
_UNIQUE_COMMON_STATS = []
for s in COMMON_STATS:
    if s["id"] not in _seen_ids:
        _seen_ids.add(s["id"])
        _UNIQUE_COMMON_STATS.append(s)
COMMON_STATS = _UNIQUE_COMMON_STATS


# ═══════════════════════════════════════════════════════════
#  Full stat index — loaded from JSON, used for fuzzy matching
# ═══════════════════════════════════════════════════════════

_full_stat_dict: dict = {}  # {stat_id: ref_text}
_keyword_index: dict = {}   # {word: set(stat_ids)}


def _load_full_index():
    """Load the full condensed stat dictionary and build keyword index."""
    global _full_stat_dict, _keyword_index
    if _full_stat_dict:
        return

    json_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "trade_stats_condensed.json")
    if not os.path.exists(json_path):
        # Try alternative path
        json_path = os.path.join(os.path.dirname(__file__), "data", "trade_stats_condensed.json")
    if not os.path.exists(json_path):
        logger.warning(f"Full stat index not found at {json_path}, fuzzy matching disabled")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        _full_stat_dict = json.load(f)

    # Build keyword index: word → set of stat_ids
    for sid, ref in _full_stat_dict.items():
        words = _tokenize(ref)
        for w in words:
            if w not in _keyword_index:
                _keyword_index[w] = set()
            _keyword_index[w].add(sid)

    logger.info(f"Loaded full stat index: {len(_full_stat_dict)} stats, {len(_keyword_index)} keywords")


def _tokenize(text: str) -> list:
    """Tokenize text into lowercase words, filtering out short/common words."""
    words = re.findall(r'[a-zA-Z]+', text.lower())
    stopwords = {"to", "of", "the", "a", "an", "and", "or", "is", "for", "with",
                 "as", "on", "in", "at", "by", "from", "that", "this", "it", "be",
                 "are", "was", "has", "have", "had", "do", "does", "did", "not",
                 "but", "if", "can", "will", "its", "you", "your"}
    return [w for w in words if len(w) > 1 and w not in stopwords]


def find_stat_id(description: str, stat_type: str = "explicit") -> Optional[str]:
    """Find the best matching stat ID for a given English description.

    Uses keyword overlap scoring to find the closest match in the full dictionary.

    Args:
        description: English description of the stat (e.g. "increased Area of Effect")
        stat_type: Preferred stat type prefix (explicit, pseudo, enchant, implicit)

    Returns:
        Best matching stat_id, or None if no good match found
    """
    _load_full_index()
    if not _full_stat_dict:
        return None

    desc_words = set(_tokenize(description))
    if not desc_words:
        return None

    # Score each candidate by keyword overlap
    candidate_scores: dict[str, float] = {}
    for word in desc_words:
        if word in _keyword_index:
            for sid in _keyword_index[word]:
                if sid not in candidate_scores:
                    candidate_scores[sid] = 0
                candidate_scores[sid] += 1

    if not candidate_scores:
        return None

    # Normalize by ref text length (prefer shorter/closer matches)
    # and boost preferred stat type
    best_id = None
    best_score = 0

    for sid, raw_score in candidate_scores.items():
        ref = _full_stat_dict.get(sid, "")
        ref_words = set(_tokenize(ref))
        if not ref_words:
            continue

        # Jaccard-like similarity
        overlap = len(desc_words & ref_words)
        score = overlap / max(len(desc_words | ref_words), 1)

        # Boost preferred type
        if sid.startswith(f"{stat_type}."):
            score *= 1.2
        # Slight penalty for pseudo when looking for explicit
        if stat_type == "explicit" and sid.startswith("pseudo."):
            score *= 0.8

        if score > best_score:
            best_score = score
            best_id = sid

    # Minimum threshold to avoid bad matches
    if best_score < 0.3:
        logger.debug(f"No good match for '{description}' (best score: {best_score:.2f})")
        return None

    return best_id


def get_common_stats_prompt() -> str:
    """Generate the stat reference text for the LLM prompt."""
    lines = []
    for s in COMMON_STATS:
        lines.append(f"  {s['id']} | {s['zh']} | {s['ref']}")
    return "\n".join(lines)


# Initialize on import
_load_full_index()
