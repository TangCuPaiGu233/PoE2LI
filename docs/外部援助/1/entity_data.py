"""entity_data.py — 全量实体数据加载层（由 poe2db 爬虫产出驱动）。

数据源：
  - poe2db_uniques.json       446 个传奇（含流派标签）
  - poe2db_ascendancies.json  升华职业列表（已清洗）

职责：把爬虫 JSON 加载成内存索引，提供给推荐 Agent 的实体解析 + 候选召回。
与 entity_dict.py 配合：entity_dict 管口语别名，本模块管全量真实数据。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

_DIR = os.path.dirname(os.path.abspath(__file__))

# 导航/非升华噪声词，加载时过滤
_ASC_NOISE = {
    "工艺", "使命", "引路石", "赞助", "天赋", "职业", "首页", "物品",
    "宝石", "词缀", "Act", "Economy", "家园",
}


@lru_cache(maxsize=1)
def load_uniques() -> list[dict]:
    """加载全量传奇：[{name, base_type, slug, archetypes:[...]}]"""
    path = os.path.join(_DIR, "poe2db_uniques.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_ascendancies() -> list[str]:
    """加载升华职业名（已清洗噪声）。"""
    path = os.path.join(_DIR, "poe2db_ascendancies.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    names = []
    for a in raw:
        n = a["name"] if isinstance(a, dict) else a
        if n and n not in _ASC_NOISE and n not in names:
            names.append(n)
    return names


@lru_cache(maxsize=1)
def _unique_name_set() -> set[str]:
    return {u["name"] for u in load_uniques()}


def is_unique(name: str) -> bool:
    """判断一个名字是否是已知传奇物品。"""
    return name in _unique_name_set()


def find_uniques_by_archetype(archetype: str, limit: int = 15) -> list[dict]:
    """按流派标签召回候选传奇（auto 候选来源的核心能力）。

    archetype: minion / ignite / poison / lightning / cold / physical / crit
    """
    hits = [u for u in load_uniques() if archetype in u.get("archetypes", [])]
    return hits[:limit]


def extract_unique_mentions(text: str, limit: int = 12) -> list[str]:
    """从用户提问里抽取出现的传奇名（user 候选来源：用户文字里点名了传奇）。"""
    found = []
    for u in load_uniques():
        if u["name"] in text and u["name"] not in found:
            found.append(u["name"])
        if len(found) >= limit:
            break
    return found


def stats() -> dict:
    uniques = load_uniques()
    arche = {}
    for u in uniques:
        for a in u.get("archetypes", []):
            arche[a] = arche.get(a, 0) + 1
    return {
        "total_uniques": len(uniques),
        "total_ascendancies": len(load_ascendancies()),
        "archetype_distribution": arche,
    }
