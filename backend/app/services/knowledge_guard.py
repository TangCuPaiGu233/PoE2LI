"""Guardrails: force rag_search when answers need grounded game knowledge."""

from __future__ import annotations

import re
from typing import Any

from app.core.game_context import is_ninja_cost_guide_query
from app.services.chat_tools import POB_INPUT_RE, find_build_input
from app.services.multi_item_price import is_build_cost_query, is_price_query
from app.services.retrieval_pipeline import extract_alias_keywords

_CJK = re.compile(r"[\u4e00-\u9fff]")

_KNOWLEDGE_DOMAIN = re.compile(
    r"(词缀|机制|装备|技能|召唤|天赋|升华|属性|效果|暗金|稀有|配装|"
    r"被动|珠宝|项链|戒指|腰带|手套|鞋子|头盔|胸甲|"
    r"伤害|抗性|生命|魔力|护甲|闪避|能量护盾|"
    r"怎么|如何|为什么|对比|推荐|除了|哪些|什么)",
    re.I,
)

_TRADE_INTENT = re.compile(r"(找|搜|买|市价|多少钱|查价|交易)")
_TRADE_KNOWLEDGE_BLOCK = re.compile(
    r"(哪些|词缀|机制|怎么|除了|什么|对比|推荐|如何|为什么)",
    re.I,
)

_DRAFT_GAME_FACTS = re.compile(
    r"(词缀|技能|装备|暗金|稀有|召唤|天赋|升华|"
    r"生命|魔力|抗性|伤害|护甲|闪避|能量护盾|"
    r"手套|鞋子|头盔|胸甲|项链|戒指|腰带|珠宝|"
    r"###\s*[^\n]*(?:词缀|装备|技能|配装|推荐|属性))",
    re.I,
)
_DRAFT_PERCENT = re.compile(r"\d+\s*%")
_DRAFT_HEADER = re.compile(r"^###\s+", re.M)


def is_rag_exempt(user_msg: str) -> bool:
    raw = (user_msg or "").strip()
    if not raw:
        return True
    if len(raw) < 6:
        return True
    if is_ninja_cost_guide_query(raw):
        return True
    if is_build_cost_query(raw):
        return True
    if is_price_query(raw):
        return True
    if _is_pure_link_only(raw):
        return True
    if _is_trade_only_intent(raw):
        return True
    return False


def _is_pure_link_only(text: str) -> bool:
    if not mentions_knowledge_domain(text):
        if find_build_input(text) or POB_INPUT_RE.search(text):
            stripped = POB_INPUT_RE.sub("", text).strip()
            stripped = re.sub(r"https?://\S+", "", stripped).strip()
            if len(stripped) < 8:
                return True
    return False


def _is_trade_only_intent(text: str) -> bool:
    if not _TRADE_INTENT.search(text):
        return False
    if _TRADE_KNOWLEDGE_BLOCK.search(text):
        return False
    return True


def mentions_knowledge_domain(text: str) -> bool:
    return bool(_KNOWLEDGE_DOMAIN.search(text or ""))


def draft_mentions_game_facts(draft: str) -> bool:
    d = draft or ""
    if not d.strip():
        return False
    if _DRAFT_GAME_FACTS.search(d):
        return True
    if _DRAFT_HEADER.search(d) and _DRAFT_PERCENT.search(d):
        return True
    if _DRAFT_HEADER.search(d) and mentions_knowledge_domain(d):
        return True
    return False


def should_force_rag(
    user_msg: str,
    ctx: Any,
    *,
    draft_text: str = "",
) -> bool:
    if is_rag_exempt(user_msg):
        return False
    if getattr(ctx, "rag_search_calls", 0) > 0:
        return False
    if mentions_knowledge_domain(user_msg):
        return True
    aliases, entities = extract_alias_keywords(user_msg)
    if aliases or entities:
        return True
    if draft_mentions_game_facts(draft_text):
        return True
    return False


_EN_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"召唤|魔物|仆从|灵体"), "minion summon"),
    (re.compile(r"项链"), "amulet"),
    (re.compile(r"戒指"), "ring"),
    (re.compile(r"词缀"), "mods affix"),
    (re.compile(r"升华"), "ascendancy"),
    (re.compile(r"天赋"), "passive skill tree"),
]


def build_forced_rag_query(user_msg: str, draft_hint: str = "") -> str:
    raw = (user_msg or "").strip()
    combined = f"{raw} {draft_hint}".strip()
    if _CJK.search(combined):
        parts: list[str] = []
        for pat, en in _EN_HINTS:
            if pat.search(combined):
                parts.append(en)
        if mentions_knowledge_domain(combined):
            parts.append(combined[:120])
        if parts:
            return " ".join(dict.fromkeys(parts))
    if raw:
        return raw[:200]
    return (draft_hint or "")[:200] or "Path of Exile 2"
