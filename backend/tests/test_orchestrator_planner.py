"""Tests for orchestrator dispatch planning."""

from app.orchestrator.planner import plan_dispatch


def test_plan_trade_only():
    plan = plan_dispatch("帮我搜一条 +2 召唤技能等级的项链")
    agents = [t.agent for t in plan.tasks]
    assert agents == ["trade_search"]


def test_plan_recommend_only():
    plan = plan_dispatch("死灵法师用哪个项链更好")
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "recommend"


def test_plan_parallel_trade_and_mechanism():
    plan = plan_dispatch("腰带怎么获得召唤物近战扩散效果，帮我搜一条")
    agents = [t.agent for t in plan.tasks]
    assert "trade_search" in agents
    assert "encyclopedia" in agents
    assert len(plan.tasks) >= 2


def test_plan_pob_adds_decode():
    pob = "eNp" + ("A" * 30)
    plan = plan_dispatch(pob)
    assert any(t.agent == "decode_pob" for t in plan.tasks)


def test_plan_empty_fallback():
    plan = plan_dispatch("")
    assert len(plan.tasks) >= 1
    assert plan.tasks[0].agent == "encyclopedia"
