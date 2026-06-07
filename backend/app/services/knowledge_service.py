"""Knowledge service — chunking, ingestion, and vector retrieval.

Turns build data + homework into structured knowledge chunks, stores them with
embeddings in the `knowledge_chunks` table, and provides vector similarity search
for RAG-enhanced Q&A.

Supports both PostgreSQL (pgvector cosine distance) and SQLite (in-memory cosine similarity).
"""

import logging
import json
from sqlalchemy.orm import Session

from app.models.build import KnowledgeChunk, Build
from app.services.embedding_service import get_embedding

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  Chunking
# ──────────────────────────────────────────────

def chunk_build_and_homework(build: Build, homework: dict) -> list[dict]:
    """Split build data + homework into semantically meaningful knowledge chunks.

    Each chunk is a self-contained text block suitable for embedding and retrieval.
    Returns a list of {"content": str, "chunk_type": str} dicts.
    """
    build_data = build.get_build_data()
    chunks = []

    # ── Build summary (always created) ──
    summary_parts = [
        f"[BD概要] {build.class_name or '未知'}",
    ]
    if build.ascendancy:
        summary_parts[0] += f" / {build.ascendancy}"
    if build.level:
        summary_parts[0] += f" Lv{build.level}"

    stats = build_data.get("playerStats", {})
    stat_line = []
    for label, key in [("生命", "Life"), ("DPS", "TotalDPS"), ("EHP", "TotalEHP")]:
        val = stats.get(key)
        if val:
            stat_line.append(f"{label}={val}")
    if stat_line:
        summary_parts.append(" | ".join(stat_line))

    # Skills
    skills = []
    for ss in build_data.get("skillSets", []):
        for g in ss.get("gems", []):
            if g.get("nameSpec") and g.get("enabled"):
                name = g["nameSpec"]
                lvl = g.get("level", "")
                skills.append(f"{name}(Lv{lvl})" if lvl else name)
    if skills:
        summary_parts.append(f"技能: {', '.join(list(dict.fromkeys(skills)))}")  # dedupe, keep order

    chunks.append({
        "content": "\n".join(summary_parts),
        "chunk_type": "build_summary",
    })

    # ── Homework sections ──
    section_meta = {
        "core_idea": ("核心思路", "💡"),
        "core_items": ("核心装备", "🛡️"),
        "budget_alternatives": ("平价替代", "💰"),
        "talent_highlights": ("天赋亮点", "🌳"),
        "strength_review": ("强度评估", "📊"),
    }

    for key, (label, icon) in section_meta.items():
        text = homework.get(key, "")
        if text and text != f"AI 未生成 {key} 内容":
            header = f"[{label}] {build.class_name or ''} {build.ascendancy or ''}".strip()
            chunks.append({
                "content": f"{icon} {header}\n{text}",
                "chunk_type": key,
            })

    return chunks


# ──────────────────────────────────────────────
#  Ingestion
# ──────────────────────────────────────────────

def ingest_build(db: Session, build: Build, homework: dict | None = None) -> int:
    """Chunk a build + homework, generate embeddings, and store in knowledge_chunks.

    Returns the number of new chunks ingested.
    Skips if chunks already exist for this build (idempotent).
    """
    if homework is None:
        homework = build.get_homework()
    if not homework:
        logger.warning(f"Build {build.id} has no homework, skipping ingestion.")
        return 0

    # Deduplicate: skip if already ingested
    existing = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.build_id == build.id
    ).count()
    if existing > 0:
        logger.info(f"Build {build.id} already has {existing} chunks, skipping.")
        return 0

    # Create chunks
    text_chunks = chunk_build_and_homework(build, homework)
    count = 0

    for chunk_info in text_chunks:
        embedding = get_embedding(chunk_info["content"])
        kc = KnowledgeChunk(
            content=chunk_info["content"],
            embedding=embedding,
            build_id=build.id,
            league=build.league,
            game_version=build.game_version,
            source="homework",
            chunk_type=chunk_info.get("chunk_type", ""),
        )
        db.add(kc)
        count += 1

    db.commit()
    logger.info(f"Ingested {count} chunks for build {build.id}")
    return count


def bulk_ingest(db: Session, league: str | None = None) -> dict:
    """Ingest all done builds that don't have knowledge chunks yet.

    Returns a summary dict with counts.
    """
    builds = db.query(Build).filter(Build.status == "done").all()
    ingested_builds = 0
    total_chunks = 0

    for build in builds:
        n = ingest_build(db, build)
        if n > 0:
            ingested_builds += 1
            total_chunks += n

    logger.info(f"Bulk ingest: {ingested_builds} builds, {total_chunks} chunks total")
    return {"ingested_builds": ingested_builds, "total_chunks": total_chunks}


# ──────────────────────────────────────────────
#  Retrieval
# ──────────────────────────────────────────────

