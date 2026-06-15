"""entity_dict.py — PoE2 国服（腾讯）官方中文译名词典。

数据来源：
  - poe2.qq.com 官方页面
  - poe2cn.caimogu.cc 社区资料站（对齐国服译名）
  - poe2db 三语数据交叉验证

覆盖：基础职业 → 升华职业 → 流派别名，用于检索前精确匹配，避免向量跨语对齐偏差。
"""

# ═══════════════════════════════════════════════════════════════════
# 基础职业（Class）：国服官方名 + 社区别名 → 英文标准名
# ═══════════════════════════════════════════════════════════════════
CLASS_ALIASES: dict[str, str] = {
    # Witch
    "女巫": "Witch", "法师": "Witch", "巫师": "Witch",
    # Sorceress
    "魔巫": "Sorceress", "术士": "Sorceress",
    # Warrior
    "战士": "Warrior", "野蛮人": "Warrior",
    # Ranger
    "游侠": "Ranger", "弓手": "Ranger",
    # Mercenary
    "佣兵": "Mercenary", "枪手": "Mercenary",
    # Monk
    "行者": "Monk", "武僧": "Monk", "僧侣": "Monk",
    # Huntress
    "女猎手": "Huntress", "女猎": "Huntress",
    # Druid
    "德鲁伊": "Druid",
}

# ═══════════════════════════════════════════════════════════════════
# 升华职业（Ascendancy）：国服官方中文名 → 所属 Class
# ═══════════════════════════════════════════════════════════════════
ASCENDANCY_TO_CLASS: dict[str, str] = {
    # ── Witch 女巫 ──
    "驱炎使": "Witch",
    "命源法师": "Witch",
    "巫妖": "Witch",
    "深渊巫妖": "Witch",
    # ── Sorceress 魔巫 ──
    "风暴编织者": "Sorceress",
    "塑时术师": "Sorceress",
    "瓦拉煞的门徒": "Sorceress",
    # ── Warrior 战士 ──
    "泰坦": "Warrior",
    "战争使者": "Warrior",
    "奇塔弗匠师": "Warrior",
    # ── Ranger 游侠 ──
    "锐眼": "Ranger",
    "追猎者": "Ranger",
    # ── Monk 行者 ──
    "祈求者": "Monk",
    "灵魂行者": "Monk",
    "夏乌拉追随者": "Monk",
    # ── Mercenary 佣兵 ──
    "猎巫人": "Mercenary",
    "古灵使徒斗士": "Mercenary",
    "战术家": "Mercenary",
    # ── Huntress 女猎手 ──
    "亚马逊": "Huntress",
    "仪祭师": "Huntress",
    # ── Druid 德鲁伊 ──
    "神谕者": "Druid",
    "萨满": "Druid",
}

# 升华中文名 → 英文标准名（用于拼入检索 query）
ASCENDANCY_CN_TO_EN: dict[str, str] = {
    "驱炎使": "Infernalist",
    "命源法师": "Blood Mage",
    "巫妖": "Lich",
    "深渊巫妖": "Abyssal Lich",
    "风暴编织者": "Stormweaver",
    "塑时术师": "Chronomancer",
    "瓦拉煞的门徒": "Disciple of Varakath",
    "泰坦": "Titan",
    "战争使者": "Warbringer",
    "奇塔弗匠师": "Smith of Kitava",
    "锐眼": "Deadeye",
    "追猎者": "Pathfinder",
    "祈求者": "Invoker",
    "灵魂行者": "Spirit Walker",
    "夏乌拉追随者": "Acolyte of Chayula",
    "猎巫人": "Witchhunter",
    "古灵使徒斗士": "Gemling Legionnaire",
    "战术家": "Tactician",
    "亚马逊": "Amazon",
    "仪祭师": "Ritualist",
    "神谕者": "Oracle",
    "萨满": "Shaman",
}

