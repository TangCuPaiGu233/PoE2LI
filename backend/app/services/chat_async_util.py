"""Async helpers for chat handlers — sync offload with timeouts."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

DEFAULT_SYNC_TIMEOUT_SEC = float(os.getenv("CHAT_SYNC_TIMEOUT_SEC", "45"))
TRADE_SEARCH_TIMEOUT_SEC = float(os.getenv("CHAT_TRADE_SEARCH_TIMEOUT_SEC", "120"))
TRADE_QUOTE_TIMEOUT_SEC = float(os.getenv("CHAT_TRADE_QUOTE_TIMEOUT_SEC", "35"))
LLM_EXTRACT_TIMEOUT_SEC = float(os.getenv("CHAT_LLM_EXTRACT_TIMEOUT_SEC", "30"))


async def run_sync_with_timeout(
    fn: Callable[..., T],
    /,
    *args,
    timeout: float | None = None,
    **kwargs,
) -> T:
    """Run blocking work in a thread with asyncio.wait_for."""
    limit = timeout if timeout is not None else DEFAULT_SYNC_TIMEOUT_SEC
    return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=limit)
