"""API endpoints for PoE2 Trade search."""

import os
import logging
from typing import Literal
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from app.services.trade_agent import run_agent
from app.services.trade_stat_service import ingest_trade_stats, backfill_embeddings, get_ingest_stats, clear_trade_stats
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

# Track background ingestion state
_ingest_state = {"running": False, "result": None}


class TradeSearchRequest(BaseModel):
    """Natural language trade search request."""
    query: str = Field(..., min_length=2, description="自然语言搜索，如：'帮我找一条加2召唤兽等级的项链'")
    league: str | None = Field(None, description="赛季名称，留空则用市场默认")
    market: Literal["cn", "global"] = Field("cn", description="交易市场：国服/ 国际服")


class SearchMatch(BaseModel):
    """A single search result entry."""
    label: str = ""
    url: str | None = None
    count: int = 0
    reason: str = ""


class TradeSearchResponse(BaseModel):
    """Rich trade search result with best match + alternatives."""
    best_match: SearchMatch | None = None
    alternatives: list[SearchMatch] = []
    explanation: str = ""
    need_user_input: bool = False


@router.post("/api/trade/search", response_model=TradeSearchResponse)
async def trade_search_endpoint(req: TradeSearchRequest):
    """Parse natural language query and return PoE2 Trade search URL."""
    result = run_agent(req.query, req.league, req.market)
    return TradeSearchResponse(
        best_match=SearchMatch(**result["best_match"]) if result.get("best_match") else None,
        alternatives=[SearchMatch(**a) for a in result.get("alternatives", [])],
        explanation=result.get("explanation", ""),
        need_user_input=result.get("need_user_input", False),
    )


def _run_ingest_background(json_path: str):
    """Background task: ingest all trade stats with batch embedding."""
    _ingest_state["running"] = True
    _ingest_state["result"] = None
    db = SessionLocal()
    try:
        result = ingest_trade_stats(db, json_path)
        _ingest_state["result"] = result
        logger.info(f"Background ingestion complete: {result}")
    except Exception as e:
        logger.error(f"Background ingestion failed: {e}")
        _ingest_state["result"] = {"error": str(e)}
    finally:
        db.close()
        _ingest_state["running"] = False


@router.post("/api/trade/admin/ingest")
async def ingest_trade_stats_endpoint(background_tasks: BackgroundTasks):
    """Admin: Start ingesting trade stat dictionary into vector database.

    Runs in background — check progress with GET /api/trade/admin/ingest/status.
    """
    if _ingest_state["running"]:
        return {"status": "already_running", "message": "入库任务正在运行中"}

    json_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "trade_stats_condensed.json"),
        "/app/data/trade_stats_condensed.json",
    ]
    json_path = None
    for p in json_paths:
        if os.path.exists(p):
            json_path = p
            break

    if not json_path:
        return {"error": "trade_stats_condensed.json not found"}

    background_tasks.add_task(_run_ingest_background, json_path)
    return {
        "status": "started",
        "message": "入库任务已启动（后台运行），预计 1-2 分钟完成",
        "json_path": json_path,
    }


@router.get("/api/trade/admin/ingest/status")
async def ingest_status_endpoint():
    """Admin: Check ingestion progress."""
    return {
        "running": _ingest_state["running"],
        "result": _ingest_state["result"],
    }


@router.get("/api/trade/admin/stats")
async def trade_stats_endpoint():
    """Admin: Get trade stats ingestion status."""
    db = SessionLocal()
    try:
        return get_ingest_stats(db)
    finally:
        db.close()


@router.post("/api/trade/admin/backfill")
async def backfill_embeddings_endpoint():
    """Admin: Generate missing embeddings for trade stats."""
    db = SessionLocal()
    try:
        count = backfill_embeddings(db)
        return {"backfilled": count}
    finally:
        db.close()


@router.post("/api/trade/admin/reingest")
async def reingest_trade_stats_endpoint(background_tasks: BackgroundTasks):
    """Admin: Clear all trade stats and re-ingest from scratch.

    Use this when embedding format changes or stat dictionary updates.
    """
    if _ingest_state["running"]:
        return {"status": "already_running"}

    db = SessionLocal()
    try:
        cleared = clear_trade_stats(db)
    finally:
        db.close()

    # Also clear trade search cache
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        keys = r.keys("trade:*")
        if keys:
            r.delete(*keys)
            logger.info(f"Cleared {len(keys)} trade cache entries")
    except Exception:
        pass

    json_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "trade_stats_condensed.json"),
        "/app/data/trade_stats_condensed.json",
    ]
    json_path = None
    for p in json_paths:
        if os.path.exists(p):
            json_path = p
            break

    if not json_path:
        return {"error": "trade_stats_condensed.json not found"}

    background_tasks.add_task(_run_ingest_background, json_path)
    return {
        "status": "started",
        "cleared": cleared,
        "message": f"已清除 {cleared} 条旧数据，重新入库任务已启动",
    }
