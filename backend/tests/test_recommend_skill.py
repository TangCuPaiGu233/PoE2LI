"""Tests for recommend skill routing."""

from app.skills.router import route


def test_route_recommend_before_encyclopedia():
    skill = route("死灵法师用哪个项链更好")
    assert skill.name == "recommend"


def test_route_build_design_priority():
    skill = route("帮我配一套开荒BD推荐")
    assert skill.name == "build_design"


def test_route_encyclopedia_fallback():
    skill = route("火球术是什么技能")
    assert skill.name == "encyclopedia"
