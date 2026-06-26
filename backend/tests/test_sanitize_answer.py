"""Unit tests for chat_agent._sanitize_answer and _sanitize_reasoning.

These tests cover the output sanitization that strips:
- tool-call XML leaks (<｜DSML｜...>)
- wiki link syntax ([[...]], [poe:...])
- stray pipe fragments (|poe:)
"""

from app.services.chat_agent import _sanitize_answer, _sanitize_reasoning


class TestSanitizeAnswer:
    # ── Baseline: empty / None ──

    def test_none_returns_none(self):
        assert _sanitize_answer(None) is None

    def test_empty_string_returns_empty(self):
        assert _sanitize_answer("") == ""

    def test_whitespace_only_returns_stripped(self):
        assert _sanitize_answer("   ") == ""

    # ── Tool-call XML removal ──

    def test_full_tool_call_xml_removed(self):
        text = '回答内容<｜DSML｜tool_calls>{"name":"trade_search"}</｜DSML｜tool_calls>结尾'
        result = _sanitize_answer(text)
        assert "DSML" not in result
        assert "tool_calls" not in result

    def test_unclosed_tool_call_xml_removed(self):
        text = '回答内容<｜DSML｜tool_calls>{"name":"trade_search"}结尾'
        result = _sanitize_answer(text)
        assert "DSML" not in result

    def test_ascii_pipe_tool_call_xml_removed(self):
        text = '回答<|DSML|tool_calls>{"name":"rag_search"}</|DSML|tool_calls>结尾'
        result = _sanitize_answer(text)
        assert "DSML" not in result

    # ── Wiki link conversion ──

    def test_wiki_link_double_bracket(self):
        text = "[[poe:法师之血|法师之血]]"
        result = _sanitize_answer(text)
        assert result == "法师之血"

    def test_wiki_link_simple_display(self):
        text = "[[灵魂行者|Spirit Walker]]"
        result = _sanitize_answer(text)
        assert result == "Spirit Walker"

    def test_wiki_single_bracket_poe(self):
        text = "[poe:法师之血]"
        result = _sanitize_answer(text)
        assert result == "法师之血"

    def test_wiki_single_bracket_with_en(self):
        text = "[poe:法师之血|The Surgeon]"
        result = _sanitize_answer(text)
        assert result == "法师之血"

    def test_wiki_orphan_unclosed(self):
        text = "** [poe:法师之血"
        result = _sanitize_answer(text)
        assert "[poe:" not in result
        assert "法师之血" in result

    def test_wiki_pipe_stray_removed(self):
        text = "some text |poe:法师之血 more"
        result = _sanitize_answer(text)
        assert "|poe:" not in result

    # ── Mixed content ──

    def test_mixed_xml_and_wiki(self):
        # _sanitize_answer strips DSML XML and [poe:...] tags.
        # Plain [[...]] without a pipe is not a wiki link pattern it handles.
        text = '[[法师之血]]<｜DSML｜tool_calls>{} </｜DSML｜tool_calls>[poe:灵魂行者]'
        result = _sanitize_answer(text)
        assert "DSML" not in result
        assert "[poe:" not in result
        assert "灵魂行者" in result

    def test_clean_text_passthrough(self):
        text = "这件装备很强，值得考虑。"
        result = _sanitize_answer(text)
        assert result == text

    def test_strip_whitespace(self):
        text = "  \n\n  内容  \n  "
        result = _sanitize_answer(text)
        assert result == "内容"


class TestSanitizeReasoning:
    # ── Baseline ──

    def test_none_returns_none(self):
        assert _sanitize_reasoning(None) is None

    def test_empty_string_returns_empty(self):
        assert _sanitize_reasoning("") == ""

    # ── Tool-call XML removal from reasoning ──

    def test_tool_call_xml_removed(self):
        text = '思考过程<｜DSML｜tool_calls>{} </｜DSML｜tool_calls>继续'
        result = _sanitize_reasoning(text)
        assert "DSML" not in result

    # ── Wiki syntax removal from reasoning ──

    def test_wiki_link_removed(self):
        text = "[[poe:法师之血|法师之血]]"
        result = _sanitize_reasoning(text)
        assert "[[poe:" not in result

    def test_wiki_single_bracket_removed(self):
        text = "[poe:灵魂行者]"
        result = _sanitize_reasoning(text)
        assert "[poe:" not in result

    # ── Clean reasoning passthrough ──

    def test_clean_reasoning_passthrough(self):
        text = "用户询问装备价格，我需要先查市集。"
        result = _sanitize_reasoning(text)
        assert result == text
