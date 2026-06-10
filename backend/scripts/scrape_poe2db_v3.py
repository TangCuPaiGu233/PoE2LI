"""Poe2DB Encyclopedia Scraper v3 — complete detail pages.

Phase 1: Scrape index pages → collect all detail URLs (name, type, level, tags)
Phase 2: Scrape each detail page → full description, stats per level, implicit mods
Phase 3: Merge 3-language data → comprehensive chunks for RAG

Output: JSONL ready for embedding + DB ingestion.
Each chunk covers one game entity with complete tri-language data.
"""

import cloudscraper
from bs4 import BeautifulSoup
import json, re, time, sys, os, hashlib

# Use cloudscraper to bypass Cloudflare
_scraper = None

def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
    return _scraper

# Index pages to collect URLs from
INDEX_PAGES = [
    ("Skill_Gems", "skill"),
    ("Support_Gems", "skill"),
    ("Spirit_Gems", "skill"),
    ("Unique_item", "item"),
    ("Modifiers", "mod"),
    ("Desecrated_Modifiers", "mod"),
    ("Ascendancy_class", "passive"),
    ("Quest", "quest"),
]


def fetch(url):
    try:
        s = _get_scraper()
        resp = s.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.text
        return None
    except Exception as e:
        return None


# ═══ Phase 1: Collect detail URLs from index pages ═══

def collect_urls(page, content_type):
    """Parse index page (EN version) to collect all detail page URLs."""
    html = fetch(f"https://poe2db.tw/us/{page}")
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    entries = []
    seen = set()

    for td in soup.find_all('td'):
        links = td.find_all('a')
        for a in links:
            href = a.get('href', '')
            text = a.get_text(strip=True)
            if not (href.startswith('/us/') and text and len(text) >= 2):
                continue
            # Skip navigation links
            if href in ('/us/', '/us/Items', '/us/Gem', '/us/Modifiers'):
                continue
            path = href.replace('/us/', '')
            if path in seen:
                continue
            seen.add(path)

            # Extract level from surrounding text
            full_text = td.get_text(strip=True)
            lv_match = re.search(r'\((\d+)\)', full_text)
            level = int(lv_match.group(1)) if lv_match else 0

            # Extract tags
            tags = []
            if lv_match:
                after = full_text[lv_match.end():]
                tag_match = re.match(r'([A-Z][A-Za-z, ]+)', after)
                if tag_match:
                    tags = [t.strip() for t in tag_match.group(1).split(',') if t.strip()]

            entries.append({
                "path": path,
                "name_en": text,
                "level": level,
                "tags": tags,
                "content_type": content_type,
                "source_page": page,
            })

    return entries


# ═══ Phase 2: Scrape detail pages ═══

def scrape_detail(path, lang_code):
    """Scrape a detail page in one language using specific CSS classes."""
    url = f"https://poe2db.tw/{lang_code}/{path}"
    html = fetch(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'html.parser')
    result = {"url": url}

    # Gem name: .itemName
    name_el = soup.find(class_="itemName")
    if name_el:
        result["name"] = name_el.get_text(strip=True)

    # Skill description: .secDescrText
    desc_el = soup.find(class_="secDescrText")
    if desc_el:
        result["description"] = desc_el.get_text(separator=" ", strip=True)

    # Tags/properties: .property elements
    props = soup.find_all(class_="property")
    if props:
        result["properties"] = [p.get_text(strip=True) for p in props[:10]]

    # Gem stats: .Stats
    stats_el = soup.find(class_="Stats")
    if stats_el:
        result["stats"] = stats_el.get_text(separator=" ", strip=True)

    # Data tables: .table-responsive (support gems, attributes, versions)
    tables_data = []
    for container in soup.find_all(class_="table-responsive"):
        table = container.find('table')
        if not table:
            continue
        rows_data = []
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
            if cell_texts and any(t for t in cell_texts):
                rows_data.append(cell_texts)
        if rows_data:
            tables_data.append(rows_data)
    result["tables"] = tables_data

    # Implicit mods: .implicitMod
    implicits = soup.find_all(class_="implicitMod")
    if implicits:
        result["implicit_mods"] = [i.get_text(strip=True) for i in implicits[:5]]

    return result


# ═══ Phase 3: Merge into chunks ═══

