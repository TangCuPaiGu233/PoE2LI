"""Debug: check actual caimogu item page URLs."""
import json, sys, requests, re
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk

db = SessionLocal()
chunks = db.query(KnowledgeChunk).filter(
    KnowledgeChunk.source == "poe2db",
    KnowledgeChunk.chunk_type == "item"
).limit(15).all()

headers = {"User-Agent": "Mozilla/5.0"}
for c in chunks:
    data = json.loads(c.content)
    path = data.get("detail_path", "?")
    name_en = data.get("name_en", "?")[:40]

    url = f"https://poe2cn.caimogu.cc/p/{path}.html"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        title = re.search(r"<title>([^<]+)</title>", r.text)
        t = title.group(1)[:80] if title else "N/A"
        has_cjk = bool(re.search(r'[一-鿿]', t))
        no_page = "页面不存在" in r.text
        print(f"{r.status_code} | {name_en} | {path} | cjk={has_cjk} nopage={no_page} | {t}")
    except Exception as e:
        print(f"ERR | {name_en} | {path} | {str(e)[:80]}")

print(f"\nTotal poe2db items: {db.query(KnowledgeChunk).filter(KnowledgeChunk.source == 'poe2db', KnowledgeChunk.chunk_type == 'item').count()}")
db.close()
