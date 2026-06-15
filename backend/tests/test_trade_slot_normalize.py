"""Trade slot and canonical label normalization."""
from app.services.trade_service import normalize_trade_item_slot
from app.services.trade_stats_index import normalize_canonical_stat_label


def test_normalize_trade_item_slot_amulet():
    assert normalize_trade_item_slot("amulet") == "accessory.amulet"
    assert normalize_trade_item_slot("accessory.amulet") == "accessory.amulet"
    assert normalize_trade_item_slot("  Amulet  ") == "accessory.amulet"


def test_normalize_canonical_stat_label_strips_numeric_suffix():
    assert normalize_canonical_stat_label("召唤技能等级+4") == "召唤技能等级"
    assert normalize_canonical_stat_label("冰冷抗性＋25") == "冰冷抗性"
    assert normalize_canonical_stat_label("最大生命") == "最大生命"
