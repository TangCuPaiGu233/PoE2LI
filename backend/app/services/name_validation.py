"""Validate PoE2 unique/item English names — reject scraper glue, cross-check PoB."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from functools import lru_cache

CDN = "https://cdn.jsdelivr.net/gh/PathOfBuildingCommunity/PathOfBuilding-PoE2@dev/src/Data/Uniques"
UNIQUE_FILES = [
    "amulet", "axe", "belt", "body", "boots", "bow", "claw", "crossbow",
    "dagger", "flail", "flask", "focus", "gloves", "helmet", "jewel",
    "mace", "quiver", "ring", "sceptre", "shield", "spear", "staff",
    "sword", "talisman", "traptool", "wand",
]

_GLUE_RE = re.compile(r"[a-zà-öø-ÿ][A-ZÀ-ÖØ-Þ]")
_LUA_NAME_RE = re.compile(r'^\s*"([^"]+)"')


def is_concatenated_name(name: str) -> bool:
    if not name or len(name) < 4:
        return False
    for token in name.split():
        if len(token) >= 6 and _GLUE_RE.search(token):
            return True
    return False


def normalize_en_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


@lru_cache(maxsize=1)
def load_pob_unique_names() -> frozenset[str]:
    names: set[str] = set()
    for fname in UNIQUE_FILES:
        url = f"{CDN}/{fname}.lua"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PoE2LI/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            m = _LUA_NAME_RE.match(line)
            if m:
                names.add(m.group(1).strip())
    return frozenset(names)


def load_local_unique_names() -> set[str]:
    names: set[str] = set()
    data_dir = "/app/data"
    if not os.path.isdir(data_dir):
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    path = os.path.join(data_dir, "caimogu_items.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for row in json.load(f):
                en = (row.get("en") or "").strip()
                if en:
                    names.add(en)
    try:
        from app.services.entity_dict import ITEM_CN_ALIASES
        names.update(ITEM_CN_ALIASES.values())
    except Exception:
        pass
    return names


@lru_cache(maxsize=1)
def known_unique_names() -> frozenset[str]:
    pob = load_pob_unique_names()
    if pob:
        return pob
    return frozenset(load_local_unique_names())


def _norm_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _match_canon(candidate: str, canon: frozenset[str]) -> str | None:
    candidate = normalize_en_name(candidate)
    if not candidate:
        return None
    if candidate in canon:
        return candidate
    key = _norm_key(candidate)
    for known in canon:
        if known.lower() == candidate.lower() or _norm_key(known) == key:
            return known
    return None


def _longest_canon_prefix(dirty: str, canon: frozenset[str]) -> str | None:
    """e.g. Sadist's MercyFlanged Mace → Sadist's Mercy"""
    lower = dirty.lower()
    for known in sorted(canon, key=len, reverse=True):
        if len(known) < 4:
            continue
        kl = known.lower()
        if not lower.startswith(kl):
            continue
        rest = dirty[len(known):]
        if not rest or rest[0] in " ,(" or rest[0].isupper():
            return known
    return None


def resolve_unique_name(
    index_name: str,
    item_path: str,
    scraped_name: str | None = None,
) -> str:
    """Resolve canonical EN unique name; never drop a page for dirty index glue."""
    index_name = normalize_en_name(index_name)
    scraped_name = normalize_en_name(scraped_name) if scraped_name else ""
    canon = known_unique_names()

    if canon:
        path_title = item_path.replace("_", " ").strip()
        for candidate in (path_title, scraped_name, index_name):
            hit = _match_canon(candidate, canon)
            if hit:
                return hit
        if is_concatenated_name(index_name):
            prefix = _longest_canon_prefix(index_name, canon)
            if prefix:
                return prefix

    for candidate in (scraped_name, index_name):
        if candidate and not is_concatenated_name(candidate):
            return candidate

    if scraped_name:
        return scraped_name
    return index_name


def validate_name_en(name_en: str, index_name: str | None = None) -> tuple[bool, str]:
    name_en = normalize_en_name(name_en)
    index_name = normalize_en_name(index_name) if index_name else ""
    if is_concatenated_name(name_en):
        if index_name and not is_concatenated_name(index_name):
            return True, index_name
        return False, name_en
    canon = known_unique_names()
    if canon:
        hit = _match_canon(name_en, canon) or (index_name and _match_canon(index_name, canon))
        if hit:
            return True, hit
        for candidate in (name_en, index_name):
            if not candidate:
                continue
            for known in canon:
                if candidate.lower().startswith(known.lower() + " "):
                    return True, known
    return not is_concatenated_name(name_en), name_en


def is_trusted_en_name(name_en: str) -> bool:
    ok, _ = validate_name_en(name_en)
    return ok
