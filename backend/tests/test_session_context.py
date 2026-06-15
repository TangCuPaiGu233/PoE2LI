"""Tests for session context and trade anchor resolution."""

from app.orchestrator.session_context import build_session_context


def _msgs(*pairs: tuple[str, str]) -> list[dict]:
    out: list[dict] = []
    for role, content in pairs:
        out.append({"role": role, "content": content})
    return out


def test_trade_anchor_from_prior_item_description():
    messages = _msgs(
        (
            "user",
            "帮我看这条项链：+2 召唤技能等级，+35% 召唤物伤害，+48 最大生命",
        ),
        ("assistant", "这是一条稀有项链，词缀不错。"),
        ("user", "这个装备现在值多少钱？"),
    )
    ctx = build_session_context(messages)
    assert ctx.is_trade_followup
    assert ctx.trade_anchor_text
    assert "召唤" in ctx.trade_anchor_text
    assert "多少钱" in ctx.trade_search_query() or "项链" in ctx.trade_search_query()


def test_trade_refine_not_jewel():
    messages = _msgs(
        (
            "user",
            "蓝玉珠宝 +3 召唤技能等级 +25% 召唤物伤害",
        ),
        ("assistant", "已搜索珠宝类目。"),
        ("user", "我这个不是珠宝啊，是项链上的词缀"),
    )
    ctx = build_session_context(messages)
    assert ctx.is_trade_refine
    q = ctx.trade_search_query()
    assert "更正" in q or "项链" in q


def test_effective_user_msg_includes_prior_snippet():
    messages = _msgs(
        ("user", "灵魂行者有哪些升华技能"),
        ("assistant", "灵魂行者有…"),
        ("user", "偶像词缀怎么搭配"),
    )
    ctx = build_session_context(messages)
    eff = ctx.effective_user_msg()
    assert "对话上下文" in eff
    assert "灵魂行者" in eff
    assert "偶像词缀" in eff


def test_build_gear_query_enriched_with_anchor():
    messages = _msgs(
        ("user", "灵魂行者偶像词缀装备"),
        ("assistant", "…"),
        ("user", "怎么搭配"),
    )
    ctx = build_session_context(messages)
    rag = ctx.rag_query_text()
    assert "搭配" in rag
