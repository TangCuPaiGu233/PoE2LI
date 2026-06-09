"""Scrape all unique items from poe2db with full mod data.

Extracts: item name, type, explicit mods, implicit mods, unique effect.
Covers 3 languages (us/cn/tw).

The mods are directly in the HTML via CSS classes:
  .itemName, .explicitMod, .implicitMod, .Stats, .property
No lazy loading needed — mods render server-side.
"""

import cloudscraper
from bs4 import BeautifulSoup
import json, re, time, sys, os

_scraper = None

def _get_scraper():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
    return _scraper


def fetch(url):
    try:
        resp = _get_scraper().get(url, timeout=20)
        return resp.text if resp.status_code == 200 else None
    except:
        return None


def scrape_unique_item(path, lang_code):
    """Scrape one unique item detail page in one language."""
    url = f"https://poe2db.tw/{lang_code}/{path}"
    html = fetch(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'html.parser')
    result = {"url": url}

    # Item name
    name_el = soup.find(class_="itemName")
    if name_el:
        result["name"] = name_el.get_text(strip=True)

    # Item type (e.g. "Belts", "Swords")
    props = soup.find_all(class_="property")
    if props:
        result["item_type"] = [p.get_text(strip=True) for p in props]

    # Implicit mods (dedup)
    seen_imp = set()
    implicits = []
    for i in soup.find_all(class_="implicitMod"):
        text = i.get_text(strip=True)
        if text and text not in seen_imp:
            seen_imp.add(text)
            implicits.append(text)
    if implicits:
        result["implicit_mods"] = implicits

    # Explicit mods (dedup — same mod appears in multiple page tabs)
    seen_texts = set()
    explicits = []
    for e in soup.find_all(class_="explicitMod"):
        text = e.get_text(strip=True)
        if text and text not in seen_texts:
            seen_texts.add(text)
            explicits.append(text)
    if explicits:
        result["explicit_mods"] = explicits

    # Full stats line
    stats = soup.find(class_="Stats")
    if stats:
        result["stats_full"] = stats.get_text(separator=" | ", strip=True)

    # Description/unique effect (first long text paragraph)
    for p in soup.find_all(['p', 'div']):
        text = p.get_text(strip=True)
        cls = ' '.join(p.get('class', []))
        if len(text) > 50 and 'cookie' not in text.lower():
            result["description"] = text
            break

    return result


def collect_unique_urls():
    """Collect all unique item detail page URLs from the index page."""
    html = fetch("https://poe2db.tw/us/Unique_item")
    if not html:
        print("ERROR: cannot fetch Unique_item index page")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    entries = []
    seen = set()

    for td in soup.find_all('td'):
        for a in td.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)
            if not (href.startswith('/us/') and text and len(text) >= 3):
                continue
            path = href.replace('/us/', '')
            if not path or path in seen or path in ('Unique_item',):
                continue
            seen.add(path)

            # Extract level if present
            lv_match = re.search(r'\((\d+)\)', td.get_text(strip=True))
            level = int(lv_match.group(1)) if lv_match else 0

            entries.append({"path": path, "name_en": text, "level": level})

    return entries


def scrape():
    """Main: collect URLs, scrape each in 3 languages."""
    print("=== Collecting unique item URLs ===")
    entries = collect_unique_urls()
    print(f"Found {len(entries)} unique items\n")

    chunks = []
    for i, entry in enumerate(entries):
        # Scrape 3 languages
        en = scrape_unique_item(entry["path"], "us")
        cn = scrape_unique_item(entry["path"], "cn")
        tw = scrape_unique_item(entry["path"], "tw")
        time.sleep(0.3)

        if not en:
            continue

        # Build search text
        parts = [f"[EN] Item: {en.get('name', entry['name_en'])}"]
        if en.get("item_type"):
            parts.append(f"Type: {', '.join(en['item_type'])}")
        if en.get("implicit_mods"):
            parts.append(f"Implicit: {'; '.join(en['implicit_mods'])}")
        if en.get("explicit_mods"):
            parts.append(f"Explicit: {'; '.join(en['explicit_mods'])}")
        if en.get("description"):
            parts.append(f"[EN] Effect: {en['description']}")
        if cn and cn.get("name"):
            parts.append(f"[CN] Name: {cn['name']}")
            if cn.get("explicit_mods"):
                parts.append(f"[CN] Explicit: {'; '.join(cn['explicit_mods'])}")
        if tw and tw.get("name"):
            parts.append(f"[TW] Name: {tw['name']}")

        search_text = "\n".join(parts)

        chunk = {
            "chunk_id": f"unique_{entry['path']}",
            "content_type": "item",
            "source_page": "Unique_item",
            "item_path": entry["path"],
            "name_en": entry["name_en"],
            "search_text": search_text[:4000],
            "en_data": json.dumps(en, ensure_ascii=False) if en else "",
            "cn_data": json.dumps(cn, ensure_ascii=False) if cn else "",
            "tw_data": json.dumps(tw, ensure_ascii=False) if tw else "",
        }
        chunks.append(chunk)

        if (i + 1) % 20 == 0:
            _save(chunks)
            print(f"  [{i+1}/{len(entries)}] {len(chunks)} chunks saved")
            time.sleep(2)

    _save(chunks)
    return chunks


def _save(chunks, path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "poe2db_uniques.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    chunks = scrape()
    if out:
        _save(chunks, out)
    print(f"\nDone: {len(chunks)} unique items")
    total_mods = sum(
        len(json.loads(c.get('en_data', '{}')).get('explicit_mods', [])) +
        len(json.loads(c.get('en_data', '{}')).get('implicit_mods', []))
        for c in chunks
    )
    print(f"Total mods extracted: {total_mods}")
