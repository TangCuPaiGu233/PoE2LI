"""Comprehensive poe2db.tw scraper.

Covers all 3 languages (us/cn/tw) across all major content sections:
  Skill Gems, Support Gems, Spirit Gems
  Modifiers (explicit, implicit, etc.)
  Unique Items, Base Items
  Passive Skills, Ascendancy Classes
  Keywords (mechanics), Crafting, Quests

Each entry is stored as a chunk with:
  - English text, Simplified Chinese text, Traditional Chinese text
  - Source URL (for traceability)
  - Content type (skill, mod, item, keyword, etc.)
  - Page section / category

Output: JSONL file ready for embedding + DB ingestion.
"""

import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import json
import re
import time
import sys
import os
import hashlib

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
}

# Key pages to scrape (same paths work for /us/, /cn/, /tw/)
PAGES = [
    # Gems
    ("Skill_Gems", "skill"),
    ("Support_Gems", "skill"),
    ("Spirit_Gems", "skill"),
    # Items
    ("Items", "item"),
    ("Unique_items", "item"),
    # Modifiers
    ("Modifiers", "mod"),
    ("Desecrated_Modifiers", "mod"),
    # Passive tree
    ("Passive_Skill_Tree", "passive"),
    ("Ascendancy_class", "passive"),
    # Mechanics / Keywords
    ("Keywords", "mechanic"),
    ("Crafting", "mechanic"),
    # Quests / Acts
    ("Quest", "quest"),
    ("Act", "quest"),
    ("Waystones", "map"),
]

BATCH_SIZE = 50


def fetch_page(lang: str, path: str) -> tuple[str | None, str | None]:
    """Fetch a poe2db page. Returns (html, effective_url) or (None, error)."""
    url = f"https://poe2db.tw/{lang}/{path}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
            effective_url = resp.geturl()
        return html, effective_url
    except Exception as e:
        return None, str(e)


def extract_tables(html: str) -> list[dict]:
    """Extract data from HTML tables. Returns list of row dicts."""
    soup = BeautifulSoup(html, 'html.parser')
    results = []

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
                # Get text from both regular text and spans
                text = col.get_text(separator=" ", strip=True)
                row_data[key] = text

            if row_data:
                results.append(row_data)

    return results


def extract_text_content(html: str) -> str:
    """Extract readable text content from page (for long-form pages like mechanics)."""
    soup = BeautifulSoup(html, 'html.parser')

    # Remove scripts and styles
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()

    # Get main content
    main = soup.find('main') or soup.find('article') or soup.find('div', class_='content') or soup

    # Extract paragraphs and list items
    parts = []
    for tag in main.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th']):
        text = tag.get_text(strip=True)
        if text and len(text) > 3:
            parts.append(text)

    return '\n'.join(parts)


def build_chunk_id(lang: str, page: str, index: int) -> str:
    """Generate a stable chunk ID from content hash."""
    raw = f"{lang}/{page}/{index}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def scrape() -> list[dict]:
    """Main scraping function. Returns list of knowledge chunks."""
    all_chunks = []
    total_pages = len(PAGES) * 3  # 3 languages

    for i, (page, content_type) in enumerate(PAGES):
        # Collect all 3 language versions for this page
        lang_data = {}
        for lang in ['us', 'cn', 'tw']:
            page_num = i * 3 + ['us', 'cn', 'tw'].index(lang) + 1
            print(f"[{page_num}/{total_pages}] Fetching {lang}/{page}...", end=" ", flush=True)

            html, error = fetch_page(lang, page)
            if error:
                print(f"ERROR: {error}")
                continue
            print(f"OK ({len(html)} bytes)")

            # Extract structured data
            tables = extract_tables(html)
            text = extract_text_content(html)

            lang_data[lang] = {
                "tables": tables,
                "text": text,
                "url": f"https://poe2db.tw/{lang}/{page}",
            }

            time.sleep(1)  # be nice to the server

        # Merge across languages into unified chunks
        merged = merge_language_data(lang_data, page, content_type)
        all_chunks.extend(merged)

        # Save progress periodically
        if len(all_chunks) >= BATCH_SIZE and len(all_chunks) % BATCH_SIZE == 0:
            save_progress(all_chunks)
            print(f"  [Progress: {len(all_chunks)} chunks saved]")

        time.sleep(2)  # rate limit between pages

    return all_chunks


