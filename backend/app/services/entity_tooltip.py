"""Entity mention detection and tooltip payloads for chat UI."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services.entity_resolver import _load_aliases
from app.services.retrieval_pipeline import (
    default_game_version,
    default_league,
    structured_entity_lookup,
)

ICON_RE = re.compile(
    r"(?:https?://cdn\.poe2db\.tw/image/)?(Art/2DItems/[^\s\"\'\]]+\.(?:png|webp|jpg))",
    re.IGNORECASE,
)
RARITY_RE = re.compile(r"Rarity:\s*(UNIQUE|RARE|MAGIC|NORMAL)", re.IGNORECASE)

POE2DB_TYPE_PATH = {
    "item": "Unique_item",
    "skill": "Skill_Gems",
    "ascendancy": "Ascendancy",
    "class": "Classes",
    "mod": "Modifiers",
}


def find_mentions(text: str) -> list[dict[str, Any]]:
    """Find non-overlapping CN entity mentions (longest match first)."""
    if not text:
        return []
    aliases = _load_aliases()
    sorted_cn = sorted(aliases.keys(), key=len, reverse=True)
    occupied = [False] * len(text)
    mentions: list[dict[str, Any]] = []

    for cn in sorted_cn:
        if len(cn) < 2:
            continue
        start = 0
        while True:
            idx = text.find(cn, start)
            if idx < 0:
                break
            end = idx + len(cn)
            if not any(occupied[idx:end]):
                for i in range(idx, end):
                    occupied[i] = True
                en_name, etype, _, _ = aliases[cn]
                mentions.append(
                    {
                        "start": idx,
                        "end": end,
                        "label": cn,
                        "name_en": en_name,
                        "type": etype,
                    },
                )
            start = idx + 1

    mentions.sort(key=lambda m: m["start"])
    return mentions


def _resolve_entity(name: str) -> tuple[str, str, str] | None:
    """Resolve display label, EN name, and type from CN or EN input."""
    key = (name or "").strip()
    if not key:
        return None
    aliases = _load_aliases()
    if key in aliases:
        en_name, etype, _, _ = aliases[key]
        return key, en_name, etype

    for cn, (en_name, etype, _, _) in aliases.items():
        if en_name.lower() == key.lower():
            return cn, en_name, etype
    return None


def _chunk_filter(etype: str) -> str | None:
    if etype == "ascendancy":
        return "asc_nodes"
    if etype in ("item", "skill"):
        return etype
    return None


def _parse_chunk_payload(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {"search_text": content}


def _extract_icon(content: str, data: dict[str, Any]) -> str | None:
    for blob in (content, data.get("search_text", ""), json.dumps(data, ensure_ascii=False)):
        if not blob:
            continue
        m = ICON_RE.search(str(blob))
        if m:
            path = m.group(1)
            if path.lower().startswith("http"):
                return path
            return f"https://cdn.poe2db.tw/image/{path.lstrip('/')}"
    detail = data.get("detail_path") or data.get("path")
    if detail:
        return f"https://cdn.poe2db.tw/image/Art/2DItems/{detail}.png"
    return None


def _description_excerpt(data: dict[str, Any], raw: str) -> str:
    for key in ("cn_description", "en_description", "tw_description", "description"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:320]
    text = data.get("search_text") or raw
    for marker in ("[CN Description]", "[EN Description]"):
        if marker in text:
            part = text.split(marker, 1)[1].split("[", 1)[0].strip()
            if part:
                return part[:320]
    return text.strip()[:320]


def _poe2db_url(data: dict[str, Any], etype: str, name_en: str) -> str | None:
    detail = data.get("detail_path") or data.get("path")
    if detail:
        return f"https://poe2db.tw/cn/{detail.lstrip('/')}"
    page = POE2DB_TYPE_PATH.get(etype)
    if page and name_en:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name_en).strip("_")
        return f"https://poe2db.tw/cn/{page}#{slug}"
    return None


def get_tooltip(db: Session, name: str) -> dict[str, Any] | None:
    resolved = _resolve_entity(name)
    if not resolved:
        return None
    label, name_en, etype = resolved
    chunk_filter = _chunk_filter(etype)
    if not chunk_filter:
        return {
            "label": label,
            "name_en": name_en,
            "type": etype,
            "rarity": None,
            "description": "",
            "icon_url": None,
            "poe2db_url": None,
        }

    chunks = structured_entity_lookup(
        db,
        [(etype, name_en, chunk_filter)],
        league=default_league(),
        game_version=default_game_version(),
    )
    if not chunks:
        return {
            "label": label,
            "name_en": name_en,
            "type": etype,
            "rarity": None,
            "description": "",
            "icon_url": None,
            "poe2db_url": _poe2db_url({}, etype, name_en),
        }

    chunk = chunks[0]
    raw = chunk.get("content") or ""
    data = _parse_chunk_payload(raw)
    search_blob = data.get("search_text") or raw
    rarity = data.get("rarity")
    if not rarity:
        rm = RARITY_RE.search(search_blob)
        rarity = rm.group(1).upper() if rm else None
    if etype == "item" and chunk.get("chunk_type") == "item" and not rarity:
        rarity = "UNIQUE"

    return {
        "label": label,
        "name_en": name_en,
        "type": etype,
        "rarity": rarity,
        "description": _description_excerpt(data, raw),
        "icon_url": _extract_icon(raw, data),
        "poe2db_url": _poe2db_url(data, etype, name_en),
    }
