"""LLM streaming helpers extracted from chat_agent."""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncIterator

from app.core.llm_config import LLM_MODEL, llm_thinking_extra_body
from app.core.llm_client import get_async_llm_client

logger = logging.getLogger(__name__)

# Patterns for sanitizing LLM output
_TOOL_CALL_XML_RE = re.compile(
    r"<\s*[｜|]\s*DSML\s*[｜|][^>]*>.*?</\s*[｜|]\s*DSML\s*[｜|][^>]*>",
    re.DOTALL,
)
_TOOL_CALL_XML_OPEN_RE = re.compile(r"<\s*[｜|]\s*DSML\s*[｜|][^>]*/?\s*>", re.DOTALL)
_WIKI_LINK_RE = re.compile(r"\[\[(?:poe:)?([^|\]]+)\|([^\]]+)\]\]")
_WIKI_BRACKET_RE = re.compile(r"\[poe:([^\]|\n]+?)(?:\|[^\]|\n]+?)?\]")
_WIKI_ORPHAN_RE = re.compile(r"\[poe:([^|\n\]]+)")
_WIKI_PIPE_RE = re.compile(r"\|poe:")

_TOOL_TAG_RE = re.compile(r"<\s*[｜|]\s*DSML\s*[｜|][^>]*>")
_TOOL_TAG_CLOSE_RE = re.compile(r"</\s*[｜|]\s*DSML\s*[｜|][^>]*>")


def sanitize_answer(text: str) -> str:
    """Strip wiki syntax and tool-call XML leaks from LLM output."""
    if not text:
        return text
    text = _TOOL_CALL_XML_RE.sub("", text)
    text = _TOOL_CALL_XML_OPEN_RE.sub("", text)
    text = _WIKI_LINK_RE.sub(r"\2", text)
    text = _WIKI_BRACKET_RE.sub(r"\1", text)
    text = _WIKI_ORPHAN_RE.sub(r"\1", text)
    text = _WIKI_PIPE_RE.sub("", text)
    return text.strip()


def sanitize_reasoning(text: str) -> str:
    """Strip tool-call XML and wiki syntax from reasoning/thinking content."""
    if not text:
        return text
    text = _TOOL_CALL_XML_RE.sub("", text)
    text = _TOOL_CALL_XML_OPEN_RE.sub("", text)
    text = _WIKI_LINK_RE.sub(r"\2", text)
    text = _WIKI_BRACKET_RE.sub(r"\1", text)
    text = _WIKI_ORPHAN_RE.sub(r"\1", text)
    text = _WIKI_PIPE_RE.sub("", text)
    return text.strip()


def safe_flush_point(buf: str) -> int:
    """Find the last safe position to flush the content buffer."""
    last_open = buf.rfind("[poe:")
    if last_open < 0:
        return len(buf)
    close = buf.find("]", last_open + 5)
    if close >= 0:
        return len(buf)
    return last_open


def filter_reasoning_chunk(
    text: str, in_tool_xml: bool, partial: str
) -> tuple[str, bool, str]:
    """Filter tool-call XML from a streaming reasoning chunk."""
    combined = partial + text
    if not combined:
        return "", in_tool_xml, ""

    result_chars: list[str] = []
    i = 0
    while i < len(combined):
        ch = combined[i]
        if in_tool_xml:
            m = _TOOL_TAG_CLOSE_RE.search(combined, i)
            if m:
                i = m.end()
                in_tool_xml = False
            else:
                return "".join(result_chars), True, ""
        elif ch == "<":
            rest = combined[i:]
            tag_match = _TOOL_TAG_RE.match(rest)
            if tag_match:
                i += tag_match.end()
                in_tool_xml = True
            elif len(rest) <= 25 and any(
                rest.startswith(pfx)
                for pfx in (
                    "<|",
                    "<｜",
                    "< |",
                    "< ｜",
                    "<|D",
                    "<｜D",
                    "< |D",
                    "< ｜D",
                    "<| D",
                    "<｜ D",
                    "< | D",
                    "< ｜D",
                )
            ):
                return "".join(result_chars), in_tool_xml, rest
            else:
                result_chars.append(ch)
                i += 1
        else:
            result_chars.append(ch)
            i += 1

    return "".join(result_chars), in_tool_xml, ""


def is_tool_call_only(text: str) -> bool:
    """Check if the text is entirely tool-call XML (no real answer content)."""
    if not text or not text.strip():
        return False
    cleaned = _TOOL_CALL_XML_RE.sub("", text).strip()
    return len(cleaned) < 10


def get_llm_client() -> Any:
    """Return async LLM client."""
    return get_async_llm_client()


def get_model() -> str:
    """Return current LLM model name."""
    return LLM_MODEL


def first_choice(obj: Any) -> Any | None:
    """Return first choice from LLM response."""
    choices = getattr(obj, "choices", None) or []
    return choices[0] if choices else None


async def emit_streamed_answer(
    client: Any,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event_type, text) for answer/reasoning. Falls back to non-stream if needed."""
    stream_kwargs: dict[str, Any] = {
        "model": get_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    thinking = llm_thinking_extra_body()
    if thinking:
        stream_kwargs["extra_body"] = thinking
        stream_kwargs["reasoning_effort"] = "max"

    answer_parts: list[str] = []
    try:
        stream = await client.chat.completions.create(**stream_kwargs)
        async for chunk in stream:
            choice = first_choice(chunk)
            if choice is None:
                continue
            delta = choice.delta
            reasoning = getattr(delta, "reasoning_content", None) or (
                delta.model_extra.get("reasoning_content")
                if hasattr(delta, "model_extra") and delta.model_extra
                else None
            )
            if reasoning:
                yield ("reasoning", reasoning)
            if delta.content:
                answer_parts.append(delta.content)
                yield ("answer", delta.content)
    except Exception as e:
        logger.warning("[CHAT] stream synthesis failed, fallback: %s", e)

    if answer_parts:
        return

    # MiMo sometimes returns empty stream chunks — non-stream fallback
    fb_kwargs = dict(stream_kwargs)
    fb_kwargs.pop("stream", None)
    fb_kwargs.pop("extra_body", None)
    fb_kwargs.pop("reasoning_effort", None)
    if thinking:
        fb_kwargs["extra_body"] = thinking
        fb_kwargs["reasoning_effort"] = "max"
    resp = await client.chat.completions.create(**fb_kwargs)
    choice = first_choice(resp)
    if choice is None:
        raise RuntimeError("LLM returned no choices")
    msg = choice.message
    reasoning = getattr(msg, "reasoning_content", None) or ""
    if reasoning:
        yield ("reasoning", reasoning)
    text = msg.content or ""
    if text:
        yield ("answer", text)
