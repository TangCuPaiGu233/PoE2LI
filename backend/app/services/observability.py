"""Agent-level observability — trace context managers for chat turns.

Builds a trace hierarchy:

    chat_turn (trace)
    ├── plan (span)
    ├── tool: trade_search (span)
    │   └── (LLM calls auto-traced via wrapped client)
    ├── tool: rag_search (span)
    └── synthesis (span)

Usage:
    from app.services.observability import trace_chat_turn, span_tool, flush

    with trace_chat_turn("用户问题...") as trace:
        with span_tool("trade_search", {"query": "猎首"}) as tool:
            result = execute_tool(...)
            tool.set_metadata({"ok": True, "latency_ms": 320})
    flush()
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from app.core.llm_config import LANGFUSE_ENABLED

logger = logging.getLogger(__name__)

# ── Lazy Langfuse client (created once per process) ──
_langfuse: Any = None


def _get_langfuse():
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    if not LANGFUSE_ENABLED:
        return None
    try:
        from langfuse import Langfuse  # type: ignore[import-untyped]

        _langfuse = Langfuse()
        logger.info("Langfuse observability client initialized")
        return _langfuse
    except Exception as e:
        logger.warning("Langfuse client init failed: %s", e)
        return None


def flush():
    """Non-blocking flush of pending traces. Call at end of chat turn."""
    lf = _get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception as e:
            logger.debug("Langfuse flush error (non-critical): %s", e)


@contextmanager
def trace_chat_turn(user_msg: str, *, session_id: str = "", metadata: dict | None = None):
    """Create a top-level trace for one chat turn.

    Yields the trace object (or a no-op dict when disabled).
    """
    t0 = time.monotonic()
    lf = _get_langfuse()
    trace: Any = None
    trace_id = ""

    if lf:
        try:
            snippet = user_msg[:200] + ("..." if len(user_msg) > 200 else "")
            trace = lf.trace(
                name="chat_turn",
                input={"user_msg": snippet},
                metadata=metadata,
                session_id=session_id or None,
            )
            trace_id = getattr(trace, "id", "")
        except Exception as e:
            logger.debug("Langfuse trace creation failed: %s", e)
            trace = None

    class _SpanCtx:
        """Simple span factory bound to this trace."""

        @contextmanager
        def span(self, name: str, **kwargs: Any):
            t_start = time.monotonic()
            current_span: Any = None
            if trace and hasattr(trace, "span"):
                try:
                    current_span = trace.span(name=name, input=kwargs.get("input"))
                except Exception:
                    current_span = None
            span_result: dict[str, Any] = {"ok": True, "latency_ms": 0}
            try:
                yield span_result
                span_result["latency_ms"] = round((time.monotonic() - t_start) * 1000)
            except Exception as exc:
                span_result["ok"] = False
                span_result["error"] = str(exc)[:500]
                span_result["latency_ms"] = round((time.monotonic() - t_start) * 1000)
                raise
            finally:
                if current_span:
                    try:
                        current_span.update(
                            output=span_result,
                            metadata={
                                "latency_ms": span_result["latency_ms"],
                                "ok": span_result["ok"],
                            },
                        )
                        current_span.end()
                    except Exception:
                        pass

    ctx = _SpanCtx()

    try:
        yield ctx
    finally:
        elapsed = round((time.monotonic() - t0) * 1000)
        if trace:
            try:
                trace.update(output={"total_latency_ms": elapsed})
            except Exception:
                pass


@contextmanager
def span_tool(name: str, input_data: dict | None = None):
    """Create a span for a single tool execution. Yields a dict for metadata."""
    # This is a lightweight version for use OUTSIDE of trace_chat_turn context
    # Inside trace_chat_turn, use ctx.span() instead.
    t0 = time.monotonic()
    lf = _get_langfuse()
    span: Any = None
    if lf:
        try:
            span = lf.span(name=f"tool:{name}", input=input_data)
        except Exception:
            span = None

    result: dict[str, Any] = {"ok": True}
    try:
        yield result
        result["latency_ms"] = round((time.monotonic() - t0) * 1000)
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)[:500]
        result["latency_ms"] = round((time.monotonic() - t0) * 1000)
        raise
    finally:
        if span:
            try:
                span.update(output=result, metadata={"latency_ms": result.get("latency_ms", 0)})
                span.end()
            except Exception:
                pass
