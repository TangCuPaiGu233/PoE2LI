"""Tests for chat stream lifecycle wrapper."""

import pytest

from app.services.chat_stream_lifecycle import wrap_chat_stream


async def _events(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_wrap_guarantees_done():
    async def source():
        yield {"type": "answer", "content": "hi"}

    out = []
    async for ev in wrap_chat_stream("req1", "hello", "test", source()):
        out.append(ev)
    assert out[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_wrap_passes_through_existing_done():
    async def source():
        yield {"type": "answer", "content": "hi"}
        yield {"type": "done"}

    out = []
    async for ev in wrap_chat_stream("req2", "hello", "test", source()):
        out.append(ev)
    assert sum(1 for e in out if e["type"] == "done") == 1
