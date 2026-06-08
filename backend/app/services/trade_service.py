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

logger = logging.getLogger(__name__)

# ── Trade API endpoints ──
TRADE_API_BASE = "https://www.pathofexile.com/api/trade2/search/poe2"
TRADE_URL_BASE = "https://www.pathofexile.com/trade2/search/poe2"
TRADE_EXCHANGE_API = "https://www.pathofexile.com/api/trade2/exchange/poe2"

# ── Rate limiting ──
MIN_REQUEST_INTERVAL = 6  # seconds between requests
_last_request_time = 0.0

# ── LLM config ──
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")


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

## 解析要点
1. desc_en 必须用 PoE2 游戏中的标准英文表述，例如：
   - "火焰抗性" → "+#% to Fire Resistance"
   - "最大生命" → "+# to maximum Life"
   - "召唤技能等级" → "+# to Level of all Minion Skill Gems"
   - "移动速度" → "#% increased Movement Speed"
   - "法术技能等级" → "+# to Level of all Spell Skill Gems"
   - "攻击速度" → "#% increased Attack Speed"
   - "召唤伤害" → "Minions deal #% increased Damage"
   - "召唤攻速和施法速度" → "Minions have #% increased Attack and Cast Speed"
   - "召唤生命" → "Minions have #% increased maximum Life"
   - "护盾" → "+# to maximum Energy Shield"
2. 数值："加2" → min=2；"80以上" → min=80；"50到100" → min=50, max=100
3. 没指定具体数值时 min 和 max 都为 null
4. 只有用户明确提到的筛选条件才填写，未提及的整个对象设为 null
5. 价格："50c以内" → price.currency=chaos, price.max=50
6. 物品等级(ilvl)："ilvl 85以上" → item_level.min=85
7. 需求等级："需求等级55以下" → level_requirement.max=55
8. 品质："满品质" → quality.min=20
9. 孔和链接："6连" → links.min=6
10. 武器面板："物理DPS 300以上" → weapon.pdps.min=300
11. 护甲面板："护盾500以上" → armour.es.min=500

## 关键示例
### 示例1："加2召唤等级的项链，其他词条为召唤兽加成，需求等级55以下"
{{
  "item_type": "accessory.amulet",
  "level_requirement": {{"max": 55}},
  "stat_groups": [
    {{
      "type": "and",
      "stats": [
        {{"desc_zh": "召唤技能等级+2", "desc_en": "+# to Level of all Minion Skill Gems", "min": 2, "max": null}}
      ]
    }},
    {{
      "type": "count",
      "count_min": 1,
      "stats": [
        {{"desc_zh": "召唤伤害", "desc_en": "Minions deal #% increased Damage", "min": 1, "max": null}},
        {{"desc_zh": "召唤攻速和施法速度", "desc_en": "Minions have #% increased Attack and Cast Speed", "min": 1, "max": null}},
        {{"desc_zh": "召唤生命", "desc_en": "Minions have #% increased maximum Life", "min": 1, "max": null}}
      ]
    }}
  ]
}}

### 示例2："稀有戒指，生命80以上，火抗30以上，不要有诅咒效果"
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
    }},
    {{
      "type": "not",
      "stats": [
        {{"desc_zh": "诅咒效果", "desc_en": "#% increased Effect of Curses on you", "min": null, "max": null}}
      ]
    }}
  ]
}}

