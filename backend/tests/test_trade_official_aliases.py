"""Trade API official CN names must back entity_resolver — not hand-curated bases."""

import re

import pytest

from app.services.entity_dict import ITEM_CN_ALIASES
from app.services.entity_resolver import _load_aliases, resolve_all_entities
from app.services.trade_items_index import _cn_to_en_map, counts_summary


def test_trade_index_has_substantial_cn_coverage():
    summary = counts_summary()
    assert summary["cn_to_en"] >= 2000


@pytest.mark.parametrize(
    "cn,en",
    [
        ("扭曲项链", "Distorted Amulet"),
        ("畸变项链", "Twisted Amulet"),
        ("红玉戒指", "Ruby Ring"),
        ("赤红项链", "Crimson Amulet"),
    ],
)
def test_official_trade_pairs_in_index(cn, en):
    assert _cn_to_en_map().get(cn) == en


def test_resolver_uses_trade_not_colloquial_conflict():
    ents = resolve_all_entities("扭曲项链都能提供什么词条")
    names = [e[0] for e in ents]
    assert names == ["Distorted Amulet"]


def test_curated_aliases_must_not_override_official_trade_cn():
    """ITEM_CN_ALIASES is for slang/uniques only — keys must not remap official trade CN."""
    trade = _cn_to_en_map()
    conflicts: list[str] = []
    for cn, en in ITEM_CN_ALIASES.items():
        official = trade.get(cn)
        if official and official != en:
            conflicts.append(f"{cn}: curated->{en} trade->{official}")
    assert not conflicts, "Remove from ITEM_CN_ALIASES (use trade API): " + "; ".join(conflicts)


def test_trade_aliases_loaded_in_resolver():
    aliases = _load_aliases()
    trade_loaded = sum(1 for v in aliases.values() if v[3] == "trade_api")
    assert trade_loaded >= 2000


def test_cjk_curated_keys_not_in_trade_or_same_en():
    trade = _cn_to_en_map()
    for cn, en in ITEM_CN_ALIASES.items():
        if not re.search(r"[\u4e00-\u9fff]", cn):
            continue
        if cn in trade:
            assert trade[cn] == en, f"{cn} conflicts with trade official name"
