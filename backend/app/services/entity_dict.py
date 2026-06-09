"""entity_dict.py — PoE2 职业 / 升华 / 流派别名词典。

用于推荐 Agent 的实体解析阶段：把玩家的口语化称呼（"死灵法师""召唤流"）
映射到标准实体，缩小向量检索范围、消除歧义。

数据可后续从 poe2db 抓取自动扩充，这里先内置高频项作为种子。
"""

# ── 基础职业（Class） ──
# 玩家口语别名 → 标准英文 Class
CLASS_ALIASES: dict[str, str] = {
    "女巫": "Witch", "法师": "Witch", "巫师": "Witch",
    "战士": "Warrior", "野蛮人": "Warrior",
    "游侠": "Ranger", "弓手": "Ranger",
    "佣兵": "Mercenary", "枪手": "Mercenary",
    "僧侣": "Monk", "武僧": "Monk",
    "德鲁伊": "Druid",
}

# ── 升华职业（Ascendancy） ──
# poe2db 中文升华名 → 所属 Class
ASCENDANCY_TO_CLASS: dict[str, str] = {
    # Witch
    "驱炎使": "Witch", "命源法师": "Witch", "巫妖": "Witch",
    "深渊巫妖": "Witch", "魔巫": "Witch",
    # Sorceress（poe2db 部分按法系细分）
    "风暴编织者": "Sorceress", "塑时术师": "Sorceress",
    # Warrior / Titan
    "泰坦": "Warrior", "战争使者": "Warrior", "奇塔弗匠师": "Warrior",
    # Ranger
    "锐眼": "Ranger", "追猎者": "Ranger",
    # Huntress
    "女猎手": "Huntress", "亚马逊": "Huntress",
    # Monk
    "灵魂行者": "Monk", "仪祭师": "Monk",
    # Mercenary
    "战术家": "Mercenary", "猎巫人": "Mercenary",
    # Druid
    "神谕者": "Druid", "萨满": "Druid", "行者": "Druid",
}

# ── 流派原型（Archetype） ──
# 玩家口语 → 内部 archetype 标签 + 检索增强关键词
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


def normalize_class(text: str) -> str | None:
    """从一段文本中识别基础职业，返回标准英文名。"""
    for alias, std in CLASS_ALIASES.items():
        if alias in text:
            return std
    # 也尝试直接匹配升华名反推职业
    for asc, cls in ASCENDANCY_TO_CLASS.items():
        if asc in text:
            return cls
    return None


def normalize_ascendancy(text: str) -> str | None:
    """从文本中识别升华职业（中文标准名）。"""
    for asc in ASCENDANCY_TO_CLASS:
        if asc in text:
            return asc
    return None


def detect_archetype(text: str) -> dict | None:
    """识别流派原型，返回 {archetype, keywords, ...}。"""
    for word, info in ARCHETYPE_HINTS.items():
        if word in text:
            return {"matched": word, **info}
    return None


def build_retrieval_keywords(parsed: dict) -> list[str]:
    """根据解析结果，拼出用于向量检索的增强关键词列表。"""
    kws: list[str] = []
    arche = parsed.get("archetype_info")
    if arche:
        kws.extend(arche.get("keywords", []))
    if parsed.get("class"):
        kws.append(parsed["class"])
    if parsed.get("ascendancy"):
        kws.append(parsed["ascendancy"])
    return list(dict.fromkeys(kws))  # 去重保序
