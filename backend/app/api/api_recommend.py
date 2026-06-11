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

from app.services.recommend_runtime import get_recommend_agent, _get_llm
from app.core.redis_client import get_redis

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


import os

def _cache_key(req: RecommendRequest) -> str:
    payload = json.dumps(req.model_dump(), ensure_ascii=False, sort_keys=True)
    return "rec:" + hashlib.md5(payload.encode()).hexdigest()


# ─────────────────────── 接口 ───────────────────────
@router.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest):
    has_cand = bool(req.candidates or req.page_candidates)
    intent = route_intent(req.question, has_cand)

    if intent == "encyclopedia":
        from app.services.retrieval_pipeline import (
            RetrievalOptions,
            retrieve_knowledge,
            extract_alias_keywords,
            build_search_query,
            build_context,
            default_league,
            default_game_version,
        )
        import os as _os

        league = req.league or default_league()
        game_version = req.game_version or default_game_version()
        alias_keywords, _ = extract_alias_keywords(req.question)
        search_query = build_search_query(req.question, alias_keywords=alias_keywords)
        result = retrieve_knowledge(
            search_query,
            RetrievalOptions(
                top_k=5,
                classify_text=req.question,
                league=league,
                game_version=game_version,
                alias_keywords=alias_keywords,
                expand_concepts=True,
            ),
        )
        chunks = result.chunks
        if not chunks:
            return RecommendResponse(
                intent="encyclopedia", resolved={"source": "rag"},
                ranking=[], best_pick=None,
                summary="未找到相关知识。",
                disclaimer="基于 poe2db 当前赛季数据。",
            )

        context = build_context(chunks)

        client = _get_llm()
        resp = client.chat.completions.create(
            model=_os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            messages=[
                {"role": "system", "content": f"你是流放之路2知识助手。基于以下资料回答问题。\n\n资料：\n{context}"},
                {"role": "user", "content": req.question},
            ],
            temperature=0.3, max_tokens=1024,
        )
        answer = resp.choices[0].message.content.strip()

        return RecommendResponse(
            intent="encyclopedia", resolved={"source": "rag"},
            ranking=[], best_pick=None,
            summary=answer,
            disclaimer="基于 poe2db 当前赛季数据。",
        )

    # Redis 缓存（复用现有 redis_client）
    # key = _cache_key(req)
    # if (cached := await redis_client.get(key)):
    #     data = json.loads(cached)
    #     data["cached"] = True
    #     return RecommendResponse(**data)

    agent = get_recommend_agent()
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
