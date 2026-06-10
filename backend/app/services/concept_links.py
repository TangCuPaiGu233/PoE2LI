"""concept_links.py — 知识图谱概念指针系统。

三层关联体系:
  1. 实体名指针: 扫描文本中的已知实体名 (entity_resolver)
  2. 机制关键词: CONCEPT_HOOKS 词典 (~50 词)
  3. chunk_type 自关联: 同类型热门 chunk

新数据入库时调用 compute_links() 自动计算关联。
存量数据通过 backfill_links.py 批处理补算。
"""
import json
import re

# ═══════════════════════════════════════════════════════════════════
# 机制关键词 → 概念类型 (chunk_type) + 检索关键词
# 量小稳定，一个赛季加 1-2 个
# ═══════════════════════════════════════════════════════════════════
CONCEPT_HOOKS: dict[str, tuple[str, str]] = {
    # (触发词, chunk_type, 用于二级检索的关键词)
    # ── 涂油/启迪 ──
    "涂油": ("wiki", "anoint instilled notable enchant"),
    "anoint": ("wiki", "instilled notable enchantment oil"),
    "instilled": ("wiki", "instilled notable anoint"),
    "instill": ("wiki", "instilled notable anoint enchant"),
    "启迪": ("wiki", "anoint instilled notable enchant"),
    "notable": ("passive", "notable passive skill enchant"),
    "notable enchant": ("wiki", "instilled notable passive skill"),

    # ── 词缀系统 ──
    "前缀": ("mod", "prefix modifier affix"),
    "后缀": ("mod", "suffix modifier affix"),
    "词缀": ("mod", "prefix suffix affix modifier"),
    "prefix": ("mod", "prefix modifier affix"),
    "suffix": ("mod", "suffix modifier affix"),
    "modifier allowed": ("mod", "prefix suffix modifier slot limit"),
    "prefix modifier": ("mod", "prefix affix"),
    "suffix modifier": ("mod", "suffix affix"),

    # ── Delirium/梦魇 ──
    "梦魇": ("wiki", "delirium encounter"),
    "delirium": ("wiki", "delirium encounter mechanic"),

    # ── 腐化/瓦爾 ──
    "腐化": ("wiki", "corrupt vaal"),
    "corrupt": ("wiki", "corrupted vaal item"),
    "瓦爾": ("wiki", "vaal corrupt"),
    "vaal": ("wiki", "vaal corrupt orb"),

    # ── 精华 ──
    "精华": ("wiki", "essence item crafting"),
    "essence": ("item", "essence mod"),

    # ── Breach/裂痕 ──
    "裂痕": ("wiki", "breach encounter"),
    "breach": ("wiki", "breach encounter ring"),

    # ── Ritual/仪式 ──
    "仪式": ("wiki", "ritual tribute altar"),
    "ritual": ("wiki", "ritual tribute"),

    # ── 催化剂 ──
    "催化剂": ("item", "catalyst quality jewellery"),
    "catalyst": ("item", "catalyst quality"),

    # ── 预兆 ──
    "预兆": ("wiki", "omen crafting"),
    "omen": ("wiki", "omen crafting"),

    # ── 宝石系统 ──
    "辅助宝石": ("skill", "support gem"),
    "support gem": ("skill", "support gem link"),
    "精神宝石": ("skill", "spirit gem buff"),
    "spirit gem": ("skill", "spirit gem buff persistent"),

    # ── 其他通用 ──
    "基底": ("item", "base type"),
    "base type": ("item", "base item"),
    "暗金": ("item", "unique item"),
    "unique item": ("item", "unique legendary"),
    "天赋": ("passive", "passive skill tree"),
    "passive tree": ("passive", "skill tree node"),
    "升华": ("asc_nodes", "ascendancy notable"),
    "ascendancy": ("asc_nodes", "ascendancy notable passive"),
}


def compute_links(search_text: str, chunk_type: str = "") -> list[str]:
    """从文本中提取可关联的概念。

    Returns: list of concept keys, e.g. ["concept:涂油", "entity:Fireball", "concept:prefix_modifier"]
    """
    links: list[str] = []
    seen: set[str] = set()
    text_lower = search_text.lower()

    # 1. 机制关键词匹配
    for keyword, (ctype, search_kw) in CONCEPT_HOOKS.items():
        key = f"concept:{keyword}"
        if key in seen:
            continue
        if keyword.lower() in text_lower:
            links.append(f"concept:{keyword}:{ctype}:{search_kw}")
            seen.add(key)

    # 2. 实体名指针 — by entity_resolver
    try:
        from app.services.entity_resolver import resolve_all_entities as _resolve
        entities = _resolve(search_text)
        for en_name, cn_name, etype in entities:
            key = f"entity:{cn_name}"
            if key in seen:
                continue
            seen.add(key)
            links.append(f"entity:{cn_name}:{etype}:{en_name}")
    except Exception:
        pass  # entity_resolver not available (e.g. during migration)

    # 3. Chunk_type 自关联
    if chunk_type and chunk_type not in seen:
        seen.add(chunk_type)
        links.append(f"type:{chunk_type}")

    return links[:12]  # 最多 12 个关联


def parse_link(link: str) -> dict:
    """解析 link 字符串为结构化 dict。

    Link 格式: "prefix:key:type:extra"
    示例:
      "concept:涂油:wiki:anoint instilled notable enchant"
      "entity:灵魂行者:ascendancy:Spirit Walker"
      "type:item"
    """
    parts = link.split(":", 3)
    if len(parts) < 2:
        return {"kind": "unknown", "key": link, "type": "", "extra": ""}
    return {
        "kind": parts[0],        # concept / entity / type
        "key": parts[1],         # 概念名或实体名
        "type": parts[2] if len(parts) > 2 else "",
        "extra": parts[3] if len(parts) > 3 else "",
    }


def expand_query_for_link(link: str) -> tuple[str, str]:
    """根据 link 生成二级检索参数。(chunk_type_filter, search_keywords)"""
    info = parse_link(link)
    if info["kind"] == "concept":
        # 用 concept 的 type 作为 chunk_type 过滤，extra 作为检索词
        return info["type"], info["extra"]
    elif info["kind"] == "entity":
        # 用实体名作为检索词，不限类型
        return "", info["key"] + " " + info["extra"]
    elif info["kind"] == "type":
        return info["key"], info["key"]
    return "", info["key"]
