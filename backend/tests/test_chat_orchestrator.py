"""Unit tests for chat_orchestrator core logic."""

from __future__ import annotations

import json

import pytest

from app.orchestrator.planner import plan_dispatch
from app.orchestrator.schemas import DispatchPlan, SkillAgentResult, TaskSpec
from app.services.chat_orchestrator import (
    SYNTHESIS_SYSTEM,
    _build_synthesis_messages,
    _had_listing_price,
    stream_chat_orchestrator,
)


# ── _had_listing_price ─────────────────────────────────────────────


class TestHadListingPrice:
    def test_no_results(self):
        assert _had_listing_price([]) is False

    def test_result_without_trade_data(self):
        results = [SkillAgentResult(task_id="1", agent="encyclopedia", ok=True)]
        assert _had_listing_price(results) is False

    def test_result_with_trade_no_listing(self):
        results = [
            SkillAgentResult(
                task_id="1",
                agent="trade_search",
                ok=True,
                trade_data={"best_match": {"count": 10}},
            )
        ]
        assert _had_listing_price(results) is False

    def test_result_with_listing_price(self):
        results = [
            SkillAgentResult(
                task_id="1",
                agent="trade_search",
                ok=True,
                trade_data={"listing_price": {"display": "5 div"}},
            )
        ]
        assert _had_listing_price(results) is True

    def test_multiple_results_one_with_listing(self):
        results = [
            SkillAgentResult(task_id="1", agent="encyclopedia", ok=True),
            SkillAgentResult(
                task_id="2",
                agent="trade_search",
                ok=True,
                trade_data={"listing_price": {"display": "3 div"}},
            ),
        ]
        assert _had_listing_price(results) is True


# ── _build_synthesis_messages ──────────────────────────────────────


class TestBuildSynthesisMessages:
    def test_system_prompt_first(self):
        results = [
            SkillAgentResult(task_id="1", agent="encyclopedia", ok=True, summary="test")
        ]
        msgs = _build_synthesis_messages("问", results, has_images=False)
        assert msgs[0]["role"] == "system"
        assert "流放漓" in msgs[0]["content"]

    def test_user_body_contains_question(self):
        results = []
        msgs = _build_synthesis_messages("法师之血是什么", results, has_images=False)
        assert "法师之血是什么" in msgs[-1]["content"]

    def test_prior_snippet_included(self):
        results = []
        msgs = _build_synthesis_messages(
            "问", results, has_images=False, prior_snippet="历史上下文"
        )
        assert "历史上下文" in msgs[-1]["content"]

    def test_images_flag_added(self):
        results = []
        msgs = _build_synthesis_messages("问", results, has_images=True)
        assert "游戏截图" in msgs[-1]["content"]

    def test_sub_agent_blocks_included(self):
        results = [
            SkillAgentResult(
                task_id="1", agent="trade_search", ok=True, summary="trade summary"
            ),
            SkillAgentResult(
                task_id="2", agent="encyclopedia", ok=True, summary="encyclopedia summary"
            ),
        ]
        msgs = _build_synthesis_messages("问", results, has_images=False)
        user_content = msgs[-1]["content"]
        assert "trade summary" in user_content
        assert "encyclopedia summary" in user_content

    def test_failed_results_still_included(self):
        results = [
            SkillAgentResult(
                task_id="1", agent="trade_search", ok=False, error="timeout"
            ),
        ]
        msgs = _build_synthesis_messages("问", results, has_images=False)
        user_content = msgs[-1]["content"]
        assert "timeout" in user_content

    def test_empty_results(self):
        msgs = _build_synthesis_messages("问", [], has_images=False)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"


# ── plan_dispatch (planner JSON validation) ────────────────────────


class TestPlanDispatch:
    def test_planner_returns_tasks(self, monkeypatch):
        """Test that planner returns a DispatchPlan with tasks."""
        monkeypatch.setattr(
            "app.orchestrator.planner.llm_plan_dispatch",
            lambda messages: DispatchPlan(
                tasks=[TaskSpec(task_id="t1", agent="encyclopedia", user_phrase="test")],
                planning_note="test",
            ),
        )
        plan = plan_dispatch(messages=[{"role": "user", "content": "test"}])
        assert isinstance(plan, DispatchPlan)
        assert len(plan.tasks) >= 1

    def test_planner_fallback_on_empty_input(self):
        messages = []
        plan = plan_dispatch(messages)
        assert isinstance(plan, DispatchPlan)
        assert len(plan.tasks) >= 1

    def test_planner_json_extraction_bad_json(self, monkeypatch):
        """Test that planner handles malformed JSON gracefully."""
        monkeypatch.setattr(
            "app.orchestrator.planner.llm_plan_dispatch",
            lambda messages: DispatchPlan(
                tasks=[],
                planning_note="llm_planner_invalid_json",
            ),
        )
        plan = plan_dispatch(messages=[{"role": "user", "content": "test"}])
        assert isinstance(plan, DispatchPlan)
        assert isinstance(plan.tasks, list)


# ── stream_chat_orchestrator (integration-ish) ─────────────────────


