"""Resolve official PoE2 entity icons (web.poecdn.com via poe2db pages)."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

POECDN_ICON_RE = re.compile(
    r"https://web\.poecdn\.com/gen/image/[^\"'\s\]]+\.(?:png|webp)",
    re.IGNORECASE,
)
POE2DB_ART_RE = re.compile(
    r"(?:https?://cdn\.poe2db\.tw/image/)?(Art/[^\s\"'\]]+\.(?:png|webp|jpg))",
    re.IGNORECASE,
)

UI_FRAME_MARKERS = (
    "ascendancyframe",
    "passiveskillscreen",
    "frameallocated",
    "canallocate",
    "framenormal",
    "framesmall",
)

GENERIC_PASSIVE_MARKERS = (
    "/passives/damage",
    "/passives/plus",
    "skillicons/passives/",
)

OG_IMAGE_RE = re.compile(
    r"<meta[^>]+property=[\"\']og:image[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']",
    re.IGNORECASE,
)
OG_IMAGE_RE_ALT = re.compile(
    r"<meta[^>]+content=[\"\']([^\"\']+)[\"\'][^>]+property=[\"\']og:image[\"\']",
    re.IGNORECASE,
)

_SERVICES_DIR: Path = Path(__file__).resolve().parent
_ASC_SLUG_BY_CN: dict[str, str] | None = None

ICON_BLOCKLIST = frozenset(
    {
        "vendor.png",
        "currencyitem.png",
        "blank.png",
    },
)

_DATA_DIR: Path | None = None
_ICON_FILE: Path | None = None
_ICONS_DIR: Path | None = None
_WIKI_INDEX_FILE: Path | None = None
_file_cache: dict[str, str] | None = None
_wiki_index: dict[str, dict] | None = None

WIKI_ETYPE_SEARCH: dict[str, tuple[str, ...]] = {
    "skill": ("skill", "support", "spirit", "meta_skill", "lineage_support"),
    "item": ("item", "jewel", "flask", "charm", "omen", "waystone"),
    "ascendancy": ("ascendancy",),
}


def _data_dir() -> Path:
    global _DATA_DIR, _ICON_FILE, _ICONS_DIR, _WIKI_INDEX_FILE
    if _DATA_DIR is not None:
        return _DATA_DIR
    candidates: list[Path] = []
    env = os.environ.get("POE2LI_DATA_DIR")
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/app/data"))
    backend_root = Path(__file__).resolve().parent.parent.parent
    repo_root = backend_root.parent
    candidates.extend((repo_root / "data", backend_root / "data"))
    for path in candidates:
        if path.is_dir():
            _DATA_DIR = path
            break
    else:
        _DATA_DIR = backend_root / "data"
    _ICON_FILE = _DATA_DIR / "entity_icons.json"
    _ICONS_DIR = _DATA_DIR / "icons"
    _WIKI_INDEX_FILE = _DATA_DIR / "wiki_icons" / "index.json"
    return _DATA_DIR

REDIS_PREFIX = "entity_icon:"
REDIS_TTL_SEC = 7 * 24 * 3600


def _cache_key(name_en: str, etype: str) -> str:
    return f"{etype}:{name_en.strip().lower()}"


def _load_file_cache() -> dict[str, str]:
    global _file_cache
    if _file_cache is not None:
        return _file_cache
    _file_cache = {}
    icon_file = _ICON_FILE or _data_dir() / "entity_icons.json"
    if icon_file.is_file():
        try:
            raw = json.loads(icon_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _file_cache = {str(k).lower(): str(v) for k, v in raw.items() if v}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("entity_icons.json load failed: %s", exc)
    return _file_cache


def _load_wiki_index() -> dict[str, dict]:
    global _wiki_index
    if _wiki_index is not None:
        return _wiki_index
    _wiki_index = {}
    index_file = _WIKI_INDEX_FILE or _data_dir() / "wiki_icons" / "index.json"
    if index_file.is_file():
        try:
            raw = json.loads(index_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _wiki_index = raw
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("wiki_icons/index.json load failed: %s", exc)
    return _wiki_index


def _wiki_lookup_keys(name_en: str, etype: str, name_cn: str | None = None) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        k = key.strip().lower()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)

    if name_en:
        en = name_en.strip()
        slug = _poe2db_slug(en).lower()
        add(en.lower())
        add(slug)
        for wet in WIKI_ETYPE_SEARCH.get(etype, (etype,)):
            add(f"{wet}:{en.lower()}")
            add(f"{wet}:{slug}")
    if name_cn:
        cn = name_cn.strip()
        add(cn.lower())
        add(f"{etype}:{cn.lower()}")
    return keys


def _wiki_index_entry(
    name_en: str,
    etype: str,
    *,
    name_cn: str | None = None,
) -> dict | None:
    index = _load_wiki_index()
    if not index:
        return None
    for key in _wiki_lookup_keys(name_en, etype, name_cn):
        hit = index.get(key)
        if isinstance(hit, dict) and (hit.get("local_path") or hit.get("image_url")):
            return hit
    return None


def _wiki_local_path(entry: dict) -> Path | None:
    local = entry.get("local_path")
    if not local:
        return None
    path = Path(local)
    if not path.is_absolute():
        path = _data_dir() / local
    return path if path.is_file() else None


def _normalize_icon_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    base = u.rsplit("/", 1)[-1].lower()
    if base in ICON_BLOCKLIST:
        return None
    return u


def _art_to_cdn(path: str) -> str:
    if path.lower().startswith("http"):
        return path
    return f"https://cdn.poe2db.tw/image/{path.lstrip('/')}"


def _is_generic_passive_icon(url: str) -> bool:
    low = url.lower()
    if any(m in low for m in UI_FRAME_MARKERS):
        return True
    return any(m in low for m in GENERIC_PASSIVE_MARKERS)


def _score_icon_url(url: str, etype: str) -> int:
    low = url.lower()
    score = 0
    if _is_generic_passive_icon(url):
        score -= 100
        if etype == "ascendancy":
            score -= 100
    if etype == "item":
        if "2ditems" in low:
            score += 80
        if "gems" in low and "skillgem" not in low:
            score += 40
        if "passives" in low or "skillicons" in low:
            score -= 40
    elif etype == "skill":
        if "gems" in low or "skillgem" in low:
            score += 80
        if "passives" in low:
            score -= 50
    elif etype == "ascendancy":
        if "uiimages/ascendancy" in low or "characterselection" in low:
            score += 100
        if "characterselection" in low:
            score += 120
        if "ascendancy" in low and "frame" not in low:
            score += 30
    else:
        if "2ditems" in low or "gems" in low:
            score += 20
    return score


def _collect_icon_urls(blob: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for m in POECDN_ICON_RE.finditer(blob):
        u = _normalize_icon_url(m.group(0))
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    for m in POE2DB_ART_RE.finditer(blob):
        u = _normalize_icon_url(_art_to_cdn(m.group(1)))
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def extract_icon_from_text(blob: str, etype: str | None = None) -> str | None:
    """Pick best-scoring icon URL from chunk HTML/JSON text (not first match)."""
    if not blob:
        return None
    et = (etype or "item").strip().lower() or "item"
    urls = _collect_icon_urls(blob)
    if not urls:
        return None
    best_url: str | None = None
    best_score = -10_000
    for u in urls:
        s = _score_icon_url(u, et)
        if s > best_score:
            best_score = s
            best_url = u
    if best_score < 0 or not best_url:
        return None
    return best_url


def _load_asc_slug_by_cn() -> dict[str, str]:
    global _ASC_SLUG_BY_CN
    if _ASC_SLUG_BY_CN is not None:
        return _ASC_SLUG_BY_CN
    _ASC_SLUG_BY_CN = {}
    asc_file = _SERVICES_DIR / "poe2db_ascendancies.json"
    if asc_file.is_file():
        try:
            for row in json.loads(asc_file.read_text(encoding="utf-8")):
                slug = (row.get("slug") or "").strip()
                name = (row.get("name") or "").strip()
                if slug and name:
                    _ASC_SLUG_BY_CN[name] = slug.rsplit("/", 1)[-1]
        except (json.JSONDecodeError, OSError):
            pass
    return _ASC_SLUG_BY_CN


def _ascendancy_poe2db_path(name_cn: str | None, name_en: str) -> str | None:
    if name_cn:
        hit = _load_asc_slug_by_cn().get(name_cn.strip())
        if hit:
            return hit
    slug = _poe2db_slug(name_en)
    return slug or None


def _accept_cached_icon(url: str, etype: str) -> str | None:
    u = _normalize_icon_url(url)
    if not u:
        return None
    if etype == "ascendancy" and _is_generic_passive_icon(u):
        return None
    return u


def _og_image_from_html(html: str, etype: str) -> str | None:
    for pattern in (OG_IMAGE_RE, OG_IMAGE_RE_ALT):
        m = pattern.search(html)
        if not m:
            continue
        u = _normalize_icon_url(m.group(1).strip())
        if not u:
            continue
        if etype == "ascendancy" and _is_generic_passive_icon(u):
            continue
        if _score_icon_url(u, etype) >= 0:
            return u
    return None


def _poe2db_slug(name_en: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name_en).strip("_")


def _poe2db_fetch_url(name_en: str, etype: str, *, name_cn: str | None = None) -> str | None:
    if etype == "ascendancy":
        slug = _ascendancy_poe2db_path(name_cn, name_en)
        return f"https://poe2db.tw/cn/{slug}" if slug else None
    if etype == "item":
        path = _item_path_from_data(name_cn, name_en)
        if path:
            return f"https://poe2db.tw/cn/{path.lstrip('/')}"
    page_map = {"skill": "Skill_Gems", "item": "Unique_item"}
    page = page_map.get(etype)
    slug = _poe2db_slug(name_en)
    if page and slug:
        return f"https://poe2db.tw/cn/{page}#{slug}"
    return f"https://poe2db.tw/cn/{slug}" if slug else None


def _probe_wiki_icon_paths(name_en: str, etype: str) -> Path | None:
    icons_dir = _ICONS_DIR or _data_dir() / "icons"
    slug = _poe2db_slug(name_en)
    if not slug:
        return None
    subdirs = WIKI_ETYPE_SEARCH.get(etype, (etype,))
    for sub in subdirs:
        folder = icons_dir / "wiki" / sub
        if not folder.is_dir():
            continue
        for ext in (".png", ".webp", ".jpg"):
            candidate = folder / f"{slug}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _fetch_icon_from_poe2db(
    name_en: str,
    etype: str,
    *,
    name_cn: str | None = None,
) -> str | None:
    url = _poe2db_fetch_url(name_en, etype, name_cn=name_cn)
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PoE2LI-Bot/1.0 (entity icons; +https://github.com/TangCuPaiGu233/PoE2LI)"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("poe2db icon fetch %s: %s", url, exc)
        return None
    og = _og_image_from_html(html, etype)
    if og:
        return og
    return extract_icon_from_text(html, etype)


def _redis_get(key: str) -> str | None:
    try:
        from app.core.redis_client import get_redis

        val = get_redis().get(REDIS_PREFIX + key)
        return val if val else None
    except Exception:
        return None


def _redis_set(key: str, url: str) -> None:
    try:
        from app.core.redis_client import get_redis

        get_redis().setex(REDIS_PREFIX + key, REDIS_TTL_SEC, url)
    except Exception:
        pass


def resolve_icon_url(
    name_en: str,
    etype: str,
    *,
    name_cn: str | None = None,
    chunk_blob: str | None = None,
    allow_fetch: bool = True,
) -> str | None:
    """Resolve icon URL. Prefer wiki index → static file → redis → chunk → live poe2db."""
    if not name_en and not name_cn:
        return None

    wiki = _wiki_index_entry(name_en, etype, name_cn=name_cn)
    if wiki:
        wiki_url = _normalize_icon_url(wiki.get("image_url"))
        if wiki_url:
            return wiki_url

    keys: list[str] = []
    if name_en:
        keys.extend(
            (
                _cache_key(name_en, etype),
                name_en.strip().lower(),
                _poe2db_slug(name_en).lower(),
            ),
        )
    if name_cn:
        cn = name_cn.strip().lower()
        if cn and cn not in keys:
            keys.append(cn)
    file_cache = _load_file_cache()
    for key in keys:
        hit = file_cache.get(key)
        if hit:
            accepted = _accept_cached_icon(hit, etype)
            if accepted:
                return accepted

    for key in keys:
        hit = _redis_get(key)
        if hit:
            accepted = _accept_cached_icon(hit, etype)
            if accepted:
                return accepted

    if chunk_blob:
        found = extract_icon_from_text(chunk_blob, etype)
        if found:
            _redis_set(keys[0], found)
            return found

    if not allow_fetch or not name_en:
        return None

    fetched = _fetch_icon_from_poe2db(name_en, etype, name_cn=name_cn)
    if fetched:
        _redis_set(keys[0], fetched)
    return fetched


def _item_path_from_data(name_cn: str | None, name_en: str) -> str | None:
    """Look up poe2db path from unique_cn_en.json."""
    path_file = _data_dir() / "unique_cn_en.json"
    if not path_file.is_file():
        return None
    try:
        data = json.loads(path_file.read_text(encoding="utf-8"))
        cn_map = data.get("cn_to_en") or {}
        if name_cn and name_cn in cn_map:
            return cn_map[name_cn].get("path") or None
        for _cn, info in cn_map.items():
            if (info.get("en") or "").lower() == name_en.lower():
                return info.get("path") or None
    except (json.JSONDecodeError, OSError):
        pass
    return None


def resolve_local_icon(
    name_en: str,
    etype: str,
    *,
    name_cn: str | None = None,
) -> Path | None:
    """Return cached PNG/WebP on disk (wiki scrape first, then poe2db crawler)."""
    wiki = _wiki_index_entry(name_en, etype, name_cn=name_cn)
    if wiki:
        path = _wiki_local_path(wiki)
        if path:
            return path

    probed = _probe_wiki_icon_paths(name_en, etype)
    if probed:
        return probed

    slug = _poe2db_slug(name_en)
    item_path = _item_path_from_data(name_cn, name_en)
    stems = [s for s in (item_path, slug) if s]
    icons_dir = _ICONS_DIR or _data_dir() / "icons"
    etype_dir = icons_dir / etype
    for stem in stems:
        for ext in (".png", ".webp"):
            candidate = etype_dir / f"{stem}{ext}"
            if candidate.is_file():
                return candidate

    # poecdn fallback dir (backfill_poe2db_icon_gaps.py)
    fallback_dir = icons_dir / "fallback" / etype
    for stem in stems:
        for ext in (".png", ".webp"):
            candidate = fallback_dir / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    return None


def proxy_icon_bytes(url: str) -> tuple[bytes, str] | tuple[None, None]:
    """Fetch remote icon server-side (browser cannot load poecdn reliably)."""
    headers = {
        "User-Agent": "PoE2LI/1.0",
        "Referer": "https://poe2db.tw/",
    }
    try:
        import requests

        resp = requests.get(url, timeout=20, headers=headers)
        if resp.status_code == 200 and resp.content:
            ctype = resp.headers.get("Content-Type") or "image/png"
            return resp.content, ctype
    except Exception as exc:
        logger.debug("icon proxy requests failed %s: %s", url[:80], exc)

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type") or "image/png"
            if data:
                return data, ctype
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("icon proxy urllib failed %s: %s", url[:80], exc)
    return None, None


def resolve_icons_batch(
    items: list[dict[str, str]],
    *,
    allow_fetch: bool = True,
) -> dict[str, str | None]:
    """Batch resolve icons. items: [{name_en, type}, ...] → {name_en: url}."""
    out: dict[str, str | None] = {}
    for item in items:
        name_en = (item.get("name_en") or "").strip()
        etype = (item.get("type") or "item").strip()
        if not name_en or name_en in out:
            continue
        out[name_en] = resolve_icon_url(name_en, etype, allow_fetch=allow_fetch)
    return out
