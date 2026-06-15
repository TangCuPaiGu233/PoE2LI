"""PoE2 Trade Search Service.

Parses natural-language Chinese queries into Trade API search requests,
returns clickable URLs that take users directly to search results.

Architecture:
  - LLM (SiliconFlow DeepSeek) extracts structured intent from Chinese query
  - BGE-M3 vector search maps stat descriptions to Trade API stat_ids
  - cloudscraper bypasses Cloudflare to call the official Trade API

Covers ALL trade page filter categories:
  - Item type (category)
  - Stat mods (via vector search on 7204 stat IDs)
  - Price range (chaos / divine / exalted)
  - Rarity (normal / magic / rare / unique)
  - Item level, quality, sockets, links
  - Weapon stats (damage, APS, crit, pDPS, eDPS)
  - Armour stats (armour, evasion, energy shield, block)
  - Map tier, map series
  - Special flags (corrupted, identified, mirrored, synthesised, etc.)
  - Gem level, flask quality
"""

import json
import re
import hashlib
import logging
import time
import os
from typing import Optional

import cloudscraper

from app.services import trade_items_index

from app.services.trade_realm import (
    DEFAULT_MARKET,
    referer_url,
    resolve_league,
    search_api_url,
    trade_page_url,
    trade_status_filter,
    get_realm,
)

logger = logging.getLogger(__name__)

# ── Rate limiting ──
MIN_REQUEST_INTERVAL = 6  # seconds between requests
_last_request_time = 0.0

# ── LLM config ──
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")


TRADE_CN_POESESSID = os.getenv("TRADE_CN_POESESSID", "")


# ═══════════════════════════════════════════════════════════
#  Item type reference (compact, for LLM prompt)
# ═══════════════════════════════════════════════════════════

ITEM_TYPES_ZH = {
    "项链": ("accessory.amulet", "Amulet"),
    "护身符": ("accessory.amulet", "Amulet"),
    "戒指": ("accessory.ring", "Ring"),
    "腰带": ("accessory.belt", "Belt"),
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
    "药剂": ("flask", "Flask"),
    "生命药剂": ("flask.life", "Life Flask"),
    "魔力药剂": ("flask.mana", "Mana Flask"),
    "珠宝": ("jewel", "Jewel"),
    "宝石": ("jewel", "Jewel"),
    "技能宝石": ("gem", "Skill Gem"),
    "地图": ("map", "Map"),
}

# Build compact item type reference for prompt
_ITEM_TYPE_REF = "\n".join(
    f"  {zh} → {cat_id}" for zh, (cat_id, _) in ITEM_TYPES_ZH.items()
)

# ═══════════════════════════════════════════════════════════
#  Rarity reference
# ═══════════════════════════════════════════════════════════

RARITY_ZH = {
    "普通": "normal",
    "白色": "normal",
    "魔法": "magic",
    "蓝色": "magic",
    "稀有": "rare",
    "黄色": "rare",
    "金装": "rare",
    "传奇": "unique",
    "暗金": "unique",
    "Unique": "unique",
}

_RARITY_REF = ", ".join(f"{zh}={v}" for zh, v in {
    "普通/白色": "normal",
    "魔法/蓝色": "magic",
    "稀有/黄色": "rare",
    "传奇/暗金": "unique",
}.items())


# ═══════════════════════════════════════════════════════════
#  LLM Intent Parsing — full filter + stat groups support
# ═══════════════════════════════════════════════════════════

