"""Build DispatchPlan from user message (keyword multi-match + PoB detection)."""

from __future__ import annotations

import re
import uuid

from app.orchestrator.schemas import AgentName, DispatchPlan, TaskSpec
from app.services.chat_tools import find_build_input
from app.skills.build_design import BuildDesignSkill
from app.skills.encyclopedia import EncyclopediaSkill
from app.skills.recommend import RecommendSkill
from app.skills.trade_search import TradeSearchSkill

_SKILLS = [
    TradeSearchSkill(),
    BuildDesignSkill(),
    RecommendSkill(),
    EncyclopediaSkill(),
]

# Compound queries: mechanism + trade in one message
_MECHANISM_WITH_TRADE = re.compile(
    r"(机制|怎么得|是什么|什么意思|涂油|腐蚀|扩散|词缀|效果|怎么获得)",
    re.I,
)
_TRADE_STRONG = re.compile(
    r"(搜|找|买|卖|市价|多少钱|查价|交易|帮我找|帮我搜|trade|集市)",
    re.I,
)


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def _trade_task(user_msg: str, *, detail_count: int = 5) -> TaskSpec:
    return TaskSpec(
        task_id=_new_task_id(),
        agent="trade_search",
        user_phrase=user_msg,
        payload={"query": user_msg[:300], "detail_count": detail_count},
    )


def _encyclopedia_task(user_msg: str, *, query: str | None = None) -> TaskSpec:
    return TaskSpec(
        task_id=_new_task_id(),
        agent="encyclopedia",
        user_phrase=user_msg,
        payload={"query": query or user_msg[:200]},
    )


def _build_task(user_msg: str) -> TaskSpec:
    return TaskSpec(
        task_id=_new_task_id(),
        agent="build_design",
        user_phrase=user_msg,
        payload={"query": user_msg[:300]},
    )


def _recommend_task(user_msg: str) -> TaskSpec:
    return TaskSpec(
        task_id=_new_task_id(),
        agent="recommend",
        user_phrase=user_msg,
        payload={"question": user_msg},
    )


def _decode_pob_task(user_msg: str, build_input: str) -> TaskSpec:
    return TaskSpec(
        task_id=_new_task_id(),
        agent="decode_pob",
        user_phrase=user_msg,
        payload={"input": build_input},
        priority=10,
    )


def plan_dispatch(user_msg: str) -> DispatchPlan:
    """Return one or more TaskSpecs to run in parallel."""
    text = (user_msg or "").strip()
    if not text:
        return DispatchPlan(
            tasks=[_encyclopedia_task(text or "你好")],
            planning_note="empty_input_fallback",
        )

    tasks: list[TaskSpec] = []
    notes: list[str] = []

    build_input = find_build_input(text)
    if build_input:
        tasks.append(_decode_pob_task(text, build_input))
        notes.append("decode_pob")

    matched_agents: list[AgentName] = []
    for skill in _SKILLS:
        if skill.matches(text):
            matched_agents.append(skill.name)  # type: ignore[arg-type]

    trade_hit = "trade_search" in matched_agents
    enc_hit = "encyclopedia" in matched_agents
    mech_trade_combo = trade_hit and _MECHANISM_WITH_TRADE.search(text)

    if mech_trade_combo or (trade_hit and enc_hit):
        if "trade_search" not in [t.agent for t in tasks]:
            tasks.append(_trade_task(text))
        if "encyclopedia" not in [t.agent for t in tasks]:
            tasks.append(_encyclopedia_task(text))
        notes.append("parallel_trade_and_knowledge")
    else:
        for name in matched_agents:
            if name == "trade_search" and "trade_search" not in [t.agent for t in tasks]:
                tasks.append(_trade_task(text))
            elif name == "recommend" and "recommend" not in [t.agent for t in tasks]:
                tasks.append(_recommend_task(text))
            elif name == "build_design" and "build_design" not in [t.agent for t in tasks]:
                tasks.append(_build_task(text))
            elif name == "encyclopedia" and "encyclopedia" not in [t.agent for t in tasks]:
                tasks.append(_encyclopedia_task(text))

    if not tasks or all(t.agent == "decode_pob" for t in tasks):
        if not any(t.agent == "encyclopedia" for t in tasks):
            tasks.append(_encyclopedia_task(text))
            notes.append("encyclopedia_fallback")

    # decode_pob only: still add encyclopedia if user asked a question beyond link
    if len(text) > 40 and build_input and len(tasks) == 1:
        tasks.append(_encyclopedia_task(text))
        notes.append("pob_plus_question")

    tasks.sort(key=lambda t: -t.priority)
    return DispatchPlan(tasks=tasks, planning_note=",".join(notes) or "keyword_match")
