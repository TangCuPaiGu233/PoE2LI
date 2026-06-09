"""api/recommend.py — 推荐问答接口。

挂载到现有 FastAPI app：
    from app.api.recommend import router as recommend_router
    app.include_router(recommend_router)

意图路由放在这里：先判 recommend vs encyclopedia，
recommend 走 RecommendAgent，其余回退到现有 /api/knowledge/ask。
"""
from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.recommend_agent import RecommendAgent
from app.services.embedding_service import get_embedding
from app.services.knowledge_service import retrieve_similar
from app.core.database import SessionLocal
from app.core.redis_client import get_redis
# PoB decoder optional
try:
    from app.services.pob_service import decode_pob
except ImportError:
    decode_pob = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/knowledge", tags=["recommend"])

# 推荐意图触发词（命中即走 Agent，否则回退百科）
_RECOMMEND_TRIGGERS = [
    "哪个最适合", "哪个好", "推荐", "选哪个", "哪个更", "对比",
    "适不适合", "值不值得", "该用", "用哪", "比较",
]


# ─────────────────────── Schema ───────────────────────
class RecommendRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    pob_code: str | None = None
    candidates: list[str] | None = None        # 用户显式指定
    page_candidates: list[str] | None = None    # 页面上下文带入
    league: str | None = None
    game_version: str | None = None


class SourceRef(BaseModel):
    chunk_type: str | None = None
    similarity: float | None = None


class RankItem(BaseModel):
    name: str
    fit_score: int = Field(ge=0, le=100)
    pros: list[str] = []
    cons: list[str] = []
    synergy: str = ""
    verdict: str
    sources: list[SourceRef] = []


class RecommendResponse(BaseModel):
    intent: str
    resolved: dict
    ranking: list[RankItem]
    best_pick: str | None
    summary: str
    disclaimer: str
    cached: bool = False


# ─────────────────────── 意图路由 ───────────────────────
def route_intent(question: str, has_candidates: bool) -> str:
    """返回 'recommend' 或 'encyclopedia'。"""
    if has_candidates:
        return "recommend"
    if any(t in question for t in _RECOMMEND_TRIGGERS):
        return "recommend"
    return "encyclopedia"


# ─────────────────────── Adapter functions ───────────────────────
import os
import asyncio
from openai import OpenAI

_llm_client = None

def _get_llm():
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"),
            api_key=os.getenv("LLM_API_KEY", ""),
        )
    return _llm_client


async def _embed_adapter(text: str) -> list[float]:
    """Async wrapper around sync get_embedding."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_embedding, text)


async def _retrieve_adapter(vec: list[float], top_k: int = 5, filters: dict | None = None) -> list[dict]:
    """Adapter: vector + filters → knowledge chunks."""
    # Build a search query from the vector context
    # Since retrieve_similar needs a text query, we do a direct vector search
    db = SessionLocal()
    try:
        from sqlalchemy import func
        from app.models.build import KnowledgeChunk
        import json as _json

        dist = KnowledgeChunk.embedding.cosine_distance(vec).label("distance")
        q = db.query(KnowledgeChunk, dist).filter(
            KnowledgeChunk.embedding != None,
            KnowledgeChunk.source == "poe2db",
            KnowledgeChunk.stale == False,
        )
        if filters:
            if filters.get("chunk_type"):
                q = q.filter(KnowledgeChunk.chunk_type == filters["chunk_type"])
            if filters.get("league"):
                q = q.filter(KnowledgeChunk.league == filters["league"])
            if filters.get("game_version"):
                q = q.filter(KnowledgeChunk.game_version == filters["game_version"])
        q = q.order_by(dist).limit(top_k)
        rows = q.all()
        chunks = []
        for c, d in rows:
            sim = round(1.0 - d, 3) if d is not None else 0
            if sim > 0.3:
                chunks.append({"content": c.content, "chunk_type": c.chunk_type, "similarity": sim})
        return chunks
    finally:
        db.close()


async def _llm_adapter(messages: list[dict], **kw) -> str:
    """Async LLM call adapter."""
    loop = asyncio.get_running_loop()
    def _call():
        client = _get_llm()
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            messages=messages,
            temperature=kw.get("temperature", 0.3),
            max_tokens=kw.get("max_tokens", 1024),
        )
        return resp.choices[0].message.content.strip()
    return await loop.run_in_executor(None, _call)


# ─────────────────────── Agent singleton ───────────────────────

_agent = None

def _build_agent():
    global _agent
    if _agent is None:
        _agent = RecommendAgent(
            embed_fn=_embed_adapter,
            retrieve_fn=_retrieve_adapter,
            llm_fn=_llm_adapter,
            decode_pob_fn=decode_pob,
        )
    return _agent


def _cache_key(req: RecommendRequest) -> str:
    payload = json.dumps(req.model_dump(), ensure_ascii=False, sort_keys=True)
    return "rec:" + hashlib.md5(payload.encode()).hexdigest()


# ─────────────────────── 接口 ───────────────────────
@router.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest):
    has_cand = bool(req.candidates or req.page_candidates)
    intent = route_intent(req.question, has_cand)

    if intent == "encyclopedia":
        # 非推荐问题 → 提示走现有 /ask（或在此内部转发）
        raise HTTPException(
            status_code=400,
            detail="该问题更像百科查询，请使用 /api/knowledge/ask 接口。",
        )

    # Redis 缓存（复用现有 redis_client）
    # key = _cache_key(req)
    # if (cached := await redis_client.get(key)):
    #     data = json.loads(cached)
    #     data["cached"] = True
    #     return RecommendResponse(**data)

    agent = _build_agent()
    try:
        result = await agent.run(
            question=req.question,
            pob_code=req.pob_code,
            candidates=req.candidates,
            page_candidates=req.page_candidates,
            league=req.league,
            game_version=req.game_version,
        )
    except Exception as e:  # noqa
        logger.exception("recommend failed")
        raise HTTPException(status_code=500, detail=f"推荐失败：{e}")

    resp = RecommendResponse(
        intent=result.intent,
        resolved=result.resolved,
        ranking=result.ranking,        # pydantic 会校验每项 schema
        best_pick=result.best_pick,
        summary=result.summary,
        disclaimer=result.disclaimer,
    )
    # await redis_client.setex(key, 3600, resp.model_dump_json())
    return resp
