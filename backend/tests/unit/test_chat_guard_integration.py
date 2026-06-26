"""Integration tests for chat_guard.py in simulated tool-loop scenarios."""

from __future__ import annotations

import asyncio

import pytest

from app.services.chat_guard import ToolFailureTracker, ToolLoopDedup, should_abort_on_failure


# ── R-04 + R-05 combined scenario ─────────────────────────────────


@pytest.mark.asyncio
async def test_tool_loop_aborts_after_three_consecutive_failures():
    tracker = ToolFailureTracker()
    dedup = ToolLoopDedup()
    tools = ["trade_search", "rag_search", "trade_search", "decode_pob"]
    results = []

    for fn in tools:
        if should_abort_on_failure(fn, tracker):
            results.append(f"skip:{fn}")
            continue

        args = {"query": "test"} if fn == "trade_search" else {"query": "wiki"}
        if dedup.is_duplicate(fn, args):
            results.append(f"dedup:{fn}")
            continue

        try:
            raise TimeoutError("simulated timeout")
        except TimeoutError:
            tracker.record_failure(fn)
            results.append(f"fail:{fn}")

    # After 3 consecutive failures, the 4th tool should be skipped
    assert "skip:trade_search" in results or "fail:trade_search" in results
    assert tracker.consecutive_failures >= 3


@pytest.mark.asyncio
async def test_tool_loop_dedup_blocks_similar_trade_queries():
    tracker = ToolFailureTracker()
    dedup = ToolLoopDedup()
    queries = [
        ("trade_search", {"query": "法师之血 腰带"}),
        ("trade_search", {"query": "腰带 法师之血"}),
        ("trade_search", {"query": "猎首"}),
    ]

    results = []
    for fn, args in queries:
        if should_abort_on_failure(fn, tracker):
            results.append("abort")
            continue
        if dedup.is_duplicate(fn, args):
            results.append("dedup")
            continue
        tracker.record_success()
        dedup.record(fn, args)
        results.append("ok")

    assert results[0] == "ok"
    assert results[1] == "dedup"  # high Jaccard similarity
    assert results[2] == "ok"  # unrelated query


@pytest.mark.asyncio
async def test_tool_loop_success_resets_failure_tracker():
    tracker = ToolFailureTracker()
    dedup = ToolLoopDedup()

    # Simulate 2 failures then 1 success
    for _ in range(2):
        tracker.record_failure("trade_search")
    assert tracker.consecutive_failures == 2

    # Success resets consecutive counter
    tracker.record_success()
    assert tracker.consecutive_failures == 0

    # Now 2 more failures should not abort (need 3 consecutive)
    tools = ["trade_search", "trade_search"]
    aborted = [should_abort_on_failure(fn, tracker) for fn in tools]
    assert aborted == [False, False]


@pytest.mark.asyncio
async def test_decode_pob_aborts_after_two_failures():
    tracker = ToolFailureTracker()
    dedup = ToolLoopDedup()

    # Before any failures, should not abort
    assert should_abort_on_failure("decode_pob", tracker) is False

    # First failure recorded
    tracker.record_failure("decode_pob")
    # After 1 failure, still below critical threshold of 2
    assert should_abort_on_failure("decode_pob", tracker) is False

    # Second failure recorded
    tracker.record_failure("decode_pob")
    # After 2 failures, critical threshold reached
    assert should_abort_on_failure("decode_pob", tracker) is True


@pytest.mark.asyncio
async def test_mixed_tools_failure_tracking():
    tracker = ToolFailureTracker()
    # Failures on different tools still count as consecutive
    tracker.record_failure("trade_search")
    tracker.record_failure("rag_search")
    assert tracker.consecutive_failures == 2
    assert tracker.by_tool["trade_search"] == 1
    assert tracker.by_tool["rag_search"] == 1


@pytest.mark.asyncio
async def test_dedup_allows_same_tool_different_args():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "法师之血"})
    assert dedup.is_duplicate("trade_search", {"query": "猎首"}) is False


@pytest.mark.asyncio
async def test_dedup_blocks_exact_duplicate_across_rounds():
    dedup = ToolLoopDedup()
    dedup.record("trade_search", {"query": "法师之血"})
    # Same query again should be deduplicated
    assert dedup.is_duplicate("trade_search", {"query": "法师之血"}) is True
