"""Scrape poe2wiki.net — English MediaWiki with rich mechanics data.

Fills gaps poe2db missed: mechanics, auras, huntress, detailed interactions.
"""

import cloudscraper
from bs4 import BeautifulSoup
import json, re, time, sys, os, hashlib

_scraper = None

def _s():
    global _scraper
    if _scraper is None:
        _scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    return _scraper


def fetch(url):
    try:
        resp = _s().get(url, timeout=20)
        return resp.text if resp.status_code == 200 else None
    except:
        return None


def collect_pages():
    """Recursively collect all wiki page URLs."""
    base = "https://www.poe2wiki.net"
    html = fetch(base + "/wiki/Path_of_Exile_2_Wiki")
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    pages = set()
    seen = set()

    # Collect all /wiki/ links from main page
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('/wiki/') and ':' not in href and '#' not in href:
            path = href.replace('/wiki/', '')
            if path and path not in seen:
                seen.add(path)
                pages.add(path)

    # Also crawl category pages for more links
    categories = ['Skills', 'Items', 'Monsters', 'Bosses', 'Classes', 'Ascendancy',
                   'Equipment', 'Gems', 'Mechanics', 'Quests', 'NPCs']
    for cat in categories:
        html2 = fetch(base + "/wiki/Category:" + cat)
        if not html2:
            continue
        soup2 = BeautifulSoup(html2, 'html.parser')
        for a in soup2.find_all('a', href=True):
            href = a['href']
            if href.startswith('/wiki/') and ':' not in href and '#' not in href:
                path = href.replace('/wiki/', '')
                if path and path not in seen:
                    seen.add(path)
                    pages.add(path)
        time.sleep(1)

    return list(pages)


def scrape_page(path):
    """Scrape one wiki page - extract title, content, infobox data."""
    url = "https://www.poe2wiki.net/wiki/" + path
    html = fetch(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'html.parser')
    result = {"path": path, "url": url}

    # Title
    title = soup.find('h1', class_='firstHeading') or soup.find('h1')
    if title:
        result["title"] = title.get_text(strip=True)

    # Main content
    content_div = soup.find('div', class_='mw-parser-output')
    if not content_div:
        return result

    # Extract structured sections
    sections = {}
    current_section = "overview"
    current_text = []

    for el in content_div.find_all(['h2', 'h3', 'h4', 'p', 'li', 'table', 'div']):
        if el.name in ('h2', 'h3', 'h4'):
            if current_text:
                sections[current_section] = '\n'.join(current_text)
            current_section = el.get_text(strip=True).replace('[edit]', '').strip()
            current_text = []
        elif el.name in ('p', 'li'):
            text = el.get_text(strip=True)
            if text and len(text) > 10:
                current_text.append(text)
        elif el.name == 'table' and 'wikitable' in el.get('class', []):
            rows = []
            for tr in el.find_all('tr'):
                cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if cells:
                    rows.append(' | '.join(cells))
            if rows:
                current_text.append('\n'.join(rows))

    if current_text:
        sections[current_section] = '\n'.join(current_text)

    result["sections"] = sections

    # Build search text
    parts = [result.get("title", path)]
    for sec, text in sections.items():
        parts.append(f"[{sec}]\n{text[:500]}")
    result["search_text"] = '\n\n'.join(parts)[:4000]

    return result


def scrape():
    pages = collect_pages()
    print(f"Found {len(pages)} wiki pages")

    chunks = []
    for i, path in enumerate(pages):
        data = scrape_page(path)
        if data:
            chunks.append({
                "chunk_id": f"wiki_{path.replace('/','_')}",
                "content_type": "wiki",
                "source_page": "poe2wiki",
                "title": data.get("title", path),
                "path": path,
                "search_text": data.get("search_text", ""),
                "sections": data.get("sections", {}),
            })

        if (i + 1) % 20 == 0:
            _save(chunks)
            print(f"  [{i+1}/{len(pages)}] {len(chunks)} chunks")
            time.sleep(2)

    _save(chunks)
    return chunks


def _save(chunks, path=None):
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "poe2wiki_chunks.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    chunks = scrape()
    if out:
        _save(chunks, out)
    print(f"\nDone: {len(chunks)} chunks")
