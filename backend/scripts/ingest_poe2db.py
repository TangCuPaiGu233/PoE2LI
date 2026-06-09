"""Ingest poe2db chunks into knowledge_chunks table with embeddings."""

import json, os, sys, time, logging, hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode()[:500]).hexdigest()[:12]


def ingest(jsonl_path: str):
    if not os.path.exists(jsonl_path):
        logger.error(f"File not found: {jsonl_path}")
        return

    with open(jsonl_path, "r", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]

    logger.info(f"Loaded {len(chunks)} chunks from {jsonl_path}")

    db = SessionLocal()
    try:
        # Check existing by content hash to avoid duplicates
        existing = set(
            row[0] for row in db.query(KnowledgeChunk.source).filter(
                KnowledgeChunk.source == "poe2db"
            ).all()
        )
        logger.info(f"Existing poe2db chunks: {len(existing)}")

        ingested, skipped, failed = 0, 0, 0
        for i, chunk in enumerate(chunks):
            search_text = chunk.get("search_text", "")[:2000]
            chash = content_hash(search_text)

            # Use search_text hash as dedup key (stored in chunk_type)
            if chash in existing:
                skipped += 1
                continue

            try:
                embedding = get_embedding(search_text)
                if not embedding:
                    failed += 1
                    continue

                kc = KnowledgeChunk(
                    content=json.dumps(chunk, ensure_ascii=False),
                    embedding=embedding,
                    source="poe2db",
                    chunk_type=chunk.get("content_type", "unknown"),
                    league=chunk.get("source_page", ""),
                )
                db.add(kc)
                existing.add(chash)
                ingested += 1

                if ingested % 50 == 0:
                    db.commit()
                    logger.info(f"  {ingested}/{len(chunks)} ingested")
            except Exception as e:
                logger.error(f"Error on chunk {i}: {e}")
                failed += 1

        db.commit()
        logger.info(f"Done: {ingested} added, {skipped} skipped, {failed} failed")
    finally:
        db.close()


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "/app/data/poe2db_chunks_v2.jsonl"
    ingest(p)