def merge_language_data(lang_data: dict, page: str, content_type: str) -> list[dict]:
    """Merge 3-language data for a single page into unified chunks."""
    chunks = []

    us_tables = lang_data.get('us', {}).get('tables', [])
    cn_tables = lang_data.get('cn', {}).get('tables', [])
    tw_tables = lang_data.get('tw', {}).get('tables', [])

    urls = {
        'en': lang_data.get('us', {}).get('url', ''),
        'zh_cn': lang_data.get('cn', {}).get('url', ''),
        'zh_tw': lang_data.get('tw', {}).get('url', ''),
    }

    # Method 1: If tables exist, merge by row index
    max_rows = max(len(us_tables), len(cn_tables), len(tw_tables))
    for idx in range(max_rows):
        chunk = {
            "chunk_id": build_chunk_id("all", page, idx),
            "content_type": content_type,
            "source_page": page,
            "urls": urls,
            "text_en": us_tables[idx].get('text', '') if idx < len(us_tables) else '',
            "text_zh_cn": cn_tables[idx].get('text', '') if idx < len(cn_tables) else '',
            "text_zh_tw": tw_tables[idx].get('text', '') if idx < len(tw_tables) else '',
        }

        # Build a combined search text for embedding
        texts = []
        if chunk["text_en"]:
            texts.append(f"[EN] {chunk['text_en']}")
        if chunk["text_zh_cn"]:
            texts.append(f"[CN] {chunk['text_zh_cn']}")
        if chunk["text_zh_tw"]:
            texts.append(f"[TW] {chunk['text_zh_tw']}")
        chunk["search_text"] = " | ".join(texts)

        if any(texts):  # only keep chunks with at least some content
            chunks.append(chunk)

    # Method 2: Also chunk long-form text content
    for lang, lang_code in [('us', 'en'), ('cn', 'zh_cn'), ('tw', 'zh_tw')]:
        text = lang_data.get(lang, {}).get('text', '')
        if not text or len(text) < 50:
            continue

        # Split long text into paragraphs
        paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]
        for p_idx, para in enumerate(paragraphs):
            chunk = {
                "chunk_id": build_chunk_id(lang, page, 10000 + p_idx),
                "content_type": content_type,
                "source_page": page,
                "urls": {lang_code: lang_data.get(lang, {}).get('url', '')},
                "search_text": f"[{lang_code.upper()}] {para}",
            }
            # Set the appropriate language field
            if lang == 'us':
                chunk["text_en"] = para
            elif lang == 'cn':
                chunk["text_zh_cn"] = para
            else:
                chunk["text_zh_tw"] = para
            chunks.append(chunk)

    return chunks


def save_progress(chunks: list[dict], path: str = None):
    """Save chunks to disk as JSONL."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_chunks.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    print("=== PoE2DB Full Scraper ===")
    print(f"Pages: {len(PAGES)} x 3 languages = {len(PAGES) * 3} requests")
    print()

    chunks = scrape()

    # Save final output
    if out_path is None:
        out_path = os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_chunks.jsonl")
    save_progress(chunks, out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print()
    print(f"=== Done: {len(chunks)} chunks saved to {out_path} ===")

    # Stats
    types = {}
    for c in chunks:
        t = c.get('content_type', '?')
        types[t] = types.get(t, 0) + 1
    print("By type:")
    for t, count in sorted(types.items()):
        print(f"  {t}: {count}")


if __name__ == "__main__":
    main()
