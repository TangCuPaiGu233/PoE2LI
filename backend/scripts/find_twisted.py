"""Find twisted items in knowledge base."""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()
chunks = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.source == "poe2db",
    KnowledgeChunk.content.ilike("%Twisted%")
).all()
for c in chunks:
    data = json.loads(c.content)
    name_en = data.get("name_en", "?")[:60]
    cn_raw = data.get("cn_data", "?")
    cn_name = "?"
    if isinstance(cn_raw, str) and len(cn_raw) > 10:
        try:
            cn_data = json.loads(cn_raw)
            cn_name = cn_data.get("name", "?")[:60]
        except:
            pass
    search = data.get("search_text", "")[:100]
    print(f"EN: {name_en}")
    print(f"CN: {cn_name}")
    print(f"ST: {search}")
    print("---")
print(f"Total: {len(chunks)}")
db.close()
