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


def _classify_intent(question: str) -> str:
    """Classify user intent to route retrieval."""
    q = question.lower()
    bd_keywords = ['bd', 'build', '构建', '配装', '开荒', '转型', '升级', '加点',
                    '天赋怎么点', '技能搭配', '装备搭配', '怎么玩', '设计', '配一套',
                    '给我配', '帮我配', '怎么做', '玩法', 'builds', '攻略']
    recommend_keywords = ['推荐', '哪个好', '选哪个', '对比', '更适合', '最好']
    trade_keywords = ['搜', '找装备', '买', '卖', '价格', '交易']

    if any(k in q for k in bd_keywords):
        return "build_design"
    if any(k in q for k in recommend_keywords):
        return "recommend"
    if any(k in q for k in trade_keywords):
        return "trade"
    return "encyclopedia"


def _classify_question(question: str) -> list[str] | None:
    """Quick keyword-based content type filter to narrow vector search scope.

    Returns a LIST of chunk_type values matching how data was actually ingested:
    PoB chunks use 'gem'/'passive'/'asc_nodes'/'item'/'mod', poe2db uses
    'skill'/'item'/'mod'/'quest'/'map', poe2wiki uses 'wiki', homework uses
    'build_summary' etc. A single-type equality filter silently excluded most
    of the corpus (e.g. gems, ascendancy node lists, waystone/map data).

    IMPORTANT: accumulates ALL matching types instead of early-returning —
    "升华技能" must match BOTH asc_nodes AND skill, not just skill first.
    """
    q = question.lower()
    types: list[str] = []
    if any(w in q for w in ['skill', 'gem', 'herald', 'aura', 'attack', 'spell',
                              '技能', '宝石', '光环', '攻击', '法术', '召唤']):
        types.extend(['skill', 'gem', 'wiki'])
    if any(w in q for w in ['unique', 'item', 'weapon', 'armour', 'sword', 'bow',
                              '暗金', '装备', '武器', '防具', '传奇', '项链', '戒指']):
        types.extend(['item', 'mod'])
    if any(w in q for w in ['mod', 'affix', 'prefix', 'suffix', 'enchant',
                              '词缀', '前缀', '后缀', '附魔']):
        types.extend(['mod', 'item'])
    if any(w in q for w in ['quest', 'act', 'boss', 'map', 'waystone',
                              '任务', '章节', 'boss', '首领', '地图']):
        types.extend(['quest', 'map'])
    if any(w in q for w in ['passive', 'ascendancy', 'tree', 'node',
                              '天赋', '升华', '节点']):
        types.extend(['passive', 'asc_nodes'])
    return list(dict.fromkeys(types)) or None  # dedup, keep order


def _vector_search(db, q_embedding, filters: list, top_k: int,
                   min_similarity: float = 0.3) -> list[dict]:
    """Run a vector similarity search with the given filters."""
    db_url = str(db.get_bind().url)
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        chunks = db.query(KnowledgeChunk).filter(*filters).all()
        scored = []
        for c in chunks:
            emb = c.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            sim = _cosine_sim(q_embedding, emb)
            scored.append((sim, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"content": c.content, "chunk_type": c.chunk_type,
                 "source": c.source, "similarity": round(s, 3)}
                for s, c in scored[:top_k] if s > min_similarity]
    else:
        dist = KnowledgeChunk.embedding.cosine_distance(q_embedding).label("distance")
        rows = (
            db.query(KnowledgeChunk, dist)
            .filter(*filters)
            .order_by(dist)
            .limit(top_k)
            .all()
        )
        return [
            {"content": c.content, "chunk_type": c.chunk_type,
             "source": c.source, "similarity": round(1.0 - d, 3)}
            for c, d in rows if (1.0 - d) > min_similarity
        ]


