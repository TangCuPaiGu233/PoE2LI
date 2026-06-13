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


def test_colloquial_lieshou_resolves_headhunter():
    hit = resolve_trade_unique_name("猎首")
    assert hit is not None
    assert hit["unique_name"] == "Headhunter"


def test_build_trade_query_unique_fields():
    q = build_trade_query(
        {
            "rarity": "unique",
            "unique_name": "Headhunter",
            "base_type": "Leather Belt",
        },
        market="cn",
    )
    body = q["query"]
    assert body["name"] == "Headhunter"
    assert body["type"] == "Leather Belt"
    assert body["filters"]["type_filters"]["filters"]["rarity"]["option"] == "unique"


def test_colloquial_aliases_include_faxue():
    assert COLLOQUIAL_CN_ALIASES["法血"] == "Mageblood"
