"""Runtime Entity Catalog ? O(1) lookup for chip icon + tooltip."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.entity_icon_service import _data_dir
from app.services.entity_profile import EntityProfile, has_cjk

logger = logging.getLogger(__name__)

TYPE_LABEL_CN = {
    "item": "\u6697\u91d1",
    "item_base": "\u57fa\u5e95",
    "skill": "\u6280\u80fd",
    "ascendancy": "\u5347\u534e",
}

RARITY_LABEL_CN = {
    "UNIQUE": "\u4f20\u5947",
    "RARE": "\u7a00\u6709",
    "MAGIC": "\u9b54\u6cd5",
    "NORMAL": "\u666e\u901a",
}

_catalog_mtime: float | None = None
_entities: dict[str, dict[str, Any]] = {}
_alias_index: dict[str, str] = {}


def _catalog_path() -> Path:
    return _data_dir() / "entity_catalog.json"


def _load_catalog(force: bool = False) -> bool:
    global _catalog_mtime, _entities, _alias_index
    path = _catalog_path()
    if not path.is_file():
        _entities = {}
        _alias_index = {}
        _catalog_mtime = None
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    if not force and _catalog_mtime == mtime and _entities:
        return True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("entity_catalog.json load failed: %s", exc)
        return False
    entities = raw.get("entities") or {}
    if not isinstance(entities, dict):
        return False
    alias_index: dict[str, str] = {}
    for key, row in entities.items():
        if not isinstance(row, dict):
            continue
        for alias in row.get("aliases") or []:
            if alias:
                alias_index[str(alias).strip().lower()] = key
        for field in ("name_cn", "name_en"):
            val = row.get(field)
            if val:
                alias_index[str(val).strip().lower()] = key
        alias_index[str(key).split(":", 1)[-1].lower()] = key
    _entities = entities
    _alias_index = alias_index
    _catalog_mtime = mtime
    logger.info("entity catalog loaded: %d entities, %d aliases", len(_entities), len(_alias_index))
    return True


def catalog_available() -> bool:
    return _load_catalog()


def catalog_stats() -> dict[str, int | bool]:
    ok = _load_catalog()
    return {"available": ok, "entity_count": len(_entities), "alias_count": len(_alias_index)}


def resolve_entity_key(name: str) -> str | None:
    if not name or not _load_catalog():
        return None
    return _alias_index.get(name.strip().lower())


def get_entity_profile(name: str) -> EntityProfile | None:
    entity_key = resolve_entity_key(name)
    if not entity_key:
        return None
    row = _entities.get(entity_key)
    if not row:
        return None
    fields = EntityProfile.__dataclass_fields__
    return EntityProfile(**{k: row.get(k) for k in fields})


def icon_local_path(profile: EntityProfile) -> Path | None:
    if not profile.icon_local:
        return None
    path = _data_dir() / profile.icon_local
    return path if path.is_file() else None


def profile_to_tooltip(profile: EntityProfile, *, lang: str = "cn") -> dict[str, Any]:
    label = profile.name_cn or profile.name_en
    if lang == "cn":
        description = profile.description_cn or ""
        if not has_cjk(description):
            if profile.type == "ascendancy":
                description = "\u6682\u65e0\u4e2d\u6587\u5347\u534e\u8bf4\u660e\uff0c\u8bf7\u70b9\u51fb\u94fe\u63a5\u67e5\u770b poe2db \u8be6\u60c5\u3002"
            elif not description:
                description = "\u6682\u65e0\u4e2d\u6587\u8bf4\u660e\uff0c\u8bf7\u70b9\u51fb\u4e0b\u65b9\u94fe\u63a5\u67e5\u770b poe2db \u8be6\u60c5\u3002"
    else:
        description = profile.description_en or profile.description_cn or ""
    rarity = profile.rarity
    is_base = (
        profile.type == "item"
        and (rarity or "").upper() == "NORMAL"
    )
    if lang == "cn":
        type_label = (
            TYPE_LABEL_CN["item_base"]
            if is_base
            else TYPE_LABEL_CN.get(profile.type, profile.type)
        )
    else:
        type_label = profile.type
    return {
        "label": label,
        "name_en": profile.name_en,
        "type": profile.type,
        "item_kind": "base" if is_base else "unique",
        "type_label": type_label,
        "rarity": rarity,
        "rarity_label": (
            RARITY_LABEL_CN.get(rarity.upper(), rarity) if rarity and lang == "cn" else rarity
        ),
        "description": description,
        "icon_url": profile.icon_url,
        "poe2db_url": profile.poe2db_url,
        "entity_key": profile.entity_key,
        "from_catalog": True,
    }
