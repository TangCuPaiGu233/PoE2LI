"""Full crawl of poe2wiki — scrape ALL game mechanics pages into knowledge base.

Rate-limited (1s/page), resumable (skips already-ingested pages).
"""
import json, re, sys, os, time, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding

WIKI_BASE = "https://www.poe2wiki.net"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Seed pages to start crawling from
SEEDS = [
    "/wiki/Path_of_Exile_2_Wiki",
    "/wiki/Delirium",
    "/wiki/Breach",
    "/wiki/Ritual",
    "/wiki/Expedition",
    "/wiki/Essence",
    "/wiki/Catalyst",
    "/wiki/Omen",
    "/wiki/Instilling",
    "/wiki/Corruption",
    "/wiki/Crafting",
    "/wiki/Unique_item",
    "/wiki/Skill_gem",
    "/wiki/Passive_Skill_Tree",
    "/wiki/Ascendancy",
]

# URL patterns to SKIP (non-content pages)
SKIP_PATTERNS = [
    "/wiki/Special:", "/wiki/Talk:", "/wiki/User:", "/wiki/File:",
    "/wiki/Template:", "/wiki/Help:", "/wiki/Category:",
    "/w/", "/wiki/index.php", "#", "action=edit", "oldid=",
]


def get_existing_urls(db) -> set:
    """Get set of already-ingested wiki URLs."""
    existing = set()
    chunks = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.source == "poe2wiki"
    ).all()
    for c in chunks:
        try:
            data = json.loads(c.content)
            url = data.get("url", "")
            if url:
                existing.add(url)
        except:
            pass
    return existing


def extract_links(soup, base_url):
    """Extract wiki article links from a page."""
    links = set()
    content = soup.find("div", class_="mw-parser-output")
    if not content:
        content = soup
    for a in content.find_all("a", href=True):
        href = a["href"]
        # Only follow /wiki/ links
        if not href.startswith("/wiki/"):
            continue
        # Skip non-content
        if any(p in href for p in SKIP_PATTERNS):
            continue
        full = urljoin(base_url, href)
        # Remove fragment
        full = full.split("#")[0]
        links.add(full)
    return links


def scrape_page(url):
    """Scrape a wiki page and return clean text + title."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        # Title
        title_el = soup.find("title")
        title = title_el.get_text(strip=True).replace(" - Path of Exile 2 Wiki", "") if title_el else ""

        # Main content
        content = soup.find("div", class_="mw-parser-output")
        if not content:
            return None

        # Remove unwanted elements
        for tag in content.find_all(["script", "style", "nav", "table", "sup"]):
            tag.decompose()

        # Extract paragraphs and list items
        parts = []
        for el in content.find_all(["p", "li", "h2", "h3", "h4"]):
            text = el.get_text(strip=True)
            if text and len(text) > 5:
                if el.name.startswith("h"):
                    parts.append(f"\n## {text}\n")
                elif el.name == "li":
                    parts.append(f"- {text}")
                else:
                    parts.append(text)

        text = "\n".join(parts[:80])  # Limit to 80 elements
        if len(text) < 100:
            return None

        return {
            "title": title,
            "text": text[:8000],  # Cap at 8KB
            "url": url,
        }
    except Exception as e:
        return None


def ingest_page(db, page_data):
    """Insert or skip a scraped page into knowledge_chunks."""
    url = page_data["url"]
    existing = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.source == "poe2wiki",
        KnowledgeChunk.content.ilike(f"%{url}%")
    ).first()
    if existing:
        return False

    search_text = f"{page_data['title']}\n\n{page_data['text']}"
    emb = get_embedding(search_text[:4000])
    if not emb:
        return False

    kc = KnowledgeChunk(
        content=json.dumps(page_data, ensure_ascii=False),
        embedding=emb,
        source="poe2wiki",
        chunk_type="wiki",
    )
    db.add(kc)
    db.flush()
    return True


def crawl():
    db = SessionLocal()
    try:
        existing_urls = get_existing_urls(db)
        print(f"Already ingested: {len(existing_urls)} pages")

        to_visit = [urljoin(WIKI_BASE, s) for s in SEEDS]
        visited = set(existing_urls)
        new_count = 0
        fail_count = 0

        while to_visit and len(visited) < 1000:  # Max 1000 pages
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            print(f"[{len(visited)}] {url.split('/')[-1][:60]} ...", end=" ", flush=True)

            page = scrape_page(url)
            if not page:
                fail_count += 1
                print("SKIP")
                time.sleep(0.5)
                continue

            # Extract more links
            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(r.text, "html.parser")
                new_links = extract_links(soup, url)
                for link in new_links:
                    if link not in visited and link not in to_visit:
                        to_visit.append(link)
            except:
                pass

            # Ingest
            ok = ingest_page(db, page)
            if ok:
                new_count += 1
                db.commit()
                print(f"OK ({page['title'][:40]})")
            else:
                print("DUP")

            # Save progress periodically
            if new_count % 20 == 0:
                print(f"  --- progress: {new_count} new, {len(to_visit)} queued ---")

            time.sleep(1)  # Rate limit

        print(f"\nDone: {new_count} new pages ingested, {fail_count} failed")
        print(f"Total wiki pages: {len(visited)}")

    finally:
        db.close()


if __name__ == "__main__":
    crawl()
