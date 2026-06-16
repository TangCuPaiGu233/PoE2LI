"""Scrape instilled notables list from poe2wiki Instilling page."""
import requests, re, json, os, sys
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding

r = requests.get("https://www.poe2wiki.net/wiki/Instilling",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
soup = BeautifulSoup(r.text, "html.parser")
content = soup.find("div", class_="mw-parser-output")
tables = content.find_all("table") if content else []

notables = []
# Table 2 = notable passives (header starts with "Name")
for t in tables:
    first_header = t.find("th")
    if first_header and first_header.get_text(strip=True).lower() == "name":
        for row in t.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if cells:
                name = cells[0].get_text(strip=True)
                effect = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                if name and len(name) > 2:
                    notables.append({"name": name, "effect": effect})
        break  # Only process the first "Name" table

print(f"Found {len(notables)} instilled notables")
for n in notables[:5]:
    print(f"  {n['name']}: {n['effect'][:80]}")

# Build search text and ingest as one chunk
search_text = "Instilled Notables / Anointments (涂油) - PoE2\n\n"
for n in notables:
    search_text += f"- {n['name']}: {n['effect']}\n"

# Get embedding
emb = get_embedding(search_text)
if not emb:
    print("ERROR: no embedding")
    sys.exit(1)

# Ingest
db = SessionLocal()
try:
    # Check if already exists
    existing = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.source == "poe2wiki",
        KnowledgeChunk.chunk_type == "wiki",
        KnowledgeChunk.content.ilike("%Instilled Notables%")
    ).first()
    if existing:
        print(f"Already exists (id={existing.id}), updating...")
        existing.content = json.dumps({"search_text": search_text, "name": "Instilled Notables"}, ensure_ascii=False)
        existing.embedding = emb
    else:
        kc = KnowledgeChunk(
            content=json.dumps({"search_text": search_text, "name": "Instilled Notables"}, ensure_ascii=False),
            embedding=emb,
            source="poe2wiki",
            chunk_type="wiki",
            league="Standard",
            game_version="0_1",
        )
        db.add(kc)
    db.commit()
    print(f"Saved {len(notables)} notables")
finally:
    db.close()
