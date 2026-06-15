"""Shared entity profile extraction — used by catalog builder and runtime fallback."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.services.entity_icon_service import (
    _item_path_from_data,
    _poe2db_slug,
    resolve_icon_url,
    resolve_local_icon,
)
from app.services.retrieval_pipeline import (
    default_game_version,
    default_league,
    structured_entity_lookup,
)

POE2DB_TYPE_PATH = {
    "item": "Unique_item",
    "skill": "Skill_Gems",
    "ascendancy": "Ascendancy",
}

RARITY_RE = re.compile(r"Rarity:\s*(UNIQUE|RARE|MAGIC|NORMAL)", re.IGNORECASE)


@dataclass
class EntityProfile:
    """Canonical game entity record — single source for chip UI."""

    entity_key: str
    type: str
    name_en: str
    name_cn: str | None = None
    aliases: list[str] = field(default_factory=list)
    description_cn: str | None = None
    description_en: str | None = None
    rarity: str | None = None
    icon_local: str | None = None  # path relative to POE2LI data dir
    icon_url: str | None = None
    poe2db_url: str | None = None
    kb_chunk_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def entity_key(etype: str, name_en: str) -> str:
    return f"{etype}:{_poe2db_slug(name_en)}"


def parse_chunk_payload(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {"search_text": content}


def has_cjk(text: str) -> bool:
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text)


def cn_from_item_data(data: dict[str, Any]) -> str:
    cn = data.get("cn_data")
    if isinstance(cn, str):
        try:
            cn = json.loads(cn)
        except (json.JSONDecodeError, TypeError):
            cn = None
    if not isinstance(cn, dict):
        return ""
    parts: list[str] = []
    name = cn.get("name")
    if isinstance(name, str) and name.strip():
        parts.append(name.strip())
    stats = cn.get("stats_full")
    if isinstance(stats, str) and stats.strip():
        parts.append(stats.strip())
    else:
        for key in ("item_type", "implicit_mods", "explicit_mods"):
            val = cn.get(key)
            if isinstance(val, list):
                parts.extend(str(x).strip() for x in val if str(x).strip())
            elif isinstance(val, str) and val.strip():
                parts.append(val.strip())
    return " · ".join(parts)[:320]


def description_from_chunk(
    data: dict[str, Any],
    raw: str,
    *,
    lang: str = "cn",
) -> str:
    if lang == "cn":
        for key in ("cn_description", "tw_description"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:320]
        item_cn = cn_from_item_data(data)
        if item_cn and has_cjk(item_cn):
            return item_cn
        text_blob = data.get("search_text") or raw
        if "[CN Description]" in text_blob:
            part = text_blob.split("[CN Description]", 1)[1].split("[", 1)[0].strip()
            if part:
                return part[:320]
        for line in text_blob.splitlines():
            line = line.strip()
            if line and has_cjk(line) and not line.startswith("http"):
                return line[:320]
    for key in ("cn_description", "en_description", "tw_description", "description"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:320]
    text_blob = data.get("search_text") or raw
    for marker in ("[CN Description]", "[EN Description]"):
        if marker in text_blob:
            part = text_blob.split(marker, 1)[1].split("[", 1)[0].strip()
            if part:
                return part[:320]
    return (text_blob.strip()[:320] if lang != "cn" else "")


def poe2db_url_from_data(data: dict[str, Any], etype: str, name_en: str) -> str | None:
    detail = data.get("detail_path") or data.get("path") or data.get("item_path")
    if detail:
        return f"https://poe2db.tw/cn/{str(detail).lstrip('/')}"
    page = POE2DB_TYPE_PATH.get(etype)
    if page and name_en:
        slug = _poe2db_slug(name_en)
        return f"https://poe2db.tw/cn/{page}#{slug}"
    if etype == "item":
        path = _item_path_from_data(None, name_en)
        if path:
            return f"https://poe2db.tw/cn/{path.lstrip('/')}"
    return None


def _chunk_filter(etype: str) -> str | None:
    if etype == "ascendancy":
        return "asc_nodes"
    if etype in ("item", "skill"):
        return etype
    return None


def _relative_icon_path(local_path: Any, data_dir: Any) -> str | None:
    if not local_path:
        return None
    try:
        rel = local_path.resolve().relative_to(data_dir.resolve())
        return rel.as_posix()
    except ValueError:
        return str(local_path)


def build_profile(
    db: Session,
    etype: str,
    name_en: str,
    *,
    name_cn: str | None = None,
    extra_aliases: list[str] | None = None,
    data_dir: Any = None,
) -> EntityProfile:
    """Build one profile from KB + icon caches (catalog builder entry point)."""
    from app.services.entity_icon_service import _data_dir

    data_root = data_dir or _data_dir()
    chunk_filter = _chunk_filter(etype)
    raw = ""
    data: dict[str, Any] = {}
    chunk_id: int | None = None
    rarity: str | None = None

    if chunk_filter:
        chunks = structured_entity_lookup(
            db,
            [(etype, name_en, chunk_filter)],
            league=default_league(),
            game_version=default_game_version(),
        )
        if chunks:
            chunk = chunks[0]
            raw = chunk.get("content") or ""
            data = parse_chunk_payload(raw)
            chunk_id = chunk.get("id")
            search_blob = data.get("search_text") or raw
            rarity = data.get("rarity")
            if not rarity:
                rm = RARITY_RE.search(search_blob)
                rarity = rm.group(1).upper() if rm else None
            if etype == "item" and chunk.get("chunk_type") == "item" and not rarity:
                rarity = "UNIQUE"

    desc_cn = description_from_chunk(data, raw, lang="cn")
    desc_en = description_from_chunk(data, raw, lang="en")
    poe2db = poe2db_url_from_data(data, etype, name_en)

    local = resolve_local_icon(name_en, etype, name_cn=name_cn)
    icon_local = _relative_icon_path(local, data_root) if local else None
    icon_url = resolve_icon_url(
        name_en,
        etype,
        name_cn=name_cn,
        chunk_blob=raw or None,
        allow_fetch=False,
    )

    aliases = list(extra_aliases or [])
    if name_cn and name_cn not in aliases:
        aliases.insert(0, name_cn)

    return EntityProfile(
        entity_key=entity_key(etype, name_en),
        type=etype,
        name_en=name_en,
        name_cn=name_cn,
        aliases=aliases,
        description_cn=desc_cn or None,
        description_en=desc_en or None,
        rarity=rarity,
        icon_local=icon_local,
        icon_url=icon_url,
        poe2db_url=poe2db,
        kb_chunk_id=chunk_id,
    )