def build_chunk(entry, en_detail, cn_detail, tw_detail):
    """Merge 3-language data into one comprehensive chunk."""
    parts = []

    # Name and type
    parts.append(f"Name: {entry['name_en']}")
    if entry.get("tags"):
        parts.append(f"Tags: {', '.join(entry['tags'])}")
    if entry.get("level"):
        parts.append(f"Level: {entry['level']}")
    parts.append(f"Type: {entry.get('content_type', '?')}")

    # EN detail
    if en_detail:
        if en_detail.get("description"):
            parts.append(f"[EN Description]\n{en_detail['description']}")
        if en_detail.get("tables"):
            for i, t in enumerate(en_detail['tables'][:5]):
                t_text = "\n".join(" | ".join(row) for row in t[:20])
                parts.append(f"[EN Table {i}]\n{t_text}")

    # CN detail
    if cn_detail and cn_detail.get("description"):
        parts.append(f"[CN Description]\n{cn_detail['description']}")

    # TW detail
    if tw_detail and tw_detail.get("description"):
        parts.append(f"[TW Description]\n{tw_detail['description']}")

    search_text = "\n\n".join(parts)

    # Truncate if too long (embedding limit ~2000 tokens)
    if len(search_text) > 4000:
        search_text = search_text[:4000] + "\n... (truncated)"

    return {
        "chunk_id": f"detail_{entry['path']}",
        "content_type": entry.get("content_type", "?"),
        "source_page": entry.get("source_page", ""),
        "detail_path": entry["path"],
        "name_en": entry["name_en"],
        "search_text": search_text,
        "en_description": en_detail.get("description", "") if en_detail else "",
        "cn_description": cn_detail.get("description", "") if cn_detail else "",
        "tw_description": tw_detail.get("description", "") if tw_detail else "",
        "en_tables": en_detail.get("tables", [])[:3] if en_detail else [],
    }


# ═══ Main ═══

def _load_existing_paths(jsonl_path):
    """Load set of already-scraped detail paths from existing output file."""
    existing = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    c = json.loads(line.strip())
                    if c.get("detail_path"):
                        existing.add(c["detail_path"])
                except json.JSONDecodeError:
                    pass
    return existing


def _get_output_path():
    return os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_chunks_v3.jsonl")


def scrape(resume=True):
    output_path = _get_output_path()
    all_entries = []

    # Phase 1: Collect URLs
    print("=== Phase 1: Collect detail URLs ===")
    for page, ctype in INDEX_PAGES:
        entries = collect_urls(page, ctype)
        all_entries.extend(entries)
        print(f"  {page}: {len(entries)} entries")

    # Deduplicate by path
    seen_paths = set()
    unique_entries = []
    for e in all_entries:
        if e["path"] not in seen_paths:
            seen_paths.add(e["path"])
            unique_entries.append(e)

    print(f"\nTotal unique detail pages: {len(unique_entries)}")

    # Resume: skip already scraped
    existing_paths = _load_existing_paths(output_path) if resume else set()
    pending = [e for e in unique_entries if e["path"] not in existing_paths]
    if existing_paths:
        print(f"Resume: {len(existing_paths)} already done, {len(pending)} remaining")

    # Phase 2: Scrape details (append mode for resilience)
    print(f"\n=== Phase 2: Scrape detail pages (x3 languages) ===")
    chunks = []
    languages = [("us", "en"), ("cn", "zh_cn"), ("tw", "zh_tw")]

    for idx, entry in enumerate(pending):
        try:
            details = {}
            for lang_code, lang_key in languages:
                try:
                    detail = scrape_detail(entry["path"], lang_code)
                    if detail:
                        details[lang_key] = detail
                except Exception as le:
                    print(f"  WARN: {lang_code}/{entry['path']} failed: {le}", flush=True)
                time.sleep(0.3)

            if details:
                chunk = build_chunk(entry,
                                    details.get("en"),
                                details.get("zh_cn"),
                                details.get("zh_tw"))
                chunks.append(chunk)
        except Exception as e:
            print(f"  ERROR at {entry['path']}: {e}", flush=True)
            time.sleep(1)

        # Save incrementally: append to file every 10 entries
        if (idx + 1) % 10 == 0 and chunks:
            _append_save(chunks[-10:], output_path)
            print(f"  [{idx+1}/{len(pending)}] {len(chunks)} new, "
                  f"{len(existing_paths) + len(chunks)} total")
            time.sleep(2)

        # Periodic full save every 50
        if (idx + 1) % 50 == 0:
            _append_save(chunks[-50:], output_path)
            print(f"  [{idx+1}/{len(pending)}] checkpoint: {len(chunks)} new chunks")
            time.sleep(3)

    # Final save
    if chunks:
        _append_save(chunks, output_path)
    return chunks


def _save(chunks, path=None):
    if path is None:
        path = _get_output_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')


def _append_save(chunks, path):
    """Append chunks to existing file (for incremental saving)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-resume", action="store_true", help="Start fresh, ignore existing chunks")
    parser.add_argument("-o", "--output", help="Output JSONL path")
    args = parser.parse_args()

    print("=== PoE2DB Scraper v3 — Full Detail Pages ===")
    chunks = scrape(resume=not args.no_resume)
    if args.output:
        _save(chunks, args.output)
    print(f"\nDone: {len(chunks)} new detail chunks this run")
    types = {}
    for c in chunks:
        t = c.get('content_type', '?')
        types[t] = types.get(t, 0) + 1
    for t, n in sorted(types.items()):
        print(f"  {t}: {n}")
    # Estimate total text
    total_chars = sum(len(c.get('search_text', '')) for c in chunks)
    print(f"Total text: {total_chars} chars ({total_chars//1000}k)")
