"""Tests for multimodal chat message normalization."""

from app.services.chat_multimodal import (
    build_agent_messages,
    extract_image_urls,
    extract_text,
    message_has_images,
    resolve_user_text,
    to_llm_user_content,
)

PNG_DATA = "data:image/png;base64,iVBORw0KGgo="


def test_extract_text_string():
    assert extract_text({"role": "user", "content": "  hello  "}) == "hello"


def test_extract_text_parts():
    msg = {"content": [{"type": "text", "text": "line1"}, {"type": "text", "text": "line2"}]}
    assert extract_text(msg) == "line1\nline2"


def test_images_field_to_llm_parts():
    msg = {"role": "user", "content": "这是什么装备", "images": [PNG_DATA]}
    parts = to_llm_user_content(msg)
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"] == PNG_DATA


def test_image_only_default_prompt():
    msg = {"role": "user", "content": "", "images": [PNG_DATA]}
    assert "Path of Exile 2" in resolve_user_text([msg])
    parts = to_llm_user_content(msg)
    assert isinstance(parts, list)
    assert "Path of Exile 2" in parts[0]["text"]


def test_build_agent_messages_images_only_on_last_user():
    history = [
        {"role": "user", "content": "早", "images": [PNG_DATA]},
        {"role": "assistant", "content": "你好"},
        {"role": "user", "content": "看这张图", "images": [PNG_DATA]},
    ]
    built = build_agent_messages(history, "sys")
    user_msgs = [m for m in built if m["role"] == "user"]
    assert len(user_msgs) == 2
    assert user_msgs[0]["content"] == "早"
    assert isinstance(user_msgs[1]["content"], list)


def test_invalid_image_url_filtered():
    assert extract_image_urls({"images": ["https://example.com/x.png"]}) == []