def _retrieve_knowledge(question: str, top_k: int = 5,
                        classify_text: str | None = None,
                        q_embedding: list[float] | None = None) -> list[dict]:
    """Retrieve relevant knowledge chunks using vector similarity.

    Args:
        question: text to embed for the vector search (may include LLM keywords)
        classify_text: text used for intent / content-type classification.
            Defaults to `question`. The chat flow passes the raw user message
            here so LLM-generated English keywords (e.g. "skill gem", "map")
            don't accidentally trigger the wrong pre-filter.
        q_embedding: optional precomputed embedding (avoids duplicate API calls)

    The chunk_type pre-filter is a soft optimization: if the filtered search
    yields nothing, we retry without the filter instead of returning empty.
    """
    db = SessionLocal()
    try:
        if q_embedding is None:
            q_embedding = get_embedding(question)
        if not q_embedding:
            logger.error("RAG retrieval aborted: query embedding unavailable "
                         "(check EMBEDDING_API_KEY / embedding service)")
            return []

        base_filters = [
            KnowledgeChunk.embedding != None,  # noqa: E711
            KnowledgeChunk.stale == False,  # noqa: E712
        ]

        cls_text = classify_text if classify_text is not None else question
        filters = list(base_filters)

        # Intent-based content-type narrowing
        intent = _classify_intent(cls_text)
        if intent == "recommend":
            filters.append(KnowledgeChunk.chunk_type.in_(["item", "skill", "gem", "mod"]))

        content_types = _classify_question(cls_text)
        if content_types:
            filters.append(KnowledgeChunk.chunk_type.in_(content_types))

        results = _vector_search(db, q_embedding, filters, top_k)

        # Soft-filter fallback: pre-filter may have excluded the right chunks
        if not results and len(filters) > len(base_filters):
            logger.info("Pre-filtered retrieval empty, retrying without chunk_type filter")
            results = _vector_search(db, q_embedding, base_filters, top_k)

        return results
    finally:
        db.close()


def _cosine_sim(a, b):
    # embeddings may arrive as numpy arrays (pgvector on sqlite) — normalize to list
    if a is not None and not isinstance(a, (list, tuple)):
        a = list(a)
    if b is not None and not isinstance(b, (list, tuple)):
        b = list(b)
    if not a or not b:
        return 0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0


def _chunk_to_dict(c: KnowledgeChunk) -> dict:
    """Convert an ORM KnowledgeChunk to the dict format expected by _stream_chat."""
    return {
        "content": c.content,
        "chunk_type": c.chunk_type,
        "source": c.source or "db",
        "similarity": 1.0,  # direct lookup, not vector match
    }


def _get_cache_key(question: str, top_k: int) -> str:
    """Generate a stable cache key for a QA query."""
    import hashlib
    raw = f"qa:{question.strip().lower()}:{top_k}"
    return f"qa_cache:{hashlib.md5(raw.encode()).hexdigest()[:16]}"


@qa_router.post("/api/knowledge/ask", response_model=AskResponse)
async def ask_question(req: AskRequest):
    """RAG QA: answer PoE2 questions using poe2db knowledge base."""
    import time
    t_start = time.time()

    # Redis cache check
    cache_key = _get_cache_key(req.question, req.top_k)
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


def _build_design_prompt(context: str, asc_en: str | None, asc_cn: str | None) -> str:
    """Progressive BD design prompt — forces deep analysis of retrieved mechanics."""
    anchor = ""
    if asc_en and asc_cn:
        anchor = (
            f"用户询问的升华是 **{asc_cn}（{asc_en}）**。"
            f"必须先深入分析该升华的核心机制，再基于机制推导技能和装备选择。\n"
        )
    return (
        "你是 PoE2 BD 架构师。基于检索到的游戏数据设计可行的 Build 方案。\n\n"
        + anchor +
        "## 分析要求\n"
        "1. **读懂核心机制**：仔细阅读升华节点、技能描述中的具体数值和联动关系\n"
        "2. **确定核心技能**：基于机制选出 1-2 个核心主动技能，说明为什么它们与机制配合\n"
        "3. **构建辅助链路**：为核心技能搭配辅助宝石，解释联动逻辑\n"
        "4. **寻找装备支撑**：推荐能强化核心机制的暗金或黄装词缀\n"
        "5. **完善防御**：根据职业特性推荐防御层\n\n"
        "## 输出格式\n"
        "### 核心机制\n"
        "（2-3 句话解释这个 BD 的核心运作方式，引用资料中的具体数值）\n\n"
        "### 核心技能\n"
        "- 主动技能（名称 + 为什么选它）\n"
        "- 辅助宝石链接（联动关系）\n\n"
        "### 关键装备\n"
        "- 暗金推荐（具体名称 + 作用）\n"
        "- 黄装词缀优先级（按重要性排序）\n\n"
        "### 防御与天赋\n"
        "- 关键天赋圈\n"
        "- 防御机制\n\n"
        "### 开荒/过渡建议\n"
        "- 哪些装备可以降配\n"
        "- 前期替代技能\n\n"
        "## 规则\n"
        "- 每个推荐必须关联资料中的具体数据，引用数值\n"
        "- 不编造不存在的装备/技能，不确定的标注[推测]\n"
        "- 如果资料不足，诚实说明"缺什么信息"，不要凑答案\n"
        "- 回答末尾列出来源（如[pob/asc_nodes]、[poe2db/skill]）\n\n"
        "资料：\n" + context
    )


