"""Knowledge base management + RAG QA endpoints."""

import os, json, logging, re, time, hashlib
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db, SessionLocal
from app.models.build import Build, KnowledgeChunk
from app.services.knowledge_service import (
    ingest_build, bulk_ingest, mark_stale, clear_stale, get_stats,
)
from app.services.embedding_service import get_embedding
from app.core.game_context import POE2_SITE_RULE

from app.services.retrieval_pipeline import (
    RetrievalOptions,
    retrieve_knowledge,
    retrieve_dual_path,
    extract_alias_keywords,
    build_search_query,
    build_context,
    classify_question,
    default_league,
    default_game_version,
)

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
    league: str | None = Field(None, description="League filter for retrieval")
    game_version: str | None = Field(None, description="Game version filter for retrieval")


class AskResponse(BaseModel):
    answer: str
    sources: list[dict]


def _retrieve_knowledge(question: str, top_k: int = 5,
                        classify_text: str | None = None,
                        q_embedding: list[float] | None = None,
                        league: str | None = None,
                        game_version: str | None = None,
                        alias_keywords: list[str] | None = None,
                        expand_concepts: bool = True,
                        multi_source: bool = False) -> list[dict]:
    """Backward-compatible wrapper around unified retrieval pipeline."""
    result = retrieve_knowledge(
        question,
        RetrievalOptions(
            top_k=top_k,
            classify_text=classify_text,
            q_embedding=q_embedding,
            league=league or default_league(),
            game_version=game_version or default_game_version(),
            alias_keywords=alias_keywords or [],
            expand_concepts=expand_concepts,
            multi_source=multi_source,
        ),
    )
    return result.chunks


def _get_cache_key(question: str, top_k: int,
                   league: str | None = None, game_version: str | None = None) -> str:
    """Generate a stable cache key for a QA query."""
    raw = (
        f"qa:{question.strip().lower()}:{top_k}:"
        f"{league or ''}:{game_version or ''}"
    )
    return f"qa_cache:{hashlib.md5(raw.encode()).hexdigest()[:16]}"


