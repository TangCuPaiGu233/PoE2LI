"""Comprehensive knowledge base statistics."""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from sqlalchemy import func

db = SessionLocal()

# By source+type
rows = db.query(
    KnowledgeChunk.source, KnowledgeChunk.chunk_type, func.count()
).group_by(KnowledgeChunk.source, KnowledgeChunk.chunk_type).order_by(func.count().desc()).all()

print("Source          | Type            | Count")
print("-" * 50)
total = 0
for s, t, c in rows:
    print(f"{s or '?':15s} | {t:15s} | {c}")
    total += c

# CN coverage
sample_size = 3000
has_cn = 0
has_en = 0
for chunk in db.query(KnowledgeChunk).limit(sample_size):
    try:
        data = json.loads(chunk.content)
        st = data.get("search_text", "")
        if any('一' <= ch <= '鿿' for ch in st[:200]):
            has_cn += 1
        if any(ch.isascii() and ch.isalpha() for ch in st[:200]):
            has_en += 1
    except:
        pass

print(f"\nTotal: {total} chunks")
print(f"CN coverage (sample {sample_size}): {has_cn} ({100*has_cn//sample_size}%)")
print(f"EN coverage (sample {sample_size}): {has_en} ({100*has_en//sample_size}%)")

# Alias table coverage
for fname in ["caimogu_skills.json", "caimogu_items.json", "game_aliases.json"]:
    try:
        with open(f"/app/data/{fname}") as f:
            data = json.load(f)
        if isinstance(data, dict) and "cn_to_en" in data:
            n = len(data["cn_to_en"])
        elif isinstance(data, list):
            n = len(data)
        else:
            n = "?"
        print(f"{fname}: {n} entries")
    except:
        print(f"{fname}: MISSING")

db.close()