TRADE_PARSE_SYSTEM_PROMPT = f"""你是一个 Path of Exile 2（流放之路2）装备交易搜索解析器。
用户会用中文描述想搜索的装备，你需要将其解析为结构化 JSON。

注意：这是 PoE2（流放之路2），不是 PoE1。

## 装备类型映射
{_ITEM_TYPE_REF}

## 稀有度映射
{_RARITY_REF}

## 货币类型
  混沌石 = chaos, 神圣石 = divine, 崇高石 = exalted

## 输出规则
请严格输出 JSON，不要其他文字。格式：
{{
  "item_type": "装备类型ID（从上面映射表选，没有则为 null）",
  "item_type_name": "装备英文名（没有则为 null）",
  "rarity": "稀有度（normal/magic/rare/unique 之一，没有则为 null）",
  "price": {{
    "currency": "货币类型（chaos/divine/exalted）",
    "min": 最低价格（数字或 null）,
    "max": 最高价格（数字或 null）
  }},
  "item_level": {{
    "min": 最低物品等级（数字或 null）,
    "max": 最高物品等级（数字或 null）
  }},
  "level_requirement": {{
    "min": 最低需求等级（数字或 null）,
    "max": 最高需求等级（数字或 null）
  }},
  "quality": {{
    "min": 最低品质（数字或 null）,
    "max": 最高品质（数字或 null）
  }},
  "sockets": {{
    "min": 最少孔数（数字或 null）,
    "max": 最多孔数（数字或 null）
  }},
  "links": {{
    "min": 最少链接数（数字或 null）,
    "max": 最多链接数（数字或 null）
  }},
  "weapon": {{
    "damage": {{"min": 数字或 null, "max": 数字或 null}},
    "aps": {{"min": 数字或 null, "max": 数字或 null}},
    "crit": {{"min": 数字或 null, "max": 数字或 null}},
    "pdps": {{"min": 物理DPS数字或 null, "max": 数字或 null}},
    "edps": {{"min": 元素DPS数字或 null, "max": 数字或 null}}
  }},
  "armour": {{
    "ar": {{"min": 护甲值数字或 null, "max": 数字或 null}},
    "ev": {{"min": 闪避值数字或 null, "max": 数字或 null}},
    "es": {{"min": 能量护盾数字或 null, "max": 数字或 null}},
    "block": {{"min": 格挡值数字或 null, "max": 数字或 null}}
  }},
  "map_tier": {{
    "min": 最低地图等级（数字或 null）,
    "max": 最高地图等级（数字或 null）
  }},
  "gem_level": {{
    "min": 最低宝石等级（数字或 null）,
    "max": 最高宝石等级（数字或 null）
  }},
  "flags": {{
    "corrupted": "是否腐化（true/false/null）",
    "identified": "是否已鉴定（true/false/null）",
    "mirrored": "是否镜子（true/false/null）",
    "synthesised": "是否合成（true/false/null）",
    "replica": "是否仿品（true/false/null）"
  }},
  "stat_groups": [
    {{
      "type": "and / not / count / weight2（选一种，见下方说明）",
      "count_min": "（仅 count 类型）至少匹配几条，数字",
      "weight_min": "（仅 weight2 类型）加权总分最低阈值，数字",
      "stats": [
        {{
          "desc_zh": "属性的中文描述",
          "desc_en": "The exact English stat name as it appears in-game. Be precise and use standard PoE2 wording.",
          "min": 数值最小值（数字或 null）,
          "max": 数值最大值（数字或 null）,
          "weight": "（仅 weight2 类型）权重值，正数=期望，负数=惩罚"
        }}
      ]
    }}
  ],
  "summary": "简短的搜索摘要（中文）"
}}

## stat_groups 类型说明（重要！）
这是 PoE2 交易网站的核心搜索逻辑，请根据用户意图选择最合适的类型：

### "and" — 全部匹配（最常用）
装备必须拥有组内所有词缀。用户说"要A和B"就用 and。
示例：用户说"火抗和生命" → type=and, 包含火抗+生命

### "not" — 排除（反面要求）
排除拥有组内任何词缀的装备。用户说"不要X"、"排除X"就用 not。
示例：用户说"不要有诅咒效果的" → type=not, 包含诅咒相关词缀

### "count" — 计数匹配（主题/方向性要求）
装备只需匹配组内至少 count_min 条词缀。当用户描述装备"方向"或"主题"时用 count。
示例：用户说"其他词条为召唤兽加成" → type=count, count_min=1, 包含多个召唤兽相关词缀
示例：用户说"至少有2条抗性" → type=count, count_min=2, 包含火/冰/电/混沌抗性

### "weight2" — 加权评分（高级比较）
给每个词缀设置权重，计算总分。用户说"生命比抗性重要"或"综合评分"时用。
weight 为正数表示期望（如生命 weight=3），负数表示惩罚（如减速 weight=-2）。
weight_min 是总分阈值。
示例：用户说"生命最重要，抗性其次" → type=weight2, 生命 weight=3, 抗性 weight=1

## 中文→英文游戏词缀对照表（来源：PoE2 官方交易站数据）

⚠️ desc_en 必须用下表中的标准英文表述。这些是游戏实际使用的文本，不是直译！

### 通用词缀
| 中文 | desc_en（标准游戏英文） |
|------|----------------------|
| 最大生命 | +# to maximum Life |
| 最大护盾/能量护盾 | +# to maximum Energy Shield |
| 最大魔力 | +# to maximum Mana |
| 火焰抗性/火炕 | +#% to Fire Resistance |
| 冰霜抗性/冰抗 | +#% to Cold Resistance |
| 闪电抗性/电抗 | +#% to Lightning Resistance |
| 混沌抗性/混抗 | +#% to Chaos Resistance |
| 全元素抗性 | +#% to all Elemental Resistances |
| 移动速度/移速 | #% increased Movement Speed |
| 攻击速度/攻速 | #% increased Attack Speed |
| 施法速度 | #% increased Cast Speed |
| 物品稀有度 | #% increased Rarity of Items found |
| 力量/敏捷/智慧 | +# to Strength / Dexterity / Intelligence |
| 全属性 | +# to all Attributes |

### 召唤/光环词缀
| 中文 | desc_en（标准游戏英文） |
|------|----------------------|
| 召唤技能等级 | # to Level of all Minion Skills |
| 法术技能等级 | # to Level of all Spell Skills |
| 精魂/精魄/Spirit | # to Spirit |
| 精魂提高% | #% increased Spirit |
| 召唤伤害 | Minions deal #% increased Damage |
| 召唤攻速/施法速度 | Minions have #% increased Attack and Cast Speed |
| 召唤生命 | Minions have #% increased maximum Life |
| 召唤全抗 | Minions have +#% to all Elemental Resistances |
| 召唤移动速度 | Minions have #% increased Movement Speed |
| 友军附加火焰伤害 | Allies in your Presence deal # to # added Attack Fire Damage |
| 友军附加冰霜伤害 | Allies in your Presence deal # to # added Attack Cold Damage |
| 友军附加闪电伤害 | Allies in your Presence deal # to # added Attack Lightning Damage |
| 友军附加物理伤害 | Allies in your Presence deal # to # added Attack Physical Damage |
| 友军伤害提高 | Allies in your Presence deal #% increased Damage |
| 友军攻速 | Allies in your Presence have #% increased Attack Speed |
| 友军施法速度 | Allies in your Presence have #% increased Cast Speed |
| 友军暴伤 | Allies in your Presence have #% increased Critical Damage Bonus |
| 光环效果 | #% increased effect of Non-Curse Auras from your Skills |

### 解析规则
1. desc_en 从上表中选。如果用户说的词不在表里，找最接近的，用游戏标准英文写。
2. 数值："加2" → min=2；"80以上" → min=80；"50到100" → min=50, max=100
3. 没指定具体数值时 min 和 max 都为 null
4. 只有用户明确提到的筛选条件才填写，未提及的对象设为 null
5. count 组的每个 stat 的 min/max 都设为 null（只要有这个词缀就行）
6. ⚠️ count 组的池子必须包含通用词缀！不要只列主题词缀——主题词缀可能在该装备上不存在。至少放 3-4 条通用词缀（最大生命 + 三种抗性）到池子里兜底

## 关键示例
### 示例1："加2召唤等级的项链，且至少包含2条召唤光环相关词缀"
⚠️ 注意 count 组里既有主题词缀（精魂、友军攻速/施法速度）也有通用词缀（最大生命、三抗、护盾）。通用词缀是兜底用的！
{{
  "item_type": "accessory.amulet",
  "stat_groups": [
    {{
      "type": "and",
      "stats": [
        {{"desc_zh": "召唤技能等级+2", "desc_en": "# to Level of all Minion Skills", "min": 2, "max": null}}
      ]
    }},
    {{
      "type": "count",
      "count_min": 2,
      "stats": [
        {{"desc_zh": "精魂", "desc_en": "# to Spirit", "min": null, "max": null}},
        {{"desc_zh": "友军攻速", "desc_en": "Allies in your Presence have #% increased Attack Speed", "min": null, "max": null}},
        {{"desc_zh": "友军施法速度", "desc_en": "Allies in your Presence have #% increased Cast Speed", "min": null, "max": null}},
        {{"desc_zh": "最大生命", "desc_en": "+# to maximum Life", "min": null, "max": null}},
        {{"desc_zh": "最大护盾", "desc_en": "+# to maximum Energy Shield", "min": null, "max": null}},
        {{"desc_zh": "火焰抗性", "desc_en": "+#% to Fire Resistance", "min": null, "max": null}},
        {{"desc_zh": "冰霜抗性", "desc_en": "+#% to Cold Resistance", "min": null, "max": null}},
        {{"desc_zh": "闪电抗性", "desc_en": "+#% to Lightning Resistance", "min": null, "max": null}}
      ]
    }}
  ]
}}

### 示例2："稀有戒指，生命80以上，火抗30以上"
{{
  "item_type": "accessory.ring",
  "rarity": "rare",
  "stat_groups": [
    {{
      "type": "and",
      "stats": [
        {{"desc_zh": "最大生命", "desc_en": "+# to maximum Life", "min": 80, "max": null}},
        {{"desc_zh": "火焰抗性", "desc_en": "+#% to Fire Resistance", "min": 30, "max": null}}
      ]
    }}
  ]
}}

### 示例3："召唤伤害和攻速的权杖"
{{
  "item_type": "weapon.sceptre",
  "stat_groups": [
    {{
      "type": "and",
      "stats": [
        {{"desc_zh": "召唤伤害", "desc_en": "Minions deal #% increased Damage", "min": null, "max": null}},
        {{"desc_zh": "友军攻速", "desc_en": "Allies in your Presence have #% increased Attack Speed", "min": null, "max": null}}
      ]
    }}
  ]
}}
"""


