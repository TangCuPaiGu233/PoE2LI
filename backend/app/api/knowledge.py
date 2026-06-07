"""Admin endpoints for knowledge base management (RAG)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.build import Build
from app.services.knowledge_service import (
    ingest_build,
    bulk_ingest,
    mark_stale,
    clear_stale,
    get_stats,
)

router = APIRouter(prefix="/api/admin/knowledge", tags=["knowledge"])


# ── Request / Response schemas ──


class IngestBuildRequest(BaseModel):
    build_id: int = Field(..., description="ID of the build to ingest into knowledge base")


class IngestBuildResponse(BaseModel):
    build_id: int
    chunks_created: int
    message: str


class BulkIngestResponse(BaseModel):
    ingested_builds: int
    total_chunks: int
    message: str


class MarkStaleRequest(BaseModel):
    league: str | None = Field(None, description="League name to mark as stale")
    game_version: str | None = Field(None, description="Game version to mark as stale")


class MarkStaleResponse(BaseModel):
    chunks_marked: int
    message: str


class KnowledgeStatsResponse(BaseModel):
    total_chunks: int
    active_chunks: int
    stale_chunks: int
    without_embedding: int
    builds_with_chunks: int


# ── Endpoints ──


@router.post("/ingest/{build_id}", response_model=IngestBuildResponse)
async def ingest_single_build(build_id: int, db: Session = Depends(get_db)):
    """Ingest a single build's homework into the knowledge base."""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    if build.status != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Build status is '{build.status}', must be 'done' to ingest.",
        )

    n = ingest_build(db, build)
    return IngestBuildResponse(
        build_id=build_id,
        chunks_created=n,
        message=f"Created {n} knowledge chunks." if n > 0 else "Already ingested or no homework.",
    )


@router.post("/ingest-all", response_model=BulkIngestResponse)
async def ingest_all_builds(db: Session = Depends(get_db)):
    """Bulk ingest all builds with completed homework into the knowledge base.

    Idempotent — builds that already have chunks are skipped.
    """
    result = bulk_ingest(db)
    return BulkIngestResponse(
        **result,
        message=f"Ingested {result['ingested_builds']} builds, {result['total_chunks']} chunks total.",
    )


@router.post("/mark-stale", response_model=MarkStaleResponse)
async def mark_chunks_stale(req: MarkStaleRequest, db: Session = Depends(get_db)):
    """Mark knowledge chunks as stale (e.g. when a new league starts).

    Stale chunks are excluded from RAG retrieval but not deleted.
    Provide league and/or game_version to target specific chunks.
    If neither is provided, ALL chunks are marked stale.
    """
    count = mark_stale(db, league=req.league, game_version=req.game_version)
    return MarkStaleResponse(
        chunks_marked=count,
        message=f"Marked {count} chunks as stale.",
    )


@router.post("/clear-stale", response_model=MarkStaleResponse)
async def clear_all_stale(db: Session = Depends(get_db)):
    """Remove the stale flag from all chunks (admin operation)."""
    count = clear_stale(db)
    return MarkStaleResponse(
        chunks_marked=count,
        message=f"Cleared stale flag on {count} chunks.",
    )


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def knowledge_stats(db: Session = Depends(get_db)):
    """Get knowledge base statistics."""
    return KnowledgeStatsResponse(**get_stats(db))
