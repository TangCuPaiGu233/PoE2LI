"""Centralized LLM client factory with Langfuse observability.

All OpenAI/AsyncOpenAI instantiation must go through this module.
In production this wraps clients with Langfuse for automatic tracing;
in dev/test without Langfuse credentials it returns raw clients.

Usage:
    from app.core.llm_client import get_llm_client, get_async_llm_client

    client = get_llm_client()          # sync
    client = get_async_llm_client()    # async
"""

from __future__ import annotations

import logging

from app.core.llm_config import (
    LANGFUSE_ENABLED,
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
    LLM_API_KEY,
    LLM_BASE_URL,
)

logger = logging.getLogger(__name__)


def get_llm_client():
    """Return a sync OpenAI-compatible client, Langfuse-wrapped when available."""
    if LANGFUSE_ENABLED:
        try:
            from langfuse.openai import OpenAI  # type: ignore[import-untyped]

            return OpenAI(
                base_url=LLM_BASE_URL,
                api_key=LLM_API_KEY,
            )
        except Exception as e:
            logger.warning("Langfuse sync client init failed, falling back to raw OpenAI: %s", e)

    from openai import OpenAI

    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)


def get_async_llm_client():
    """Return an async OpenAI-compatible client, Langfuse-wrapped when available."""
    if LANGFUSE_ENABLED:
        try:
            from langfuse.openai import AsyncOpenAI  # type: ignore[import-untyped]

            return AsyncOpenAI(
                base_url=LLM_BASE_URL,
                api_key=LLM_API_KEY,
            )
        except Exception as e:
            logger.warning("Langfuse async client init failed, falling back to raw AsyncOpenAI: %s", e)

    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
