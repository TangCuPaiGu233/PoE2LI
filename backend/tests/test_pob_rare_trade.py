from app.services.pob_rare_trade import (
    build_pob_rare_stat_groups,
    is_skill_level_mod,
    parse_pob_item_mods,
    relax_mod_min,
)


def test_parse_pob_mods_after_separator():
    raw = """Rarity: RARE
Foo
Ring
--------
Item Level: 82
+80 to maximum Life
+2 to Level of all Minion Skills
"""
    mods = parse_pob_item_mods(raw)
    assert len(mods) == 2
    assert mods[0].value == 80
    assert "+2 to Level" in mods[1].line


def test_skill_level_min_not_relaxed():
    assert relax_mod_min(2, "+2 to Level of all Minion Skills") == 2
    assert relax_mod_min(2, "life", stat_id="explicit.stat_2162097452") == 2


def test_non_skill_min_relaxed():
    assert relax_mod_min(80, "+80 to maximum Life") == 68


def test_build_groups_keeps_full_mod_count():
    groups = build_pob_rare_stat_groups(
        [
            {"id": "explicit.stat_3299347043", "min": 80, "mod_line": "+80 to maximum Life"},
            {
                "id": "explicit.stat_2162097452",
                "min": 2,
                "mod_line": "+2 to Level of all Minion Skills",
            },
        ]
    )
    assert len(groups) == 1
    assert groups[0]["type"] == "count"
    assert groups[0]["count_min"] == 2
    mins = {s["id"]: s["min"] for s in groups[0]["stats"]}
    assert mins["explicit.stat_2162097452"] == 2
    assert mins["explicit.stat_3299347043"] == 68


def test_is_skill_level_mod():
    assert is_skill_level_mod("+2 to Level of all Spell Skills")
    assert not is_skill_level_mod("+80 to maximum Life")
