"""Build DispatchPlan — LLM-first (agent decides), minimal deterministic fallbacks."""

from __future__ import annotations

from app.orchestrator.llm_planner import llm_plan_dispatch
from app.orchestrator.schemas import DispatchPlan
from app.orchestrator.session_context import SessionContext, build_session_context


def plan_dispatch(
    user_msg: str | None = None,
    *,
    messages: list[dict] | None = None,
    session: SessionContext | None = None,
) -> DispatchPlan:
    """Plan sub-agent tasks. Requires messages for LLM planner (preferred)."""
    if messages is not None:
        return llm_plan_dispatch(messages)

    if session is not None:
        # Reconstruct minimal single-turn messages for planner
        return llm_plan_dispatch([{"role": "user", "content": session.current_user_text}])

    text = (user_msg or "").strip()
    return llm_plan_dispatch([{"role": "user", "content": text}])