def _get_llm_client():
    """Get OpenAI-compatible client for SiliconFlow."""
    from openai import OpenAI
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def _extract_min_max(d: dict | None) -> dict | None:
    """Extract a clean {min, max} dict, returning None if both are absent."""
    if not d or not isinstance(d, dict):
        return None
    result = {}
    if d.get("min") is not None:
        result["min"] = d["min"]
    if d.get("max") is not None:
        result["max"] = d["max"]
    return result if result else None


def _resolve_stat(db, s: dict) -> dict | None:
    """Resolve a single stat via CN lookup then vector search."""
    from app.services.trade_stat_service import search_stats
    from app.services.trade_stats_index import resolve_stat_query

    desc_zh = s.get("desc_zh", "")
    desc_en = s.get("desc_en", "")
    if not desc_zh and not desc_en:
        return None

    exact_id = None
    for candidate in (desc_zh, desc_en):
        if candidate:
            exact_id = resolve_stat_query(candidate)
            if exact_id:
                break

    if exact_id:
        result = {
            "id": exact_id,
            "zh_name": desc_zh,
            "matched_ref": exact_id,
            "similarity": 1.0,
        }
        search_query = desc_en or desc_zh
    else:
        search_query = desc_en if desc_en else desc_zh
        matches = search_stats(db, search_query, top_k=5, stat_type="explicit", min_similarity=0.40)
        if not matches:
            matches = search_stats(db, search_query, top_k=5, min_similarity=0.40)
        if not matches:
            logger.warning(f"No vector match for stat: '{search_query}' (zh: {desc_zh})")
            return None
        best = matches[0]
        raw_id = best["stat_id"]
        if raw_id.startswith(("pseudo.", "crafted.", "enchant.", "implicit.", "rune.")):
            normalized_id = raw_id
        else:
            stat_num = raw_id.split(".", 1)[-1] if "." in raw_id else raw_id
            normalized_id = f"explicit.{stat_num}"
        result = {
            "id": normalized_id,
            "zh_name": desc_zh,
            "matched_ref": best["ref_text"],
            "similarity": best["similarity"],
        }

    if s.get("min") is not None:
        result["min"] = s["min"]
    if s.get("max") is not None:
        result["max"] = s["max"]
    if s.get("weight") is not None:
        result["weight"] = s["weight"]

    if exact_id:
        logger.info(f"CN/exact matched: '{desc_zh or desc_en}' -> {result['id']}")
    else:
        logger.info(
            f"Vector matched: '{search_query}' -> {result['id']} "
            f"({str(result.get('matched_ref', ''))[:40]}, sim={result['similarity']:.2f})"
        )
    return result