def retrieve_similar(
    db: Session,
    query: str,
    league: str | None = None,
    game_version: str | None = None,
    top_k: int = 5,
    exclude_build_id: int | None = None,
) -> list[dict]:
    """Retrieve the most relevant knowledge chunks for a query using vector similarity.

    Uses pgvector cosine distance on PostgreSQL, or in-memory cosine similarity on SQLite.
    Filters out stale chunks and optionally filters by league/game_version.
    Returns a list of {"content": str, "similarity": float, "build_id": int, "source": str} dicts.
    """
    query_embedding = get_embedding(query)
    if not query_embedding:
        logger.warning("Failed to generate query embedding, returning empty results.")
        return []

    # Determine DB type
    db_url = str(db.get_bind().url)
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        return _retrieve_sqlite(
            db, query_embedding, league, game_version,
            top_k, exclude_build_id,
        )
    else:
        return _retrieve_postgres(
            db, query_embedding, league, game_version,
            top_k, exclude_build_id,
        )


def _retrieve_postgres(
    db: Session,
    query_embedding: list[float],
    league: str | None,
    game_version: str | None,
    top_k: int,
    exclude_build_id: int | None,
) -> list[dict]:
    """pgvector cosine distance retrieval on PostgreSQL."""
    # pgvector >= 0.3: cosine_distance is a method on the Vector column
    distance_col = KnowledgeChunk.embedding.cosine_distance(query_embedding).label("distance")

    query = db.query(KnowledgeChunk, distance_col).filter(
        KnowledgeChunk.stale == False,  # noqa: E712
    )

    if league:
        query = query.filter(KnowledgeChunk.league == league)
    if game_version:
        query = query.filter(KnowledgeChunk.game_version == game_version)
    if exclude_build_id is not None:
        query = query.filter(KnowledgeChunk.build_id != exclude_build_id)

    # Order by cosine similarity (ascending distance = most similar first)
    query = query.order_by(distance_col).limit(top_k)

    results = []
    for chunk, distance in query.all():
        results.append({
            "content": chunk.content,
            "build_id": chunk.build_id,
            "source": chunk.source,
            "chunk_type": chunk.chunk_type,
            # cosine_distance returns 0..2; similarity = 1 - distance
            "similarity": round(1.0 - distance, 4) if distance is not None else None,
        })
    return results


def _retrieve_sqlite(
    db: Session,
    query_embedding: list[float],
    league: str | None,
    game_version: str | None,
    top_k: int,
    exclude_build_id: int | None,
) -> list[dict]:
    """In-memory cosine similarity retrieval for SQLite (dev/test)."""
    query = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.stale == False,  # noqa: E712
    )

    if league:
        query = query.filter(KnowledgeChunk.league == league)
    if game_version:
        query = query.filter(KnowledgeChunk.game_version == game_version)
    if exclude_build_id is not None:
        query = query.filter(KnowledgeChunk.build_id != exclude_build_id)

    chunks = query.all()
    scored = []

    for chunk in chunks:
        if chunk.embedding:
            emb = chunk.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            sim = _cosine_similarity(query_embedding, emb)
            scored.append({
                "content": chunk.content,
                "build_id": chunk.build_id,
                "source": chunk.source,
                "chunk_type": chunk.chunk_type,
                "similarity": round(sim, 4),
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


# ──────────────────────────────────────────────
#  Staleness Management
# ──────────────────────────────────────────────

def mark_stale(
    db: Session,
    league: str | None = None,
    game_version: str | None = None,
) -> int:
    """Mark knowledge chunks as stale based on league and game version.

    Call this when a new league starts or game version changes to prevent
    outdated information from polluting RAG results.
    """
    filters = []
    if league:
        filters.append(KnowledgeChunk.league == league)
    if game_version:
        filters.append(KnowledgeChunk.game_version == game_version)

    if not filters:
        count = db.query(KnowledgeChunk).update({"stale": True})
    else:
        q = db.query(KnowledgeChunk).filter(*filters)
        count = q.update({"stale": True})

    db.commit()
    logger.info(f"Marked {count} chunks as stale (league={league}, version={game_version})")
    return count


def clear_stale(db: Session) -> int:
    """Remove the stale flag from all chunks (admin operation)."""
    count = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.stale == True,  # noqa: E712
    ).update({"stale": False})
    db.commit()
    logger.info(f"Cleared stale flag on {count} chunks")
    return count


# ──────────────────────────────────────────────
#  Stats
# ──────────────────────────────────────────────

def get_stats(db: Session) -> dict:
    """Get knowledge base statistics."""
    total = db.query(KnowledgeChunk).count()
    active = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.stale == False,  # noqa: E712
    ).count()
    stale = total - active
    without_embedding = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.embedding == None,  # noqa: E711
    ).count()

    # Builds with chunks
    builds_with_chunks = db.query(
        KnowledgeChunk.build_id
    ).distinct().count()

    return {
        "total_chunks": total,
        "active_chunks": active,
        "stale_chunks": stale,
        "without_embedding": without_embedding,
        "builds_with_chunks": builds_with_chunks,
    }


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b:
        return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
    except Exception:
        return 0.0
