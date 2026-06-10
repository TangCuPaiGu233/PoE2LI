"""scrape_wiki_bases.py — Scrape special base types from poe2wiki + caimogu CN names.

Targets: Delirium, Breach, Ritual, Expedition, and other mechanic-specific
base types that aren't in poe2db unique items.

Strategy:
  1. Scrape Twisted Amulet wiki page (known Delirium base)
  2. Scrape other Delirium bases from wiki category
  3. For each, try to find CN name on caimogu
  4. Ingest into knowledge_chunks
"""
import json, re, sys, os, time, requests
from bs4 import BeautifulSoup

# Delirium bases from wiki
DELIRIUM_BASES = [
    "Twisted_Amulet",
    "Twisted_Ring",
    "Twisted_Belt",
    # More to discover from wiki category page
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}

def scrape_wiki_page(slug):
    """Scrape item data from poe2wiki."""
    url = f"https://www.poe2wiki.net/wiki/{slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')

        # Extract title
        title = soup.find('title')
        name_en = title.get_text(strip=True).replace(" - Path of Exile 2 Wiki", "") if title else slug.replace("_", " ")

        # Extract content from infobox and text
        content_div = soup.find('div', class_='mw-parser-output')
        if not content_div:
            return None

        # Get item stats from infobox
        infobox = content_div.find('table', class_='infobox')
        stats = {}
        if infobox:
            for row in infobox.find_all('tr'):
                cells = row.find_all(['th', 'td'])
                if len(cells) == 2:
                    key = cells[0].get_text(strip=True).lower()
                    val = cells[1].get_text(strip=True)
                    stats[key] = val

        # Get description text
        desc_parts = []
        for p in content_div.find_all(['p', 'li'])[:10]:
            text = p.get_text(strip=True)
            if text and len(text) > 10:
                desc_parts.append(text)
        description = " ".join(desc_parts[:8])

        return {
            "name_en": name_en,
            "stats": stats,
            "description": description,
            "url": url,
        }
    except Exception as e:
        return None


def find_cn_name(name_en):
    """Try to find CN name from caimogu."""
    slug = name_en.replace(" ", "_")
    url = f"https://poe2cn.caimogu.cc/p/{slug}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        title_m = re.search(r'<title>([^<]+)</title>', r.text)
        if title_m:
            title = title_m.group(1)
            parts = title.split(" - ")
            if parts:
                name_part = parts[0].strip()
                words = name_part.split()
                if words:
                    return words[0]  # First word is CN name
    except:
        pass
    return None


def scrape_all(output_dir="/app/data"):
    results = []
    for slug in DELIRIUM_BASES:
        print(f"Scraping {slug}...")
        data = scrape_wiki_page(slug)
        if data:
            cn = find_cn_name(data["name_en"])
            data["name_cn"] = cn or ""
            results.append(data)
            print(f"  OK: {data['name_en']} -> CN: {cn}")
        else:
            print(f"  FAILED")
        time.sleep(1)

    # Save
    path = os.path.join(output_dir, "wiki_bases.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(results)} items to {path}")


if __name__ == "__main__":
    scrape_all(sys.argv[1] if len(sys.argv) > 1 else "/app/data")
