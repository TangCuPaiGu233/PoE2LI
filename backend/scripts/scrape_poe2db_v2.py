"""Poe2DB Encyclopedia Scraper v2 — HTML-element-level parsing.

Covers 3 languages (us/cn/tw) across:
  - Skill Gems, Support Gems, Spirit Gems
  - Modifiers, Desecrated Modifiers
  - Unique Items (via item index pages)
  - Ascendancy Classes
  - Quests, Acts
  - Crafting, Keywords, Mechanics (text pages)

Output: JSONL ready for embedding + DB ingestion.
"""

import urllib.request
from bs4 import BeautifulSoup
import json
import re
import time
import sys
import os
import hashlib

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

# ├─ Grid pages: gems laid out in <td> grid ─┤
GRID_PAGES = [
    ("Skill_Gems", "skill"),
    ("Support_Gems", "skill"),
    ("Spirit_Gems", "skill"),
]

# ├─ Table pages: data in <tr>/<td> rows ─┤
TABLE_PAGES = [
    ("Modifiers", "mod"),
    ("Desecrated_Modifiers", "mod"),
]

# ├─ Text pages: long-form content ─┤
TEXT_PAGES = [
    ("Ascendancy_class", "passive"),
    ("Quest", "quest"),
    ("Act", "quest"),
    ("Crafting", "mechanic"),
    # Keywords: use scrape_poe2db_keywords.py (per-keyword chunks)
    ("Waystones", "map"),
]


def fetch(lang, page):
    url = f"https://poe2db.tw/{lang}/{page}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode('utf-8', errors='replace'), url
    except Exception as e:
        return None, str(e)


def parse_grid_page(html):
    """Parse gem grid pages — each <td> with an <a> link is one gem."""
    soup = BeautifulSoup(html, 'html.parser')
    entries = []
    seen_names = set()

    for td in soup.find_all('td'):
        links = td.find_all('a')
        if not links:
            continue

        # Find gem name link (first meaningful link)
        gem_text = ""
        gem_href = ""
        for a in links:
            text = a.get_text(strip=True)
            href = a.get('href', '')
            if text and len(text) >= 3:
                gem_text = text
                gem_href = href
                break

        if not gem_text or gem_text in seen_names:
            continue
        seen_names.add(gem_text)

        # Extract level: (Number) after name
        full_text = td.get_text(strip=True)
        lv_match = re.search(r'\((\d+)\)', full_text)
        level = int(lv_match.group(1)) if lv_match else 0

        # Build entry
        entries.append({
            "name": gem_text,
            "level": level,
            "href": gem_href,
        })

    return entries


def parse_table_page(html):
    """Parse modifier/item tables — traditional <tr>/<td> rows."""
    soup = BeautifulSoup(html, 'html.parser')
    entries = []

    for table in soup.find_all('table'):
        headers = []
        for th in table.find_all('th'):
            headers.append(th.get_text(strip=True))

        for row in table.find_all('tr'):
            cols = row.find_all('td')
            if not cols:
                continue
            row_data = {}
            for i, col in enumerate(cols):
                key = headers[i] if i < len(headers) else f"col_{i}"
                row_data[key] = col.get_text(separator=" ", strip=True)
            if row_data:
                entries.append(row_data)

    return entries


def parse_text_page(html):
    """Parse text-heavy pages — extract paragraphs."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()

    main = soup.find('main') or soup.find('article') or soup
    paragraphs = []
    for tag in main.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4']):
        text = tag.get_text(strip=True)
        if text and len(text) > 10:
            paragraphs.append(text)

    return [{"text": "\n".join(paragraphs)}]


def build_chunks(en_data, cn_data, tw_data, page, content_type):
    """Merge 3-language data into unified chunks."""
    chunks = []

    # Grid/Table data: merge by index
    if isinstance(en_data[0], dict) and "text" not in en_data[0]:
        max_rows = max(len(en_data), len(cn_data), len(tw_data))
        for idx in range(max_rows):
            en_row = en_data[idx] if idx < len(en_data) else {}
            cn_row = cn_data[idx] if idx < len(cn_data) else {}
            tw_row = tw_data[idx] if idx < len(tw_data) else {}

            # Build search text
            parts = []
            if en_row:
                parts.append("[EN] " + json.dumps(en_row, ensure_ascii=False))
            if cn_row:
                parts.append("[CN] " + json.dumps(cn_row, ensure_ascii=False))
            if tw_row:
                parts.append("[TW] " + json.dumps(tw_row, ensure_ascii=False))

            if parts:
                chunks.append({
                    "chunk_id": f"{page}_{idx}",
                    "content_type": content_type,
                    "source_page": page,
                    "search_text": " | ".join(parts),
                    "text_en": json.dumps(en_row, ensure_ascii=False) if en_row else "",
                    "text_zh_cn": json.dumps(cn_row, ensure_ascii=False) if cn_row else "",
                    "text_zh_tw": json.dumps(tw_row, ensure_ascii=False) if tw_row else "",
                })

    # Text data: save as-is per language
    else:
        for lang_code, lang_key, data in [
            ("us", "en", en_data), ("cn", "zh_cn", cn_data), ("tw", "zh_tw", tw_data)
        ]:
            if data and data[0].get("text"):
                chunks.append({
                    "chunk_id": f"{page}_text_{lang_code}",
                    "content_type": content_type,
                    "source_page": page,
                    "search_text": f"[{lang_code.upper()}] {data[0]['text'][:2000]}",
                    "text_en": data[0]["text"] if lang_code == "us" else "",
                    "text_zh_cn": data[0]["text"] if lang_code == "cn" else "",
                    "text_zh_tw": data[0]["text"] if lang_code == "tw" else "",
                })

    return chunks


def scrape():
    all_chunks = []
    total = len(GRID_PAGES) + len(TABLE_PAGES) + len(TEXT_PAGES)

    for page_list, parser, label in [
        (GRID_PAGES, parse_grid_page, "grid"),
        (TABLE_PAGES, parse_table_page, "table"),
        (TEXT_PAGES, parse_text_page, "text"),
    ]:
        for page, content_type in page_list:
            lang_data = {}
            for lang in ['us', 'cn', 'tw']:
                html, url = fetch(lang, page)
                if html is None:
                    print(f"  SKIP {lang}/{page}: {url}")
                    continue
                data = parser(html)
                lang_data[lang] = data
                print(f"  {lang}/{page}: {len(data)} entries ({len(html)} bytes)")
                time.sleep(0.5)

            # Merge across languages
            en = lang_data.get('us', [])
            cn = lang_data.get('cn', [])
            tw = lang_data.get('tw', [])
            if en or cn or tw:
                chunks = build_chunks(en, cn, tw, page, content_type)
                all_chunks.extend(chunks)
                print(f"    -> {len(chunks)} chunks")

            # Save incrementally
            if len(all_chunks) % 200 == 0:
                _save(all_chunks)
            time.sleep(1.5)

    _save(all_chunks)
    return all_chunks


def _save(chunks, path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_chunks_v2.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    print("=== PoE2DB Scraper v2 ===")
    chunks = scrape()
    if out_path:
        _save(chunks, out_path)
    print(f"\nDone: {len(chunks)} chunks")
    types = {}
    for c in chunks:
        t = c.get('content_type', '?')
        types[t] = types.get(t, 0) + 1
    for t, n in sorted(types.items()):
        print(f"  {t}: {n}")
