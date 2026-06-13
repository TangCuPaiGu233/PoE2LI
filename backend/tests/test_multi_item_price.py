"""Tests for multi-item price heuristics and summary formatting."""

from app.services.multi_item_price import _format_summary, is_multi_item_price_query


def test_multi_item_with_comma_and_price():
    assert is_multi_item_price_query("战猫，猎首分别多少钱")


def test_multi_item_with_and_price():
    assert is_multi_item_price_query("法血和胸甲市价多少")


def test_multi_item_cheap_keyword():
    assert is_multi_item_price_query("Headhunter / Mageblood 最便宜分别多少")


def test_single_item_with_price_not_multi():
    assert not is_multi_item_price_query("猎首多少钱")


def test_two_items_no_price_keyword_not_multi():
    assert not is_multi_item_price_query("战猫和猎首哪个更强")


def test_empty_not_multi():
    assert not is_multi_item_price_query("")


def test_format_summary_totals_and_stats():
    text = _format_summary(
        [
            {"item": "A", "amount": 10, "currency": "chaos"},
            {"item": "B", "amount": 2, "currency": "chaos"},
            {"item": "C", "amount": 1, "currency": "divine"},
        ]
    )
    assert "## 市价汇总" in text
    assert "### 统计" in text
    assert "成功 **3**" in text
    assert "混汆石：**12**" in text
    assert "神圣石：**1**" in text


def test_format_summary_mixed_success_and_error():
    text = _format_summary(
        [
            {"item": "Headhunter", "amount": 2, "currency": "divine"},
            {"item": "法血", "error": "无结果"},
        ]
    )
    assert "Headhunter" in text and "2" in text
    assert "神圣石" in text
    assert "查询失败" in text
    assert "失败 **1**" in text
    assert "成功 **1**" in text
