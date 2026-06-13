"""Tests for unique-name trade search resolution."""

from app.services.trade_service import (
    COLLOQUIAL_CN_ALIASES,
    build_trade_query,
    resolve_trade_unique_name,
)


def test_colloquial_faxue_resolves_mageblood():
    hit = resolve_trade_unique_name("法血")
    assert hit is not None
    assert hit["unique_name"] == "Mageblood"
    assert hit["source"] == "colloquial"
    assert hit["trade_name_cn"] == "法师之血"


def test_colloquial_lieshou_resolves_headhunter():
    hit = resolve_trade_unique_name("猎首")
    assert hit is not None
    assert hit["unique_name"] == "Headhunter"
    assert hit["trade_name_cn"] == "猎首"


def test_build_trade_query_unique_fields():
    q = build_trade_query(
        {
            "rarity": "unique",
            "unique_name": "猎首",
            "base_type": "重革腰带",
        },
        market="cn",
    )
    body = q["query"]
    assert body["name"] == "猎首"
    assert body["type"] == "重革腰带"
    assert body["filters"]["type_filters"]["filters"]["rarity"]["option"] == "unique"


def test_colloquial_aliases_include_faxue():
    assert COLLOQUIAL_CN_ALIASES["法血"] == "Mageblood"


def test_colloquial_zhanmao_kaoms_heart():
    assert COLLOQUIAL_CN_ALIASES["战猫"] == "Kaoms Heart"
