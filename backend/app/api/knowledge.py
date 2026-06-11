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
from app.services.retrieval_pipeline import (
    RetrievalOptions,
    retrieve_knowledge,
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

    sys_prompt = f"""你是流放之路2 (Path of Exile 2) 知识助手。基于以下来自 poe2db 百科的数据回答用户问题。
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


def _build_design_prompt(context: str, asc_en, asc_cn) -> str:
    """Progressive BD design prompt — forces deep analysis of retrieved mechanics."""
    anchor = ""
    if asc_en and asc_cn:
        anchor = (
            "用户询问的升华是 " + str(asc_cn) + "(" + str(asc_en) + ")。"
            "必须先深入分析该升华的核心机制, 再基于机制推导技能和装备选择。\n"
        )
    parts = [
        "你是 PoE2 BD 架构师。基于检索到的游戏数据设计可行的 Build 方案。\n\n",
    ]
    if anchor:
        parts.append(anchor)
    parts.extend([
        "## 分析要求\n",
        "1. 读懂核心机制: 仔细阅读升华节点、技能描述中的具体数值和联动关系\n",
        "2. 确定核心技能: 基于机制选出1-2个核心主动技能, 说明为什么它们与机制配合\n",
        "3. 构建辅助链路: 为核心技能搭配辅助宝石, 解释联动逻辑\n",
        "4. 寻找装备支撑: 推荐能强化核心机制的暗金或黄装词缀\n",
        "5. 完善防御: 根据职业特性推荐防御层\n\n",
        "## 输出格式\n",
        "### 核心机制\n",
        "(2-3句话解释这个BD的核心运作方式, 引用资料中的具体数值)\n\n",
        "### 核心技能\n",
        "- 主动技能 (名称+为什么选它)\n",
        "- 辅助宝石链接 (联动关系)\n\n",
        "### 关键装备\n",
        "- 暗金推荐 (具体名称+作用)\n",
        "- 黄装词缀优先级 (按重要性排序)\n\n",
        "### 防御与天赋\n",
        "- 关键天赋圈\n",
        "- 防御机制\n\n",
        "### 开荒/过渡建议\n",
        "- 哪些装备可以降配\n",
        "- 前期替代技能\n\n",
        "## 规则\n",
        "- 每个推荐必须关联资料中的具体数据, 引用数值\n",
        "- 不编造不存在的装备/技能, 不确定的标注[推测]\n",
        "- 如果资料不足, 诚实说明缺什么信息, 不要凑答案\n",
        "- 回答末尾列出来源 (如[pob/asc_nodes], [poe2db/skill])\n\n",
        "资料:\n", context,
    ])
    return "".join(parts)


def _recommend_prompt(context: str) -> str:
    return (
        "你是 PoE2 装备推荐专家。\n"
        "1. 先列出用户可选的装备（含关键数值）\n"
        "2. 对比优劣，给出明确推荐理由\n"
        "3. 如果有预算范围, 区分[性价比]和[毕业]选项\n\n"
        "资料：\n" + context
    )


def _encyclopedia_prompt(context: str, asc_en, asc_cn) -> str:
    """Encyclopedia prompt — concise answers with progressive detail."""
    constraint = ""
    if asc_en:
        constraint = (
            "用户询问的升华是 " + str(asc_cn) + "(" + str(asc_en) + ")。"
            "只回答该升华的信息, 绝对不要用其他升华的资料替代。\n"
        )
    return (
        "你是 PoE2 百科助手。\n"
        "1. 先一句话直接回答用户的问题\n"
        "2. 如果资料有详细数据, 列表展开\n"
        "3. 如果资料不足, 诚实说明\n"
        + constraint +
        "\n资料:\n" + context
    )


async def _stream_chat(messages: list[dict]):
    """Skill-based router: classify intent → dispatch to matching Skill."""
    from app.skills.router import route

    # Init LLM client early — needed by all skill paths
    llm_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1")
    llm_key = os.getenv("LLM_API_KEY", "")
    from openai import OpenAI as OAI
    llm_client = OAI(base_url=llm_url, api_key=llm_key)

    user_msg = messages[-1]["content"] if messages else ""
    skill = route(user_msg)
    logger.info(f"[CHAT] skill={skill.name} | query={user_msg[:80]}")

    # ── Trade Search: calls trade API directly, no RAG ──
    if skill.name == "trade_search":
        yield f"data: {json.dumps({'type': 'thinking', 'content': 'AI 正在搜索交易市场...'})}\n\n"
        try:
            from app.services.trade_agent import run_agent as trade_run_agent
            trade_result = trade_run_agent(user_msg)
            best = trade_result.get("best_match")
            alts = trade_result.get("alternatives", [])

            trade_data = {
                "best_match": {"label": best["label"], "url": best["url"], "count": best["count"]} if best else None,
                "alternatives": [{"label": a["label"], "url": a["url"], "count": a["count"]} for a in alts[:3]],
                "explanation": trade_result.get("explanation", ""),
            }
            yield f"data: {json.dumps({'type': 'trade_result', 'content': trade_data})}\n\n"

            trade_prompt = skill.system_prompt(user_msg=user_msg, trade_result=trade_result)
            llm_msgs = [{"role": "system", "content": trade_prompt},
                         {"role": "user", "content": "帮我解释这些搜索结果"}]
            stream = llm_client.chat.completions.create(
                model=os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
                messages=llm_msgs, temperature=0.3, max_tokens=1024, stream=True,
                extra_body={'thinking': {'type': 'enabled'}},
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                r = getattr(delta, 'reasoning_content', None) or (
                    delta.model_extra.get('reasoning_content') if hasattr(delta, 'model_extra') and delta.model_extra else None
                )
                if r: yield f"data: {json.dumps({'type': 'reasoning', 'content': r})}\n\n"
                if delta.content: yield f"data: {json.dumps({'type': 'answer', 'content': delta.content})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logger.error(f"Trade search failed: {e}")
            yield f"data: {json.dumps({'type': 'answer', 'content': f'装备搜索失败: {str(e)}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    # ── RAG-based Skills: entity resolution → keyword gen → retrieve → answer ──
    from app.services.entity_dict import normalize_ascendancy, resolve_ascendancy_en
    from app.services.retrieval_pipeline import structured_entity_lookup

    alias_keywords, resolved_entities = extract_alias_keywords(user_msg)
    resolved_asc_cn = normalize_ascendancy(user_msg)
    resolved_asc_en = resolve_ascendancy_en(resolved_asc_cn) if resolved_asc_cn else None
    league = default_league()
    game_version = default_game_version()
    if alias_keywords:
        logger.info(f"[CHAT] alias_resolved: {alias_keywords[:8]}")

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
    # Only for build_design (where ascendancy context is relevant), not encyclopedia
    if skill.name == "build_design":
        notable_asc = find_asc_for_notable(search_keywords)
        if notable_asc and not resolved_asc_en:
            resolved_asc_en = notable_asc
            resolved_asc_cn = resolved_asc_cn or notable_asc
            logger.info(f"[CHAT] notable_resolved: asc={notable_asc}")

    # ── Phase 2: Multi-source retrieval using model's keywords + original query ──
    yield f"data: {json.dumps({'type': 'thinking', 'content': '正在检索知识库...'})}\n\n"

    search_query = build_search_query(user_msg, alias_keywords, search_keywords)
    content_types = classify_question(user_msg)
    logger.info(f"[CHAT] search: keywords={search_keywords[:5]} alias={alias_keywords} content_types={content_types}")

    q_embedding = get_embedding(search_query)
    if not q_embedding:
        logger.error("Chat retrieval failed: embedding service unavailable")
        yield f"data: {json.dumps({'type': 'answer', 'content': '知识库检索失败：embedding 服务不可用（请检查 EMBEDDING_API_KEY 配置或 API 配额）。'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    retrieval = retrieve_knowledge(
        search_query,
        RetrievalOptions(
            top_k=5,
            classify_text=user_msg,
            q_embedding=q_embedding,
            league=league,
            game_version=game_version,
            alias_keywords=alias_keywords,
            expand_concepts=False,
            multi_source=(skill.name == "build_design"),
        ),
    )
    chunks = retrieval.chunks

    if resolved_entities:
        db_lookup = SessionLocal()
        try:
            direct_chunks = structured_entity_lookup(
                db_lookup, resolved_entities, league=league, game_version=game_version,
            )
            if direct_chunks:
                existing_ids = {c.get("content", "")[:100] for c in chunks}
                for dc in direct_chunks:
                    if dc["content"][:100] not in existing_ids:
                        existing_ids.add(dc["content"][:100])
                        chunks = [dc] + chunks
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

    # ── Concept-link expansion: follow pointers from retrieved text ──
    if skill.name != "trade_search":
        yield f"data: {json.dumps({'type': 'thinking', 'content': '扩展关联概念...'})}\n\n"
        from app.services.retrieval_pipeline import expand_concepts
        concept_chunks = expand_concepts(
            chunks, max_new=6, league=league, game_version=game_version,
        )
        logger.info(f"[CHAT] concept_expand: found {len(concept_chunks)} related chunks "
                     f"(chunks_have_links={sum(1 for c in chunks if c.get('links'))}/{len(chunks)})")
        if concept_chunks:
            chunks = chunks + concept_chunks

    context = build_context(chunks)

    # ── Phase 3: Model thinks about results + answers ──
    yield f"data: {json.dumps({'type': 'thinking', 'content': '从 ' + str(len(chunks)) + ' 条资料(' + src_desc + ')中分析回答...'})}\n\n"

    # Skill-based prompt dispatch
    sys_prompt = skill.system_prompt(context=context, user_msg=user_msg,
                                      asc_en=resolved_asc_en, asc_cn=resolved_asc_cn)

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


@qa_router.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Multi-turn SSE streaming chat."""
    return StreamingResponse(
        _stream_chat(req.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
