"""PoE2 trade base-type index (EN/CN) from official trade2/data/items."""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_DATA_PATHS = (
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data")),
    "/app/data",
)

_EN_SUFFIX_CATEGORY: tuple[tuple[str, str], ...] = (
    (" amulet", "accessory.amulet"),
    (" ring", "accessory.ring"),
    (" belt", "accessory.belt"),
    (" body armour", "armour.chest"),
    (" helmet", "armour.helmet"),
    (" gloves", "armour.gloves"),
    (" boots", "armour.boots"),
    (" shield", "armour.shield"),
    (" quiver", "armour.quiver"),
    (" bow", "weapon.bow"),
    (" crossbow", "weapon.crossbow"),
    (" spear", "weapon.spear"),
    (" javelin", "weapon.javelin"),
    (" claw", "weapon.claw"),
    (" dagger", "weapon.dagger"),
    (" wand", "weapon.wand"),
    (" sceptre", "weapon.sceptre"),
    (" staff", "weapon.staff"),
    (" warstaff", "weapon.warstaff"),
    (" mace", "weapon.onemace"),
    (" axe", "weapon.oneaxe"),
    (" sword", "weapon.onesword"),
    (" flask", "flask"),
    (" jewel", "jewel"),
    (" gem", "gem"),
    (" map", "map"),
)

