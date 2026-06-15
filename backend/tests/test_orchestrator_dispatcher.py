"""Tests for parallel sub-agent dispatch."""

from unittest.mock import AsyncMock, patch

import pytest

from app.orchestrator.dispatcher import dispatch_parallel
from app.orchestrator.schemas import SkillAgentResult, TaskSpec


@pytest.mark.asyncio
async def test_dispatch_parallel_collects_results():
    tasks = [
        TaskSpec(task_id="a1", agent="encyclopedia", user_phrase="test"),
        TaskSpec(task_id="a2", agent="trade_search", user_phrase="test"),
    ]

    async def fake_run(spec: TaskSpec, *, user_msg: str) -> SkillAgentResult:
        return SkillAgentResult(
            task_id=spec.task_id,
            agent=spec.agent,
            ok=True,
            summary=f"done-{spec.agent}",
        )

    with patch("app.orchestrator.dispatcher.run_task", side_effect=fake_run):
        results = await dispatch_parallel(tasks, user_msg="test")

    assert len(results) == 2
    ids = {r.task_id for r in results}
    assert ids == {"a1", "a2"}


@pytest.mark.asyncio
async def test_dispatch_timeout_marks_failed():
    spec = TaskSpec(
        task_id="slow",
        agent="trade_search",
        user_phrase="x",
        timeout_sec=0.01,
    )

    async def slow_run(_spec: TaskSpec, *, user_msg: str) -> SkillAgentResult:
        import asyncio

        await asyncio.sleep(0.2)
        return SkillAgentResult(task_id="slow", agent="trade_search", ok=True)

    with patch("app.orchestrator.dispatcher.run_task", side_effect=slow_run):
        results = await dispatch_parallel([spec], user_msg="x")

    assert len(results) == 1
    assert results[0].ok is False
    assert "timeout" in (results[0].error or "")


@pytest.mark.asyncio
async def test_dispatch_on_task_done_callback():
    spec = TaskSpec(task_id="cb1", agent="encyclopedia", user_phrase="hi")
    callback = AsyncMock()

    async def fake_run(_spec: TaskSpec, *, user_msg: str) -> SkillAgentResult:
        return SkillAgentResult(task_id="cb1", agent="encyclopedia", ok=True)

    with patch("app.orchestrator.dispatcher.run_task", side_effect=fake_run):
        await dispatch_parallel([spec], user_msg="hi", on_task_done=callback)

    callback.assert_awaited_once()
    assert callback.await_args.args[0].task_id == "cb1"
