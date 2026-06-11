"""Fix: compute links for Twisted Amulet, fix Instilled Notables chunk_type."""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.concept_links import compute_links

db = SessionLocal()

# 1. Compute links for Twisted Amulet
ta = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Twisted Amulet%")
).first()
if ta:
    data = json.loads(ta.content)
    st = data.get("search_text", "?")
    links = compute_links(st, "item")
    ta.links = json.dumps(links, ensure_ascii=False)
    print(f"TA links ({len(links)}):")
    for l in links:
        print(f"  {l}")

# 2. Fix Instilled Notables to passive
for cn in db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%")
).all():
    old = cn.chunk_type
    cn.chunk_type = "passive"
    # Also compute its links
    data = json.loads(cn.content)
    st = data.get("search_text", "")
    cn.links = json.dumps(compute_links(st, "passive"), ensure_ascii=False)
    print(f"CN {cn.id}: {old} -> passive")

db.commit()
print("Done")
db.close()
