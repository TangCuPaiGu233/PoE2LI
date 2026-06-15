"""Tests for bilingual trade stat suggest index."""

from app.services.trade_stats_index import (
    resolve_stat_query,
    search_stat_suggestions,
    _normalize_stat_search_query,
)


def test_normalize_stat_search_query_fire_res_slang():
    assert "火焰抗性" in _normalize_stat_search_query("火抗项链")


def test_search_stat_suggestions_fire_res():
    rows = search_stat_suggestions("火焰抗性", limit=5)
    assert rows
    assert any("火焰" in (r.get("text_cn") or "") for r in rows)
    assert rows[0].get("stat_id", "").startswith(("explicit.", "rune.", "pseudo."))


def test_resolve_stat_query_total_cold():
    q = _normalize_stat_search_query("冰抗")
    sid = resolve_stat_query(q)
    if sid:
        assert sid.startswith("explicit.") or sid.startswith("rune.")
    rows = search_stat_suggestions("冰霜抗性", limit=3)
    assert rows
