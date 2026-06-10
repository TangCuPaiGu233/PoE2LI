"""Scrape all special base types and items from poe2wiki.

Scans category pages (Delirium, Breach, Ritual, etc.) for item links,
scrapes each item page for stats, and ingests into knowledge_chunks.
"""
import json, re, sys, os, time, requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CATEGORIES = [
    "Delirium",
    "Breach",
    "Ritual",
    "Expedition",
    "Essences",
    "Omens",
    "Catalysts",
]

WIKI_BASE = "https://www.poe2wiki.net"


def get_category_pages(category):
    """Get all item page links from a wiki category."""
    url = f"{WIKI_BASE}/wiki/Category:{category}"
    items = []
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}")
        return items
    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find("div", class_="mw-category")
    if not content:
        print(f"  No mw-category div")
        return items
    links = content.find_all("a")
    for a in links:
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if href.startswith("/wiki/") and not href.startswith("/wiki/Category:"):
            items.append((text, href.replace("/wiki/", "")))
    print(f"  Found {len(items)} links")
    return items


def scrape_item(slug):
    """Scrape an item page from poe2wiki."""
    url = f"{WIKI_BASE}/wiki/{slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        # Title
        title = soup.find("title")
        if not title:
            return None
        name = title.get_text(strip=True).replace(" - Path of Exile 2 Wiki", "")

        # Content
        content_div = soup.find("div", class_="mw-parser-output")
        if not content_div:
            return None

        # Extract text
        text_parts = []
        for elem in content_div.find_all(["p", "li", "td", "th"])[:30]:
            t = elem.get_text(strip=True)
            if t and len(t) > 5:
                text_parts.append(t)
        description = ". ".join(text_parts[:12])

        # Build search text
        search_text = f"{name}\n{description}"

        return {
            "name": name,
            "slug": slug,
            "url": url,
            "search_text": search_text[:4000],
        }
    except Exception:
        return None


def get_embedding(text):
    emb_url = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
    emb_key = os.getenv("EMBEDDING_API_KEY", "")
    r = requests.post(emb_url,
        headers={"Authorization": f"Bearer {emb_key}"},
        json={"model": "BAAI/bge-m3", "input": [text]}, timeout=30)
    return r.json()["data"][0]["embedding"]


def ingest(item_data):
    """Insert item into knowledge_chunks."""
    db = SessionLocal()
    try:
        existing = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.source == "poe2wiki",
            KnowledgeChunk.content.like(f"%{item_data['slug']}%")
        ).first()
        if existing:
            return False

        emb = get_embedding(item_data["search_text"])
        kc = KnowledgeChunk(
            content=json.dumps(item_data, ensure_ascii=False),
            embedding=emb,
            source="poe2wiki",
            chunk_type="item",
        )
        db.add(kc)
        db.commit()
        return True
    finally:
        db.close()


def scrape_all():
    all_items = []
    for cat in CATEGORIES:
        print(f"Category: {cat}")
        items = get_category_pages(cat)
        print(f"  Found {len(items)} pages")
        for name, slug in items[:50]:  # Limit per category
            data = scrape_item(slug)
            if data:
                print(f"  {name}")
                ingested = ingest(data)
                if ingested:
                    all_items.append(data)
            time.sleep(0.5)
        time.sleep(2)

    print(f"\nTotal ingested: {len(all_items)}")


if __name__ == "__main__":
    scrape_all()
