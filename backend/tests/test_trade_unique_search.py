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


def test_variant_label_from_mods_mercenary():
    from app.services.chat_item_profile import extract_class_variant_hint, variant_label_from_mods

    mods = ["可以从佣兵的起点配置天赋技能"]
    assert variant_label_from_mods(mods) == "佣兵起点"
    assert extract_class_variant_hint("图中词条：可以从佣兵的起点配置天赋技能") == "佣兵起点"
    assert extract_class_variant_hint("人格分裂 佣兵起点多少钱") == "佣兵起点"


def test_normalize_trade_listing_entry_full():
    from app.services.trade_service import normalize_trade_listing_entry

    entry = {
        "listing": {
            "indexed": "2026-06-11T08:00:00Z",
            "account": {"name": "seller#1234"},
            "price": {"amount": 120, "currency": "chaos", "type": "priced"},
        },
        "item": {
            "frameType": 2,
            "ilvl": 82,
            "identified": True,
            "corrupted": False,
            "name": "",
            "typeLine": "日耀项链",
            "baseType": "日耀项链",
            "properties": [{"name": "能量护盾", "values": [["45", 0]]}],
            "requirements": [{"name": "等级", "values": [["64", 0]]}],
            "implicitMods": ["+20 最大能量护盾"],
            "explicitMods": ["+35 最大生命", "+12% 火焰抗性"],
            "craftedMods": ["+15 最大生命"],
        },
    }
    out = normalize_trade_listing_entry(entry)
    assert out["display_name"] == "日耀项链"
    assert out["price"]["amount"] == 120
    assert out["implicit_mods"] == ["+20 最大能量护盾"]
    assert out["explicit_mods"] == ["+35 最大生命", "+12% 火焰抗性"]
    assert out["crafted_mods"] == ["+15 最大生命"]
    assert any("能量护盾" in p for p in out["properties"])
    assert out["level_req"] == 64
    assert out["seller"] == "seller#1234"
    assert "item" in out


@patch("app.services.trade_service._get_scraper")
@patch("app.services.trade_service._rate_limit")
def test_fetch_trade_listings_batch(mock_rate, mock_get_scraper):
    scraper = MagicMock()
    mock_get_scraper.return_value = scraper
    fetch_resp = MagicMock()
    fetch_resp.status_code = 200
    fetch_resp.json.return_value = {
        "result": [
            {
                "listing": {"price": {"amount": 7, "currency": "alch"}},
                "item": {
                    "name": "人格分裂",
                    "typeLine": "红玉",
                    "explicitMods": ["可以从佣兵的起点配置天赋技能"],
                },
            },
            {
                "listing": {"price": {"amount": 1, "currency": "divine"}},
                "item": {
                    "name": "人格分裂",
                    "typeLine": "红玉",
                    "explicitMods": ["可以从战士的起点配置天赋技能"],
                },
            },
        ]
    }
    scraper.get.return_value = fetch_resp

    from app.services.trade_service import fetch_trade_listings

    out = fetch_trade_listings(
        "https://poe.game.qq.com/trade2/search/poe2/Standard/abc123",
        market="cn",
        item_ids=["id1", "id2"],
        count=2,
    )
    assert out["fetched_count"] == 2
    assert len(out["listings"]) == 2
    assert out["listings"][0]["variant_label"] == "佣兵起点"
    assert out["listings"][1]["variant_label"] == "战士起点"
    scraper.get.assert_called_once()


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
                "item": {
                    "name": "猎首",
                    "typeLine": "重革腰带",
                    "explicitMods": ["可以从佣兵的起点配置天赋技能"],
                },
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
        "explicit_mods": ["可以从佣兵的起点配置天赋技能"],
        "implicit_mods": [],
        "variant_label": "佣兵起点",
    }
    scraper.get.assert_called_once()
    assert "hash-from-post" in scraper.get.call_args[0][0]


def test_en_apostrophe_unique_reverse_lookup():
    hit = resolve_trade_unique_name("Valako's Vice")
    assert hit is not None
    assert hit.get("source") == "unique_cn_en_reverse"
    assert hit.get("trade_name_cn")
