from unittest.mock import patch

from app.services.pob_rare_trade import resolve_base_type_cn


def test_resolve_base_type_cn_from_map():
    fake = {"Ruby Ring": "红玉戒指", "Gold Ring": "金戒指"}
    with patch("app.services.pob_rare_trade._load_base_en_cn_map", return_value=fake):
        assert resolve_base_type_cn("Ruby Ring") == "红玉戒指"
        assert resolve_base_type_cn("gold ring") == "金戒指"


def test_resolve_base_type_cn_passthrough_cjk():
    with patch("app.services.pob_rare_trade._load_base_en_cn_map", return_value={}):
        assert resolve_base_type_cn("红玉戒指") == "红玉戒指"


def test_resolve_base_type_cn_missing():
    with patch("app.services.pob_rare_trade._load_base_en_cn_map", return_value={"Ruby Ring": "红玉戒指"}):
        assert resolve_base_type_cn("Unknown Base") is None


def test_quote_pob_rare_sync_uses_cn_base_on_cn_market():
    from app.services import pob_rare_trade as prt

    raw = """Rarity: RARE
My Ring
Ruby Ring
--------
+80 to maximum Life
"""
    calls = []

    def fake_search(intent, league=None, market="cn"):
        calls.append(dict(intent))
        return {"error": "stop"}

    with (
        patch.object(
            prt,
            "resolve_pob_mods_to_stats",
            return_value=([{"id": "explicit.stat_3299347043", "min": 80, "mod_line": "+80 to maximum Life"}], []),
        ),
        patch.object(prt, "resolve_base_type_cn", return_value="红玉戒指"),
        patch("app.services.trade_service.search_trade", side_effect=fake_search),
    ):
        prt.quote_pob_rare_sync("My Ring", raw, "Ring 1", "Ruby Ring", market="cn")

    assert any(c.get("base_type") == "红玉戒指" for c in calls)

from app.services.multi_item_price import _format_rare_item_answer, _format_summary


def test_quote_pob_rare_sync_no_listing_skips_fetch():
    from app.services import pob_rare_trade as prt

    raw = """Rarity: RARE
My Ring
Ruby Ring
--------
+80 to maximum Life
"""

    def fake_search(intent, league=None, market="cn"):
        return {
            "trade_url": "https://example.com/trade/search/abc",
            "total_results": 0,
            "item_ids": [],
        }

    with (
        patch.object(
            prt,
            "resolve_pob_mods_to_stats",
            return_value=([{"id": "explicit.stat_3299347043", "min": 80, "mod_line": "+80 to maximum Life"}], []),
        ),
        patch.object(prt, "resolve_base_type_cn", return_value="\u7ea2\u7389\u6212\u6307"),
        patch("app.services.trade_service.search_trade", side_effect=fake_search),
        patch("app.services.trade_service.fetch_cheapest_listing") as fetch_mock,
    ):
        out = prt.quote_pob_rare_sync("My Ring", raw, "Ring 1", "Ruby Ring", market="cn")

    fetch_mock.assert_not_called()
    assert out.get("no_listing") is True
    assert out.get("note") == "\u5e02\u96c6\u4e2d\u6682\u65e0\u5b8c\u5168\u5339\u914d\u7684\u5728\u552e\u7269\u54c1"
    assert "error" not in out


def test_format_rare_item_answer_no_listing_friendly():
    quote = {
        "item": "Life Ring",
        "no_listing": True,
        "note": "\u5e02\u96c6\u4e2d\u6682\u65e0\u5b8c\u5168\u5339\u914d\u7684\u5728\u552e\u7269\u54c1",
        "mods_matched": 2,
        "mods_total": 3,
    }
    text = _format_rare_item_answer({"label": "Life Ring"}, quote)
    assert "\u67e5\u8be2\u5931\u8d25" not in text
    assert "2/3" in text
    assert "2/3" in text  # link only when trade_result provides url


def test_format_summary_no_listing_counts_success():
    quotes = [
        {"item": "A", "no_listing": True, "note": "\u5e02\u96c6\u4e2d\u6682\u65e0\u5b8c\u5168\u5339\u914d\u7684\u5728\u552e\u7269\u54c1"},
        {"item": "B", "error": "boom"},
    ]
    text = _format_summary(quotes)
    assert "\u6210\u529f **1**" in text
    assert "\u5931\u8d25 **1**" in text

def test_format_rare_item_answer_includes_link_when_url_present():
    quote = {
        "item": "Life Ring",
        "no_listing": True,
        "note": "市集中暂无完全匹配的在售物品",
        "mods_matched": 2,
        "mods_total": 3,
        "trade_result": {
            "best_match": {
                "label": "Life Ring (0 条)",
                "url": "https://poe.game.qq.com/trade2/search/poe2/league/xyz",
                "count": 0,
            }
        },
    }
    text = _format_rare_item_answer({"label": "Life Ring"}, quote)
    assert "xyz" in text
    assert "查看搜索条件" in text
