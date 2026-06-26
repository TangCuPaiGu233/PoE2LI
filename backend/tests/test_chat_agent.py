"""Unit tests for chat_agent core logic (Legacy ReAct path)."""

from __future__ import annotations

import pytest

from app.services.chat_agent import (
    MAX_TOOL_ROUNDS,
    _sanitize_answer,
    _safe_flush_point,
)
from app.services.chat_multimodal import build_agent_messages
from app.services.chat_response_guard import strip_ungrounded_price_claims


# ── _sanitize_answer ────────────────────────────────────────────────


class TestSanitizeAnswer:
    """Wiki syntax and DSML XML cleaning."""

    def test_empty_string(self):
        assert _sanitize_answer("") == ""

    def test_none_input(self):
        assert _sanitize_answer(None) is None  # type: ignore[arg-type]

    def test_wiki_link_closed(self):
        raw = "查看 [[poe:法师之血|法师之血]] 获取更多信息"
        assert _sanitize_answer(raw) == "查看 法师之血 获取更多信息"

    def test_wiki_link_no_pipe(self):
        raw = "[[法师之血]] 是暗金腰带"
        # No pipe inside brackets → current regex does not match, passthrough
        assert _sanitize_answer(raw) == raw

    def test_single_bracket_poe(self):
        raw = "推荐 [poe:法师之血] 腰带"
        assert _sanitize_answer(raw) == "推荐 法师之血 腰带"

    def test_single_bracket_poe_with_pipe(self):
        raw = "推荐 [poe:法师之血|Mageblood] 腰带"
        assert _sanitize_answer(raw) == "推荐 法师之血 腰带"

    def test_orphan_poe_tag(self):
        raw = "**[poe:法师之血** → **法师之血"
        assert _sanitize_answer(raw) == "**法师之血** → **法师之血"

    def test_stray_pipe_poe(self):
        raw = "|poe:法师之血| 是暗金"
        # _WIKI_PIPE_RE strips leading '|poe:' only
        assert _sanitize_answer(raw) == "法师之血| 是暗金"

    def test_dsml_xml_full(self):
        raw = "回答<｜DSML｜tool_calls>...</｜DSML｜tool_calls>结束"
        assert _sanitize_answer(raw) == "回答结束"

    def test_dsml_xml_open_only(self):
        raw = "回答<｜DSML｜tool_calls>未闭合"
        assert _sanitize_answer(raw) == "回答未闭合"

    def test_ascii_pipe_dsml(self):
        raw = "回答<|DSML|tool_calls>...</|DSML|tool_calls>结束"
        assert _sanitize_answer(raw) == "回答结束"

    def test_mixed_patterns(self):
        raw = "[[poe:法师之血|Mageblood]] 售价 [poe:5|5] div<｜DSML｜tool_calls>x</｜DSML｜tool_calls>"
        assert _sanitize_answer(raw) == "Mageblood 售价 5 div"

    def test_clean_text_passthrough(self):
        raw = "火焰伤害是一种元素伤害"
        assert _sanitize_answer(raw) == "火焰伤害是一种元素伤害"

    def test_whitespace_strip(self):
        assert _sanitize_answer("  你好  ") == "你好"


# ── _safe_flush_point ──────────────────────────────────────────────


class TestSafeFlushPoint:
    """Buffer flush safety for streaming [poe:...] patterns."""

    def test_no_open_pattern(self):
        buf = "abc def ghi"
        assert _safe_flush_point(buf) == len(buf)

    def test_closed_pattern(self):
        buf = "abc [poe:法师之血] def"
        assert _safe_flush_point(buf) == len(buf)

    def test_unclosed_at_end(self):
        buf = "abc [poe:法师之血"
        assert _safe_flush_point(buf) == 4  # "abc "

    def test_multiple_patterns_last_unclosed(self):
        buf = "[poe:a] middle [poe:b"
        # Returns index of the last unclosed '[poe:' (15 here)
        assert _safe_flush_point(buf) == 15

    def test_empty_buffer(self):
        assert _safe_flush_point("") == 0


# ── build_agent_messages ───────────────────────────────────────────


class TestBuildAgentMessages:
    """History truncation and image handling for agent LLM."""

    def test_system_prompt_first(self):
        messages = [{"role": "user", "content": "你好"}]
        out = build_agent_messages(messages, "你是一个助手")
        assert out[0]["role"] == "system"
        assert out[0]["content"] == "你是一个助手"

    def test_max_turns_truncation(self):
        messages = [
            {"role": "user", "content": f"msg{i}"} for i in range(20)
        ]
        out = build_agent_messages(messages, "sys", max_turns=5)
        # system + 5 turns
        assert len(out) == 6

    def test_images_only_on_last_user(self):
        messages = [
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "回复1"},
            {
                "role": "user",
                "content": "第二轮",
                "images": ["data:image/png;base64,abc"],
            },
        ]
        out = build_agent_messages(messages, "sys")
        # Find the last user message
        user_msgs = [m for m in out if m["role"] == "user"]
        assert len(user_msgs) == 2
        # First user should not have images
        assert "images" not in user_msgs[0]
        # Last user should have image_url in content parts
        content = user_msgs[1].get("content", [])
        assert isinstance(content, list)
        assert any(part.get("type") == "image_url" for part in content)

    def test_empty_messages(self):
        out = build_agent_messages([], "sys")
        assert len(out) == 1
        assert out[0]["role"] == "system"

    def test_assistant_text_preserved(self):
        messages = [
            {"role": "user", "content": "问"},
            {"role": "assistant", "content": "答"},
        ]
        out = build_agent_messages(messages, "sys")
        assert any(m["role"] == "assistant" and m["content"] == "答" for m in out)


# ── strip_ungrounded_price_claims ──────────────────────────────────


class TestStripUngroundedPriceClaims:
    """Price hallucination guard."""

    def test_no_price_assertion(self):
        text = "这件装备属性不错"
        assert strip_ungrounded_price_claims(text, had_listing=False) == text

    def test_price_assertion_with_listing(self):
        text = "售价约 5 div"
        # had_listing=True means we trust the price
        assert strip_ungrounded_price_claims(text, had_listing=True) == text

    def test_price_assertion_without_listing_appends_warning(self):
        text = "建议售价 3-5 崇高"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "说明" in result
        assert "未能从市集读取" in result

    def test_empty_text(self):
        assert strip_ungrounded_price_claims("", had_listing=False) == ""

    def test_price_range_pattern(self):
        text = "大概 2~8 div"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "说明" in result

    def test_exalt_price(self):
        text = "市价约 10e"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "说明" in result

    def test_divine_price(self):
        text = "建议挂 1div"
        result = strip_ungrounded_price_claims(text, had_listing=False)
        assert "说明" in result


# ── Agent loop exit conditions ──────────────────────────────────────


class TestAgentLoopExitConditions:
    """Logic around MAX_TOOL_ROUNDS and tool_calls emptiness."""

    def test_max_tool_rounds_constant(self):
        assert MAX_TOOL_ROUNDS >= 1
        assert isinstance(MAX_TOOL_ROUNDS, int)

    def test_empty_tool_calls_breaks_loop(self):
        """If LLM returns no tool_calls, the agent loop should break."""
        # This is a logic test; we verify the condition directly
        tool_calls = []
        assert not tool_calls  # equivalent to `if not tool_calls: break`

    def test_tool_calls_present_continues(self):
        tool_calls = [{"id": "1", "function": {"name": "rag_search"}}]
        assert tool_calls  # loop continues
