"""Comprehensive data summary."""
import json, sys, os
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from sqlalchemy import func

db = SessionLocal()

# 1. Source × Type distribution
rows = db.query(
    KnowledgeChunk.source, KnowledgeChunk.chunk_type, func.count()
).group_by(KnowledgeChunk.source, KnowledgeChunk.chunk_type).order_by(func.count().desc()).all()

print("=== KNOWLEDGE CHUNKS ===")
print(f"{'Source':15s} | {'Type':20s} | {'Count':>6s} | CN")
print("-" * 55)
total = 0
for s, t, c in rows:
    has_cn = "Y" if s in ("poe2db", "homework") or (s == "pob" and t == "asc_nodes") else "N"
    print(f"{s or '?':15s} | {t:20s} | {c:>6d} | {has_cn}")
    total += c
print(f"\nTotal: {total} chunks")

# 2. Alias table coverage
aliases_dir = "/app/data"
alias_files = {
    "caimogu_skills.json": "Caimogu skill CN names",
    "caimogu_items.json": "Caimogu item CN names (broken)",
    "game_aliases.json": "Poe2DB item CN names",
    "coe_cn_aliases.json": "CraftofExile mod CN names",
}
print("\n=== ALIAS TABLES ===")
for fname, desc in alias_files.items():
    path = os.path.join(aliases_dir, fname)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "cn_to_en" in data:
            n = len(data["cn_to_en"])
        elif isinstance(data, list):
            n = len(data)
        elif isinstance(data, dict):
            n = len(data)
        else:
            n = "?"
        print(f"  {desc}: {n} entries")
    else:
        print(f"  {desc}: MISSING")

# 3. Entity resolution stats
from app.services.entity_dict import ASCENDANCY_CN_TO_EN, CLASS_CN_TO_EN
from app.services.concept_links import CONCEPT_HOOKS
print(f"\n=== RESOLUTION COVERAGE ===")
print(f"  Classes: {len(CLASS_CN_TO_EN)} CN aliases")
print(f"  Ascendancies: {len(ASCENDANCY_CN_TO_EN)} CN aliases")
print(f"  Concept hooks: {len(CONCEPT_HOOKS)} keywords")

# 4. Links
with_links = db.query(KnowledgeChunk).filter(KnowledgeChunk.links.isnot(None)).count()
print(f"\n  Chunks with concept links: {with_links}/{total}")

# 5. CN text coverage sample
sample = 5000
has_cn_chars = 0
for chunk in db.query(KnowledgeChunk).limit(sample):
    try:
        data = json.loads(chunk.content)
        st = data.get("search_text", "")
    except:
        st = chunk.content or ""
    if any('一' <= c <= '鿿' for c in st[:300]):
        has_cn_chars += 1
print(f"  Chunks with CJK text (sample {sample}): {has_cn_chars} ({100*has_cn_chars//sample}%)")

db.close()
