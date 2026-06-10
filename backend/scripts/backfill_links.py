"""backfill_links.py — 为存量 knowledge_chunks 补算 concept links。

遍历所有已有 chunk，调用 compute_links() 填充 links 字段。
可中断续跑：跳过已有 links 的 chunk。
"""
import json, sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.concept_links import compute_links


def backfill():
    db = SessionLocal()
    try:
        total = db.query(KnowledgeChunk).count()
        # Count already-linked
        done = db.query(KnowledgeChunk).filter(KnowledgeChunk.links.isnot(None)).count()
        pending = total - done
        print(f"Total: {total} | Done: {done} | Pending: {pending}")

        batch_size = 500
        updated = 0
        for offset in range(0, total, batch_size):
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.links.is_(None))
                .limit(batch_size)
                .all()
            )
            if not chunks:
                break

            for chunk in chunks:
                try:
                    data = json.loads(chunk.content)
                    st = data.get("search_text", "")
                except Exception:
                    st = chunk.content or ""
                links = compute_links(st, chunk.chunk_type or "")
                if links:
                    chunk.links = json.dumps(links, ensure_ascii=False)
                else:
                    chunk.links = "[]"
                updated += 1

            db.commit()
            print(f"  {min(offset + batch_size, total)}/{total}, {updated} updated")

        print(f"\nDone: {updated} chunks linked")
    finally:
        db.close()


if __name__ == "__main__":
    backfill()
