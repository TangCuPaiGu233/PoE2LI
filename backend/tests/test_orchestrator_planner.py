"""Tests for orchestrator dispatch planning (LLM planner mocked)."""

from unittest.mock import patch

from app.orchestrator.planner import plan_dispatch
from app.orchestrator.schemas import TaskSpec
from app.services.session_context import build_session_context


def _mock_plan(tasks: list[dict], *, note: str = "test"):
    from app.orchestrator.schemas import DispatchPlan

    specs = [
        TaskSpec(
            task_id="t1",
            agent=t["agent"],
            user_phrase="",
            payload=t.get("payload", {"query": t.get("query", "x")}),
        )
        for t in tasks
    ]
    return DispatchPlan(tasks=specs, planning_note=note)


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_trade_only(mock_llm):
    mock_llm.return_value = _mock_plan([{"agent": "trade_search", "query": "项链"}])
    plan = plan_dispatch("帮我搜一条 +2 召唤技能等级的项链")
    agents = [t.agent for t in plan.tasks]
    assert agents == ["trade_search"]


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_recommend_only(mock_llm):
    mock_llm.return_value = _mock_plan([{"agent": "recommend", "payload": {"question": "q"}}])
    plan = plan_dispatch("死灵法师用哪个项链更好")
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "recommend"


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_parallel_trade_and_mechanism(mock_llm):
    mock_llm.return_value = _mock_plan(
        [
            {"agent": "trade_search", "query": "腰带"},
            {"agent": "encyclopedia", "query": "扩散"},
        ],
    )
    plan = plan_dispatch("腰带怎么获得召唤物近战扩散效果，帮我搜一条")
    agents = [t.agent for t in plan.tasks]
    assert "trade_search" in agents
    assert "encyclopedia" in agents


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_pob_adds_decode(mock_llm):
    mock_llm.return_value = _mock_plan(
        [{"agent": "decode_pob", "payload": {"input": "eNpAAA"}}],
    )
    pob = "eNp" + ("A" * 30)
    plan = plan_dispatch(pob)
    assert any(t.agent == "decode_pob" for t in plan.tasks)


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_empty_fallback(mock_llm):
    from app.orchestrator.schemas import DispatchPlan

    mock_llm.return_value = DispatchPlan(
        tasks=[TaskSpec(task_id="t", agent="encyclopedia", user_phrase="", payload={"query": "你好"})],
        planning_note="fallback",
    )
    plan = plan_dispatch("")
    assert len(plan.tasks) >= 1
    assert plan.tasks[0].agent == "encyclopedia"


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_build_gear_not_recommend(mock_llm):
    mock_llm.return_value = _mock_plan([{"agent": "build_design", "query": "偶像词缀搭配"}])
    plan = plan_dispatch("灵魂行者的偶像词缀装备如何搭配")
    agents = [t.agent for t in plan.tasks]
    assert "build_design" in agents
    assert "recommend" not in agents


@patch("app.orchestrator.planner.llm_plan_dispatch")
def test_plan_trade_followup_uses_session(mock_llm):
    messages = [
        {"role": "user", "content": "稀有项链 +2 召唤技能等级 +48 生命"},
        {"role": "assistant", "content": "词缀不错"},
        {"role": "user", "content": "这个值多少钱"},
    ]
    session = build_session_context(messages)
    mock_llm.return_value = _mock_plan(
        [
            {
                "agent": "trade_search",
                "payload": {
                    "query": "稀有项链 +2 召唤技能等级",
                    "effective_user_msg": session.effective_user_msg(),
                    "trade_followup": True,
                },
            },
        ],
    )
    plan = plan_dispatch(session=session)
    assert plan.tasks[0].agent == "trade_search"
    assert "召唤" in plan.tasks[0].payload.get("query", "")
