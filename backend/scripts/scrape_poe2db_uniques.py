"""Scrape all unique items from poe2db with full mod data.

One chunk per base-type variant (tab-pane). Parent groups share parent_entity_id.
"""

import cloudscraper
from bs4 import BeautifulSoup
import json, re, time, sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.services.name_validation import validate_name_en, normalize_en_name

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
    except Exception:
        return None


def _slug(s: str) -> str:
    s = re.sub(r"[^\w]+", "_", s.lower()).strip("_")
    return s[:40] or "variant"


def _parse_variant_pane(pane, page_name: str | None) -> dict | None:
    name_el = pane.find(class_="itemName")
    if not name_el:
        return None
    name = name_el.get_text(strip=True)
    if not name:
        return None

    props = pane.find_all(class_="property")
    item_types = [p.get_text(strip=True) for p in props if p.get_text(strip=True)]

    implicits = list(dict.fromkeys(
        i.get_text(strip=True) for i in pane.find_all(class_="implicitMod")
        if i.get_text(strip=True)
    ))
    explicits = list(dict.fromkeys(
        e.get_text(strip=True) for e in pane.find_all(class_="explicitMod")
        if e.get_text(strip=True)
    ))

    stats_el = pane.find(class_="Stats")
    stats_full = stats_el.get_text(separator=" | ", strip=True) if stats_el else ""

    return {
        "name": name or page_name,
        "item_type": item_types,
        "implicit_mods": implicits,
        "explicit_mods": explicits,
        "stats_full": stats_full,
    }


def scrape_unique_variants(path: str, lang_code: str) -> list[dict]:
    """Scrape one unique page — one dict per tab-pane variant."""
    url = f"https://poe2db.tw/{lang_code}/{path}"
    html = fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    page_name_el = soup.find(class_="itemName")
    page_name = page_name_el.get_text(strip=True) if page_name_el else None

    variants: list[dict] = []
    panes = soup.select(".tab-pane")
    for pane in panes:
        v = _parse_variant_pane(pane, page_name)
        if v:
            v["url"] = url
            variants.append(v)

    if not variants:
        root = soup.find(class_="tab-pane") or soup
        v = _parse_variant_pane(root, page_name)
        if v:
            v["url"] = url
            variants.append(v)

    # Dedup identical base types within one page
    seen: set[str] = set()
    unique_variants: list[dict] = []
    for v in variants:
        key = "|".join(v.get("item_type") or []) or v.get("name", "")
        if key in seen:
            continue
        seen.add(key)
        unique_variants.append(v)
    return unique_variants


def collect_unique_urls():
    """Collect all unique item detail page URLs from the index page."""
    html = fetch("https://poe2db.tw/us/Unique_item")
    if not html:
        print("ERROR: cannot fetch Unique_item index page")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    entries = []
    seen = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        if not (href.startswith('/us/') and text and len(text) >= 3):
            continue
        path = href.replace('/us/', '')
        if not path or path in seen or '/' in path:
            continue
        if path in ('Unique_item', 'Items', 'Gem', 'Modifiers', 'Passive_Skill_Tree'):
            continue
        seen.add(path)
        entries.append({"path": path, "name_en": text, "level": 0})

    return entries


def _build_search_text(
    en: dict,
    cn: dict | None,
    tw: dict | None,
    name_en: str,
    parent_name_cn: str | None,
) -> str:
    parts = [f"[EN] Item: {en.get('name', name_en)}"]
    if en.get("item_type"):
        parts.append(f"Type: {', '.join(en['item_type'])}")
    if en.get("implicit_mods"):
        parts.append(f"Implicit: {'; '.join(en['implicit_mods'])}")
    if en.get("explicit_mods"):
        parts.append(f"Explicit: {'; '.join(en['explicit_mods'])}")
    if cn and cn.get("name"):
        parts.append(f"[CN] Name: {cn['name']}")
        if parent_name_cn and parent_name_cn != cn["name"]:
            parts.append(f"[CN] Parent: {parent_name_cn}")
        if cn.get("explicit_mods"):
            parts.append(f"[CN] Explicit: {'; '.join(cn['explicit_mods'])}")
    if tw and tw.get("name"):
        parts.append(f"[TW] Name: {tw['name']}")
    return "\n".join(parts)


def scrape():
    """Main: collect URLs, scrape each in 3 languages, emit per-variant chunks."""
    print("=== Collecting unique item URLs ===")
    entries = collect_unique_urls()
    print(f"Found {len(entries)} unique items\n")

    chunks = []
    for i, entry in enumerate(entries):
        en_variants = scrape_unique_variants(entry["path"], "us")
        cn_variants = scrape_unique_variants(entry["path"], "cn")
        tw_variants = scrape_unique_variants(entry["path"], "tw")
        time.sleep(0.3)

        if not en_variants:
            continue

        ok, canonical_en = validate_name_en(entry["name_en"], entry["name_en"])
        if not ok:
            print(f"  SKIP dirty index name: {entry['name_en']}")
            continue

        parent_id = f"unique_{entry['path']}"
        parent_cn = cn_variants[0].get("name") if cn_variants else None

        for vi, en in enumerate(en_variants):
            cn = cn_variants[vi] if vi < len(cn_variants) else (cn_variants[0] if cn_variants else None)
            tw = tw_variants[vi] if vi < len(tw_variants) else (tw_variants[0] if tw_variants else None)

            base_slug = _slug(",".join(en.get("item_type") or []) or f"v{vi}")
            chunk_id = f"{parent_id}_{base_slug}" if len(en_variants) > 1 else parent_id

            search_text = _build_search_text(en, cn, tw, canonical_en, parent_cn)

            chunk = {
                "chunk_id": chunk_id,
                "content_type": "item",
                "source_page": "Unique_item",
                "item_path": entry["path"],
                "parent_entity_id": parent_id,
                "variant_index": vi,
                "name_en": canonical_en,
                "variant_base_type": en.get("item_type", [None])[0] if en.get("item_type") else None,
                "search_text": search_text[:4000],
                "en_data": json.dumps(en, ensure_ascii=False),
                "cn_data": json.dumps(cn, ensure_ascii=False) if cn else "",
                "tw_data": json.dumps(tw, ensure_ascii=False) if tw else "",
            }
            chunks.append(chunk)

        if (i + 1) % 20 == 0:
            _save(chunks)
            print(f"  [{i+1}/{len(entries)}] {len(chunks)} variant chunks saved")
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
    print(f"\nDone: {len(chunks)} unique variant chunks")
    total_mods = sum(
        len(json.loads(c.get('en_data', '{}')).get('explicit_mods', [])) +
        len(json.loads(c.get('en_data', '{}')).get('implicit_mods', []))
        for c in chunks
    )
    print(f"Total mods extracted: {total_mods}")
