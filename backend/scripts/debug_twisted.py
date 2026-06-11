"""Debug: check Twisted Amulet links and Instilled Notables retrieval."""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()

# Find Twisted Amulet chunk
c = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Twisted Amulet%")
).first()
if c:
    links = json.loads(c.links) if c.links else []
    print("Twisted Amulet links:")
    for l in links:
        print(f"  {l}")
    data = json.loads(c.content)
    print(f"\nSearch text: {data.get('search_text', '?')[:300]}")

# Find Instilled Notables chunk
cn = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%")
).first()
if cn:
    data = json.loads(cn.content)
    print(f"\nInstilled Notables: id={cn.id} type={cn.chunk_type}")
    print(f"Text: {data.get('search_text', '?')[:200]}")
else:
    print("\nInstilled Notables: NOT FOUND")

# Test: search for "notable" concept expansion
from app.services.embedding_service import get_embedding
from app.services.retrieval_pipeline import expand_concepts

# Simulate what happens with Twisted Amulet chunk
chunks = [_chunk_dict(c)] if c else []
concept_emb = get_embedding("notable passive skill enchant")
print(f"\nConcept embedding: {'OK' if concept_emb else 'FAIL'}")

# Search passport type for notable expansion
dist = KnowledgeChunk.embedding.cosine_distance(concept_emb).label("d")
rows = db.query(KnowledgeChunk, dist).filter(
    KnowledgeChunk.chunk_type == "passive",
    KnowledgeChunk.stale == False,
).order_by(dist).limit(5).all()
print("\nTop 5 passive chunks for 'notable passive skill enchant':")
for row, d in rows:
    data = json.loads(row.content)
    print(f"  sim={round(1-d, 3)} | id={row.id} | {data.get('name', data.get('title', '?'))[:60]}")

db.close()

def _chunk_dict(c):
    return {"content": c.content, "chunk_type": c.chunk_type,
            "source": c.source, "links": c.links, "similarity": 1.0}