def _recommend_prompt(context: str) -> str:
    return (
        "你是 PoE2 装备推荐专家。\n"
        "1. 先列出用户可选的装备（含关键数值）\n"
        "2. 对比优劣，给出明确推荐理由\n"
        "3. 如果有预算范围，区分「性价比」和「毕业」选项\n\n"
        "资料：\n" + context
    )


def _encyclopedia_prompt(context: str, asc_en: str | None, asc_cn: str | None) -> str:
    """Encyclopedia prompt — concise answers with progressive detail."""
    constraint = ""
    if asc_en:
        constraint = (
            f"⚠️ 用户询问的升华是 **{asc_cn}（{asc_en}）**。"
            f"只回答该升华的信息，**绝对不要**用其他升华的资料替代。\n"
        )
    return (
        "你是 PoE2 百科助手。\n"
        "1. 先一句话直接回答用户的问题\n"
        "2. 如果资料有详细数据，列表展开\n"
        "3. 如果资料不足，诚实说明\n"
        + constraint +
        "\n资料：\n" + context
    )


async def _stream_chat(messages: list[dict]):
    """Two-phase: LLM thinks what to search → retrieve → LLM thinks about results → answer."""
    user_msg = messages[-1]["content"] if messages else ""
    intent = _classify_intent(user_msg)
    logger.info(f"[CHAT] intent={intent} | query={user_msg[:80]}")

    # ── Alias resolution: exact-match CN entity names before vector search ──
    from app.services.entity_dict import (
        normalize_class, normalize_ascendancy,
        resolve_ascendancy_en, resolve_class_en,
    )
    from app.services.entity_resolver import resolve_all_entities

    resolved_class_en = normalize_class(user_msg)
    resolved_asc_cn = normalize_ascendancy(user_msg)
    resolved_asc_en = resolve_ascendancy_en(resolved_asc_cn) if resolved_asc_cn else None
    alias_keywords = []
    if resolved_class_en:
        alias_keywords.append(resolved_class_en)
    if resolved_asc_en:
        alias_keywords.append(resolved_asc_en)
    if resolved_asc_cn:
        alias_keywords.append(resolved_asc_cn)

    # Also resolve items/skills/notables from the comprehensive alias table
    extra_entities = resolve_all_entities(user_msg)
    for en_name, cn_name, etype in extra_entities:
        alias_keywords.append(en_name)
        alias_keywords.append(cn_name)
    if extra_entities:
        logger.info(f"[CHAT] entity_resolved: {[(e,c,t) for e,c,t in extra_entities[:5]]}")
    if alias_keywords:
        logger.info(f"[CHAT] alias_resolved: class={resolved_class_en} asc={resolved_asc_cn}({resolved_asc_en})")

    llm_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    llm_key = os.getenv("LLM_API_KEY", "")
    from openai import OpenAI as OAI
    llm_client = OAI(base_url=llm_url, api_key=llm_key)

    # ── Phase 1: Model thinks, decides what to search ──
    yield f"data: {json.dumps({'type': 'thinking', 'content': 'AI 正在分析需要查什么...'})}\n\n"

    plan_prompt = (
        "用户问了一个 PoE2 问题。你需要列出检索关键词来查找相关资料。\n"
        "输出 3-5 个英文检索关键词，一行一个，不要其他文字。\n\n"
        "用户问题: " + user_msg
    )
    try:
        resp = llm_client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            messages=[{"role": "user", "content": plan_prompt}],
            temperature=0.1, max_tokens=200,
            extra_body={'thinking': {'type': 'enabled'}},
        )
        search_keywords = resp.choices[0].message.content.strip().split('\n')
        search_keywords = [k.strip() for k in search_keywords if k.strip()][:5]
        yield f"data: {json.dumps({'type': 'thinking', 'content': '搜索关键词: ' + ', '.join(search_keywords[:5])})}\n\n"
    except Exception:
        search_keywords = [user_msg]

    # ── Fuzzy-correct LLM keywords against known entity names ──
    from app.services.entity_resolver import correct_keywords, find_asc_for_notable
    search_keywords = correct_keywords(search_keywords)

    # If any keyword matches a known notable, resolve its ascendancy for structured lookup
    notable_asc = find_asc_for_notable(search_keywords)
    if notable_asc and not resolved_asc_en:
        resolved_asc_en = notable_asc
        resolved_asc_cn = resolved_asc_cn or notable_asc
        logger.info(f"[CHAT] notable_resolved: asc={notable_asc}")

    # ── Phase 2: Multi-source retrieval using model's keywords + original query ──
    yield f"data: {json.dumps({'type': 'thinking', 'content': '正在检索知识库...'})}\n\n"

    # Combine: alias-resolved names + model's English keywords + user's original Chinese
    search_query = user_msg + " " + " ".join(alias_keywords + search_keywords)
    content_types = _classify_question(user_msg)
    logger.info(f"[CHAT] search: keywords={search_keywords[:5]} alias={alias_keywords} content_types={content_types}")

    # Embed once; surface embedding-service failures instead of pretending "no results"
    q_embedding = get_embedding(search_query)
    if not q_embedding:
        logger.error("Chat retrieval failed: embedding service unavailable")
        yield f"data: {json.dumps({'type': 'answer', 'content': '知识库检索失败：embedding 服务不可用（请检查 EMBEDDING_API_KEY 配置或 API 配额）。'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    # NOTE: classify on the raw user message, not the LLM-keyword-augmented query —
    # English keywords like "item"/"map" used to mis-trigger chunk_type pre-filters.
    if intent == "build_design":
        chunks = _retrieve_multi_source(search_query, q_embedding=q_embedding)
    elif intent == "recommend":
        chunks = _retrieve_knowledge(search_query, 8, classify_text=user_msg, q_embedding=q_embedding)
    else:
        chunks = _retrieve_knowledge(search_query, 5, classify_text=user_msg, q_embedding=q_embedding)

    # ── Structured lookup: if user asks about a specific ascendancy, direct DB fetch ──
    direct_chunk = None
    if resolved_asc_en:
        db_lookup = SessionLocal()
        try:
            direct_chunk = (
                db_lookup.query(KnowledgeChunk)
                .filter(
                    KnowledgeChunk.chunk_type == "asc_nodes",
                    KnowledgeChunk.content.ilike(f"%{resolved_asc_en}%")
                )
                .first()
            )
            if direct_chunk:
                logger.info(f"[CHAT] structured_lookup: found asc_nodes for {resolved_asc_en}")
                chunks = [_chunk_to_dict(direct_chunk)] + [
                    c for c in chunks if c.get("chunk_type") != "asc_nodes"
                ]
        finally:
            db_lookup.close()

    if not chunks:
        yield f"data: {json.dumps({'type': 'answer', 'content': '未找到相关知识。'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    source_counts = {}
    type_counts = {}
    for c in chunks:
        s = c.get("source", "?")
        source_counts[s] = source_counts.get(s, 0) + 1
        t = c.get("chunk_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
    src_desc = ", ".join(k + "(" + str(v) + ")" for k, v in source_counts.items())
    logger.info(f"[CHAT] retrieved: {len(chunks)} chunks | sources={source_counts} | types={type_counts}")

    # Build context
    ctx_parts = []
    for c in chunks:
        try:
            data = json.loads(c["content"])
            text = data.get("search_text", c["content"])
            # asc_nodes and homework need full context (node lists, build details)
            limit = 3000 if c.get("chunk_type") in ("asc_nodes", "build_summary") else 800
            ctx_parts.append("[" + c.get("source", "?") + "/" + c.get("chunk_type", "?") + "] " + text[:limit])
        except Exception:
            ctx_parts.append(c["content"][:800])
    context = "\n\n".join(ctx_parts)

    # ── Phase 3: Model thinks about results + answers ──
    yield f"data: {json.dumps({'type': 'thinking', 'content': '从 ' + str(len(chunks)) + ' 条资料(' + src_desc + ')中分析回答...'})}\n\n"

    if intent == "build_design":
        sys_prompt = _build_design_prompt(context, resolved_asc_en, resolved_asc_cn)
    elif intent == "recommend":
        sys_prompt = _recommend_prompt(context)
    else:
        sys_prompt = _encyclopedia_prompt(context, resolved_asc_en, resolved_asc_cn)

    llm_msgs = [{"role": "system", "content": sys_prompt}]
    for m in messages[-5:]:
        llm_msgs.append(m)

    try:
        stream = llm_client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            messages=llm_msgs,
            temperature=0.3, max_tokens=2048, stream=True,
            extra_body={'thinking': {'type': 'enabled'}},
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, 'reasoning_content', None) or (
                delta.model_extra.get('reasoning_content') if hasattr(delta, 'model_extra') and delta.model_extra else None
            )
            if reasoning:
                yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning})}\n\n"
            if delta.content:
                yield f"data: {json.dumps({'type': 'answer', 'content': delta.content})}\n\n"
    except Exception as e:
        logger.error(f"LLM stream error: {e}")
        yield f"data: {json.dumps({'type': 'answer', 'content': '生成失败: ' + str(e)})}\n\n"

    sources = [{"type": c.get("chunk_type", "?"), "source": c.get("source", "?"),
                 "preview": c.get("content", "")[:100]} for c in chunks[:5]]
    yield f"data: {json.dumps({'type': 'sources', 'content': sources})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


