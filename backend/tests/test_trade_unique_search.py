"""Tests for unique-name trade search resolution."""

from unittest.mock import MagicMock, patch

from app.services.trade_service import (
    COLLOQUIAL_CN_ALIASES,
    build_trade_query,
    fetch_cheapest_listing,
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


@patch("app.services.trade_service._get_scraper")
@patch("app.services.trade_service._rate_limit")
def test_fetch_cheapest_listing_uses_post_item_ids(mock_rate, mock_get_scraper):
    scraper = MagicMock()
    mock_get_scraper.return_value = scraper
    fetch_resp = MagicMock()
    fetch_resp.status_code = 200
    fetch_resp.json.return_value = {
        "result": [
            {
                "listing": {"price": {"amount": 42, "currency": "divine"}},
                "item": {"name": "猎首", "typeLine": "重革腰带"},
            }
        ]
    }
    scraper.get.return_value = fetch_resp

    out = fetch_cheapest_listing(
        "https://poe.game.qq.com/trade2/search/poe2/Standard/abc123",
        market="cn",
        item_ids=["hash-from-post"],
    )

    assert out == {
        "amount": 42,
        "currency": "divine",
        "item_name": "猎首 重革腰带",
        "search_id": "abc123",
    }
    scraper.get.assert_called_once()
    assert "hash-from-post" in scraper.get.call_args[0][0]


def test_en_apostrophe_unique_reverse_lookup():
    hit = resolve_trade_unique_name("Valako's Vice")
    assert hit is not None
    assert hit.get("source") == "unique_cn_en_reverse"
    assert hit.get("trade_name_cn")
