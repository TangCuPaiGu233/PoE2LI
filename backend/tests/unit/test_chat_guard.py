"""Unit tests for chat_guard helpers (R-03/R-04/R-05)."""

from __future__ import annotations

import asyncio

import pytest

from app.services.chat_guard import (
    ToolFailureTracker,
    ToolLoopDedup,
    retry_with_backoff,
    should_abort_on_failure,
)

# ── R-03: retry_with_backoff ────────────────────────────────────────


class _FailingThenSucceeding:
    """Callable that raises N times then returns a value."""

    def __init__(self, fail_count: int = 2, exc=TimeoutError("boom")):
        self.fail_count = fail_count
        self.exc = exc
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise self.exc
        return "ok"


@pytest.mark.asyncio
async def test_retry_eventually_succeeds():
    fn = _FailingThenSucceeding(fail_count=2)
    result = await retry_with_backoff(fn, max_attempts=5, base_delay=0.01)
    assert result == "ok"
    assert fn.calls == 3


@pytest.mark.asyncio
async def test_retry_exhausts_and_raises():
    fn = _FailingThenSucceeding(fail_count=5)
    with pytest.raises(TimeoutError):
        await retry_with_backoff(fn, max_attempts=3, base_delay=0.01)
    assert fn.calls == 3


@pytest.mark.asyncio
async def test_retry_non_retryable_raises_immediately():
    call_count = 0

    async def bad():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        await retry_with_backoff(
            bad,
            max_attempts=3,
            base_delay=0.01,
            retryable=(TimeoutError,),
        )
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_delay_increases():
    delays = []

    async def flaky():
        raise TimeoutError("boom")

    with pytest.raises(TimeoutError):
        await retry_with_backoff(
            flaky,
            max_attempts=3,
            base_delay=0.05,
            jitter=0,
            on_retry=lambda attempt, exc, delay: delays.append(delay),
        )
    assert len(delays) == 2
    assert delays[0] == pytest.approx(0.05, abs=0.01)
    assert delays[1] == pytest.approx(0.10, abs=0.02)


# ── R-04: ToolFailureTracker ───────────────────────────────────────


def test_tool_failure_tracker_defaults():
    tracker = ToolFailureTracker()
    assert tracker.consecutive_failures == 0
    assert tracker.by_tool == {}


def test_tool_failure_tracker_counts_consecutive():
    tracker = ToolFailureTracker()
    tracker.record_failure("trade_search")
    assert tracker.consecutive_failures == 1
    assert tracker.by_tool["trade_search"] == 1

    tracker.record_success()
    assert tracker.consecutive_failures == 0
    assert tracker.by_tool["trade_search"] == 1  # 历史保留


def test_tool_failure_tracker_critical_thresholds():
    tracker = ToolFailureTracker()
    for _ in range(2):
        tracker.record_failure("decode_pob")
    assert tracker.should_abort_critical("decode_pob") is True
    assert tracker.should_abort_general() is False

    tracker2 = ToolFailureTracker()
    for _ in range(3):
        tracker2.record_failure("rag_search")
    assert tracker2.should_abort_critical("rag_search") is False
    assert tracker2.should_abort_general() is True


def test_tool_failure_tracker_reset_on_success():
    tracker = ToolFailureTracker()
    tracker.record_failure("trade_search")
    tracker.record_failure("trade_search")
    tracker.record_success()
    assert tracker.consecutive_failures == 0
    assert tracker.should_abort_general() is False


# ── R-04: should_abort_on_failure 组合逻辑 ────────────────────────


def test_should_abort_after_three_consecutive():
    tracker = ToolFailureTracker()
    assert should_abort_on_failure("trade_search", tracker) is False
    tracker.record_failure("trade_search")
    assert should_abort_on_failure("trade_search", tracker) is False
    tracker.record_failure("trade_search")
    assert should_abort_on_failure("trade_search", tracker) is False
    tracker.record_failure("trade_search")
    assert should_abort_on_failure("trade_search", tracker) is True
    tracker.record_failure("trade_search")
    assert should_abort_on_failure("trade_search", tracker) is True


def test_should_abort_decode_pob_after_two():
    tracker = ToolFailureTracker()
    assert should_abort_on_failure("decode_pob", tracker) is False
    tracker.record_failure("decode_pob")
    # After 1 failure, decode_pob threshold (2) not yet reached
    assert should_abort_on_failure("decode_pob", tracker) is False
    tracker.record_failure("decode_pob")
    # After 2 failures, should abort
    assert should_abort_on_failure("decode_pob", tracker) is True


# ── R-05: ToolLoopDedup ────────────────────────────────────────────


def test_dedup_allows_first_call():
    dedup = ToolLoopDedup()
    assert dedup.is_duplicate("trade_search", {"query": "法师之血"}) is False


def test_dedup_blocks_exact_duplicate():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "法师之血"})
    assert dedup.is_duplicate("trade_search", {"query": "法师之血"}) is True


def test_dedup_allows_different_tool():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "法师之血"})
    assert dedup.is_duplicate("rag_search", {"query": "法师之血"}) is False


def test_dedup_similar_query_detected():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "法师之血 腰带"})
    # 高 Jaccard similarity 应被视为重复
    assert dedup.is_duplicate("trade_search", {"query": "腰带 法师之血"}) is True


def test_dedup_unrelated_query_allowed():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "法师之血"})
    assert dedup.is_duplicate("trade_search", {"query": "猎首"}) is False


def test_dedup_record_updates_history():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "a"})
    dedup.record("trade_search", {"query": "b"})
    assert len(dedup.history) == 2
    assert dedup.history[-1]["args"]["query"] == "b"
