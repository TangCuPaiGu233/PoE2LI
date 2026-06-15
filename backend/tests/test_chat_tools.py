"""Tests for chat_tools helpers and registry."""

from app.models.schemas import BuildInfo, DecodeResponse, Gem, Item, SkillSet
from app.services.chat_tools import (
    TOOL_DEFINITIONS,
    detect_input_signals,
    find_build_input,
    format_build_summary,
)


def test_detect_input_signals_pob_code():
    msg = "eN" + "a" * 30
    signals = detect_input_signals(msg)
    assert "message_contains_pob_code_or_build_url" in signals
    assert "pob_share_code" in signals


def test_find_build_input_wegame_url_with_dashes():
    url = (
        "评价一下 https://www.wegame.com.cn/helper/poe2/#/share/"
        "11CqvpN5q7Ly0gQ9rVxl5rK1-8cu0DMZnfTxI_isBVxVVOQYi56-wjAqQS2qfagO"
    )
    found = find_build_input(url)
    assert found is not None
    assert "11CqvpN5q7Ly0gQ9rVxl5rK1-8cu0DMZnfTxI_isBVxVVOQYi56-wjAqQS2qfagO" in found


def test_find_build_input_wegame_without_www():
    url = "https://wegame.com.cn/helper/poe2/#/share/abc123token"
    assert find_build_input(url) is not None


def test_detect_input_signals_pobb_in():
    url = "https://pobb.in/abc123"
    signals = detect_input_signals(url)
    assert "pobb_in_url" in signals
    assert "contains_http_url" in signals


def test_detect_input_signals_plain_text_empty():
    assert detect_input_signals("什么是火焰伤害") == []


def test_format_build_summary_minimal():
    data = DecodeResponse(
        build=BuildInfo(className="Ranger", ascendClassName="Deadeye", level="95"),
        playerStats={"Life": 5000, "TotalDPS": 100000},
        skillSets=[SkillSet(gems=[Gem(nameSpec="Lightning Arrow", enabled=True)])],
        items=[Item(rarity="UNIQUE", name="Windripper", baseName="Short Bow")],
    )
    summary = format_build_summary(data)
    assert "class: Ranger" in summary
    assert "ascendancy: Deadeye" in summary
    assert "Life=5000" in summary
    assert "Lightning Arrow" in summary
    assert "Windripper" in summary


def test_tool_definitions_names():
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert names == {
        "entity_resolve",
        "rag_search",
        "decode_pob",
        "resolve_trade_stat",
        "trade_search",
        "recommend",
    }
