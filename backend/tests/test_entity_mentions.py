"""Tests for chat entity mention detection."""

from app.services.entity_tooltip import find_mentions


def test_find_mentions_skips_witch_class_alias():
    text = "女巫女巫女巫 女巫流派 推荐女巫"
    assert find_mentions(text) == []


def test_find_mentions_matches_curated_unique():
    text = "推荐装备：沉默之雷，适合闪电流派"
    mentions = find_mentions(text)
    labels = [m["label"] for m in mentions]
    assert "沉默之雷" in labels
    hit = next(m for m in mentions if m["label"] == "沉默之雷")
    assert hit["type"] == "item"
    assert hit["name_en"] == "Mjölner"


def test_find_mentions_skips_inline_code():
    text = "见 `沉默之雷` 或 ```沉默之雷``` 正文"
    assert find_mentions(text) == []

def test_find_mentions_caps_per_label():
    label = "扭曲项链"
    text = " ".join([label] * 10)
    mentions = find_mentions(text)
    count = sum(1 for m in mentions if m["label"] == label)
    assert count <= 2

