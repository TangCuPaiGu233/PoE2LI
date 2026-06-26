"""Unit tests for R-01 Orchestrator truncation guards."""

from __future__ import annotations

import pytest

from app.orchestrator.llm_planner import _conversation_for_planner
from app.orchestrator.session_context import build_session_context
from app.services.chat_orchestrator import _build_synthesis_messages
from app.orchestrator.schemas import SkillAgentResult, TaskSpec


# ── R-01 Planner input control ─────────────────────────────────────


def test_conversation_for_planner_respects_max_turns():
    messages = [
        {"role": "user", "content": f"turn {i}"} for i in range(12)
    ]
    convo = _conversation_for_planner(messages, max_turns=8)
    lines = [ln for ln in convo.splitlines() if ln.startswith("用户: ")]
    assert len(lines) <= 8


def test_conversation_for_planner_truncates_long_text():
    messages = [
        {"role": "user", "content": "A" * 1000},
        {"role": "assistant", "content": "B" * 1000},
    ]
    convo = _conversation_for_planner(messages, max_turns=2)
    assert len(convo) <= 1200 + 20  # 600 per turn + labels/newlines


def test_build_synthesis_messages_respects_prior_snippet_limit():
    long_snippet = "用户: " + "X" * 5000
    results = [
        SkillAgentResult(
            task_id="t1",
            agent="encyclopedia",
            ok=True,
            summary="short",
        )
    ]
    msgs = _build_synthesis_messages(
        user_msg="test",
        results=results,
        has_images=False,
        prior_snippet=long_snippet,
    )
    user_body = msgs[-1]["content"]
    assert "对话上下文" in user_body
    assert len(user_body) <= 8000  # loose upper bound


def test_build_synthesis_messages_without_prior_snippet():
    results = [
        SkillAgentResult(
            task_id="t1",
            agent="trade_search",
            ok=True,
            summary="trade result",
            trade_data={"best_match": {"label": "法师之血", "count": 5}},
        )
    ]
    msgs = _build_synthesis_messages(
        user_msg="值多少钱",
        results=results,
        has_images=False,
    )
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert "子 Agent 结果" in msgs[-1]["content"]
