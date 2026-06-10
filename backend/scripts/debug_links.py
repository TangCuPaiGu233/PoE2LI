"""Debug: check what links are on Twisted Amulet and related chunks."""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
db = SessionLocal()

# Find Twisted Amulet chunk
chunk = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.source == "poe2wiki",
    KnowledgeChunk.content.ilike("%Twisted%")
).first()

if chunk:
    links = json.loads(chunk.links) if chunk.links else []
    print(f"Twisted Amulet links ({len(links)}):")
    for l in links:
        print(f"  {l}")
else:
    print("Not found")

# Check what concept chunks exist for 涂油, 词缀
print("\n--- Concept chunk coverage ---")
for kw, ctype in [("涂油", "wiki"), ("词缀", "mod"), ("delirium", "wiki"), ("prefix", "mod")]:
    cnt = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.chunk_type == ctype,
        KnowledgeChunk.content.ilike(f"%{kw}%")
    ).count()
    print(f"  {kw} ({ctype}): {cnt} chunks")

# Check: are any chunks actually being retrieved by concept expansion?
print("\n--- Sample entity links in homework chunks ---")
chunks = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.links.isnot(None),
    KnowledgeChunk.chunk_type == "core_idea"
).limit(3).all()
for c in chunks:
    links = json.loads(c.links) if c.links else []
    concepts = [l for l in links if l.startswith("concept:")]
    entities = [l for l in links if l.startswith("entity:")]
    print(f"  concepts={len(concepts)}, entities={len(entities)}")
    for l in concepts[:3]:
        print(f"    {l}")
db.close()
