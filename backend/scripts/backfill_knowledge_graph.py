"""Backfill kb_entities / kb_edges from existing knowledge_chunks."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.models.knowledge_graph import KbEdge, KbEntity
from app.services.knowledge_graph_service import graph_available, sync_chunk_graph


def backfill(batch_size: int = 200):
    db = SessionLocal()
    try:
        if not graph_available(db):
            print("kb_entities table not found — run alembic upgrade head first")
            return

        total = db.query(KnowledgeChunk).filter(KnowledgeChunk.stale == False).count()  # noqa: E712
        print(f"Syncing graph for up to {total} active chunks...")

        updated = 0
        offset = 0
        while offset < total:
            chunks = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.stale == False)  # noqa: E712
                .order_by(KnowledgeChunk.id)
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not chunks:
                break

            for chunk in chunks:
                try:
                    sync_chunk_graph(db, chunk)
                    updated += 1
                except Exception as e:
                    print(f"  skip chunk {chunk.id}: {e}")

            db.commit()
            offset += batch_size
            print(f"  {min(offset, total)}/{total} processed ({updated} synced)")

        entity_count = db.query(KbEntity).count()
        edge_count = db.query(KbEdge).count()
        print(f"Done: {updated} chunks synced | entities={entity_count} edges={edge_count}")
    finally:
        db.close()


if __name__ == "__main__":
    backfill()
