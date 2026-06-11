"""Merge Instilled Notables data into Twisted Amulet chunk."""
import json, sys, os, requests
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()

# Find all TA chunks
tas = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Twisted%Amulet%")
).all()
print(f"TA chunks: {len(tas)}")
best_ta = None
best_len = 0
for c in tas:
    data = json.loads(c.content)
    st = data.get("search_text", "") or data.get("text", "")
    print(f"  id={c.id} source={c.source} len={len(st)}")
    if len(st) > best_len:
        best_len = len(st)
        best_ta = c

# Find Instilled Notables
cns = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%")
).all()
print(f"\nCN chunks: {len(cns)}")
best_cn = None
best_cn_len = 0
for c in cns:
    data = json.loads(c.content)
    st = data.get("search_text", "") or data.get("text", "")
    print(f"  id={c.id} type={c.chunk_type} len={len(st)}")
    if len(st) > best_cn_len:
        best_cn_len = len(st)
        best_cn = c

if not best_ta or not best_cn:
    print("NOT FOUND")
    db.close()
    exit()

# Extract texts
ta_data = json.loads(best_ta.content)
cn_data = json.loads(best_cn.content)

ta_st = ta_data.get("search_text", "") or ta_data.get("text", "")
cn_st = cn_data.get("search_text", "") or cn_data.get("text", "")

print(f"\nTA text ({len(ta_st)}): {ta_st[:200]}")
print(f"CN text ({len(cn_st)}): {cn_st[:200]}")

if len(cn_st) < 10:
    print("CN text too short, trying to regenerate...")
    # The crawler version might have the data nested differently
    # Just use the raw content as fallback
    print(f"Raw CN content keys: {list(cn_data.keys())}")
    for k, v in cn_data.items():
        if isinstance(v, str) and len(v) > 50:
            print(f"  Found long text in field '{k}': {v[:100]}")
            cn_st = v
            break

if len(cn_st) < 10:
    print("Cannot find notable text anywhere")
    db.close()
    exit()

# Merge
new_st = ta_st + "\n\n## Possible Instilled Notables (可涂油天赋)\n" + cn_st
ta_data["search_text"] = new_st
best_ta.content = json.dumps(ta_data, ensure_ascii=False)

# Re-embed
emb_url = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
emb_key = os.getenv("EMBEDDING_API_KEY", "")
if emb_key:
    resp = requests.post(emb_url,
        headers={"Authorization": f"Bearer {emb_key}"},
        json={"model": "BAAI/bge-m3", "input": [new_st]}, timeout=15)
    best_ta.embedding = resp.json()["data"][0]["embedding"]
    print("Re-embedded")

db.commit()
print(f"OK: {best_len} -> {len(new_st)} chars, chunk id={best_ta.id}")
db.close()