### 示例3："鞋子，生命权重大于移速，综合评分超过50"
{{
  "item_type": "armour.boots",
  "stat_groups": [
    {{
      "type": "weight2",
      "weight_min": 50,
      "stats": [
        {{"desc_zh": "最大生命", "desc_en": "+# to maximum Life", "min": null, "max": null, "weight": 3}},
        {{"desc_zh": "移动速度", "desc_en": "#% increased Movement Speed", "min": null, "max": null, "weight": 1}}
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
    """Resolve a single stat via vector search. Returns matched entry or None."""
    from app.services.trade_stats_index import search_stats

    desc_zh = s.get("desc_zh", "")
    desc_en = s.get("desc_en", "")
    if not desc_zh and not desc_en:
        return None

    search_query = desc_en if desc_en else desc_zh
    # Prefer explicit type (Trade API only accepts explicit.* IDs)
    matches = search_stats(db, search_query, top_k=3, stat_type="explicit", min_similarity=0.50)
    if not matches:
        matches = search_stats(db, search_query, top_k=3, min_similarity=0.50)

    if not matches:
        logger.warning(f"No vector match for stat: '{search_query}' (zh: {desc_zh})")
        return None

    best = matches[0]
    # Normalize stat_id to explicit type for Trade API compatibility
    raw_id = best["stat_id"]
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

    logger.info(
        f"Vector matched: '{search_query}' → {normalized_id} "
        f"({best['ref_text'][:40]}, sim={best['similarity']:.2f})"
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
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": TRADE_PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": f"搜索：{query}"}
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        content = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {"item_type": None, "item_type_name": None, "stat_groups": [], "summary": query}

    # Parse JSON
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error(f"LLM returned invalid JSON: {content[:300]}")
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
    stat_groups = []
    db = SessionLocal()
    try:
        raw_groups = parsed.get("stat_groups") or []
        # Backward compatibility: if LLM outputs flat "stats" instead of "stat_groups"
        if not raw_groups and parsed.get("stats"):
            raw_groups = [{"type": "and", "stats": parsed["stats"]}]

        for group in raw_groups:
            group_type = group.get("type", "and")
            resolved_stats = []

            for s in (group.get("stats") or []):
                matched = _resolve_stat(db, s)
                if matched:
                    resolved_stats.append(matched)

            if resolved_stats:
                g = {"type": group_type, "stats": resolved_stats}
                if group_type == "count" and group.get("count_min") is not None:
                    g["count_min"] = group["count_min"]
                if group_type == "weight2" and group.get("weight_min") is not None:
                    g["weight_min"] = group["weight_min"]
                stat_groups.append(g)
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

_scraper = None

def _get_scraper() -> cloudscraper.CloudScraper:
    """Get or create a cloudscraper session."""
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        _scraper.headers.update({
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.pathofexile.com",
            "Referer": "https://www.pathofexile.com/trade2/search/poe2/Standard",
        })
    return _scraper


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

def build_trade_query(intent: dict) -> dict:
    """Build the Trade API search request body from parsed intent.

    Supports ALL trade page filter categories:
      - type_filters: category + rarity
      - trade_filters: price (chaos/divine/exalted)
      - misc_filters: ilvl, quality, corrupted, identified, mirrored, etc.
      - equipment_filters: damage, aps, crit, pdps, edps, ar, ev, es, block
      - map_filters: map_tier
      - socket_filters: sockets, links
    """
    query_body = {
        "status": {"option": "online"},
    }
    filters = {}

    # ── Type filters: category + rarity + ilvl + quality (PoE2 places ilvl/quality here) ──
    type_f = {}
    if intent.get("item_type"):
        type_f["category"] = {"option": intent["item_type"]}
    if intent.get("rarity"):
        type_f["rarity"] = {"option": intent["rarity"]}
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


def search_trade(intent: dict, league: str = "Standard") -> dict:
    """Execute a trade search and return the result."""
    trade_query = build_trade_query(intent)

    # Check Redis cache
    cache_key = f"trade:{league}:{hashlib.md5(json.dumps(trade_query, sort_keys=True).encode()).hexdigest()}"
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
    _rate_limit()
    scraper = _get_scraper()
    url = f"{TRADE_API_BASE}/{league}"

    logger.info(f"Trade search POST to {url}: {json.dumps(trade_query, ensure_ascii=False)[:300]}")

    try:
        resp = scraper.post(url, json=trade_query, timeout=30)
    except Exception as e:
        logger.error(f"Trade API request failed: {e}")
        return {"error": f"Trade API 请求失败: {e}"}

    if resp.status_code == 429:
        wait_time = 60
        logger.warning(f"Trade API rate limited, waiting {wait_time}s")
        return {"error": f"搜索过于频繁，请 {wait_time} 秒后重试"}

    if resp.status_code != 200:
        logger.error(f"Trade API returned {resp.status_code}: {resp.text[:200]}")
        return {"error": f"Trade API 返回错误 ({resp.status_code})"}

    data = resp.json()
    search_id = data.get("id", "")

    if not search_id:
        return {"error": "Trade API 未返回搜索 ID"}

    total = data.get("total", 0)
    trade_url = f"{TRADE_URL_BASE}/{league}/{search_id}"

    result = {
        "trade_url": trade_url,
        "search_id": search_id,
        "total_results": total,
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
#  Public API
# ═══════════════════════════════════════════════════════════

def trade_search(query: str, league: str = "Standard") -> dict:
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

    return search_trade(intent, league)
