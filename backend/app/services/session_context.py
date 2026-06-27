"""Turn-level session context for orchestrator — shared contract across planner and sub-agents."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from app.services.chat_multimodal import (
    DEFAULT_IMAGE_ONLY_PROMPT,
    extract_text,
    message_has_images,
    resolve_user_text,
)
from app.services.chat_tools import find_build_input

# User refers to prior turn without restating the item
_DEICTIC_FOLLOWUP = re.compile(
    r"(这个|这件|那件|这款|上述|上面|刚才|之前|同样|差不多|类似|同款|一样)",
)
_TRADE_PRICE_FOLLOWUP = re.compile(
    r"(多少钱|值多少|什么价|价格|市价|查价|卖多少|多少e|多少d|集市)",
)
_TRADE_REFINE = re.compile(
    r"(不是|别|不要|换|改成|重新搜|错了|别搜|别查)",
)
_TRADE_SEARCH_VERB = re.compile(
    r"(搜|找|买|卖|市价|多少钱|查价|交易|帮我找|帮我搜|trade|集市|价格)",
)
_ITEM_SIGNAL = re.compile(
    r"(词缀|抗性|伤害|等级|\+?\d|稀有|暗金|珠宝|项链|戒指|腰带|手套|鞋子|头盔|胸甲|"
    r"召唤|暴击|生命|魔力|护甲|闪避|能量护盾|ilvl|物等)",
)


def _is_user(msg: dict[str, Any]) -> bool:
    return msg.get("role") == "user"


def _is_assistant(msg: dict[str, Any]) -> bool:
    return msg.get("role") == "assistant"


class SessionContext(BaseModel):
    """Compressed multi-turn state passed into planner and sub-agent payloads."""

    current_user_text: str = ""
    prior_snippet: str = ""
    has_images_current: bool = False
    has_images_in_thread: bool = False
    turn_count: int = 0

    trade_anchor_text: str | None = None
    is_trade_followup: bool = False
    is_trade_refine: bool = False

    pob_input: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    def effective_user_msg(self, *, max_len: int = 2400) -> str:
        """Full context for tools / trade LLM — not just the last utterance."""
        parts: list[str] = []
        if self.prior_snippet.strip():
            parts.append("【对话上下文】\n" + self.prior_snippet.strip())
        cur = self.current_user_text.strip() or (
            DEFAULT_IMAGE_ONLY_PROMPT if self.has_images_current else ""
        )
        if cur:
            parts.append("【当前问题】\n" + cur)
        text = "\n\n".join(parts)
        return text[:max_len] if len(text) > max_len else text

    def trade_search_query(self) -> str:
        """Distilled trade query — never pass bare complaint text when anchor exists."""
        cur = (self.current_user_text or "").strip()
        anchor = (self.trade_anchor_text or "").strip()

        if self.is_trade_refine and anchor:
            return f"{anchor}（用户更正：{cur}）"[:500]

        if self.is_trade_followup and anchor:
            if _TRADE_PRICE_FOLLOWUP.search(cur) and not _ITEM_SIGNAL.search(cur):
                return anchor[:400]
            if len(cur) < 80 and anchor not in cur:
                return f"{anchor}；{cur}"[:500]
            return cur[:400] or anchor[:400]

        if self.has_images_current and not _TRADE_SEARCH_VERB.search(cur):
            return cur[:400] or DEFAULT_IMAGE_ONLY_PROMPT[:200]

        return cur[:400]

    def rag_query_text(self) -> str:
        """RAG / build agents: current question enriched with anchor entity context."""
        cur = (self.current_user_text or "").strip()
        anchor = (self.trade_anchor_text or "").strip()
        if anchor and len(cur) < 60 and anchor not in cur:
            return f"{cur}（上下文：{anchor[:200]}）"[:300]
        return cur[:300]


def _score_trade_anchor(text: str, *, has_images: bool) -> int:
    score = 0
    if has_images:
        score += 12
    if len(text) > 40:
        score += 3
    if len(text) > 100:
        score += 2
    if _ITEM_SIGNAL.search(text):
        score += 6
    if _TRADE_REFINE.search(text):
        score -= 5
    if len(text) < 15 and _DEICTIC_FOLLOWUP.search(text):
        score -= 8
    return score


def _find_trade_anchor(messages: list[dict[str, Any]], *, skip_last: bool) -> str | None:
    pool = messages[:-1] if skip_last and messages else messages
    best_text: str | None = None
    best_score = 0
    for msg in reversed(pool):
        if not _is_user(msg):
            continue
        text = extract_text(msg).strip()
        if not text and not message_has_images(msg):
            continue
        if not text and message_has_images(msg):
            text = DEFAULT_IMAGE_ONLY_PROMPT
        score = _score_trade_anchor(text, has_images=message_has_images(msg))
        if score > best_score:
            best_score = score
            best_text = text
    return best_text if best_score >= 5 else None


def _build_prior_snippet(messages: list[dict[str, Any]], *, max_chars: int = 1200) -> str:
    """Last few turns for synthesis / tools (no images)."""
    if len(messages) <= 1:
        return ""
    tail = messages[-5:-1] if len(messages) > 5 else messages[:-1]
    lines: list[str] = []
    for msg in tail:
        role = msg.get("role")
        text = extract_text(msg).strip()
        if not text:
            if _is_user(msg) and message_has_images(msg):
                text = "(用户发送了装备截图)"
            else:
                continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {text[:400]}")
    blob = "\n".join(lines)
    return blob[-max_chars:] if len(blob) > max_chars else blob


def _detect_trade_signals(
    current: str,
    *,
    has_anchor: bool,
    has_images: bool,
) -> tuple[bool, bool]:
    cur = (current or "").strip()
    is_refine = bool(_TRADE_REFINE.search(cur))
    is_followup = False
    if has_anchor or has_images:
        short = len(cur) < 90
        if short and (
            _DEICTIC_FOLLOWUP.search(cur)
            or _TRADE_PRICE_FOLLOWUP.search(cur)
            or is_refine
        ):
            is_followup = True
        if has_images and _TRADE_PRICE_FOLLOWUP.search(cur):
            is_followup = True
    return is_followup, is_refine


def build_session_context(messages: list[dict[str, Any]] | None) -> SessionContext:
    """Build SessionContext from full chat history (stateless API)."""
    msgs = messages or []
    current = resolve_user_text(msgs)
    last = msgs[-1] if msgs else {}
    has_images_current = message_has_images(last)
    has_images_thread = any(message_has_images(m) for m in msgs if _is_user(m))

    user_turns = sum(1 for m in msgs if _is_user(m))
    prior_snippet = _build_prior_snippet(msgs)
    pob_input = find_build_input(current) if current else None

    cur_stripped = (current or "").strip()
    likely_followup = bool(
        _DEICTIC_FOLLOWUP.search(cur_stripped)
        or _TRADE_PRICE_FOLLOWUP.search(cur_stripped)
        or _TRADE_REFINE.search(cur_stripped)
    )
    anchor = _find_trade_anchor(msgs, skip_last=likely_followup)
    is_followup, is_refine = _detect_trade_signals(
        current,
        has_anchor=bool(anchor),
        has_images=has_images_current,
    )

    return SessionContext(
        current_user_text=current,
        prior_snippet=prior_snippet,
        has_images_current=has_images_current,
        has_images_in_thread=has_images_thread,
        turn_count=user_turns,
        trade_anchor_text=anchor,
        is_trade_followup=is_followup,
        is_trade_refine=is_refine,
        pob_input=pob_input,
    )
