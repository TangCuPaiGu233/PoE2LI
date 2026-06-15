"""Tests for multi-affix compare heuristics, profile, and summary."""

from app.services.chat_item_profile import build_item_profile, build_searches_from_variants
from app.services.multi_affix_compare import (
    _format_summary,
    is_multi_affix_compare_query,
    resolve_searches_sync,
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
            {"label": "佣兵起点", "listing_price": {"display": "2 神圣石"}},
            {"label": "战士起点", "price_note": "无在售"},
        ]
    )
    assert "## 词条比价汇总" in text
    assert "佣兵起点" in text
    assert "2 神圣石" in text
    assert "战士起点" in text


def test_build_profile_split_personality_from_history():
    messages = [
        {"role": "user", "content": "查一下人格分裂"},
        {"role": "assistant", "content": "这是暗金珠宝人格分裂…"},
    ]
    profile = build_item_profile(messages)
    assert profile.item_name == "人格分裂"
    assert profile.rarity == "unique"
    assert len(profile.variants) >= 8


def test_resolve_searches_catalog_split_personality():
    messages = [
        {"role": "user", "content": "详细说下这个装备 人格分裂"},
        {"role": "assistant", "content": "人格分裂是暗金红玉…"},
        {"role": "user", "content": "请查看不同词条分别对应的价格"},
    ]
    searches = resolve_searches_sync("请查看不同词条分别对应的价格", messages)
    assert len(searches) >= 2
    assert all("人格分裂" in s["query"] for s in searches)
    labels = {s["label"] for s in searches}
    assert "佣兵起点" in labels


def test_build_searches_from_variants():
    rows = build_searches_from_variants(
        "人格分裂",
        [{"label": "佣兵起点", "query_suffix": "佣兵"}],
    )
    assert rows[0]["query"] == "人格分裂 佣兵"