def parse_intent_ai(query: str) -> dict:
    """Parse a Chinese natural-language query using LLM + vector search.

    Step 1: LLM extracts item_type + stat_groups + all filter categories
    Step 2: Vector search maps each stat description to a Trade API stat_id

    Returns:
        {
            "item_type": ..., "rarity": ..., "price": ..., etc.,
            "stat_groups": [
                {"type": "and", "stats": [{"id": ..., "min": ...}, ...]},
                {"type": "count", "count_min": 1, "stats": [...]},
                {"type": "not", "stats": [...]},
                {"type": "weight2", "weight_min": 50, "stats": [...]},
            ],
            "summary": "..."
        }
    """
    from app.core.database import SessionLocal

    client = _get_llm_client()

    # Step 1: LLM extracts structured intent
    logger.info(f"Step 1: Calling LLM for intent parsing...")
    t1 = time.time()
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": TRADE_PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": f"搜索：{query}"}
            ],
            temperature=0.1,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        from app.core.llm_config import llm_message_text
        content = llm_message_text(resp.choices[0].message) if resp.choices else ""
        logger.info(f"LLM parsing took {time.time() - t1:.2f}s")
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {"item_type": None, "item_type_name": None, "stat_groups": [], "summary": query}

    # Parse JSON
    # Strip markdown code fences
    if content.startswith("```"):
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

    # Try to find JSON object in the response
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        content = json_match.group(0)

    try:
        parsed = json.loads(content)
        logger.info(f"LLM raw output parsed successfully. summary={parsed.get('summary', 'N/A')}, "
                    f"stat_groups={len(parsed.get('stat_groups') or [])}")
        logger.debug(f"LLM raw JSON: {json.dumps(parsed, ensure_ascii=False)}")
    except json.JSONDecodeError:
        logger.error(f"LLM returned invalid JSON: {content[:500]}")
        return {"item_type": None, "item_type_name": None, "stat_groups": [], "summary": query}

    item_type = parsed.get("item_type")
    item_type_name = parsed.get("item_type_name")
    summary = parsed.get("summary", query)

    # Extract structured filters (pass-through from LLM)
    rarity = parsed.get("rarity")
    price = parsed.get("price")
    item_level = _extract_min_max(parsed.get("item_level"))
    level_requirement = _extract_min_max(parsed.get("level_requirement"))
    quality = _extract_min_max(parsed.get("quality"))
    sockets = _extract_min_max(parsed.get("sockets"))
    links = _extract_min_max(parsed.get("links"))
    map_tier = _extract_min_max(parsed.get("map_tier"))
    gem_level = _extract_min_max(parsed.get("gem_level"))

    # Weapon filters
    weapon_raw = parsed.get("weapon")
    weapon = None
    if weapon_raw and isinstance(weapon_raw, dict):
        weapon = {}
        for key in ("damage", "aps", "crit", "pdps", "edps"):
            val = _extract_min_max(weapon_raw.get(key))
            if val:
                weapon[key] = val
        if not weapon:
            weapon = None

    # Armour filters
    armour_raw = parsed.get("armour")
    armour = None
    if armour_raw and isinstance(armour_raw, dict):
        armour = {}
        for key in ("ar", "ev", "es", "block"):
            val = _extract_min_max(armour_raw.get(key))
            if val:
                armour[key] = val
        if not armour:
            armour = None

    # Flags
    flags_raw = parsed.get("flags")
    flags = None
    if flags_raw and isinstance(flags_raw, dict):
        flags = {}
        for key in ("corrupted", "identified", "mirrored", "synthesised", "replica"):
            val = flags_raw.get(key)
            if val is not None and isinstance(val, bool):
                flags[key] = val
        if not flags:
            flags = None

    # Price: validate and clean
    if price and isinstance(price, dict):
        price_clean = {}
        if price.get("currency"):
            price_clean["currency"] = price["currency"]
        if price.get("min") is not None:
            price_clean["min"] = price["min"]
        if price.get("max") is not None:
            price_clean["max"] = price["max"]
        price = price_clean if price_clean.get("currency") else None

    # Step 2: Vector search for each stat in each stat_group
    logger.info(f"Step 2: Starting vector search for stats...")
    t2 = time.time()
    stat_groups = []
    db = SessionLocal()
    try:
        raw_groups = parsed.get("stat_groups") or []
        # Backward compatibility: if LLM outputs flat "stats" instead of "stat_groups"
        if not raw_groups and parsed.get("stats"):
            raw_groups = [{"type": "and", "stats": parsed["stats"]}]
        
        stat_count = 0
        for group in raw_groups:
            group_type = group.get("type", "and")
            resolved_stats = []
            total_in_group = len(group.get("stats") or [])

            for s in (group.get("stats") or []):
                matched = _resolve_stat(db, s)
                if matched:
                    resolved_stats.append(matched)
                    stat_count += 1

            # Warn if stats were dropped from the group
            if resolved_stats and len(resolved_stats) < total_in_group:
                logger.warning(
                    f"Stat group type={group_type}: {len(resolved_stats)}/{total_in_group} stats resolved. "
                    f"Dropped stats: {[s.get('desc_en', s.get('desc_zh', '?')) for s in (group.get('stats') or []) if not any(m.get('id') for m in resolved_stats if m)]}"
                )
            elif not resolved_stats:
                logger.warning(
                    f"Stat group type={group_type}: ALL {total_in_group} stats failed to resolve! "
                    f"Stats: {[s.get('desc_en', s.get('desc_zh', '?')) for s in (group.get('stats') or [])]}"
                )

            if resolved_stats:
                g = {"type": group_type, "stats": resolved_stats}
                if group_type == "count" and group.get("count_min") is not None:
                    g["count_min"] = group["count_min"]
                    # Safety: if count_min > number of resolved stats, adjust it
                    if g["count_min"] > len(resolved_stats):
                        logger.warning(
                            f"count_min ({g['count_min']}) > resolved stats ({len(resolved_stats)}), "
                            f"adjusting to {len(resolved_stats)}"
                        )
                        g["count_min"] = len(resolved_stats)
                if group_type == "weight2" and group.get("weight_min") is not None:
                    g["weight_min"] = group["weight_min"]
                stat_groups.append(g)
        logger.info(f"Vector search for {stat_count} stats took {time.time() - t2:.2f}s")
    finally:
        db.close()

    return {
        "item_type": item_type,
        "item_type_name": item_type_name,
        "rarity": rarity,
        "price": price,
        "item_level": item_level,
        "level_requirement": level_requirement,
        "quality": quality,
        "sockets": sockets,
        "links": links,
        "weapon": weapon,
        "armour": armour,
        "map_tier": map_tier,
        "gem_level": gem_level,
        "flags": flags,
        "stat_groups": stat_groups,
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════
#  Cloudscraper session (reusable across requests)
# ═══════════════════════════════════════════════════════════

_scrapers: dict[str, cloudscraper.CloudScraper] = {}


def _apply_cn_session(scraper: cloudscraper.CloudScraper) -> None:
    if not TRADE_CN_POESESSID:
        return
    scraper.cookies.set("POESESSID", TRADE_CN_POESESSID, domain="poe.game.qq.com")


def _get_scraper(market: str = DEFAULT_MARKET) -> cloudscraper.CloudScraper:
    """Get or create a per-realm cloudscraper session."""
    if market not in _scrapers:
        realm = get_realm(market)
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        scraper.headers.update({
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9,zh-CN,zh;q=0.9",
            "Origin": realm.origin,
            "Referer": referer_url(market),
        })
        if market == "cn":
            _apply_cn_session(scraper)
        _scrapers[market] = scraper
    return _scrapers[market]


def _rate_limit():
    """Enforce minimum interval between API requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


# ═══════════════════════════════════════════════════════════
#  Trade API query builder — full filter support
# ═══════════════════════════════════════════════════════════



TRADE_ITEM_SLOT_ALIASES: dict[str, str] = {
    "amulet": "accessory.amulet",
    "ring": "accessory.ring",
    "belt": "accessory.belt",
    "sceptre": "weapon.sceptre",
    "wand": "weapon.wand",
    "staff": "weapon.staff",
    "bow": "weapon.bow",
    "spear": "weapon.spear",
    "crossbow": "weapon.crossbow",
    "onesword": "weapon.onesword",
    "oneaxe": "weapon.oneaxe",
    "onemace": "weapon.onemace",
    "twosword": "weapon.twosword",
    "twoaxe": "weapon.twoaxe",
    "twomace": "weapon.twomace",
    "chest": "armour.chest",
    "helmet": "armour.helmet",
    "gloves": "armour.gloves",
    "boots": "armour.boots",
    "shield": "armour.shield",
    "quiver": "armour.quiver",
    "jewel": "jewel",
}


def normalize_trade_item_slot(slot: str | None) -> str | None:
    """Map short slot names to Trade API category IDs."""
    s = (slot or "").strip()
    if not s:
        return None
    if "." in s:
        return s
    key = s.lower()
    return TRADE_ITEM_SLOT_ALIASES.get(key, s)


def resolve_trade_base_type(name: str, market: str = DEFAULT_MARKET) -> str | None:
    """Return Trade API type field for the given market."""
    raw = (name or "").strip()
    if not raw:
        return None
    if market == "cn":
        if trade_items_index.has_cjk(raw):
            return raw
        cn = trade_items_index.resolve_base_type_cn(raw)
        return cn or raw
    if trade_items_index.has_cjk(raw):
        en = trade_items_index.resolve_base_type_en(raw)
        return en or raw
    return raw


def search_trade_item_suggestions(query: str, limit: int = 15) -> list[dict]:
    """Autocomplete trade base types (EN/CN)."""
    return trade_items_index.resolve_item_query(query, limit=limit)




def search_trade_stat_suggestions(query: str, limit: int = 15) -> list[dict]:
    from app.services.trade_stats_index import search_stat_suggestions

    return search_stat_suggestions(query, limit=limit)


def resolve_trade_stat(
    canonical_label: str,
    *,
    user_phrase: str = "",
    db=None,
    suggest_limit: int = 8,
) -> dict:
    """Resolve canonical Chinese stat label to stat_id (exact only for best)."""
    from app.services.trade_stats_index import (
        normalize_canonical_stat_label,
        resolve_stat_query_exact,
        resolve_stat_detail,
        search_stat_suggestions,
    )
    from app.services.trade_stat_service import search_stats
    from app.core.database import SessionLocal

    canonical = normalize_canonical_stat_label(canonical_label or "")
    phrase = (user_phrase or "").strip()
    suggest_q = canonical or phrase
    limit = max(1, min(int(suggest_limit or 8), 20))

    suggestions: list[dict] = list(search_stat_suggestions(suggest_q, limit=limit))
    seen_ids = {s.get("stat_id") for s in suggestions if s.get("stat_id")}

    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        if db is not None and suggest_q:
            try:
                vec_hits = search_stats(db, suggest_q, top_k=limit, min_similarity=0.40)
            except Exception:
                logger.debug("resolve_trade_stat vector suggest skipped", exc_info=True)
                vec_hits = []
            for hit in vec_hits or []:
                sid = hit.get("stat_id")
                if not sid or sid in seen_ids:
                    continue
                detail = resolve_stat_detail(sid)
                if not detail:
                    continue
                row = dict(detail)
                row["score"] = float(hit.get("similarity", 0) or 0) * 100.0
                row["match"] = "vector"
                suggestions.append(row)
                seen_ids.add(sid)
    finally:
        if own_db and db:
            db.close()

    suggestions.sort(key=lambda r: (-float(r.get("score") or 0), r.get("stat_id") or ""))
    suggestions = suggestions[:limit]

    exact_id = resolve_stat_query_exact(canonical, apply_slang=False) if canonical else None
    best = None
    need_disambiguation = True
    if exact_id:
        best = resolve_stat_detail(exact_id) or {}
        best["match"] = "exact"
        best["similarity"] = 1.0
        need_disambiguation = False

    return {
        "canonical_label": canonical,
        "user_phrase": phrase,
        "best": best,
        "need_disambiguation": need_disambiguation,
        "suggestions": suggestions,
    }


def build_trade_query(intent: dict, market: str = DEFAULT_MARKET) -> dict:
    """Build the Trade API search request body from parsed intent.

    Supports ALL trade page filter categories:
      - type_filters: category + rarity
      - trade_filters: price (chaos/divine/exalted)
      - misc_filters: ilvl, quality, corrupted, identified, mirrored, etc.
      - equipment_filters: damage, aps, crit, pdps, edps, ar, ev, es, block
      - map_filters: map_tier
      - socket_filters: sockets, links
    """
    query_body = {}
    if intent.get("unique_name"):
        query_body["name"] = intent["unique_name"]
    if intent.get("base_type"):
        query_body["type"] = resolve_trade_base_type(intent["base_type"], market=market)
    status = trade_status_filter(market)
    if status is not None:
        query_body["status"] = status
    filters = {}

    # ── Type filters: category + rarity + ilvl + quality (PoE2 places ilvl/quality here) ──
    type_f = {}
    if intent.get("item_type"):
        item_type = normalize_trade_item_slot(intent["item_type"])
        type_f["category"] = {"option": item_type}
    rarity_opt = intent.get("rarity")
    if intent.get("unique_name"):
        rarity_opt = "unique"
    if rarity_opt:
        type_f["rarity"] = {"option": rarity_opt}
    if intent.get("item_level"):
        type_f["ilvl"] = intent["item_level"]
    if intent.get("quality"):
        type_f["quality"] = intent["quality"]
    if type_f:
        filters["type_filters"] = {"filters": type_f}

    # ── Trade filters: price ──
    if intent.get("price"):
        price = intent["price"]
        trade_f = {"price": {"option": price.get("currency", "chaos")}}
        if price.get("min") is not None:
            trade_f["price"]["min"] = price["min"]
        if price.get("max") is not None:
            trade_f["price"]["max"] = price["max"]
        filters["trade_filters"] = {"filters": trade_f}

    # ── Requirements filters: level requirement ──
    req_f = {}
    if intent.get("level_requirement"):
        req_f["lvl"] = intent["level_requirement"]
    if req_f:
        filters["req_filters"] = {"filters": req_f}

    # ── Misc filters: flags, gem_level, corrupted, etc. ──
    misc_f = {}
    if intent.get("flags"):
        for flag_key, flag_val in intent["flags"].items():
            misc_f[flag_key] = {"option": flag_val}
    if intent.get("gem_level"):
        misc_f["gem_level"] = intent["gem_level"]
    if misc_f:
        filters["misc_filters"] = {"filters": misc_f}

    # ── Equipment filters: weapon + armour stats (PoE2 combines these) ──
    equip_f = {}
    weapon_data = intent.get("weapon")
    if weapon_data and isinstance(weapon_data, dict):
        for key in ("damage", "aps", "crit", "pdps", "edps"):
            val = weapon_data.get(key)
            if val and isinstance(val, dict):
                equip_f[key] = val
    armour_data = intent.get("armour")
    if armour_data and isinstance(armour_data, dict):
        for key in ("ar", "ev", "es", "block"):
            val = armour_data.get(key)
            if val and isinstance(val, dict):
                equip_f[key] = val
    if equip_f:
        filters["equipment_filters"] = {"filters": equip_f}

    # ── Map filters (endgame) ──
    if intent.get("map_tier"):
        filters["map_filters"] = {"filters": {"map_tier": intent["map_tier"]}}

    # ── Socket filters ──
    socket_f = {}
    if intent.get("sockets"):
        socket_f["sockets"] = intent["sockets"]
    if intent.get("links"):
        socket_f["links"] = intent["links"]
    if socket_f:
        filters["socket_filters"] = {"filters": socket_f}

    # ── Stat groups → Trade API stats array ──
    stats_array = []

    for group in (intent.get("stat_groups") or []):
        group_type = group.get("type", "and")
        group_filters = []

        for stat in (group.get("stats") or []):
            if not stat.get("id"):
                continue
            f = {"id": stat["id"], "disabled": False}

            if group_type == "weight2":
                # weight2: each stat gets a weight in its value
                f["value"] = {"weight": stat.get("weight", 1)}
            else:
                # and/not/count/if: standard min/max value
                value = {}
                if "min" in stat:
                    value["min"] = stat["min"]
                if "max" in stat:
                    value["max"] = stat["max"]
                if value:
                    f["value"] = value

            group_filters.append(f)

        if not group_filters:
            continue

        api_group = {"type": group_type, "filters": group_filters, "disabled": False}

        if group_type == "count":
            count_min = group.get("count_min", 1)
            api_group["value"] = {"min": count_min}

        if group_type == "weight2":
            weight_min = group.get("weight_min")
            if weight_min is not None:
                api_group["value"] = {"min": weight_min}

        stats_array.append(api_group)

    # Ensure at least one stats group exists
    if not stats_array:
        stats_array.append({"type": "and", "filters": [], "disabled": False})

    query_body["stats"] = stats_array

    if filters:
        query_body["filters"] = filters

    return {
        "query": query_body,
        "sort": {"price": "asc"},
    }


def search_trade(intent: dict, league: str | None = None, market: str = DEFAULT_MARKET) -> dict:
    """Execute a trade search and return the result."""
    trade_query = build_trade_query(intent, market=market)
    resolved_league = resolve_league(market, league)

    # Check Redis cache
    cache_key = f"trade:{market}:{resolved_league}:{hashlib.md5(json.dumps(trade_query, sort_keys=True).encode()).hexdigest()}"
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        cached = r.get(cache_key)
        if cached:
            logger.info(f"Trade cache hit: {cache_key}")
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"Redis cache check failed (non-critical): {e}")

    # Call Trade API
    logger.info(f"Step 3: Calling official Trade API...")
    t3 = time.time()
    _rate_limit()
    scraper = _get_scraper(market)
    url = search_api_url(market, resolved_league)

    query_json = json.dumps(trade_query, ensure_ascii=False)
    logger.info(f"Trade search POST to {url}: {query_json[:500]}")
    logger.debug(f"Trade search full query: {query_json}")

    try:
        resp = scraper.post(url, json=trade_query, timeout=30)
        logger.info(f"Trade API call took {time.time() - t3:.2f}s (status={resp.status_code})")
    except Exception as e:
        logger.error(f"Trade API request failed: {e}")
        return {"error": f"Trade API 请求失败: {e}"}

    if resp.status_code == 429:
        logger.warning("Trade API rate limited (429)")
        return {"error": "交易市场请求过于频繁，请稍后再试", "rate_limited": True}

    if resp.status_code == 401 and market == "cn":
        logger.error("CN Trade API 401: POESESSID missing or expired")
        return {"error": "国服交易 API 未授权：POESESSID 缺失或已过期。请在服务器 .env 中配置 TRADE_CN_POESESSID（浏览器登录 poe.game.qq.com 后从 Cookie 复制）。"}

    if resp.status_code != 200:
        logger.error(f"Trade API returned {resp.status_code}: {resp.text[:200]}")
        return {"error": f"Trade API 返回错误 ({resp.status_code})"}

    data = resp.json()
    search_id = data.get("id", "")

    if not search_id:
        return {"error": "Trade API 未返回搜索 ID"}

    item_ids = data.get("result") or []
    total = data.get("total") if data.get("total") is not None else len(item_ids)
    trade_url = trade_page_url(market, resolved_league, search_id)

    result = {
        "trade_url": trade_url,
        "search_id": search_id,
        "total_results": total,
        "item_ids": item_ids[:10],
        "intent_summary": intent.get("summary", ""),
        "filters": trade_query,
        "expires_in": 300,
    }

    # Cache in Redis (5 min TTL)
    try:
        from app.core.redis_client import get_redis
        get_redis().setex(cache_key, 300, json.dumps(result))
    except Exception:
        pass

    logger.info(f"Trade search success: {trade_url} (total={total})")
    return result


# ═══════════════════════════════════════════════════════════



COLLOQUIAL_CN_ALIASES: dict[str, str] = {
    "法血": "Mageblood",
    "猎首": "Headhunter",
    "战猫": "Kaoms Heart",
    "混池": "Chaos Orb",
    "神圣": "Divine Orb",
    "醒醒石": "Awakened Sextant",
}

_unique_cn_en_cache: dict | None = None


def _data_dir() -> str:
    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    return data_dir


def _load_unique_cn_en_map() -> dict[str, dict]:
    global _unique_cn_en_cache
    if _unique_cn_en_cache is not None:
        return _unique_cn_en_cache
    path = os.path.join(_data_dir(), "unique_cn_en.json")
    if not os.path.exists(path):
        _unique_cn_en_cache = {}
        return _unique_cn_en_cache
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _unique_cn_en_cache = data.get("cn_to_en") or {}
    return _unique_cn_en_cache


def _base_type_for_unique(en_name: str) -> str | None:
    try:
        from app.services.entity_data import load_uniques

        for u in load_uniques():
            if u.get("name") == en_name:
                bt = (u.get("base_type") or "").strip()
                return bt or None
    except Exception:
        pass
    return None



def _norm_en_key(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _cn_trade_lookup_for_en(en: str) -> tuple[str | None, str | None]:
    key = _norm_en_key(en)
    if not key:
        return None, None
    cn_map = _load_unique_cn_en_map()
    for cn, meta in cn_map.items():
        meta_en = (meta.get("en") or meta.get("path") or "").strip()
        if _norm_en_key(meta_en) == key:
            base_cn = (meta.get("base_cn") or "").strip() or None
            return cn, base_cn
    return None, None


def _finalize_unique_resolve(out: dict[str, str], cn_key: str | None = None) -> dict[str, str]:
    cn_name: str | None = None
    base_cn: str | None = None
    cn_map = _load_unique_cn_en_map()
    if cn_key and cn_key in cn_map:
        cn_name = cn_key
        base_cn = (cn_map[cn_key].get("base_cn") or "").strip() or None
    else:
        cn_name, base_cn = _cn_trade_lookup_for_en(out.get("unique_name", ""))
    if cn_name:
        out["trade_name_cn"] = cn_name
    if base_cn:
        out["trade_type_cn"] = base_cn
    return out


def _trade_api_unique_name(resolved: dict[str, str], market: str) -> str:
    if market == "cn":
        return (resolved.get("trade_name_cn") or "").strip()
    return (resolved.get("unique_name") or "").strip()


def resolve_trade_unique_name(text: str) -> dict[str, str] | None:
    """Resolve CN/EN/colloquial label to Trade API unique name + optional base type."""
    raw = (text or "").strip()
    if not raw:
        return None

    # Strip common price noise
    for noise in ("多少钱", "价格", "市价", "最便宜"):
        raw = raw.replace(noise, "")
    raw = raw.strip(" 	、，,；;")

    if raw in COLLOQUIAL_CN_ALIASES:
        en = COLLOQUIAL_CN_ALIASES[raw]
        if en.endswith(" Orb"):
            return None
        out = {"unique_name": en, "matched": raw, "source": "colloquial"}
        bt = _base_type_for_unique(en)
        if bt:
            out["base_type"] = bt
        return _finalize_unique_resolve(out)

    cn_map = _load_unique_cn_en_map()
    if raw in cn_map:
        en = (cn_map[raw].get("en") or "").strip()
        if en:
            out = {"unique_name": en, "matched": raw, "source": "unique_cn_en"}
            bt = _base_type_for_unique(en)
            if bt:
                out["base_type"] = bt
            return _finalize_unique_resolve(out, cn_key=raw)

    # Longest CN substring match
    cn_hits = [cn for cn in cn_map if cn and cn in raw]
    if cn_hits:
        cn = max(cn_hits, key=len)
        en = (cn_map[cn].get("en") or "").strip()
        if en:
            out = {"unique_name": en, "matched": cn, "source": "unique_cn_en_substring"}
            bt = _base_type_for_unique(en)
            if bt:
                out["base_type"] = bt
            return _finalize_unique_resolve(out, cn_key=cn)

    cn_name, _base_cn = _cn_trade_lookup_for_en(raw)
    if cn_name:
        meta = cn_map.get(cn_name, {})
        en = (meta.get("en") or raw).strip()
        if en:
            out = {"unique_name": en, "matched": raw, "source": "unique_cn_en_reverse"}
            bt = _base_type_for_unique(en)
            if bt:
                out["base_type"] = bt
            return _finalize_unique_resolve(out, cn_key=cn_name)

    from app.services.entity_resolver import resolve_entity

    hit = resolve_entity(raw)
    if hit:
        en_name, etype = hit[0], hit[1]
        if etype == "item" and en_name:
            out = {"unique_name": en_name, "matched": raw, "source": "entity_resolver"}
            bt = _base_type_for_unique(en_name)
            if bt:
                out["base_type"] = bt
            return _finalize_unique_resolve(out)

    from app.services.name_validation import known_unique_names

    canon = known_unique_names()
    lower = raw.lower()
    for name in sorted(canon, key=len, reverse=True):
        if name.lower() == lower or lower.startswith(name.lower()):
            out = {"unique_name": name, "matched": raw, "source": "canon_en"}
            bt = _base_type_for_unique(name)
            if bt:
                out["base_type"] = bt
            return _finalize_unique_resolve(out)

    return None


def search_unique_by_name(
    item_label: str,
    market: str = DEFAULT_MARKET,
    league: str | None = None,
    required_stat_ids: list[str] | None = None,
) -> dict:
    """Direct unique-item trade search by CN/EN/colloquial name."""
    resolved = resolve_trade_unique_name(item_label)
    if not resolved or not resolved.get("unique_name"):
        return {"error": f"无法识别暗金名称: {item_label}"}

    if market == "cn" and not resolved.get("trade_name_cn"):
        return {"error": f"无法识别国服暗金名称: {item_label}"}

    api_name = _trade_api_unique_name(resolved, market)
    if not api_name:
        return {"error": f"无法识别暗金名称: {item_label}"}

    intent: dict = {
        "rarity": "unique",
        "unique_name": api_name,
        "summary": f"unique {resolved.get('unique_name') or api_name}",
    }
    if market == "cn":
        if resolved.get("trade_type_cn"):
            intent["base_type"] = resolved["trade_type_cn"]
    elif resolved.get("base_type"):
        intent["base_type"] = resolved["base_type"]

    if required_stat_ids:
        intent["stat_groups"] = [{
            "type": "and",
            "stats": [{"id": sid, "min": 1} for sid in required_stat_ids],
        }]

    result = search_trade(intent, league=league, market=market)
    if isinstance(result, dict):
        result["resolved"] = resolved
    return result


MAX_TRADE_LISTING_DETAILS = 10

_CURRENCY_CN: dict[str, str] = {
    "chaos": "混沌石",
    "divine": "神圣石",
    "exalted": "崇高石",
    "exalt": "崇高石",
    "alch": "点金石",
    "alchemy": "点金石",
    "mirror": "镜子",
    "annul": "无效石",
    "regal": "富豪石",
    "vaal": "瓦尔石",
    "chromatic": "幻色石",
    "jeweller": "工匠石",
    "fusing": "连结石",
}

_FRAME_TYPE_LABELS: dict[int, str] = {
    0: "normal",
    1: "magic",
    2: "rare",
    3: "unique",
    4: "gem",
    5: "currency",
}

_ITEM_STRIP_KEYS = frozenset({"icon", "w", "h", "verified", "league"})

_LISTING_STRIP_KEYS = frozenset({"whisper", "hideout_token"})


def currency_display_cn(currency: str) -> str:
    return _CURRENCY_CN.get((currency or "").lower(), currency or "?")


def _format_prop_values(prop: dict) -> str:
    name = (prop.get("name") or "").strip()
    values = prop.get("values") or []
    parts: list[str] = []
    for v in values:
        if isinstance(v, list) and v:
            parts.append(str(v[0]))
        elif v is not None:
            parts.append(str(v))
    if parts:
        return f"{name}: {', '.join(parts)}" if name else ", ".join(parts)
    return name


def normalize_trade_listing_entry(entry: dict) -> dict:
    """Structured view of one Trade API fetch result (listing + item)."""
    from app.services.chat_item_profile import variant_label_from_mods

    listing = entry.get("listing") or {}
    price = listing.get("price") or {}
    item = entry.get("item") or {}

    explicit_mods = list(item.get("explicitMods") or [])
    implicit_mods = list(item.get("implicitMods") or [])

    amount = price.get("amount")
    currency = price.get("currency")
    price_block: dict = {}
    if amount is not None and currency:
        price_block = {
            "amount": amount,
            "currency": currency,
            "display": f"{amount} {currency_display_cn(currency)}",
            "type": price.get("type"),
        }

    listing_public = {
        k: v
        for k, v in listing.items()
        if k not in _LISTING_STRIP_KEYS and v not in (None, "", [])
    }
    if "account" in listing_public and isinstance(listing_public["account"], dict):
        listing_public["account"] = {
            k: v for k, v in listing_public["account"].items() if k in ("name", "lastCharacterName")
        }

    item_public = {
        k: v for k, v in item.items() if k not in _ITEM_STRIP_KEYS and v not in (None, "", [])
    }

    frame = item.get("frameType")
    rarity = _FRAME_TYPE_LABELS.get(frame) if isinstance(frame, int) else None

    name = (item.get("name") or "").strip()
    type_line = (item.get("typeLine") or "").strip()
    base_type = (item.get("baseType") or "").strip()
    if name and type_line:
        display_name = f"{name} {type_line}"
    else:
        display_name = name or type_line or base_type or ""

    out: dict = {
        "display_name": display_name,
        "price": price_block or None,
        "seller": (listing.get("account") or {}).get("name"),
        "listed_at": listing.get("indexed"),
        "rarity": rarity,
        "frame_type": frame,
        "name": name or None,
        "type_line": type_line or None,
        "base_type": base_type or None,
        "ilvl": item.get("ilvl"),
        "level_req": _level_requirement(item.get("requirements") or []),
        "quality": item.get("quality"),
        "sockets": item.get("sockets"),
        "links": item.get("links"),
        "identified": item.get("identified"),
        "corrupted": item.get("corrupted"),
        "mirrored": item.get("mirrored"),
        "split": item.get("split"),
        "influences": item.get("influences"),
        "implicit_mods": implicit_mods,
        "explicit_mods": explicit_mods,
        "crafted_mods": list(item.get("craftedMods") or []),
        "fractured_mods": list(item.get("fracturedMods") or []),
        "enchant_mods": list(item.get("enchantMods") or []),
        "utility_mods": list(item.get("utilityMods") or []),
        "properties": [_format_prop_values(p) for p in (item.get("properties") or [])],
        "requirements": [_format_prop_values(r) for r in (item.get("requirements") or [])],
        "additional_properties": [
            _format_prop_values(p) for p in (item.get("additionalProperties") or [])
        ],
        "variant_label": variant_label_from_mods(explicit_mods),
        "flavour_text": item.get("flavourText"),
        "descr_text": item.get("descrText"),
        "sec_descr_text": item.get("secDescrText"),
        "note": item.get("note"),
        "extended": item.get("extended"),
        "listing": listing_public or None,
        "item": item_public or None,
    }
    return {k: v for k, v in out.items() if v not in (None, [], {}, "")}


def _level_requirement(requirements: list) -> int | None:
    for req in requirements:
        name = (req.get("name") or "").lower()
        if "level" in name or name in ("等级",):
            values = req.get("values") or []
            if values and isinstance(values[0], list) and values[0]:
                try:
                    return int(str(values[0][0]).replace(",", ""))
                except ValueError:
                    pass
    return None


def fetch_trade_listings(
    trade_url: str,
    market: str = DEFAULT_MARKET,
    league: str | None = None,
    item_ids: list | None = None,
    count: int = 1,
    skip_rate_limit: bool = False,
) -> dict:
    """Fetch top-N listings with full item+listing details from a search URL."""
    from app.services.trade_realm import fetch_api_url, resolve_league, search_result_api_url

    count = max(1, min(int(count or 1), MAX_TRADE_LISTING_DETAILS))
    search_id = trade_url.rstrip("/").split("/")[-1] if trade_url else ""
    if not search_id:
        return {"listings": [], "error": "invalid trade URL"}

    resolved_league = resolve_league(market, league)
    scraper = _get_scraper(market)

    if item_ids:
        item_ids = list(item_ids)[:count]
    else:
        if not skip_rate_limit:
            _rate_limit()
        search_url = search_result_api_url(market, resolved_league, search_id)
        try:
            resp = scraper.get(search_url, timeout=15)
        except Exception as e:
            logger.error("Trade search result fetch failed: %s", e)
            return {"listings": [], "error": f"search result fetch failed: {e}"}

        if resp.status_code == 401 and market == "cn":
            return {
                "listings": [],
                "error": "国服交易 API 未授权：POESESSID 缺失或已过期。请在服务器 .env 中配置 TRADE_CN_POESESSID。",
            }
        if resp.status_code != 200:
            return {"listings": [], "error": f"search result HTTP {resp.status_code}"}

        item_ids = resp.json().get("result", [])[:count]

    if not item_ids:
        return {"listings": [], "error": "no listings", "search_id": search_id}

    if not skip_rate_limit:
        _rate_limit()
    fetch_url = fetch_api_url(market, item_ids, search_id)
    try:
        resp2 = scraper.get(fetch_url, timeout=20)
    except Exception as e:
        logger.error("Trade item fetch failed: %s", e)
        return {"listings": [], "error": f"item fetch failed: {e}", "search_id": search_id}

    if resp2.status_code == 401 and market == "cn":
        return {
            "listings": [],
            "error": "国服交易 API 未授权：POESESSID 缺失或已过期。",
            "search_id": search_id,
        }
    if resp2.status_code != 200:
        return {
            "listings": [],
            "error": f"item fetch HTTP {resp2.status_code}",
            "search_id": search_id,
        }

    entries = resp2.json().get("result", [])
    listings = [normalize_trade_listing_entry(e) for e in entries]
    return {"listings": listings, "search_id": search_id, "fetched_count": len(listings)}


def fetch_cheapest_listing(
    trade_url: str,
    market: str = DEFAULT_MARKET,
    league: str | None = None,
    item_ids: list | None = None,
    skip_rate_limit: bool = False,
) -> dict:
    """Fetch the cheapest listing price from a trade search page URL."""
    fetched = fetch_trade_listings(
        trade_url,
        market=market,
        league=league,
        item_ids=list(item_ids)[:5] if item_ids else None,
        count=5,
        skip_rate_limit=skip_rate_limit,
    )
    if fetched.get("error") and not fetched.get("listings"):
        return {"error": fetched["error"]}

    search_id = fetched.get("search_id") or (
        trade_url.rstrip("/").split("/")[-1] if trade_url else ""
    )
    last_err = fetched.get("error") or "no price on listing"
    for listing in fetched.get("listings") or []:
        price = listing.get("price") or {}
        amount = price.get("amount")
        currency = price.get("currency")
        if amount is None or not currency:
            continue
        return {
            "amount": amount,
            "currency": currency,
            "item_name": listing.get("display_name") or "",
            "search_id": search_id,
            "explicit_mods": listing.get("explicit_mods") or [],
            "implicit_mods": listing.get("implicit_mods") or [],
            "variant_label": listing.get("variant_label"),
        }
    return {"error": last_err if last_err != "no listings" else "no price on listing"}

#  Public API
# ═══════════════════════════════════════════════════════════

def trade_search(query: str, league: str | None = None, market: str = DEFAULT_MARKET) -> dict:
    """Main entry point: natural language query → trade URL.

    Uses AI (LLM) for intent parsing + vector search for stat matching.
    Supports ALL trade page filter categories: stats, price, rarity,
    item level, quality, sockets, links, weapon/armour stats, map tier,
    special flags, and more.

    Args:
        query: Chinese natural language (e.g. "帮我找一条加2召唤兽等级的项链，要有生命和抗性")
        league: League name

    Returns:
        Dict with trade_url, intent_summary, total_results, etc.
    """
    intent = parse_intent_ai(query)
    logger.info(f"Trade intent (AI): {json.dumps(intent, ensure_ascii=False)}")

    # Check if there's ANY search criteria (not just item_type + stats)
    has_filters = any([
        intent.get("item_type"),
        intent.get("stat_groups"),
        intent.get("rarity"),
        intent.get("price"),
        intent.get("item_level"),
        intent.get("level_requirement"),
        intent.get("quality"),
        intent.get("sockets"),
        intent.get("links"),
        intent.get("weapon"),
        intent.get("armour"),
        intent.get("map_tier"),
        intent.get("gem_level"),
        intent.get("flags"),
    ])

    if not has_filters:
        return {"error": "无法解析搜索意图，请描述具体的装备类型、属性要求或筛选条件"}

    return search_trade(intent, league, market)
