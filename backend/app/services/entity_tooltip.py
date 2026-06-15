"""Entity mention detection and tooltip payloads for chat UI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.entity_icon_service import (
    _item_path_from_data,
    _poe2db_slug,
    resolve_icon_url,
)
from app.services.entity_resolver import _load_aliases
from app.services.retrieval_pipeline import default_game_version, default_league, structured_entity_lookup

ICON_RE = re.compile(
    r"(?:https?://cdn\.poe2db\.tw/image/)?(Art/2DItems/[^\s\"\'\]]+\.(?:png|webp|jpg))",
    re.IGNORECASE,
)
RARITY_RE = re.compile(r"Rarity:\s*(UNIQUE|RARE|MAGIC|NORMAL)", re.IGNORECASE)

FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

ALLOWED_MENTION_ETYPES = frozenset({"item", "skill", "ascendancy"})
MIN_MENTION_CONFIDENCE = 85

MENTION_SKIP = frozenset(
    {
        "女巫",
        "法师",
        "巫师",
        "战士",
        "野蛮人",
        "游侠",
        "僧侣",
        "佣兵",
        "女猎手",
        "闪电",
        "火焰",
        "冰霜",
        "混沌",
        "物理",
        "暴击",
        "攻击",
        "法术",
        "技能",
        "天赋",
        "装备",
        "武器",
        "护甲",
        "项链",
        "戒指",
        "腰带",
    },
)


def _is_continuation_char(ch: str) -> bool:
    if not ch:
        return False
    if ch.isalnum():
        return True
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF


def _valid_mention_boundaries(text: str, start: int, end: int) -> bool:
    if start > 0 and _is_continuation_char(text[start - 1]):
        return False
    if end < len(text) and _is_continuation_char(text[end]):
        return False
    return True


def _mask_code_spans(text: str, occupied: list[bool]) -> None:
    for pattern in (FENCED_CODE_RE, INLINE_CODE_RE):
        for match in pattern.finditer(text):
            for i in range(match.start(), match.end()):
                occupied[i] = True


def _alias_eligible_for_mention(cn: str, meta: tuple[str, str, int, str]) -> bool:
    _en, etype, confidence, source = meta
    if etype not in ALLOWED_MENTION_ETYPES:
        return False
    if confidence < MIN_MENTION_CONFIDENCE:
        return False
    if cn in MENTION_SKIP:
        return False
    if len(cn) < 3:
        return False
    if len(cn) < 4 and source != "curated_item":
        return False
    return True


POE2DB_TYPE_PATH = {
    "item": "Unique_item",
    "skill": "Skill_Gems",
    "ascendancy": "Ascendancy",
    "class": "Classes",
    "mod": "Modifiers",
}

TYPE_LABEL_CN = {
    "item": "暗金",
    "skill": "技能",
    "ascendancy": "升华",
}

RARITY_LABEL_CN = {
    "UNIQUE": "传奇",
    "RARE": "稀有",
    "MAGIC": "魔法",
    "NORMAL": "普通",
}

_POE2DB_ASC_SLUGS: dict[str, str] | None = None


def _load_asc_slug_map() -> dict[str, str]:
    global _POE2DB_ASC_SLUGS
    if _POE2DB_ASC_SLUGS is not None:
        return _POE2DB_ASC_SLUGS
    _POE2DB_ASC_SLUGS = {}
    asc_file = Path(__file__).resolve().parent / "poe2db_ascendancies.json"
    if asc_file.is_file():
        try:
            for row in json.loads(asc_file.read_text(encoding="utf-8")):
                slug = (row.get("slug") or "").strip()
                name = (row.get("name") or "").strip()
                if slug and name:
                    _POE2DB_ASC_SLUGS[name] = slug.rsplit("/", 1)[-1]
        except (json.JSONDecodeError, OSError):
            pass
    return _POE2DB_ASC_SLUGS


def _has_cjk(text: str) -> bool:
    return any(0x4E00 <= ord(ch) <= 0x9FFF for ch in text)


def _extract_cjk_excerpt(text: str, limit: int = 320) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and _has_cjk(line) and not line.startswith("http"):
            lines.append(line)
    if not lines:
        return ""
    return " ".join(lines)[:limit]


def _lookup_poe2db_detail_chunk(db: Session, path: str) -> dict[str, Any] | None:
    if not path:
        return None
    from app.models.build import KnowledgeChunk

    rows = (
        db.query(KnowledgeChunk)
        .filter(
            KnowledgeChunk.stale == False,  # noqa: E712
            KnowledgeChunk.content.ilike(f"%{path}%"),
        )
        .limit(40)
    )
    for row in rows:
        if row.chunk_type not in ("item", "skill", "wiki", "quest"):
            continue
        data = _parse_chunk_payload(row.content or "")
        dp = (data.get("detail_path") or data.get("path") or "").strip()
        if dp and path not in dp and dp.rsplit("/", 1)[-1] != path:
            continue
        return {
            "content": row.content or "",
            "data": data,
            "chunk_type": row.chunk_type,
        }
    return None


def _type_label(etype: str, lang: str) -> str:
    if lang == "cn":
        return TYPE_LABEL_CN.get(etype, etype)
    return etype


def _rarity_label(rarity: str | None, lang: str) -> str | None:
    if not rarity:
        return None
    if lang == "cn":
        return RARITY_LABEL_CN.get(rarity.upper(), rarity)
    return rarity


def find_mentions(text: str) -> list[dict[str, Any]]:
    """Find non-overlapping CN entity mentions (longest match first)."""
    if not text:
        return []
    aliases = _load_aliases()
    eligible = [
        cn for cn in aliases if _alias_eligible_for_mention(cn, aliases[cn])
    ]
    sorted_cn = sorted(eligible, key=len, reverse=True)
    occupied = [False] * len(text)
    _mask_code_spans(text, occupied)
    mentions: list[dict[str, Any]] = []

    for cn in sorted_cn:
        start = 0
        while True:
            idx = text.find(cn, start)
            if idx < 0:
                break
            end = idx + len(cn)
            if (
                not any(occupied[idx:end])
                and _valid_mention_boundaries(text, idx, end)
            ):
                for i in range(idx, end):
                    occupied[i] = True
                en_name, etype, _, _ = aliases[cn]
                icon_url = resolve_icon_url(
                    en_name,
                    etype,
                    name_cn=cn,
                    allow_fetch=False,
                )
                mentions.append(
                    {
                        "start": idx,
                        "end": end,
                        "label": cn,
                        "name_en": en_name,
                        "type": etype,
                        "icon_url": icon_url,
                    },
                )
            start = idx + 1

    seen_en: set[str] = set()
    en_entries: list[tuple[str, str, str]] = []
    for cn, meta in aliases.items():
        en_name, etype, _, _ = meta
        if etype not in ALLOWED_MENTION_ETYPES or len(en_name) < 5:
            continue
        if en_name in seen_en:
            continue
        if not _alias_eligible_for_mention(cn, meta):
            continue
        seen_en.add(en_name)
        en_entries.append((en_name, cn, etype))
    en_entries.sort(key=lambda x: len(x[0]), reverse=True)

    for en_name, cn, etype in en_entries:
        start = 0
        while True:
            idx = text.find(en_name, start)
            if idx < 0:
                break
            end = idx + len(en_name)
            if (
                not any(occupied[idx:end])
                and _valid_mention_boundaries(text, idx, end)
            ):
                for i in range(idx, end):
                    occupied[i] = True
                icon_url = resolve_icon_url(
                    en_name,
                    etype,
                    name_cn=cn,
                    allow_fetch=False,
                )
                mentions.append(
                    {
                        "start": idx,
                        "end": end,
                        "label": cn,
                        "name_en": en_name,
                        "type": etype,
                        "icon_url": icon_url,
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




def _cn_from_item_data(data: dict[str, Any]) -> str:
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
    return " ? ".join(parts)[:320]

def _description_excerpt(
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
        item_cn = _cn_from_item_data(data)
        if item_cn and _has_cjk(item_cn):
            return item_cn
        text_blob = data.get("search_text") or raw
        if "[CN Description]" in text_blob:
            part = text_blob.split("[CN Description]", 1)[1].split("[", 1)[0].strip()
            if part:
                return part[:320]
        cjk = _extract_cjk_excerpt(text_blob)
        if cjk:
            return cjk
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
    return text_blob.strip()[:320]


def _poe2db_url(data: dict[str, Any], etype: str, name_en: str) -> str | None:
    detail = data.get("detail_path") or data.get("path") or data.get("item_path")
    if detail:
        return f"https://poe2db.tw/cn/{detail.lstrip('/')}"
    page = POE2DB_TYPE_PATH.get(etype)
    if page and name_en:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name_en).strip("_")
        return f"https://poe2db.tw/cn/{page}#{slug}"
    return None


def get_tooltip(db: Session, name: str, *, lang: str = "cn") -> dict[str, Any] | None:
    resolved = _resolve_entity(name)
    if not resolved:
        return None
    label, name_en, etype = resolved
    if etype == "ascendancy" and lang == "cn":
        asc_slug = _load_asc_slug_map().get(label)
        if asc_slug:
            detail_hit = _lookup_poe2db_detail_chunk(db, asc_slug)
            if detail_hit:
                ddata = detail_hit["data"]
                desc = _description_excerpt(ddata, detail_hit["content"], lang=lang)
                if not _has_cjk(desc):
                    desc = "暂无中文升华说明，请点击链接查看 poe2db 详情。"
                icon_url = resolve_icon_url(
                    name_en,
                    etype,
                    name_cn=label,
                    chunk_blob=detail_hit["content"],
                    allow_fetch=False,
                )
                return {
                    "label": label,
                    "name_en": name_en,
                    "type": etype,
                    "type_label": _type_label(etype, lang),
                    "rarity": None,
                    "rarity_label": None,
                    "description": desc,
                    "icon_url": icon_url,
                    "poe2db_url": f"https://poe2db.tw/cn/{asc_slug}",
                }

    chunk_filter = _chunk_filter(etype)
    if not chunk_filter:
        return {
            "label": label,
            "name_en": name_en,
            "type": etype,
            "type_label": _type_label(etype, lang),
            "rarity": None,
            "rarity_label": None,
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
            "type_label": _type_label(etype, lang),
            "rarity": None,
            "rarity_label": None,
            "description": (
                "暂无中文说明，请点击下方链接查看 poe2db 详情。"
                if lang == "cn"
                else ""
            ),
            "icon_url": resolve_icon_url(
                name_en,
                etype,
                name_cn=label,
                allow_fetch=False,
            ),
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

    chunk_icon = _extract_icon(raw, data)
    icon_url = resolve_icon_url(
        name_en,
        etype,
        name_cn=label,
        chunk_blob=raw,
        allow_fetch=False,
    ) or chunk_icon

    description = _description_excerpt(data, raw, lang=lang)
    if lang == "cn" and not _has_cjk(description):
        if etype == "ascendancy":
            description = "暂无中文升华说明，请点击链接查看 poe2db 详情。"
        else:
            description = "暂无中文说明，请点击下方链接查看 poe2db 详情。"

    return {
        "label": label,
        "name_en": name_en,
        "type": etype,
        "type_label": _type_label(etype, lang),
        "rarity": rarity,
        "rarity_label": _rarity_label(rarity, lang),
        "description": description,
        "icon_url": icon_url,
        "poe2db_url": _poe2db_url(data, etype, name_en),
    }
