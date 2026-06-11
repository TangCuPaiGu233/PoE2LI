"""Tests for chat keyword planning helpers."""

from unittest.mock import MagicMock

from app.api.knowledge import (
    _conversation_snippet,
    _generate_search_keywords,
    _parse_keyword_lines,
)


def test_conversation_snippet_excludes_current_and_limits_turns():
    messages = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "follow-up question"},
    ]
    snippet = _conversation_snippet(messages, max_turns=2)
    assert "follow-up" not in snippet
    assert "old question" in snippet
    assert "old answer" in snippet


def test_conversation_snippet_empty_for_single_message():
    assert _conversation_snippet([{"role": "user", "content": "only"}]) == ""


def test_parse_keyword_lines_strips_bullets_and_numbers():
    raw = "1. Fire Damage\n- Minion\n* Spirit\n2) Aura"
    assert _parse_keyword_lines(raw) == [
        "Fire Damage",
        "Minion",
        "Spirit",
        "Aura",
    ]


def test_generate_search_keywords_fallback_on_llm_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = TimeoutError("slow")
    out = _generate_search_keywords(
        client,
        "what is spirit",
        [{"role": "user", "content": "what is spirit"}],
        ["Spirit", "Reservation"],
    )
    assert out == ["what is spirit", "Spirit", "Reservation"]

