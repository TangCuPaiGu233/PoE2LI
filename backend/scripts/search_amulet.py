"""Search DB for amulet/necklace items."""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()
# Search for amulet items in poe2db
chunks = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.source == "poe2db",
    KnowledgeChunk.content.ilike("%amulet%")
).all()

print(f"Amulet items: {len(chunks)}")
for c in chunks[:10]:
    data = json.loads(c.content)
    name_en = data.get("name_en", "?")[:80]
    cn_raw = data.get("cn_data", "")
    cn_name = "?"
    if isinstance(cn_raw, str) and len(cn_raw) > 10:
        try:
            cn_data = json.loads(cn_raw)
            cn_name = cn_data.get("name", "?")[:80]
        except:
            pass
    print(f"{name_en} | {cn_name}")

# Also search for items with CN name containing specific chars
chunks2 = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.source == "poe2db",
    KnowledgeChunk.content.ilike("%amulet%")
).limit(1).all()
if chunks2:
    data = json.loads(chunks2[0].content)
    print("\nFull content keys:", list(data.keys()))
    cn_raw = data.get("cn_data", "")
    if cn_raw:
        print("cn_data type:", type(cn_raw))
        print("cn_data[:500]:", cn_raw[:500])

db.close()
