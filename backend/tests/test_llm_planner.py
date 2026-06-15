"""Tests for LLM orchestrator planner (unit, mocked LLM)."""

import json
from unittest.mock import MagicMock, patch

from app.orchestrator.llm_planner import llm_plan_dispatch


def _fake_completion(content: str):
    msg = MagicMock()
    msg.content = content
    msg.reasoning_content = None
    msg.model_extra = {}
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@patch("openai.OpenAI")
def test_llm_planner_parses_tasks(mock_openai_cls):
    payload = {
        "tasks": [
            {"agent": "build_design", "query": "灵魂行者 偶像词缀 搭配"},
        ],
        "reasoning": "配装问题",
    }
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.chat.completions.create.return_value = _fake_completion(json.dumps(payload))

    messages = [
        {"role": "user", "content": "灵魂行者的偶像词缀装备如何搭配"},
    ]
    plan = llm_plan_dispatch(messages)
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "build_design"
    assert "llm:" in plan.planning_note


@patch("openai.OpenAI")
def test_llm_planner_fallback_on_bad_json(mock_openai_cls):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.chat.completions.create.return_value = _fake_completion("not json")

    plan = llm_plan_dispatch([{"role": "user", "content": "火焰伤害怎么算"}])
    assert len(plan.tasks) >= 1
    assert plan.tasks[0].agent == "encyclopedia"
