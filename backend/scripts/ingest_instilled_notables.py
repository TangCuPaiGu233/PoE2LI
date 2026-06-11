"""Ingest Instilled Notables from poe2wiki into knowledge_chunks."""

import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.concept_links import compute_links
from app.services.embedding_service import get_embedding
from app.services.knowledge_graph_service import graph_available, sync_chunk_graph
from scripts.ingest_poe2db import content_hash
from scripts.wiki_instilled import scrape_instilled_notables


def build_chunks() -> list[dict]:
    rows = scrape_instilled_notables()
    chunks: list[dict] = []
    for name, effect in rows:
        search_text = f"Instilled Notable: {name}\n{name}\n{effect}".strip()
        chunks.append({
            "search_text": search_text,
            "content_type": "mechanic",
            "name_en": name,
            "effect": effect,
            "source_page": "Instilling",
        })
    return chunks


def ingest(league: str | None = None, game_version: str | None = None) -> None:
    chunks = build_chunks()
    logger.info("Scraped %d instilled notables", len(chunks))
    db = SessionLocal()
    source = "poe2wiki"
    try:
        existing = set()
        for (content,) in db.query(KnowledgeChunk.content).filter(
            KnowledgeChunk.source == source,
            KnowledgeChunk.chunk_type == "mechanic",
        ).all():
            try:
                existing.add(content_hash(json.loads(content).get("search_text", "")[:2000]))
            except Exception:
                existing.add(content_hash(content[:2000]))

        ingested = skipped = failed = 0
        for chunk in chunks:
            search_text = chunk.get("search_text", "")[:2000]
            chash = content_hash(search_text)
            if chash in existing:
                skipped += 1
                continue
            embedding = get_embedding(search_text)
            if not embedding:
                failed += 1
                continue
            links = compute_links(search_text, "mechanic")
            kc = KnowledgeChunk(
                content=json.dumps(chunk, ensure_ascii=False),
                embedding=embedding,
                source=source,
                chunk_type="mechanic",
                links=json.dumps(links, ensure_ascii=False) if links else None,
                league=league,
                game_version=game_version,
            )
            db.add(kc)
            db.flush()
            try:
                if graph_available(db):
                    sync_chunk_graph(db, kc)
            except Exception:
                pass
            existing.add(chash)
            ingested += 1
        db.commit()
        logger.info("Done: %d added, %d skipped, %d failed", ingested, skipped, failed)
    finally:
        db.close()


if __name__ == "__main__":
    ingest()
