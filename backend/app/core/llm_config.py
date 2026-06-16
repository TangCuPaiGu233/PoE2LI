"""LLM provider settings — switch via docker-compose / .env (MiMo, DeepSeek, etc.)."""

from __future__ import annotations

import os

from typing import Any

# ── Langfuse observability ──
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")
LANGFUSE_ENABLED = bool(LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY)

# Active provider (override in docker-compose.yml)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.xiaomimimo.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "mimo-v2.5")


def llm_thinking_extra_body() -> dict | None:
    """Optional thinking/reasoning mode — provider-specific via extra_body."""
    mode = os.getenv("LLM_THINKING", "auto").strip().lower()
    if mode in ("0", "false", "off", "disabled"):
        return None
    if mode in ("1", "true", "on", "enabled"):
        return {"thinking": {"type": "enabled"}}
    # auto: DeepSeek + MiMo Pro support extended thinking; base MiMo-V2.5 does not
    m = LLM_MODEL.lower()
    if "deepseek" in m or "mimo-v2.5-pro" in m or "mimo-v2-pro" in m:
        return {"thinking": {"type": "enabled"}}
    return None


def llm_message_text(message: Any) -> str:
    """Extract assistant text — MiMo may put JSON only in reasoning_content."""
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content
    reasoning = getattr(message, "reasoning_content", None) or ""
    if not reasoning:
        extra = getattr(message, "model_extra", None) or {}
        reasoning = extra.get("reasoning_content") or ""
    return reasoning.strip()
