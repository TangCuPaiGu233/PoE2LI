"""Inject Twisted Amulet into knowledge base."""
import json, os, sys, requests
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

cn_name = "扭曲护身符"
search_text = f"""{cn_name} / Twisted Amulet
Item: Twisted Amulet (Delirium base type)
Class: Amulet
Base Affix: -1 Prefix Modifier Allowed
Drop: Delirium - Unethical Offering altar in Loathsome Mire, level 18+
Drops with 2 random instilled notables (passive skill enchantments)
Instilling a new notable replaces both enchantments
No unique versions exist
"""

emb_url = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
emb_key = os.getenv("EMBEDDING_API_KEY", "")
resp = requests.post(emb_url,
    headers={"Authorization": f"Bearer {emb_key}"},
    json={"model": "BAAI/bge-m3", "input": [search_text]},
    timeout=30)
emb = resp.json()["data"][0]["embedding"]

db = SessionLocal()
kc = KnowledgeChunk(
    content=json.dumps({"search_text": search_text, "name": "Twisted Amulet", "cn_name": cn_name}, ensure_ascii=False),
    embedding=emb,
    source="poe2wiki",
    chunk_type="item",
)
db.add(kc)
db.commit()
print(f"OK -> id={kc.id}")
db.close()
