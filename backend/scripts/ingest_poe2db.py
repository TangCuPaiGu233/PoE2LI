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


def ingest(jsonl_path: str, source: str = "poe2db",
           league: str | None = None, game_version: str | None = None):
    if not os.path.exists(jsonl_path):
        logger.error(f"File not found: {jsonl_path}")
        return

    with open(jsonl_path, "r", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]

    logger.info(f"Loaded {len(chunks)} chunks from {jsonl_path} (source={source})")

    db = SessionLocal()
    try:
        # Dedup by hashing the search_text of already-ingested chunks for this source.
        # (Previous version compared content hashes against the literal string
        # "poe2db", so dedup never matched and re-runs created duplicates.)
        existing = set()
        for (content,) in db.query(KnowledgeChunk.content).filter(
            KnowledgeChunk.source == source
        ).all():
            try:
                existing.add(content_hash(json.loads(content).get("search_text", "")[:2000]))
            except Exception:
                existing.add(content_hash(content[:2000]))
        logger.info(f"Existing {source} chunks: {len(existing)}")

        ingested, skipped, failed = 0, 0, 0
        for i, chunk in enumerate(chunks):
            search_text = chunk.get("search_text", "")[:2000]
            chash = content_hash(search_text)

            if chash in existing:
                skipped += 1
                continue

            try:
                embedding = get_embedding(search_text)
                if not embedding:
                    failed += 1
                    continue

                # Auto-compute concept links
                from app.services.concept_links import compute_links
                st = chunk.get("search_text", "")
                ctype = chunk.get("content_type", "unknown")
                links = compute_links(st, ctype)

                kc = KnowledgeChunk(
                    content=json.dumps(chunk, ensure_ascii=False),
                    embedding=embedding,
                    source=source,
                    chunk_type=ctype,
                    links=json.dumps(links, ensure_ascii=False) if links else None,
                    league=league,
                    game_version=game_version,
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
    import argparse
    parser = argparse.ArgumentParser(description="Ingest JSONL chunks into knowledge_chunks")
    parser.add_argument("jsonl_path", nargs="?", default="/app/data/poe2db_chunks_v2.jsonl")
    parser.add_argument("--source", default="poe2db",
                        help="source tag: poe2db / pob / poe2wiki / homework")
    parser.add_argument("--league", default=None, help="league name (optional)")
    parser.add_argument("--game-version", default=None, help="game version (optional)")
    args = parser.parse_args()
    ingest(args.jsonl_path, source=args.source,
           league=args.league, game_version=args.game_version)
