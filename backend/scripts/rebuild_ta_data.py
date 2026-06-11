"""Complete rebuild: scrape Instilled Notables + merge into TA chunk."""
import json, sys, os, requests, re
sys.path.insert(0, "/app")
from bs4 import BeautifulSoup
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding

db = SessionLocal()

# ── 1. Delete old empty CN chunks ──
for c in db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%")
).all():
    db.delete(c)
db.commit()
print("Deleted old CN chunks")

# ── 2. Scrape instilled notables from wiki ──
r = requests.get("https://www.poe2wiki.net/wiki/Instilling",
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
soup = BeautifulSoup(r.text, "html.parser")
content = soup.find("div", class_="mw-parser-output")
tables = content.find_all("table") if content else []

notables = []
for t in tables:
    first_header = t.find("th")
    if first_header and first_header.get_text(strip=True).lower() == "name":
        for row in t.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if cells:
                name = cells[0].get_text(strip=True)
                effect = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                if name and len(name) > 2:
                    notables.append((name, effect))
        break

cn_text = "Instilled Notables / Anointments (可涂油天赋) - PoE2\n\n"
for name, effect in notables:
    cn_text += f"- {name}: {effect}\n"

print(f"Scraped {len(notables)} notables")

# ── 3. Find TA chunk and merge ──
ta = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Twisted Amulet%")
).first()

if not ta:
    print("TA NOT FOUND")
    db.close()
    exit()

ta_data = json.loads(ta.content)
old_st = ta_data.get("search_text", "") or ta_data.get("text", "")

new_st = old_st + "\n\n## Possible Instilled Notables\n" + cn_text
ta_data["search_text"] = new_st
ta.content = json.dumps(ta_data, ensure_ascii=False)

# Re-embed
emb = get_embedding(new_st)
if emb:
    ta.embedding = emb
    print("Re-embedded")

db.commit()
print(f"OK: {len(old_st)} -> {len(new_st)} chars, TA id={ta.id}")
print(new_st[:500])
db.close()
