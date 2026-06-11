"""Find the REAL TA and CN chunks, merge them properly."""
import json, sys, os, requests
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()

# Find best TA chunk: prefer one with search_text field and actual content
tas = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.source == "poe2wiki",
    KnowledgeChunk.content.ilike("%Amulet%Twisted%")
).all()
print(f"TA chunks (poe2wiki): {len(tas)}")
best_ta = None
best_len = 0
for c in tas:
    data = json.loads(c.content)
    st = data.get("search_text", "") or data.get("text", "")
    has_cjk = any('一' <= ch <= '鿿' for ch in st)
    print(f"  id={c.id} len={len(st)} has_cjk={has_cjk} | {st[:80]}")
    if has_cjk and len(st) > best_len:
        best_len = len(st)
        best_ta = c

if not best_ta:
    print("No TA with CJK content found!")
    db.close()
    exit()

# Find best CN chunk: newest, with actual content
cns = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.content.ilike("%Instilled Notables%"),
    KnowledgeChunk.content.notilike("%Twisted%Amulet%")
).order_by(KnowledgeChunk.id.desc()).all()
print(f"\nCN chunks: {len(cns)}")
best_cn = None
best_cn_len = 0
for c in cns:
    data = json.loads(c.content)
    st = data.get("search_text", "") or data.get("text", "")
    has_cjk = any('一' <= ch <= '鿿' for ch in st)
    print(f"  id={c.id} len={len(st)} has_cjk={has_cjk} | {st[:80]}")
    if len(st) > best_cn_len:
        best_cn_len = len(st)
        best_cn = c

if not best_cn:
    print("No CN with content found!")
    db.close()
    exit()

# Extract texts - TA already has data in search_text
ta_data = json.loads(best_ta.content)
cn_data = json.loads(best_cn.content)
ta_st = ta_data.get("search_text", "") or ta_data.get("text", "")
cn_st = cn_data.get("search_text", "") or cn_data.get("text", "")

# If this TA already has merged content, strip the merge suffix
if "## Possible Instilled Notables" in ta_st:
    ta_st = ta_st.split("## Possible Instilled Notables")[0].strip()

new_st = ta_st + "\n\n## Possible Instilled Notables (可涂油天赋)\n" + cn_st
ta_data["search_text"] = new_st
best_ta.content = json.dumps(ta_data, ensure_ascii=False)

# Re-embed
emb_url = os.getenv("EMBEDDING_API_URL", "https://api.siliconflow.cn/v1/embeddings")
emb_key = os.getenv("EMBEDDING_API_KEY", "")
resp = requests.post(emb_url,
    headers={"Authorization": f"Bearer {emb_key}"},
    json={"model": "BAAI/bge-m3", "input": [new_st[:4000]]}, timeout=15)
best_ta.embedding = resp.json()["data"][0]["embedding"]

# Delete corrupted TA chunks
for c in tas:
    if c.id != best_ta.id:
        db.delete(c)

db.commit()
print(f"\nOK: TA id={best_ta.id}, {len(ta_st)} -> {len(new_st)} chars")
print(f"Preview: {new_st[:200]}...")
print(f"Corrupted chunks deleted: {len(tas)-1}")
db.close()
