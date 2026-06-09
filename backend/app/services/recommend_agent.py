"""recommend_agent.py — PoE2 推荐编排 Agent。

处理「这 N 个传奇哪个最适合我的死灵法师」这类多跳 + 对比 + 个性化推荐问题。
范式参考 trade_agent：parse → resolve → retrieve → score → rank。

复用现有设施：
  - embedding_service.embed_text        向量化
  - knowledge_service.retrieve_similar  向量召回
  - ai_service / OpenAI client          LLM 推理
  - pob_decoder.decode                  PoB Code 个性化（可选）

依赖以工程内实际模块为准，下方 import 为占位，接入时按真实路径调整。
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

from app.services import entity_dict
from app.services import entity_data

logger = logging.getLogger(__name__)

VERDICT_ENUM = ["强烈推荐", "推荐", "可选", "不推荐"]


# ─────────────────────────── 数据结构 ───────────────────────────
@dataclass
class ParsedIntent:
    intent: str = "recommend"          # recommend | encyclopedia
    raw_question: str = ""
    char_class: str | None = None      # Witch / Warrior ...
    ascendancy: str | None = None      # 深渊巫妖 ...
    archetype_info: dict | None = None # detect_archetype 结果
    candidates: list[str] = field(default_factory=list)
    candidate_source: str = "auto"     # user | page | auto
    budget: str | None = None
    confidence: float = 1.0


@dataclass
class CandidateScore:
    name: str
    fit_score: int
    pros: list[str]
    cons: list[str]
    synergy: str = ""
    verdict: str = "可选"
    sources: list[dict] = field(default_factory=list)


@dataclass
class RecommendResult:
    intent: str
    resolved: dict
    ranking: list[dict]
    best_pick: str | None
    summary: str
    disclaimer: str = "基于 poe2db 当前赛季数据，实战需结合个人构建验证。"


# ─────────────────────────── Agent 主体 ───────────────────────────
class RecommendAgent:
    def __init__(
        self,
        embed_fn,            # async def embed_text(str) -> list[float]
        retrieve_fn,         # async def retrieve_similar(vec, top_k, filters) -> list[chunk]
        llm_fn,              # async def chat_completion(messages, **kw) -> str
        decode_pob_fn=None,  # def decode(code) -> BuildData，可选
    ):
        self.embed = embed_fn
        self.retrieve = retrieve_fn
        self.llm = llm_fn
        self.decode_pob = decode_pob_fn

    # ── 入口 ──
    async def run(
        self,
        question: str,
        pob_code: str | None = None,
        candidates: list[str] | None = None,
        page_candidates: list[str] | None = None,
        league: str | None = None,
        game_version: str | None = None,
    ) -> RecommendResult:
        parsed = await self._parse_intent(question, candidates, page_candidates)
        parsed = self._resolve_entities(parsed)

        # 个性化上下文（PoB 优先）
        user_ctx = self._build_user_context(pob_code, parsed)

        # 候选不足 → 触发对话追问 / 自动召回兜底（见下方逻辑）
        if not parsed.candidates:
            parsed.candidates = await self._auto_recall_candidates(
                parsed, league, game_version
            )

        logger.info(f"Scoring {len(parsed.candidates)} candidates: {parsed.candidates}")
        scores = await self._score_all(
            parsed, user_ctx, league, game_version
        )

        # reduce: 排序 + 总结
        return self._rank_and_explain(parsed, scores)

    # ── 1. 意图解析（规则 + LLM 兜底） ──
    async def _parse_intent(
        self, question: str,
        user_candidates: list[str] | None,
        page_candidates: list[str] | None,
    ) -> ParsedIntent:
        p = ParsedIntent(raw_question=question)
        p.char_class = entity_dict.normalize_class(question)
        p.ascendancy = entity_dict.normalize_ascendancy(question)
        p.archetype_info = entity_dict.detect_archetype(question)

        # ── 候选来源优先级链（按你勾选的三路）──
        # 1) 用户显式指定  2) 页面上下文  3) 问题文本里点名的传奇  4) 留空→auto召回
        if user_candidates:
            p.candidates = user_candidates
            p.candidate_source = "user"
        elif page_candidates:
            p.candidates = page_candidates
            p.candidate_source = "page"
        else:
            # 从问题文本里识别真实传奇名（命中全量词典）
            mentioned = entity_data.extract_unique_mentions(question)
            if mentioned:
                p.candidates = mentioned
                p.candidate_source = "mention"
            else:
                p.candidate_source = "auto"

        # 职业/流派都没识别出来 → 低置信，建议反问
        if not p.char_class and not p.archetype_info:
            p.confidence = 0.4
            # 可在此调用 LLM 做一次抽取兜底
            extracted = await self._llm_extract(question)
            p.char_class = p.char_class or extracted.get("class")
            p.ascendancy = p.ascendancy or extracted.get("ascendancy")
        return p

    async def _llm_extract(self, question: str) -> dict:
        """LLM 兜底抽取职业/升华/预算（规则没命中时）。"""
        prompt = (
            "从下面这句 PoE2 玩家提问中抽取信息，只输出 JSON："
            '{"class":职业或null,"ascendancy":升华或null,"budget":预算或null}\n'
            f"提问：{question}"
        )
        try:
            raw = await self.llm([{"role": "user", "content": prompt}])
            return json.loads(_extract_json(raw))
        except Exception as e:  # noqa
            logger.warning("LLM extract failed: %s", e)
            return {}

    # ── 2. 实体解析 ──
    def _resolve_entities(self, p: ParsedIntent) -> ParsedIntent:
        # 升华能反推职业
        if p.ascendancy and not p.char_class:
            p.char_class = entity_dict.ASCENDANCY_TO_CLASS.get(p.ascendancy)
        return p

    # ── 3. 个性化上下文 ──
    def _build_user_context(self, pob_code: str | None, p: ParsedIntent) -> str:
        if pob_code and self.decode_pob:
            try:
                bd = self.decode_pob(pob_code)
                # 复用 BuildData 真实字段
                return (
                    f"玩家当前构建：职业={getattr(bd,'class_name','?')}, "
                    f"升华={getattr(bd,'ascendancy','?')}, "
                    f"主技能={getattr(bd,'main_skill','?')}。"
                )
            except Exception as e:  # noqa
                logger.warning("decode pob failed: %s", e)
        # 没有 PoB → 用 parse 出来的弱信息
        parts = []
        if p.char_class:
            parts.append(f"职业={p.char_class}")
        if p.archetype_info:
            parts.append(f"流派={p.archetype_info['matched']}")
        return "玩家信息：" + ("，".join(parts) if parts else "未提供，按通用情况评估")

    # ── 4. 自动召回候选（candidate_source=auto 时） ──
    async def _auto_recall_candidates(
        self, p: ParsedIntent, league, game_version, top_k: int = 10
    ) -> list[str]:
        # 优先：按流派标签从全量传奇库直接筛（精准、零 LLM 成本）
        if p.archetype_info:
            arche = p.archetype_info.get("archetype")
            tagged = entity_data.find_uniques_by_archetype(arche, limit=top_k)
            if tagged:
                return [u["name"] for u in tagged]

        # 兜底：向量召回
        kws = entity_dict.build_retrieval_keywords(
            {"class": p.char_class, "ascendancy": p.ascendancy,
             "archetype_info": p.archetype_info}
        )
        query = f"适合{p.archetype_info['matched'] if p.archetype_info else ''}的传奇物品 " + " ".join(kws)
        vec = await self.embed(query)
        chunks = await self.retrieve(
            vec, top_k=top_k,
            filters=_league_filter(league, game_version, chunk_type="item"),
        )
        # 去重提取词条名
        names, seen = [], set()
        for c in chunks:
            name = c.get("title") or c.get("name")
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names[:top_k]

    # ── 5. 逐项召回 + 打分（map，并行） ──
    async def _score_all(self, p, user_ctx, league, game_version) -> list[CandidateScore]:
        tasks = [
            self._score_one(name, p, user_ctx, league, game_version)
            for name in p.candidates
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        scores = [r for r in results if isinstance(r, CandidateScore)]
        return scores

    async def _score_one(self, name, p, user_ctx, league, game_version) -> CandidateScore:
        # Priority 1: Use JSON data if this is a known unique item
        json_data = entity_data.load_uniques()
        item_info = next((u for u in json_data if u["name"] == name), None)

        if item_info:
            parts = [f"传奇物品：{item_info['name']}"]
            if item_info.get("base_type"):
                parts.append(f"基底：{item_info['base_type']}")
            if item_info.get("archetypes"):
                parts.append(f"流派标签：{', '.join(item_info['archetypes'])}")
            context = "\n".join(parts)
        else:
            vec = await self.embed(f"{name} 属性 词缀 效果")
            chunks = await self.retrieve(vec, top_k=3, filters=_league_filter(league, game_version))
            context = "\n".join(c.get("content", "") for c in chunks)

        if not context:
            logger.warning(f"_score_one: no context for '{name}'")
            return CandidateScore(name=name, fit_score=0, pros=[], cons=["资料不足"], synergy="", verdict="可选")

        arche = p.archetype_info["matched"] if p.archetype_info else "通用"
        prompt = (
            f"{user_ctx}\n"
            f"评估物品「{name}」对「{arche}」流派的适配性。\n"
            f"只能基于以下资料，禁止编造：\n---\n{context}\n---\n"
            f"严格输出 JSON："
            '{"name":"","fit_score":0-100整数,"pros":[],"cons":[],'
            f'"synergy":"","verdict":"{"/".join(VERDICT_ENUM)}其一"}}'
        )
        try:
            raw = await self.llm([{"role": "user", "content": prompt}])
            data = _safe_parse_score(raw, name)
            data["sources"] = [{"source": "entity_data" if item_info else "vector"}]
            logger.info(f"_score_one: {name} → {data.get('fit_score',0)}分")
            return CandidateScore(**data)
        except Exception as e:
            logger.error(f"_score_one failed for '{name}': {e}")
            return CandidateScore(name=name, fit_score=0, pros=[], cons=[f"评分失败: {e}"], synergy="", verdict="可选")

    # ── 6. 排序 + 总结（reduce） ──
    def _rank_and_explain(self, p: ParsedIntent, scores: list[CandidateScore]) -> RecommendResult:
        ranked = sorted(scores, key=lambda s: s.fit_score, reverse=True)
        best = ranked[0].name if ranked else None
        if ranked:
            top = ranked[0]
            summary = (
                f"对{p.archetype_info['matched'] if p.archetype_info else '该构建'}而言，"
                f"「{top.name}」适配度最高（{top.fit_score}分）：{top.synergy}"
            )
        else:
            summary = "未能从知识库召回到足够资料，建议补充候选项或提供 PoB 构建码。"
        return RecommendResult(
            intent=p.intent,
            resolved={
                "class": p.char_class,
                "ascendancy": p.ascendancy,
                "archetype": p.archetype_info["matched"] if p.archetype_info else None,
                "candidate_source": p.candidate_source,
            },
            ranking=[asdict(s) for s in ranked],
            best_pick=best,
            summary=summary,
        )


# ─────────────────────────── 工具函数 ───────────────────────────
def _league_filter(league, game_version, chunk_type=None) -> dict:
    f = {}
    if league:
        f["league"] = league
    if game_version:
        f["game_version"] = game_version
    if chunk_type:
        f["chunk_type"] = chunk_type
    return f


def _extract_json(text: str) -> str:
    """从 LLM 回复里抠出第一段 JSON。"""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text


def _safe_parse_score(raw: str, fallback_name: str) -> dict:
    """解析打分 JSON，失败则降级为保守结果，符合 schema 校验铁律。"""
    try:
        d = json.loads(_extract_json(raw))
        verdict = d.get("verdict", "可选")
        if verdict not in VERDICT_ENUM:
            verdict = "可选"
        return {
            "name": d.get("name") or fallback_name,
            "fit_score": int(max(0, min(100, d.get("fit_score", 50)))),
            "pros": list(d.get("pros", []))[:5],
            "cons": list(d.get("cons", []))[:5],
            "synergy": str(d.get("synergy", "")),
            "verdict": verdict,
        }
    except Exception as e:  # noqa
        logger.warning("score parse failed for %s: %s", fallback_name, e)
        return {
            "name": fallback_name, "fit_score": 0,
            "pros": [], "cons": ["资料不足，无法评估"],
            "synergy": "", "verdict": "可选",
        }
