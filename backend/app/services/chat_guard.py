"""Chat guard helpers: retry, failure tracking, dedup — extracted from R-03/R-04/R-05 plans."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

# ── R-03: retry_with_backoff ────────────────────────────────────────

_DEFAULT_RETRYABLE: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError, OSError)


async def retry_with_backoff(
    fn: Callable[..., Any],
    /,
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    jitter: float = 0.25,
    retryable: tuple[type[BaseException], ...] = _DEFAULT_RETRYABLE,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Call *fn* with exponential backoff retry.

    Returns the first successful result.  If all attempts fail, re-raises the
    last exception.

    Parameters
    ----------
    fn:
        Async callable to invoke.
    max_attempts:
        Total attempts including the first call.  Must be >= 1.
    base_delay:
        Initial delay in seconds between retries.  Actual delay = base_delay
        * 2**(attempt-1) +/- jitter.
    jitter:
        Random jitter fraction applied to each delay (0 = no jitter).
    retryable:
        Exception types that trigger a retry.  Anything else propagates
        immediately.
    on_retry:
        Optional callback ``(attempt_number, exception, delay_seconds)``
        invoked after each failed attempt before sleeping.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                if jitter:
                    delay *= 1 + random.uniform(-jitter, jitter)
                logger.warning(
                    "[CHAT_GUARD] retry attempt=%d/%d after %.2fs: %s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    exc,
                )
                if on_retry is not None:
                    on_retry(attempt, exc, delay)
                await asyncio.sleep(delay)
        except Exception:
            raise

    raise last_exc  # type: ignore[misc]


# ── R-04: ToolFailureTracker ───────────────────────────────────────

# Decode PoB is critical: if the same input fails twice, retrying is pointless.
_CRITICAL_TOOL_THRESHOLDS: dict[str, int] = {
    "decode_pob": 2,
}


@dataclass
class ToolFailureTracker:
    """Track consecutive tool failures across the agent loop."""

    consecutive_failures: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)

    def record_failure(self, tool_name: str) -> None:
        self.consecutive_failures += 1
        self.by_tool[tool_name] = self.by_tool.get(tool_name, 0) + 1

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def should_abort_general(self, threshold: int = 3) -> bool:
        return self.consecutive_failures >= threshold

    def should_abort_critical(self, tool_name: str) -> bool:
        threshold = _CRITICAL_TOOL_THRESHOLDS.get(tool_name, 999)
        return self.by_tool.get(tool_name, 0) >= threshold


def should_abort_on_failure(tool_name: str, tracker: ToolFailureTracker) -> bool:
    """Return True if the loop should skip/abort BEFORE running this tool.

    Checks the CURRENT recorded state: if we've already hit an abort threshold
    from prior failures, don't run another round.
    """
    if tracker.should_abort_critical(tool_name):
        return True
    if tracker.should_abort_general():
        return True
    return False


# ── R-05: ToolLoopDedup ────────────────────────────────────────────


def _jaccard(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a.lower().split()), set(b.lower().split())
    union = len(sa | sb)
    return len(sa & sb) / union if union > 0 else 0.0


_DEDUP_SIMILARITY_THRESHOLD = 0.60


@dataclass
class ToolLoopDedup:
    """Detect duplicate tool calls within the current agent loop."""

    history: list[dict[str, Any]] = field(default_factory=list)
    similarity_threshold: float = _DEDUP_SIMILARITY_THRESHOLD

    def record(self, tool_name: str, args: dict[str, Any], round_num: int = 0) -> None:
        self.history.append(
            {"fn": tool_name, "args": args, "round": round_num}
        )

    def is_duplicate(self, tool_name: str, args: dict[str, Any]) -> bool:
        if not self.history:
            return False
        last = self.history[-1]
        if last["fn"] != tool_name:
            return False
        prev_args = last.get("args", {})
        if tool_name == "trade_search":
            prev_query = str(prev_args.get("query", ""))
            curr_query = str(args.get("query", ""))
            if prev_query and curr_query:
                if _jaccard(prev_query, curr_query) >= self.similarity_threshold:
                    return True
            return False
        return prev_args == args
