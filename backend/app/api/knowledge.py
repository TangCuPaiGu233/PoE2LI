"""Knowledge base management + RAG QA endpoints."""

import os, json, logging, re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db, SessionLocal
from app.models.build import Build, KnowledgeChunk
from app.services.knowledge_service import (
    ingest_build, bulk_ingest, mark_stale, clear_stale, get_stats,
)
from app.services.embedding_service import get_embedding

logger = logging.getLogger(__name__)

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


# ── Public RAG QA endpoint ──

qa_router = APIRouter(tags=["qa"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Question about PoE2 mechanics")
    top_k: int = Field(5, ge=1, le=10, description="Number of knowledge chunks to retrieve")


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]


def _retrieve_knowledge(question: str, top_k: int = 5) -> list[dict]:
    """Retrieve relevant knowledge chunks using vector similarity."""
    db = SessionLocal()
    try:
        q_embedding = get_embedding(question)
        if not q_embedding:
            return []

        db_url = str(db.get_bind().url)
        is_sqlite = db_url.startswith("sqlite")

        if is_sqlite:
            # In-memory cosine similarity
            chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.embedding != None,  # noqa: E711
                KnowledgeChunk.source == "poe2db",
                KnowledgeChunk.stale == False,  # noqa: E712
            ).all()
            scored = []
            for c in chunks:
                emb = c.embedding
                if isinstance(emb, str):
                    emb = json.loads(emb)
                sim = _cosine_sim(q_embedding, emb)
                scored.append((sim, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [{"content": c.content, "chunk_type": c.chunk_type, "similarity": round(s, 3)}
                    for s, c in scored[:top_k] if s > 0.3]
        else:
            # pgvector
            dist = KnowledgeChunk.embedding.cosine_distance(q_embedding).label("distance")
            rows = (
                db.query(KnowledgeChunk, dist)
                .filter(
                    KnowledgeChunk.embedding != None,  # noqa: E711
                    KnowledgeChunk.source == "poe2db",
                    KnowledgeChunk.stale == False,  # noqa: E712
                )
                .order_by(dist)
                .limit(top_k)
                .all()
            )
            return [
                {"content": c.content, "chunk_type": c.chunk_type, "similarity": round(1.0 - d, 3)}
                for c, d in rows if (1.0 - d) > 0.3
            ]
    finally:
        db.close()


def _cosine_sim(a, b):
    if not a or not b:
        return 0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0


@qa_router.post("/api/knowledge/ask", response_model=AskResponse)
async def ask_question(req: AskRequest):
    """RAG QA: answer PoE2 questions using poe2db knowledge base."""
    # Retrieve relevant chunks
    chunks = _retrieve_knowledge(req.question, req.top_k)
    if not chunks:
        return AskResponse(
            answer="未找到相关知识。poe2db 知识库中暂无与此问题匹配的内容。",
            sources=[],
        )

    # Build context from retrieved chunks
    context_parts = []
    for i, c in enumerate(chunks):
        try:
            data = json.loads(c["content"])
            search = data.get("search_text", "")[:800]
        except Exception:
            search = c["content"][:800]
        context_parts.append(f"[{i+1}] {search}")

    context = "\n\n".join(context_parts)

    # Ask LLM to answer
    llm_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

    from openai import OpenAI
    client = OpenAI(base_url=llm_url, api_key=llm_key)

    sys_prompt = f"""你是流放之路2 (Path of Exile 2) 知识助手。基于以下来自 poe2db 百科的数据回答用户问题。

规则：
-只基于提供的资料回答，不要编造
- 如果资料不足以回答，明确说明
- 回答尽量简洁准确
- 如果资料包含中文和英文，优先用中文回答

参考资料：
{context}"""

    try:
        resp = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": req.question},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"LLM QA failed: {e}")
        answer = f"回答生成失败: {e}"

    # Build source list
    sources = [
        {"type": c["chunk_type"], "similarity": c["similarity"], "preview": c["content"][:100]}
        for c in chunks[:3]
    ]

    return AskResponse(answer=answer, sources=sources)