# 基础职业中文名 → 英文标准名
CLASS_CN_TO_EN: dict[str, str] = {
    "女巫": "Witch", "法师": "Witch", "巫师": "Witch",
    "魔巫": "Sorceress", "术士": "Sorceress",
    "战士": "Warrior", "野蛮人": "Warrior",
    "游侠": "Ranger", "弓手": "Ranger",
    "佣兵": "Mercenary", "枪手": "Mercenary",
    "行者": "Monk", "武僧": "Monk", "僧侣": "Monk",
    "女猎手": "Huntress", "女猎": "Huntress",
    "德鲁伊": "Druid",
}

# ═══════════════════════════════════════════════════════════════════
ITEM_CN_ALIASES: dict[str, str] = {
    "沉默之雷": "Mjölner",
    # 国服 Trade API 官方译名（见 trade_items_en_cn.json）
    "畸变项链": "Twisted Amulet",
    "扭曲项链": "Distorted Amulet",
    # 社区俗称：Delirium 涂油项链底（非国服「扭曲项链」）
    "扭曲护身符": "Twisted Amulet",
}

# 流派原型（Archetype）
# ═══════════════════════════════════════════════════════════════════
ARCHETYPE_HINTS: dict[str, dict] = {
    "死灵": {
        "archetype": "minion",
        "keywords": ["召唤物", "尸体", "亡灵", "minion", "骷髅", "傀儡"],
        "preferred_class": "Witch",
        "preferred_ascendancy": ["深渊巫妖", "魔巫", "巫妖"],
    },
    "召唤": {
        "archetype": "minion",
        "keywords": ["召唤物", "minion", "图腾", "傀儡", "野兽"],
    },
    "点燃": {
        "archetype": "ignite",
        "keywords": ["点燃", "燃烧", "火焰伤害", "持续伤害", "ignite"],
    },
    "中毒": {
        "archetype": "poison",
        "keywords": ["中毒", "混沌伤害", "持续伤害", "poison"],
    },
    "暴击": {
        "archetype": "crit",
        "keywords": ["暴击", "暴击伤害", "critical"],
    },
    "电系": {
        "archetype": "lightning",
        "keywords": ["闪电伤害", "感电", "电能", "lightning"],
    },
}


# ═══════════════════════════════════════════════════════════════════
# 查找函数
# ═══════════════════════════════════════════════════════════════════

def normalize_class(text: str) -> str | None:
    """从文本中识别基础职业，返回标准英文名。"""
    for alias, std in CLASS_ALIASES.items():
        if alias in text:
            return std
    for asc, cls in ASCENDANCY_TO_CLASS.items():
        if asc in text:
            return cls
    return None


def normalize_ascendancy(text: str) -> str | None:
    """从文本中识别升华职业（国服中文标准名）。"""
    for asc in ASCENDANCY_TO_CLASS:
        if asc in text:
            return asc
    return None


def resolve_ascendancy_en(cn_name: str) -> str | None:
    """国服中文升华名 → 英文标准名。"""
    return ASCENDANCY_CN_TO_EN.get(cn_name)


def resolve_class_en(cn_name: str) -> str | None:
    """国服中文职业名 → 英文标准名。"""
    return CLASS_CN_TO_EN.get(cn_name)


def detect_archetype(text: str) -> dict | None:
    """识别流派原型，返回 {archetype, keywords, ...}。"""
    for word, info in ARCHETYPE_HINTS.items():
        if word in text:
            return {"matched": word, **info}
    return None


def build_retrieval_keywords(parsed: dict) -> list[str]:
    """根据解析结果，拼出向量检索增强关键词。"""
    kws: list[str] = []
    arche = parsed.get("archetype_info")
    if arche:
        kws.extend(arche.get("keywords", []))
    if parsed.get("class"):
        kws.append(parsed["class"])
    if parsed.get("ascendancy"):
        kws.append(parsed["ascendancy"])
    return list(dict.fromkeys(kws))
