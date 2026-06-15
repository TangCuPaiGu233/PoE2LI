"""Tests for resolve_trade_stat exact-first resolution."""

from app.services.trade_service import resolve_trade_stat
from app.services.trade_stats_index import resolve_stat_query_exact


def test_resolve_trade_stat_exact_canonical():
    payload = resolve_trade_stat("火焰抗性 #%", suggest_limit=8)
    assert payload["canonical_label"] == "火焰抗性 #%"
    assert payload["need_disambiguation"] is False
    best = payload.get("best") or {}
    assert best.get("match") == "exact"
    assert best.get("stat_id", "").startswith(("explicit.", "rune.", "pseudo."))
    assert "火焰" in (best.get("text_cn") or "")


def test_resolve_trade_stat_slang_not_auto_best():
    assert resolve_stat_query_exact("火抗", apply_slang=False) is None
    payload = resolve_trade_stat("火抗", suggest_limit=8)
    best = payload.get("best")
    assert payload["need_disambiguation"] is True
    assert best is None or best.get("match") != "exact"
