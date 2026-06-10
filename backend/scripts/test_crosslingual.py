"""Test BGE-M3 cross-lingual retrieval quality."""
import json, sys, os, requests
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from sqlalchemy import func

emb_url = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
emb_key = os.getenv("EMBEDDING_API_KEY", "")

test_queries = [
    "火焰伤害",
    "召唤物伤害",
    "最大生命",
    "混沌抗性",
    "攻击速度",
]

db = SessionLocal()

for q in test_queries:
    # Get embedding
    r = requests.post(emb_url,
        headers={"Authorization": f"Bearer {emb_key}"},
        json={"model": "BAAI/bge-m3", "input": [q]},
        timeout=15)
    emb = r.json()["data"][0]["embedding"]

    # Search passives and mods
    dist = KnowledgeChunk.embedding.cosine_distance(emb).label("distance")
    rows = db.query(KnowledgeChunk, dist).filter(
        KnowledgeChunk.chunk_type.in_(["passive", "mod"])
    ).order_by(dist).limit(3).all()

    print(f"\n=== {q} ===")
    for c, d in rows:
        data = json.loads(c.content)
        st = data.get("search_text", "?")[:150]
        sim = round(1.0 - d, 3)
        print(f"  sim={sim} | [{c.chunk_type}] {st}")

db.close()
