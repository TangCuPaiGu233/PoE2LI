"""Trade base type inference from official index."""

from app.services.trade_agent import _infer_base_type
from app.services.trade_items_index import infer_base_type_label, match_base_type_in_text


def test_match_distorted_amulet_cn():
    hit = match_base_type_in_text("扭曲项链都能提供什么词条")
    assert hit == ("扭曲项链", "Distorted Amulet")


def test_infer_base_type_cn_market():
    assert infer_base_type_label("搜一条扭曲项链", market="cn") == "扭曲项链"
    assert infer_base_type_label("Twisted Amulet mods", market="en") == "Twisted Amulet"


def test_trade_agent_infer_amulet_base():
    base = _infer_base_type("扭曲项链 Distorted Amulet", "accessory.amulet", market="cn")
    assert base == "扭曲项链"
