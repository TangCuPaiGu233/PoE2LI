"""Tests for trade agent fallback link behavior."""
from app.services.trade_agent import (
    _filter_concept_candidates,
    _infer_item_slot,
    _pick_best_plan,
    sanitize_trade_query,
)


def test_infer_item_slot_jewel():
    assert _infer_item_slot("蓝玉珠宝 召唤暴击伤害") == "jewel"
    assert _infer_item_slot("找一条项链") == "accessory.amulet"


def test_sanitize_strips_ilvl_from_screenshot_query():
    q = "蓝玉珠宝 物品等级81 混沌伤害 召唤暴击"
    cleaned = sanitize_trade_query(q, user_msg="看下这个值多少钱")
    assert "81" not in cleaned
    assert "物品等级" not in cleaned
    assert "混沌伤害" in cleaned


def test_sanitize_keeps_ilvl_when_user_asked():
    q = "项链 物等80以上 生命"
    assert "物等" in sanitize_trade_query(q, user_msg="要物等80以上的项链")


def test_pick_best_plan_prefers_specificity():
    results = [
        {"plan": "core", "result": {"total": 0, "url": "https://x/1"}, "stats": {"must_have_count": 3, "nice_to_have_count": 0}},
        {"plan": "full", "result": {"total": 10000, "url": "https://x/2"}, "stats": {"must_have_count": 0, "nice_to_have_count": 0}},
    ]
    best = _pick_best_plan(results)
    assert best["plan"] == "core"


def test_pick_best_plan_prefers_hits_when_same_specificity():
    results = [
        {"plan": "core", "result": {"total": 0, "url": "https://x/1"}, "stats": {"must_have_count": 2, "nice_to_have_count": 0}},
        {"plan": "full", "result": {"total": 5, "url": "https://x/2"}, "stats": {"must_have_count": 2, "nice_to_have_count": 1, "count_min": 1}},
    ]
    best = _pick_best_plan(results)
    assert best["plan"] == "full"


def test_pick_best_plan_url_when_zero():
    results = [
        {"plan": "core", "result": {"total": 0, "url": "https://x/1"}, "stats": {}},
    ]
    best = _pick_best_plan(results)
    assert best["result"]["url"] == "https://x/1"


def test_filter_minion_concept_drops_bleed_false_positive():
    candidates = [
        {"stat_id": "explicit.stat_2506820610", "ref_text": "Monsters have #% chance to inflict Bleeding on Hit", "source": "vector"},
        {"stat_id": "explicit.stat_1854213750", "ref_text": "Minions have #% increased Critical Damage Bonus", "source": "regex"},
    ]
    filtered = _filter_concept_candidates("minion_critical_damage", candidates)
    assert len(filtered) == 1
    assert filtered[0]["stat_id"] == "explicit.stat_1854213750"


def test_remap_minion_crit_concept():
    from app.services.trade_agent import _remap_concepts_from_query

    intent = {
        "must_have": [{"concept": "critical_damage_bonus", "operator": "exists"}],
        "nice_to_have": [],
    }
    out = _remap_concepts_from_query(intent, "蓝玉 召唤生物暴击伤害加成")
    assert out["must_have"][0]["concept"] == "minion_critical_damage"


def test_unique_fast_path_skips_rare_jewel_query():
    from unittest.mock import patch
    from app.services.trade_agent import _try_unique_trade

    with patch("app.services.trade_service.search_unique_by_name") as mock_search:
        mock_search.return_value = {"trade_url": "https://x/u1", "total_results": 12}
        with patch("app.services.trade_service.resolve_trade_unique_name") as mock_resolve:
            mock_resolve.return_value = {
                "unique_name": "Split Personality",
                "trade_name_cn": "人格分裂",
                "matched": "人格分裂",
            }
            resp = _try_unique_trade("人格分裂 红玉 宝珠", "Standard", "cn")
    assert resp is not None
    assert resp["best_match"]["url"] == "https://x/u1"
    assert "人格分裂" in resp["best_match"]["label"]
