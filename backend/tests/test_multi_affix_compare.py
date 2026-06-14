"""Tests for multi-affix compare heuristics and summary."""

from app.services.multi_affix_compare import (
    _format_summary,
    is_multi_affix_compare_query,
)


def test_multi_affix_per_variant_price():
    assert is_multi_affix_compare_query("请查看不同词条分别对应的价格")


def test_multi_affix_other_class_mods():
    assert is_multi_affix_compare_query("如果是其他职业的词缀会是什么价格")


def test_single_affix_price_not_compare():
    assert not is_multi_affix_compare_query("召唤暴击伤害多少钱")


def test_affix_compare_without_price_keyword():
    assert not is_multi_affix_compare_query("对比一下这几个词缀")


def test_format_summary_mixed():
    text = _format_summary(
        [
            {
                "label": "佣兵起点",
                "listing_price": {"display": "2 神圣石"},
            },
            {
                "label": "战士起点",
                "price_note": "无在售",
            },
        ]
    )
    assert "## 词条比价汇总" in text
    assert "佣兵起点" in text
    assert "2 神圣石" in text
    assert "战士起点" in text
