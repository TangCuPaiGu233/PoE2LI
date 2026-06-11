"""Shared RecommendAgent factory for /recommend API and /chat skill."""

from __future__ import annotations

import asyncio
import os

from openai import OpenAI

from app.core.database import SessionLocal
from app.models.build import KnowledgeChunk
from app.services.embedding_service import get_embedding
from app.services.recommend_agent import RecommendAgent

try:
    from app.services.pob_service import decode_pob
except ImportError:
    decode_pob = None

_agent: RecommendAgent | None = None
_llm_client: OpenAI | None = None


def _get_llm() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"),
            api_key=os.getenv("LLM_API_KEY", ""),
        )
    return _llm_client


async def _embed_adapter(text: str) -> list[float]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_embedding, text)


async def _retrieve_adapter(vec: list[float], top_k: int = 5, filters: dict | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        dist = KnowledgeChunk.embedding.cosine_distance(vec).label("distance")
        q = db.query(KnowledgeChunk, dist).filter(
            KnowledgeChunk.embedding.isnot(None),
            KnowledgeChunk.source == "poe2db",
            KnowledgeChunk.stale == False,  # noqa: E712
        )
        if filters:
            if filters.get("chunk_type"):
                q = q.filter(KnowledgeChunk.chunk_type == filters["chunk_type"])
            if filters.get("league"):
                q = q.filter(KnowledgeChunk.league == filters["league"])
            if filters.get("game_version"):
                q = q.filter(KnowledgeChunk.game_version == filters["game_version"])
        rows = q.order_by(dist).limit(top_k).all()
        chunks = []
        for c, d in rows:
            sim = round(1.0 - d, 3) if d is not None else 0
            if sim > 0.3:
                chunks.append({"content": c.content, "chunk_type": c.chunk_type, "similarity": sim})
        return chunks
    finally:
        db.close()


async def _llm_adapter(messages: list[dict], **kw) -> str:
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


def get_recommend_agent() -> RecommendAgent:
    global _agent
    if _agent is None:
        _agent = RecommendAgent(
            embed_fn=_embed_adapter,
            retrieve_fn=_retrieve_adapter,
            llm_fn=_llm_adapter,
            decode_pob_fn=decode_pob,
        )
    return _agent


def format_recommend_markdown(result) -> str:
    """Format RecommendResult as chat-friendly markdown."""
    lines = [result.summary, ""]
    if not result.ranking:
        return result.summary

    lines.append("### 推荐排序")
    for i, item in enumerate(result.ranking[:5], 1):
        name = item.get("name", "?")
        score = item.get("fit_score", 0)
        verdict = item.get("verdict", "")
        synergy = item.get("synergy", "")
        lines.append(f"{i}. **{name}** — {score}分 ({verdict})")
        if synergy:
            lines.append(f"   - {synergy}")
        pros = item.get("pros") or []
        cons = item.get("cons") or []
        if pros:
            lines.append(f"   - 优点: {', '.join(pros[:3])}")
        if cons:
            lines.append(f"   - 缺点: {', '.join(cons[:2])}")

    if result.best_pick:
        lines.extend(["", f"**首选**: {result.best_pick}"])
    lines.extend(["", f"_{result.disclaimer}_"])
    return "\n".join(lines)
