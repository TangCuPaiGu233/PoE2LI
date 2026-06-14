"""Normalize chat messages with optional image attachments for multimodal LLMs."""

from __future__ import annotations

import re
from typing import Any

MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DEFAULT_IMAGE_ONLY_PROMPT = "请分析图片中与 Path of Exile 2 相关的内容（装备、技能、天赋、词缀、面板数值等）。"

_DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,", re.IGNORECASE)


def extract_text(msg: dict[str, Any] | None) -> str:
    """Plain text from a chat message (string or multimodal parts)."""
    if not msg:
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def _normalize_data_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if not _DATA_URL_RE.match(raw):
        return None
    # Rough size guard (base64 ~4/3 of binary)
    if len(raw) > MAX_IMAGE_BYTES * 2:
        return None
    return raw


def extract_image_urls(msg: dict[str, Any] | None) -> list[str]:
    """Image data URLs from `images` field or OpenAI-style content parts."""
    if not msg:
        return []
    urls: list[str] = []
    images = msg.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str):
                norm = _normalize_data_url(item)
                if norm:
                    urls.append(norm)
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            iu = part.get("image_url")
            if isinstance(iu, dict):
                norm = _normalize_data_url(str(iu.get("url") or ""))
                if norm:
                    urls.append(norm)
    return urls[:MAX_IMAGES_PER_MESSAGE]


def message_has_images(msg: dict[str, Any] | None) -> bool:
    return bool(extract_image_urls(msg))


def resolve_user_text(messages: list[dict[str, Any]]) -> str:
    """Text for tool routing / RAG; default prompt when image-only."""
    last = messages[-1] if messages else {}
    text = extract_text(last)
    if text:
        return text
    if message_has_images(last):
        return DEFAULT_IMAGE_ONLY_PROMPT
    return ""


def to_llm_user_content(msg: dict[str, Any], *, include_images: bool = True) -> str | list[dict[str, Any]]:
    """OpenAI-compatible user content (string or text+image_url parts)."""
    text = extract_text(msg)
    images = extract_image_urls(msg) if include_images else []
    if not images:
        return text
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    else:
        parts.append({"type": "text", "text": DEFAULT_IMAGE_ONLY_PROMPT})
    for url in images:
        parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
    return parts


def build_agent_messages(
    messages: list[dict[str, Any]],
    system_prompt: str,
    *,
    max_turns: int = 8,
) -> list[dict[str, Any]]:
    """History for the agent LLM; images only on the latest user turn."""
    tail = messages[-max_turns:] if messages else []
    last_user_idx = -1
    for i, m in enumerate(tail):
        if m.get("role") == "user":
            last_user_idx = i

    out: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for i, m in enumerate(tail):
        role = m.get("role")
        if role == "assistant":
            text = extract_text(m)
            if text:
                out.append({"role": "assistant", "content": text})
        elif role == "user":
            content = to_llm_user_content(m, include_images=(i == last_user_idx))
            if content:
                out.append({"role": "user", "content": content})
    return out
