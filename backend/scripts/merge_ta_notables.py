"""Merge Instilled Notables data into Twisted Amulet chunk's search_text."""
import json, sys, os, requests
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()

ta = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Twisted Amulet%")
).first()
cn = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%")
).first()

if not ta or not cn:
    print("NOT FOUND")
    exit()

ta_data = json.loads(ta.content)
cn_data = json.loads(cn.content)
old_st = ta_data.get("search_text", "?")
cn_st = cn_data.get("search_text", "?")

# Merge: TA data + possible notables list
new_st = old_st + "\n\n## Possible Instilled Notables\n" + cn_st

ta_data["search_text"] = new_st
ta.content = json.dumps(ta_data, ensure_ascii=False)

# Re-embed
emb_url = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
emb_key = os.getenv("EMBEDDING_API_KEY", "")
resp = requests.post(emb_url,
    headers={"Authorization": f"Bearer {emb_key}"},
    json={"model": "BAAI/bge-m3", "input": [new_st]}, timeout=15)
ta.embedding = resp.json()["data"][0]["embedding"]

db.commit()
print(f"OK: {len(old_st)} -> {len(new_st)} chars")
print(new_st[:500])
db.close()