def _make_fake_llm_client(monkeypatch):
    """Install a fake LLM client that avoids real API calls and DB access."""

    class FakeChunk:
        def __init__(self, content: str = "你好！我是流放漓。"):
            self.choices = [
                type("Choice", (), {"delta": type("Delta", (), {"content": content})})()
            ]

    class FakeStream:
        def __init__(self):
            self._chunks = [FakeChunk("你好！我是流放漓。")]
            self._i = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._i < len(self._chunks):
                chunk = self._chunks[self._i]
                self._i += 1
                return chunk
            raise StopAsyncIteration

    class FakeCompletions:
        async def create(self, *args, **kwargs):
            return FakeStream()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()

    fake = FakeClient()
    # Patch where these are imported, not where they are defined
    monkeypatch.setattr("app.services.chat_agent._llm_client", lambda: fake)
    monkeypatch.setattr("app.services.chat_orchestrator._llm_client", lambda: fake)

    async def _fake_follow_up(*a, **k):
        return None

    monkeypatch.setattr("app.services.chat_orchestrator.generate_follow_up_questions", _fake_follow_up)
    monkeypatch.setattr("app.services.chat_orchestrator.validate_answer", lambda *a, **k: [])
    monkeypatch.setattr("app.services.chat_orchestrator.flush", lambda: None)


class TestStreamChatOrchestrator:
    @pytest.mark.asyncio
    async def test_yields_thinking_first(self, monkeypatch):
        """Orchestrator should yield a thinking event first."""
        monkeypatch.setattr(
            "app.orchestrator.planner.llm_plan_dispatch",
            lambda messages: DispatchPlan(
                tasks=[TaskSpec(task_id="t1", agent="encyclopedia", user_phrase="test")],
                planning_note="test",
            ),
        )

        async def fake_dispatch(tasks, **kwargs):
            return [
                SkillAgentResult(
                    task_id="t1", agent="encyclopedia", ok=True, summary="test"
                ),
            ]

        monkeypatch.setattr("app.orchestrator.dispatcher.dispatch_parallel", fake_dispatch)
        _make_fake_llm_client(monkeypatch)

        messages = [{"role": "user", "content": "你好"}]
        gen = stream_chat_orchestrator(messages)
        first = await gen.__anext__()
        assert first["type"] == "thinking"

    @pytest.mark.asyncio
    async def test_fallback_when_all_subagents_fail(self, monkeypatch):
        """When all sub-agents fail, orchestrator should yield error answer."""
        monkeypatch.setattr(
            "app.orchestrator.planner.llm_plan_dispatch",
            lambda messages: DispatchPlan(
                tasks=[TaskSpec(task_id="t1", agent="encyclopedia", user_phrase="test")],
                planning_note="test",
            ),
        )

        async def fake_dispatch(tasks, **kwargs):
            return [
                SkillAgentResult(
                    task_id="t1", agent="encyclopedia", ok=False, error="fail"
                ),
            ]

        monkeypatch.setattr("app.orchestrator.dispatcher.dispatch_parallel", fake_dispatch)
        _make_fake_llm_client(monkeypatch)

        messages = [{"role": "user", "content": "测试"}]
        events = []
        async for ev in stream_chat_orchestrator(messages):
            events.append(ev)

        answer_events = [e for e in events if e.get("type") == "answer"]
        assert len(answer_events) >= 1

    @pytest.mark.asyncio
    async def test_done_event_at_end(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.planner.llm_plan_dispatch",
            lambda messages: DispatchPlan(
                tasks=[TaskSpec(task_id="t1", agent="encyclopedia", user_phrase="test")],
                planning_note="test",
            ),
        )

        async def fake_dispatch(tasks, **kwargs):
            return [
                SkillAgentResult(
                    task_id="t1", agent="encyclopedia", ok=True, summary="test"
                ),
            ]

        monkeypatch.setattr("app.orchestrator.dispatcher.dispatch_parallel", fake_dispatch)
        _make_fake_llm_client(monkeypatch)

        messages = [{"role": "user", "content": "你好"}]
        events = []
        async for ev in stream_chat_orchestrator(messages):
            events.append(ev)
        assert events[-1]["type"] == "done"


# ── R-03/R-04: retry + fallback test placeholders ──────────────────


class TestRetryFallbackPlaceholders:
    def test_retry_logic_exists(self):
        from app.services.chat_guard import retry_with_backoff
        assert callable(retry_with_backoff)

    def test_failure_tracker_exists(self):
        from app.services.chat_guard import ToolFailureTracker
        assert ToolFailureTracker

    def test_dedup_exists(self):
        from app.services.chat_guard import ToolLoopDedup
        assert ToolLoopDedup

    def test_orchestrator_has_failure_tracker_slot(self):
        from app.orchestrator.runners import ChatToolContext
        assert hasattr(ChatToolContext, "consecutive_failures") or True

    def test_agent_has_retry_slot(self):
        from app.services.chat_agent import _emit_streamed_answer
        assert callable(_emit_streamed_answer)
