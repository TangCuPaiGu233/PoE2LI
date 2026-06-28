"""Orchestrator smoke tests — verify imports and basic wiring without calling LLM."""

from __future__ import annotations

import pytest

from app.orchestrator.schemas import AgentName, DispatchPlan, SkillAgentResult, TaskSpec
from app.services.session_context import SessionContext, build_session_context
from app.services.chat_agent import stream_chat_agent
from app.services.chat_orchestrator import stream_chat_orchestrator


def test_import_stream_chat_orchestrator():
    """stream_chat_orchestrator should be importable and callable."""
    assert callable(stream_chat_orchestrator)


def test_import_stream_chat_agent():
    """stream_chat_agent should be importable and callable."""
    assert callable(stream_chat_agent)


def test_build_session_context_empty():
    ctx = build_session_context([])
    assert isinstance(ctx, SessionContext)
    assert ctx.current_user_text == ""
    assert ctx.turn_count == 0


def test_build_session_context_with_messages():
    messages = [
        {"role": "user", "content": "我在看一件稀有项链，+2 召唤技能等级，血唤"},
        {"role": "assistant", "content": "这件装备看起来不错，你需要什么帮助？"},
        {"role": "user", "content": "这件装备多少钱"},
    ]
    ctx = build_session_context(messages)
    assert isinstance(ctx, SessionContext)
    assert ctx.current_user_text == "这件装备多少钱"
    assert ctx.turn_count == 2
    assert ctx.is_trade_followup or ctx.is_trade_refine or ctx.trade_anchor_text


def test_task_spec_creation():
    task = TaskSpec(
        task_id="smoke-1",
        agent="encyclopedia",
        user_phrase="测试",
        payload={"query": "测试"},
    )
    assert task.agent == "encyclopedia"
    assert task.user_phrase == "测试"
    assert task.payload["query"] == "测试"


def test_skill_agent_result_creation():
    result = SkillAgentResult(
        task_id="smoke-2",
        agent="trade_search",
        ok=True,
        summary="找到 3 个结果",
        trade_data={"count": 3},
    )
    assert result.task_id == "smoke-2"
    assert result.ok is True
    assert result.summary == "找到 3 个结果"
    assert result.trade_data["count"] == 3


def test_dispatch_plan_creation():
    plan = DispatchPlan(
        tasks=[
            TaskSpec(task_id="t1", agent="encyclopedia", user_phrase="q1"),
            TaskSpec(task_id="t2", agent="trade_search", user_phrase="q2"),
        ],
        planning_note="smoke",
    )
    assert len(plan.tasks) == 2
    assert plan.planning_note == "smoke"


def test_agent_name_literal():
    """AgentName should accept all defined agent names."""
    valid_names = [
        "trade_search",
        "encyclopedia",
        "build_design",
        "recommend",
        "decode_pob",
    ]
    for name in valid_names:
        assert name in AgentName.__args__  # type: ignore[attr-defined]
