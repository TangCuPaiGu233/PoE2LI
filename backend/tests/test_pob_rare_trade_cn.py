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
    captured = {}

    def fake_search(intent, league=None, market="cn"):
        captured["intent"] = dict(intent)
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

    assert captured["intent"]["base_type"] == "红玉戒指"