_GROUP_DEFAULT_CATEGORY: dict[str, str] = {
    "accessory": "accessory",
    "armour": "armour.chest",
    "weapon": "weapon",
    "flask": "flask",
    "jewel": "jewel",
    "gem": "gem",
    "map": "map",
    "currency": "currency",
    "sanctum": "sanctum",
    "wombgift": "wombgift",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _data_dir() -> str:
    for base in _DATA_PATHS:
        if os.path.isdir(base):
            return base
    return _DATA_PATHS[0]


def _read_json(name: str) -> dict[str, Any]:
    path = os.path.join(_data_dir(), name)
    if not os.path.isfile(path):
        logger.warning("Missing trade items JSON: %s", name)
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def _load_en_cn() -> dict[str, Any]:
    return _read_json("trade_items_en_cn.json")


@lru_cache(maxsize=1)
def _load_bilingual() -> dict[str, Any]:
    return _read_json("trade_items_bilingual.json")


def _best_bilingual_pairs() -> tuple[dict[str, str], dict[str, str]]:
    best_en: dict[str, tuple[int, str]] = {}
    best_cn: dict[str, tuple[int, str]] = {}
    for group in _load_bilingual().get("groups") or []:
        for ent in group.get("entries") or []:
            en = (ent.get("text_en") or "").strip()
            cn = (ent.get("text_cn") or "").strip()
            if not en or not cn:
                continue
            idx = int(ent.get("index") or 0)
            prev_en = best_en.get(en)
            if prev_en is None or idx < prev_en[0]:
                best_en[en] = (idx, cn)
            prev_cn = best_cn.get(cn)
            if prev_cn is None or idx < prev_cn[0]:
                best_cn[cn] = (idx, en)
    return (
        {k: v[1] for k, v in best_en.items()},
        {k: v[1] for k, v in best_cn.items()},
    )


@lru_cache(maxsize=1)
def _en_to_cn_map() -> dict[str, str]:
    en_to_cn, _cn_to_en = _best_bilingual_pairs()
    raw = _load_en_cn().get("en_to_cn") or {}
    for k, v in raw.items():
        key = str(k).strip()
        val = str(v).strip()
        if key and val and key not in en_to_cn:
            en_to_cn[key] = val
    return en_to_cn


@lru_cache(maxsize=1)
def _cn_to_en_map() -> dict[str, str]:
    _en_to_cn, cn_to_en = _best_bilingual_pairs()
    raw = _load_en_cn().get("cn_to_en") or {}
    for k, v in raw.items():
        key = str(k).strip()
        val = str(v).strip()
        if key and val and key not in cn_to_en:
            cn_to_en[key] = val
    return cn_to_en


@lru_cache(maxsize=1)
def _cn_to_group_map() -> dict[str, str]:
    raw = _load_en_cn().get("cn_to_group") or {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if k and v}


@lru_cache(maxsize=1)
def _en_to_group_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for group in _load_bilingual().get("groups") or []:
        gid = (group.get("id") or "").strip()
        if not gid:
            continue
        for ent in group.get("entries") or []:
            en = (ent.get("text_en") or "").strip()
            if en:
                out[en] = gid
    cn_group = _cn_to_group_map()
    for en, cn in _en_to_cn_map().items():
        if en not in out and cn in cn_group:
            out[en] = cn_group[cn]
    return out


@lru_cache(maxsize=1)
def _prefix_index() -> tuple[list[str], list[str]]:
    return (
        sorted(_en_to_cn_map().keys(), key=str.lower),
        sorted(_cn_to_en_map().keys(), key=str.lower),
    )


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def en_to_cn_item(en_name: str) -> str | None:
    key = (en_name or "").strip()
    if not key:
        return None
    hit = _en_to_cn_map().get(key)
    if hit:
        return hit
    lower = key.lower()
    for k, v in _en_to_cn_map().items():
        if k.lower() == lower:
            return v
    return None


def cn_to_en_item(cn_name: str) -> str | None:
    key = (cn_name or "").strip()
    if not key:
        return None
    return _cn_to_en_map().get(key)


def resolve_base_type_cn(en_base: str) -> str | None:
    raw = (en_base or "").strip()
    if not raw:
        return None
    if has_cjk(raw):
        return raw
    return en_to_cn_item(raw)


def resolve_base_type_en(cn_base: str) -> str | None:
    raw = (cn_base or "").strip()
    if not raw:
        return None
    if not has_cjk(raw):
        return raw
    return cn_to_en_item(raw)


def group_id_for_en_type(en_type: str) -> str | None:
    key = (en_type or "").strip()
    if not key:
        return None
    hit = _en_to_group_map().get(key)
    if hit:
        return hit
    lower = key.lower()
    for k, v in _en_to_group_map().items():
        if k.lower() == lower:
            return v
    return None


def group_id_for_cn_type(cn_type: str) -> str | None:
    key = (cn_type or "").strip()
    if not key:
        return None
    hit = _cn_to_group_map().get(key)
    if hit:
        return hit
    en = cn_to_en_item(key)
    return group_id_for_en_type(en) if en else None


def trade_category_for_base(base_name: str) -> str | None:
    raw = (base_name or "").strip()
    if not raw:
        return None
    en = raw if not has_cjk(raw) else (cn_to_en_item(raw) or raw)
    lower = en.lower()
    for suffix, cat in _EN_SUFFIX_CATEGORY:
        if lower.endswith(suffix):
            return cat
    gid = group_id_for_en_type(en) or group_id_for_cn_type(raw)
    if gid:
        return _GROUP_DEFAULT_CATEGORY.get(gid, gid)
    return None


def resolve_item_query(query: str, limit: int = 15) -> list[dict[str, str]]:
    q = (query or "").strip()
    if not q or limit <= 0:
        return []
    ql = q.lower()
    en_keys, cn_keys = _prefix_index()
    en_to_cn = _en_to_cn_map()
    cn_to_en = _cn_to_en_map()
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    def add(en: str, cn: str) -> None:
        en = (en or "").strip()
        cn = (cn or "").strip()
        if not en or en in seen:
            return
        seen.add(en)
        out.append(
            {
                "text_en": en,
                "text_cn": cn or en_to_cn.get(en, ""),
                "group_id": group_id_for_en_type(en) or "",
                "category": trade_category_for_base(en) or "",
            }
        )

    if has_cjk(q):
        for cn in cn_keys:
            if not cn.startswith(q):
                continue
            add(cn_to_en.get(cn, ""), cn)
            if len(out) >= limit:
                return out
    else:
        for en in en_keys:
            if not en.lower().startswith(ql):
                continue
            add(en, en_to_cn.get(en, ""))
            if len(out) >= limit:
                return out
        if len(out) < limit:
            for cn in cn_keys:
                if not cn.lower().startswith(ql):
                    continue
                en = cn_to_en.get(cn, "")
                if en:
                    add(en, cn)
                if len(out) >= limit:
                    break
    return out


def counts_summary() -> dict[str, Any]:
    data = _load_en_cn()
    return {
        "counts": data.get("counts") or {},
        "en_to_cn": len(_en_to_cn_map()),
        "cn_to_en": len(_cn_to_en_map()),
    }
