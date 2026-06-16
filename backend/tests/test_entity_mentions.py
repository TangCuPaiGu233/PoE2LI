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
    assert hit["item_kind"] == "unique"


def test_find_mentions_skips_inline_code():
    text = "见 `沉默之雷` 或 ```沉默之雷``` 正文"
    assert find_mentions(text) == []


def test_find_mentions_caps_per_label():
    label = "扭曲项链"
    text = " ".join([label] * 10)
    mentions = find_mentions(text)
    count = sum(1 for m in mentions if m["label"] == label)
    assert count == 2


def test_find_mentions_skips_metadata_value():
    text = "英文名：扭曲项链 / 畸变项链\n正文里扭曲项链很好用"
    mentions = find_mentions(text)
    assert len(mentions) == 1
    assert mentions[0]["label"] == "扭曲项链"
    assert mentions[0]["name_en"] == "Distorted Amulet"
    assert mentions[0]["item_kind"] == "base"


def test_find_mentions_skips_parenthetical():
    text = "扭曲护身符（畸变项链）是涂油底；正文扭曲护身符说明"
    mentions = find_mentions(text)
    labels = [m["label"] for m in mentions]
    assert "畸变项链" not in labels
    assert labels.count("扭曲护身符") == 1


def test_find_mentions_trade_base_kind():
    text = "市集上常见的畸变项链属于涂油基底"
    mentions = find_mentions(text)
    hit = next(m for m in mentions if m["label"] == "畸变项链")
    assert hit["name_en"] == "Twisted Amulet"
    assert hit["item_kind"] == "base"
