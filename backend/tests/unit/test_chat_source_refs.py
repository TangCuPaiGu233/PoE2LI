"""Unit tests for R-02 source_refs tracing and price-claim guard."""

from __future__ import annotations

import pytest

from app.services.chat_response_guard import strip_ungrounded_price_claims
from app.orchestrator.schemas import SkillAgentResult


# ── R-02 price guard behavior ──────────────────────────────────────


def test_strip_ungrounded_price_claims_noop_when_listing_present():
    text = "市集参考价：5 divine"
    out = strip_ungrounded_price_claims(text, had_listing=True)
    assert out == text


def test_strip_ungrounded_price_claims_appends_warning_when_no_listing():
    text = "大概 3-8 崇高"
    out = strip_ungrounded_price_claims(text, had_listing=False)
    assert "未能从市集读取在售标价" in out
    assert "3-8 崇高" in out


def test_strip_ungrounded_price_claims_noop_when_no_price():
    text = "这个装备很适合召唤"
    out = strip_ungrounded_price_claims(text, had_listing=False)
    assert out == text


# ── R-02 source_refs scaffold tests ────────────────────────────────


def test_skill_agent_result_synthesis_block_includes_warnings():
    r = SkillAgentResult(
        task_id="t1",
        agent="trade_search",
        ok=True,
        summary="trade summary",
        warnings=["无在售标价样本，禁止编造具体价格"],
        trade_data={"best_match": {"label": "法师之血", "count": 1}},
    )
    block = r.to_synthesis_block()
    assert "warnings" in block
    assert "无在售标价样本" in block


def test_skill_agent_result_synthesis_block_without_trade_data():
    r = SkillAgentResult(
        task_id="t2",
        agent="encyclopedia",
        ok=True,
        summary="wiki summary",
    )
    block = r.to_synthesis_block()
    assert "encyclopedia" in block
    assert "wiki summary" in block
