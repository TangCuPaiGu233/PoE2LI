"""Fix Twisted Amulet chunk: dedupe corrupted merges + fresh wiki scrape."""
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(__file__))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding

from wiki_instilled import scrape_instilled_notables


def merge_into_ta(db) -> int:
    notables = scrape_instilled_notables()
    cn_text = "Instilled Notables / Anointments (可涂油天赋) - PoE2\n\n"
    for name, effect in notables:
        cn_text += f"- {name}: {effect}\n"
    print(f"Scraped {len(notables)} notables, cn_text_len={len(cn_text)}")

    tas = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.content.ilike("%Twisted Amulet%")
    ).all()
    best_ta = None
    best_score = -1
    for c in tas:
        data = json.loads(c.content)
        st = data.get("search_text", "") or data.get("text", "")
        cjk = sum(1 for ch in st[:400] if "\u4e00" <= ch <= "\u9fff")
        score = cjk * 1000 + len(st)
        if score > best_score:
            best_score = score
            best_ta = c

    if not best_ta:
        print("TA NOT FOUND")
        return 1

    ta_data = json.loads(best_ta.content)
    ta_st = ta_data.get("search_text", "") or ta_data.get("text", "")
    if "## Possible Instilled Notables" in ta_st:
        ta_st = ta_st.split("## Possible Instilled Notables")[0].strip()
    if "扭曲项链" not in ta_st:
        ta_st = ta_st.replace(
            "Twisted Amulet",
            "扭曲项链 / 扭曲护身符 / Twisted Amulet",
            1,
        )

    new_st = ta_st + "\n\n## Possible Instilled Notables (可涂油天赋)\n" + cn_text
    ta_data["search_text"] = new_st
    ta_data["cn_aliases"] = ["扭曲项链"]
    best_ta.content = json.dumps(ta_data, ensure_ascii=False)
    best_ta.chunk_type = "item"

    emb = get_embedding(new_st[:4000])
    if emb:
        best_ta.embedding = emb
        print("Re-embedded")

    db.commit()
    print(f"OK: TA id={best_ta.id}, total_len={len(new_st)}")
    for name, effect in notables[:5]:
        print(f"  - {name}: {effect[:70]}")
    return 0


if __name__ == "__main__":
    db = SessionLocal()
    try:
        raise SystemExit(merge_into_ta(db))
    finally:
        db.close()
