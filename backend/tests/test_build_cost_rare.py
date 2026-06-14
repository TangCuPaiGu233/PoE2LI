import asyncio
from unittest.mock import patch

import pytest

from app.models.schemas import BuildInfo, DecodeResponse, Item
from app.services.multi_item_price import _extract_rare_items, stream_build_cost

RARE_RAW = """Rarity: RARE
My Ring
Gold Ring
--------
Item Level: 82
+80 to maximum Life
"""

UNPARSEABLE_RARE = """Rarity: RARE
Empty
Gold Ring
--------
Item Level: 82
"""


def test_extract_rare_items_filters_rare_with_mods():
    data = DecodeResponse(
        build=BuildInfo(),
        items=[
            Item(rarity="RARE", name="My Ring", raw=RARE_RAW, slot="Ring 1", baseName="Gold Ring"),
            Item(rarity="RARE", name="Empty", raw=UNPARSEABLE_RARE, slot="Ring 2", baseName="Gold Ring"),
            Item(rarity="UNIQUE", name="Headhunter", raw="Rarity: UNIQUE\nHeadhunter\n"),
            Item(rarity="RARE", name="Dup", raw=RARE_RAW, slot="Ring 2", baseName="Gold Ring"),
        ],
    )
    rares = _extract_rare_items(data)
    assert len(rares) == 1
    assert rares[0]["label"] == "My Ring"
    assert rares[0]["base_name"] == "Gold Ring"
    assert "+80 to maximum Life" in rares[0]["raw"]


@pytest.mark.asyncio
async def test_stream_build_cost_includes_rares():
    decode = DecodeResponse(
        build=BuildInfo(className="Ranger", ascendClassName="Deadeye", level="90"),
        items=[
            Item(rarity="RARE", name="Life Ring", raw=RARE_RAW, slot="Ring 1", baseName="Gold Ring"),
            Item(rarity="UNIQUE", name="Headhunter", raw="Rarity: UNIQUE\nHeadhunter\nLeather Belt\n"),
        ],
    )
    rare_quote = {
        "item": "Life Ring",
        "amount": 5,
        "currency": "divine",
        "mods_matched": 1,
        "mods_total": 1,
    }
    unique_quote = {
        "item": "Headhunter",
        "amount": 100,
        "currency": "divine",
    }
    call_order = []

    def fake_rare(*args, **kwargs):
        call_order.append("rare")
        return rare_quote

    def fake_unique(item, market="cn", league=None):
        call_order.append("unique")
        return unique_quote

    with (
        patch("app.services.chat_tools.find_build_input", return_value="code"),
        patch("app.services.pob_service.decode_pob", return_value=decode),
        patch("app.services.pob_rare_trade.quote_pob_rare_sync", side_effect=fake_rare),
        patch("app.services.multi_item_price._quote_one_sync", side_effect=fake_unique),
    ):
        events = [e async for e in stream_build_cost("cost code")]

    answers = [e["content"] for e in events if e.get("type") == "answer"]
    assert any("Life Ring" in a and "5" in a for a in answers)
    assert any("Headhunter" in a for a in answers)
    assert call_order == ["rare", "unique"]

def test_trade_link_line_includes_item_url():
    from app.services.multi_item_price import _format_item_answer, _trade_link_line

    quote = {
        "amount": 10,
        "currency": "divine",
        "trade_result": {
            "best_match": {
                "label": "Headhunter (100 条)",
                "url": "https://poe.game.qq.com/trade2/search/poe2/league/abc123",
                "count": 100,
            }
        },
    }
    link = _trade_link_line(quote)
    assert "abc123" in link
    text = _format_item_answer("Headhunter", quote)
    assert "abc123" in text