@qa_router.post("/api/knowledge/ask", response_model=AskResponse)
async def ask_question(req: AskRequest):
    """RAG QA: answer PoE2 questions using poe2db knowledge base."""
    import time
    t_start = time.time()

    league = req.league or default_league()
    game_version = req.game_version or default_game_version()

    # Redis cache check
    cache_key = _get_cache_key(req.question, req.top_k, league, game_version)
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        cached = r.get(cache_key)
        if cached:
            data = json.loads(cached)
            logger.info(f"QA cache hit for '{req.question[:50]}' ({(time.time()-t_start)*1000:.0f}ms)")
            return AskResponse(**data)
    except Exception:
        pass  # Redis unavailable, continue without cache

    # Entity resolution + unified retrieval (reverse lookup + concept expansion)
    alias_keywords, resolved_entities = extract_alias_keywords(req.question)
    search_query = build_search_query(req.question, alias_keywords=alias_keywords)
    retrieval = retrieve_knowledge(
        search_query,
        RetrievalOptions(
            top_k=req.top_k,
            classify_text=req.question,
            league=league,
            game_version=game_version,
            alias_keywords=alias_keywords,
            expand_concepts=True,
            max_concept_chunks=6,
        ),
    )
    chunks = retrieval.chunks

    if resolved_entities:
        db_lookup = SessionLocal()
        try:
            from app.services.retrieval_pipeline import structured_entity_lookup
            direct_chunks = structured_entity_lookup(
                db_lookup, resolved_entities, league=league, game_version=game_version,
            )
            if direct_chunks:
                existing = {c.get("content", "")[:100] for c in chunks}
                for dc in direct_chunks:
                    if dc["content"][:100] not in existing:
                        chunks = [dc] + chunks
        finally:
            db_lookup.close()

    if not chunks:
        return AskResponse(
            answer="未找到相关知识。poe2db 知识库中暂无与此问题匹配的内容。",
            sources=[],
        )

    context = build_context(chunks)
    intent_hint = ""
    if retrieval.intent == "reverse_lookup":
        concepts = ", ".join(retrieval.matched_concepts) or "相关效果"
        intent_hint = f"\n用户在进行反向查询（通过效果找装备/词缀）。已识别效果概念：{concepts}。请列出能提供该效果的装备类型、词缀或技能，并说明出处。\n"

    # Ask LLM to answer
    llm_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")

    from openai import OpenAI
    client = OpenAI(base_url=llm_url, api_key=llm_key)

    sys_prompt = f"""{POE2_SITE_RULE}

你是流放之路2 (Path of Exile 2) 知识助手。基于以下来自 poe2db 百科的数据回答用户问题。
{intent_hint}
规则：
- 只基于提供的资料回答，不要编造
- 如果资料不足以回答，明确说明
- 回答尽量简洁准确
- 如果资料包含中文和英文，优先用中文回答
- 若资料包含关联概念（via_link / 关联），请一并解释相关术语定义

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

    response = AskResponse(answer=answer, sources=sources)

    # Cache in Redis (1 hour TTL)
    try:
        from app.core.redis_client import get_redis
        r2 = get_redis()
        r2.setex(cache_key, 3600, json.dumps(response.model_dump(), ensure_ascii=False))
        logger.info(f"QA cached: '{req.question[:50]}' ({(time.time()-t_start)*1000:.0f}ms total)")
    except Exception:
        pass

    return response


# ── SSE Streaming Chat endpoint ──

class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role":"user"/"assistant","content":"..."}]
    stream: bool = True




def _conversation_snippet(messages: list[dict], max_turns: int = 4) -> str:
    """Recent turns (excluding current user message) for follow-up context."""
    if not messages or len(messages) <= 1:
        return ""
    prior = messages[:-1][-max_turns:]
    parts: list[str] = []
    for m in prior:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = m.get("role", "user")
        label = "\u7528\u6237" if role == "user" else "\u52a9\u624b"
        parts.append(f"{label}: {content[:500]}")
    return "\n".join(parts)


def _parse_keyword_lines(raw: str) -> list[str]:
    keywords: list[str] = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*\u2022\d]+[\.\)\:\s]+", "", line).strip()
        line = re.sub(r"^[\-\*\u2022]+\s*", "", line).strip()
        if line:
            keywords.append(line)
    return keywords[:5]


def _generate_search_keywords(
    llm_client,
    user_msg: str,
    messages: list[dict],
    alias_keywords: list[str],
    timeout_s: float = 12.0,
) -> list[str]:
    fallback = [user_msg, *(alias_keywords or [])][:5]
    context = _conversation_snippet(messages, max_turns=4)
    plan_prompt = (
        "\u7528\u6237\u95ee\u4e86 Path of Exile 2 \u76f8\u5173\u95ee\u9898\u3002\u5217\u51fa 3-5 \u4e2a\u82f1\u6587\u68c0\u7d22\u5173\u952e\u8bcd\uff0c\u4e00\u884c\u4e00\u4e2a\uff0c\u4e0d\u8981\u5176\u4ed6\u6587\u5b57\u3002\n"
    )
    if context:
        plan_prompt += f"\n\u8fd1\u671f\u5bf9\u8bdd:\n{context}\n"
    plan_prompt += f"\n\u5f53\u524d\u95ee\u9898: {user_msg}"

    t0 = time.time()
    try:
        resp = llm_client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            messages=[{"role": "user", "content": plan_prompt}],
            temperature=0.1,
            max_tokens=200,
            timeout=timeout_s,
        )
        raw = (resp.choices[0].message.content or "").strip()
        search_keywords = _parse_keyword_lines(raw)
        if not search_keywords:
            search_keywords = fallback
        elapsed = time.time() - t0
        logger.info(
            "[CHAT] keyword_plan ok in %.2fs: %s",
            elapsed,
            search_keywords[:5],
        )
        return search_keywords
    except Exception as e:
        elapsed = time.time() - t0
        logger.warning(
            "[CHAT] keyword_plan failed in %.2fs (%s), fallback=%s",
            elapsed,
            e,
            fallback[:5],
        )
        return fallback




def _rewrite_standalone_question(
    llm_client,
    user_msg: str,
    messages: list[dict],
    alias_keywords: list[str] | None = None,
    timeout_s: float = 12.0,
) -> str:
    """Rewrite the current question as a self-contained English search sentence."""
    context = _conversation_snippet(messages, max_turns=2)
    prompt = (
        "Rewrite the user's CURRENT Path of Exile 2 question as one self-contained "
        "English encyclopedia search sentence. Output exactly one line, no bullets.\n"
        "Keep official EN item/skill names from the Resolved entities line; do not invent literal translations of Chinese names.\n"
    )
    if alias_keywords:
        prompt += "\nResolved entities (use these EN names): " + ", ".join(alias_keywords[:8]) + "\n"
    if context:
        prompt += f"\nRecent conversation:\n{context}\n"
    prompt += f"\nCurrent question: {user_msg}"

    t0 = time.time()
    try:
        resp = llm_client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=120,
            timeout=timeout_s,
        )
        raw = (resp.choices[0].message.content or "").strip()
        rewrite = raw.split("\n")[0].strip()
        rewrite = re.sub(r'^["\']|["\']$', "", rewrite).strip()
        if rewrite:
            logger.info("[CHAT] rewrite ok in %.2fs: %s", time.time() - t0, rewrite[:120])
            return rewrite
    except Exception as e:
        logger.warning("[CHAT] rewrite failed in %.2fs (%s)", time.time() - t0, e)
    return user_msg


async def _stream_chat(messages: list[dict]):
    """AI-first agent runtime (ClawCode-style ReAct + tool registry)."""
    from app.services.chat_agent import stream_chat_agent

    user_msg = messages[-1]["content"] if messages else ""
    logger.info("[CHAT] agent_runtime | query=%s", user_msg[:120])

    async for event in stream_chat_agent(messages):
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@qa_router.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Multi-turn SSE streaming chat."""
    return StreamingResponse(
        _stream_chat(req.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
