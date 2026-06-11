"""Scrape poe2db Keywords index into per-keyword mechanic chunks.

The v2 scraper collapsed the entire Keywords page into 3 long text chunks.
This script extracts ~320 individual keyword definitions (CN/US/TW).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import cloudscraper
from bs4 import BeautifulSoup

LANGS = ("us", "cn", "tw")
HEADERS = {"Referer": "https://poe2db.tw/cn/Keywords"}

_scraper: cloudscraper.CloudScraper | None = None


def get_scraper() -> cloudscraper.CloudScraper:
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    return _scraper


def fetch(url: str, timeout: int = 60) -> str | None:
    try:
        resp = get_scraper().get(url, timeout=timeout, headers=HEADERS)
        if resp.status_code == 200:
            return resp.text
        print(f"  HTTP {resp.status_code} {url}")
    except Exception as exc:
        print(f"  ERR {url}: {exc}")
    return None


def parse_index(lang: str) -> dict[str, dict]:
    html = fetch(f"https://poe2db.tw/{lang}/Keywords")
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    entries: dict[str, dict] = {}
    for el in soup.find_all(class_="KeywordPopups"):
        kw_id = el.get("data-keyword")
        if not kw_id or kw_id in entries:
            continue
        entries[kw_id] = {
            "keyword_id": kw_id,
            "href": (el.get("href") or "").strip(),
            f"name_{lang}": el.get_text(strip=True),
        }
    return entries


def _dedupe_texts(texts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in texts:
        norm = re.sub(r"\s+", " ", t).strip()
        if len(norm) < 8 or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def parse_detail(lang: str, href: str) -> tuple[str, str]:
    """Return (title, definition) for a keyword detail page."""
    if not href:
        return "", ""

    html = fetch(f"https://poe2db.tw/{lang}/{href}")
    if not html:
        return "", ""

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    popup = soup.find(class_="newItemPopup") or soup.find(class_="item-popup--poe2")
    if popup:
        name_el = popup.find(class_=re.compile("itemName|name"))
        if name_el:
            title = name_el.get_text(strip=True)

    bodies = _dedupe_texts(
        [b.get_text(separator=" ", strip=True) for b in soup.find_all(class_="keyword-body")]
    )
    definition = bodies[0] if bodies else ""
    if not title and bodies:
        # Fallback: first sentence fragment before nested keyword links.
        title = re.split(r"[。.\n]", bodies[0])[0][:80]
    return title, definition


def merge_index(lang_maps: dict[str, dict[str, dict]]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for lang, entries in lang_maps.items():
        for kw_id, row in entries.items():
            base = merged.setdefault(
                kw_id,
                {"keyword_id": kw_id, "href": row.get("href", "")},
            )
            if row.get("href") and not base.get("href"):
                base["href"] = row["href"]
            if row.get(f"name_{lang}"):
                base[f"name_{lang}"] = row[f"name_{lang}"]
    return merged


def build_chunk(kw_id: str, meta: dict, texts: dict[str, tuple[str, str]]) -> dict | None:
    href = meta.get("href", "")
    names = {
        lang: meta.get(f"name_{lang}") or texts.get(lang, ("", ""))[0]
        for lang in LANGS
    }
    defs = {lang: texts.get(lang, ("", ""))[1] for lang in LANGS}

    if not any(defs.values()):
        return None

    parts = []
    for lang in LANGS:
        name = names.get(lang) or names.get("us") or kw_id
        body = defs.get(lang) or defs.get("us") or defs.get("cn") or ""
        if name or body:
            parts.append(f"[{lang.upper()}] {name}: {body}")

    return {
        "chunk_id": f"keyword_{kw_id}",
        "content_type": "mechanic",
        "source_page": "Keywords",
        "keyword_id": kw_id,
        "href": href,
        "name_en": names.get("us", ""),
        "name_cn": names.get("cn", ""),
        "name_tw": names.get("tw", ""),
        "text_en": defs.get("us", ""),
        "text_zh_cn": defs.get("cn", ""),
        "text_zh_tw": defs.get("tw", ""),
        "search_text": " | ".join(parts),
    }


def scrape(delay: float = 0.35, limit: int | None = None) -> list[dict]:
    print("=== Phase 1: Keywords index ===")
    lang_maps = {}
    for lang in LANGS:
        lang_maps[lang] = parse_index(lang)
        print(f"  {lang}: {len(lang_maps[lang])} keywords")
        time.sleep(delay)

    merged = merge_index(lang_maps)
    items = sorted(merged.items())
    if limit:
        items = items[:limit]
    print(f"  merged unique: {len(merged)} (processing {len(items)})")

    print("=== Phase 2: keyword detail pages ===")
    chunks: list[dict] = []
    for i, (kw_id, meta) in enumerate(items, 1):
        href = meta.get("href", "")
        if not href:
            print(f"  SKIP {kw_id}: no href")
            continue

        texts: dict[str, tuple[str, str]] = {}
        for lang in LANGS:
            texts[lang] = parse_detail(lang, href)
            time.sleep(delay)

        chunk = build_chunk(kw_id, meta, texts)
        if chunk:
            chunks.append(chunk)
        else:
            print(f"  SKIP {kw_id}: empty body")

        if i % 25 == 0:
            print(f"  progress {i}/{len(items)} chunks={len(chunks)}")
            _save(chunks)

    return chunks


def _save(chunks: list[dict], path: str | None = None) -> None:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_keywords.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape poe2db Keywords into JSONL")
    parser.add_argument("out_path", nargs="?", default=None)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=None, help="only scrape first N keywords")
    args = parser.parse_args()

    chunks = scrape(delay=args.delay, limit=args.limit)
    out = args.out_path or os.path.join(
        os.path.dirname(__file__), "..", "data", "poe2db_keywords.jsonl"
    )
    _save(chunks, out)
    print(f"\nDone: {len(chunks)} chunks -> {out}")


if __name__ == "__main__":
    main()
