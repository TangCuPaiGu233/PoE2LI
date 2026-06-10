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

# 接入时按工程真实路径调整
# from app.services.recommend_agent import RecommendAgent
# from app.services.embedding_service import embed_text
# from app.services.knowledge_service import retrieve_similar
# from app.services.ai_service import chat_completion
# from app.services.pob_decoder import decode as decode_pob
# from app.core.cache import redis_client

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


# ─────────────────────── 依赖装配 ───────────────────────
def _build_agent():
    """组装 RecommendAgent，注入现有服务函数。接入时解除注释。"""
    # return RecommendAgent(
    #     embed_fn=embed_text,
    #     retrieve_fn=retrieve_similar,
    #     llm_fn=chat_completion,
    #     decode_pob_fn=decode_pob,
    # )
    raise NotImplementedError("接线现有服务后启用")


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
