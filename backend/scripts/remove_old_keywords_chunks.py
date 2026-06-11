"""Remove legacy whole-page Keywords_text mechanic chunks."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.models.knowledge_graph import KbEdge, KbEntity


def main() -> None:
    db = SessionLocal()
    try:
        rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.source == "poe2db").all()
        targets: list[KnowledgeChunk] = []
        for row in rows:
            try:
                payload = json.loads(row.content)
            except Exception:
                continue
            cid = payload.get("chunk_id", "")
            if cid.startswith("Keywords_text_"):
                targets.append(row)
            elif payload.get("source_page") == "Keywords" and payload.get("keyword_id") is None:
                targets.append(row)

        print(f"Found {len(targets)} legacy Keywords chunks")
        chunk_ids = [row.id for row in targets]
        entity_ids = [
            eid for (eid,) in db.query(KbEntity.id).filter(
                KbEntity.chunk_id.in_(chunk_ids)
            ).all()
        ]
        if entity_ids:
            db.query(KbEdge).filter(
                (KbEdge.src_entity_id.in_(entity_ids))
                | (KbEdge.dst_entity_id.in_(entity_ids))
            ).delete(synchronize_session=False)
            db.query(KbEntity).filter(KbEntity.id.in_(entity_ids)).delete(
                synchronize_session=False
            )
        for row in targets:
            db.delete(row)
        db.commit()
        print("Deleted.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
