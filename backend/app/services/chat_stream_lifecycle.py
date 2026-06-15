"""SSE stream lifecycle — wall-clock budget, guaranteed done, structured logs."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

logger = logging.getLogger(__name__)

CHAT_WALL_CLOCK_SEC = float(os.getenv("CHAT_WALL_CLOCK_SEC", "90"))


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


async def wrap_chat_stream(
    req_id: str,
    user_msg: str,
    intent: str,
    source: AsyncIterator[dict[str, Any]],
    *,
    budget_sec: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Wrap any chat handler stream: budget check, error → answer, finally done."""
    budget = budget_sec if budget_sec is not None else CHAT_WALL_CLOCK_SEC
    start = time.monotonic()
    done_sent = False
    trade_calls = 0
    extract_count: int | None = None
    error: str | None = None

    try:
        async for event in source:
            if time.monotonic() - start > budget:
                yield {
                    "type": "answer",
                    "content": "\n\n*(已达本轮时间上限，以上为已有结果。)*\n",
                }
                break

            etype = event.get("type")
            if etype == "trade_result":
                trade_calls += 1
            if etype == "handler_meta" and isinstance(event.get("content"), dict):
                meta = event["content"]
                if "extract_count" in meta:
                    extract_count = int(meta["extract_count"])

            yield event
            if etype == "done":
                done_sent = True
                return
    except Exception as e:
        error = str(e)
        logger.exception("[CHAT] stream error req_id=%s intent=%s", req_id, intent)
        yield {"type": "answer", "content": f"\n\n处理出错：{e}\n"}
        yield {"type": "error", "content": error}
    finally:
        if not done_sent:
            yield {"type": "done"}
        duration_ms = int((time.monotonic() - start) * 1000)
        log_payload = {
            "req_id": req_id,
            "intent": intent,
            "extract_count": extract_count,
            "trade_calls": trade_calls,
            "fallback": False,
            "duration_ms": duration_ms,
            "error": error,
            "query_preview": (user_msg or "")[:120],
        }
        logger.info("[CHAT] decision %s", json.dumps(log_payload, ensure_ascii=False))