def _retrieve_multi_source(question: str, per_source: int = 5,
                           q_embedding: list[float] | None = None) -> list[dict]:
    """Multi-source: homework + pob + poe2db + poe2wiki.

    Sources are discovered from the DB (DISTINCT) rather than hardcoded, so
    chunks ingested with unexpected source values are still searchable.
    Falls back to a source-agnostic search if per-source retrieval is empty.
    """
    db = SessionLocal()
    try:
        if q_embedding is None:
            q_embedding = get_embedding(question)
        if not q_embedding:
            logger.error("Multi-source retrieval aborted: query embedding unavailable")
            return []

        sources = [
            row[0] for row in db.query(KnowledgeChunk.source)
            .filter(KnowledgeChunk.stale == False)  # noqa: E712
            .distinct().all() if row[0]
        ] or ["homework", "pob", "poe2db", "poe2wiki"]

        all_chunks = []
        for source in sources:
            filters = [
                KnowledgeChunk.embedding != None,  # noqa: E711
                KnowledgeChunk.source == source,
                KnowledgeChunk.stale == False,  # noqa: E712
            ]
            all_chunks.extend(_vector_search(db, q_embedding, filters, per_source))

        if not all_chunks:
            logger.info("Multi-source empty, falling back to source-agnostic search")
            fallback_filters = [
                KnowledgeChunk.embedding != None,  # noqa: E711
                KnowledgeChunk.stale == False,  # noqa: E712
            ]
            all_chunks = _vector_search(db, q_embedding, fallback_filters, 10)

        all_chunks.sort(key=lambda x: x["similarity"], reverse=True)
        logger.info(f"Multi-source: {len(all_chunks)} chunks from sources={sources}")
        return all_chunks[:20]
    finally:
        db.close()


@qa_router.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Multi-turn SSE streaming chat."""
    return StreamingResponse(
        _stream_chat(req.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
