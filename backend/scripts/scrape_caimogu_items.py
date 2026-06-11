# Scrape caimogu unique item CN names from per-item pages.
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass

import requests

CAIMOGU_BASE = "https://poe2cn.caimogu.cc"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://poe2cn.caimogu.cc/",
}
MIN_PAGE_LEN = 15000

NON_ITEMS = {
    "skill gems", "support gems", "spirit gems", "lineage supports",
    "desecrated modifiers", "keywords", "crafting", "quest",
    "ascendancy classes", "act", "waystones", "patreon", "modifiers",
    "unique item", "items",
}

BASE_TYPES = {
    "vest", "robe", "circlet", "belt", "ring", "amulet", "boots",
    "gloves", "gauntlets", "helm", "helmet", "shield", "sword", "axe",
    "mace", "bow", "wand", "sceptre", "staff", "spear", "crossbow",
    "quiver", "flask", "jewel", "cuisses", "greaves", "sollerets",
    "coat", "mail", "plate", "mask", "crown", "hood", "shroud", "sash",
    "talisman", "spirit", "diamond", "pearl", "coral", "tiara", "buckle",
    "clasp", "torque", "charm", "focus", "buckler", "targe", "kite",
    "tower", "dagger", "claw", "flail", "halberd", "javelin", "musket",
    "pistol", "warstaff", "body", "armour", "armor",
}

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk


@dataclass
class ItemRecord:
    key: str
    name_en: str
    slugs: list[str]


def _split_camel_name(name_en: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name_en)
    words = spaced.split()
    while len(words) > 1 and words[-1].lower() in BASE_TYPES:
        words = words[:-1]
    return " ".join(words).strip() or name_en.strip()


def _path_to_slug(path: str) -> str:
    path = path.strip().strip("/")
    if not path:
        return ""
    if "/" in path:
        path = path.rsplit("/", 1)[-1]
    if path.endswith(".html"):
        path = path[:-5]
    return path


def _slug_variants_from_name(name: str) -> list[str]:
    if not name:
        return []
    out: list[str] = []

    def add(raw: str) -> None:
        s = _path_to_slug(raw)
        if s and s not in out:
            out.append(s)

    add(name)
    compact = name.replace(" ", "_")
    add(compact)
    add(compact.replace("'", ""))
    add(compact.replace("'", "_"))
    add(re.sub(r"[^A-Za-z0-9_]+", "", compact.replace("'", "")))
    add(re.sub(r"[^A-Za-z0-9_]+", "_", compact.replace("'", "")))
    return out


def _proper_en_name(data: dict) -> str:
    en_data_raw = data.get("en_data")
    if isinstance(en_data_raw, str) and en_data_raw.strip().startswith("{"):
        try:
            en_name = json.loads(en_data_raw).get("name", "").strip()
            if en_name:
                return en_name
        except json.JSONDecodeError:
            pass
    name_en = (data.get("name_en") or "").strip()
    if name_en:
        return _split_camel_name(name_en)
    path = data.get("detail_path") or data.get("item_path") or ""
    if path:
        return _path_to_slug(path).replace("_", " ")
    return ""


def _item_key(data: dict, name_en: str) -> str:
    for field in ("detail_path", "item_path", "chunk_id"):
        val = (data.get(field) or "").strip()
        if val:
            return val.lower()
    return name_en.lower()


def _collect_slug_candidates(data: dict, name_en: str) -> list[str]:
    slugs: list[str] = []
    for field in ("detail_path", "item_path", "href"):
        raw = data.get(field)
        if isinstance(raw, str) and raw.strip():
            slug = _path_to_slug(raw)
            if slug and slug not in slugs:
                slugs.append(slug)
    for variant in _slug_variants_from_name(_split_camel_name(name_en)):
        if variant not in slugs:
            slugs.append(variant)
    for variant in _slug_variants_from_name(name_en):
        if variant not in slugs:
            slugs.append(variant)
    return slugs


def load_item_records() -> list[ItemRecord]:
    db = SessionLocal()
    try:
        chunks = (
            db.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.source == "poe2db",
                KnowledgeChunk.chunk_type == "item",
            )
            .all()
        )
        records: list[ItemRecord] = []
        seen_keys: set[str] = set()
        for chunk in chunks:
            try:
                data = json.loads(chunk.content)
            except (json.JSONDecodeError, TypeError):
                continue
            raw_name = (data.get("name_en") or "").strip()
            if not raw_name or raw_name.lower() in NON_ITEMS:
                continue
            name_en = _proper_en_name(data)
            if not name_en:
                continue
            key = _item_key(data, name_en)
            if key in seen_keys:
                continue
            slugs = _collect_slug_candidates(data, raw_name)
            if not slugs:
                continue
            seen_keys.add(key)
            records.append(ItemRecord(key=key, name_en=name_en, slugs=slugs))
        return records
    finally:
        db.close()


def _parse_cn_from_title(title: str) -> str | None:
    if title.startswith("\u6d41\u653e\u4e4b\u8def") or title.startswith("\u8e29\u83c7\u83c7"):
        return None
    name_part = title.split(" - ", 1)[0].strip()
    if not name_part:
        return None
    cn_name = name_part.split()[0]
    if not re.search(r"[\u4e00-\u9fff]", cn_name):
        return None
    return cn_name


def scrape_item_page(slug: str) -> dict | None:
    url = f"{CAIMOGU_BASE}/p/{slug}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    text = resp.text
    if "\u9875\u9762\u4e0d\u5b58\u5728" in text or len(text) < MIN_PAGE_LEN:
        return None
    title_match = re.search(r"<title>([^<]+)</title>", text)
    if not title_match:
        return None
    cn = _parse_cn_from_title(title_match.group(1).strip())
    if not cn:
        return None
    return {"cn": cn, "slug": slug}


def _load_existing(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    by_key: dict[str, dict] = {}
    for item in raw:
        key = (item.get("key") or item.get("en") or "").strip().lower()
        if not key:
            continue
        normalized = dict(item)
        normalized.setdefault("key", key)
        by_key[key] = normalized
    return by_key


def _save_items(items: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def scrape_all(output_dir: str = "/app/data") -> list[dict]:
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "caimogu_items.json")

    by_key = _load_existing(output_path)
    print(f"Resume: {len(by_key)} items already saved")

    records = load_item_records()
    print(f"Total poe2db unique items: {len(records)}")

    pending = [r for r in records if r.key not in by_key]
    print(f"Pending: {len(pending)}")

    for i, rec in enumerate(pending):
        found = None
        winning_slug = ""
        for slug in rec.slugs:
            hit = scrape_item_page(slug)
            if hit:
                found = hit
                winning_slug = slug
                break
            time.sleep(0.12)
        if found:
            by_key[rec.key] = {
                "cn": found["cn"],
                "en": rec.name_en,
                "type": "item",
                "source": "caimogu",
                "slug": winning_slug,
                "key": rec.key,
            }
        if (i + 1) % 25 == 0:
            _save_items(list(by_key.values()), output_path)
            print(f"  [{i + 1}/{len(pending)}] total {len(by_key)} items")
        time.sleep(0.3)

    items = list(by_key.values())
    _save_items(items, output_path)
    print(f"Done: {len(items)} items -> {output_path}")
    return items


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/app/data"
    scrape_all(out)
