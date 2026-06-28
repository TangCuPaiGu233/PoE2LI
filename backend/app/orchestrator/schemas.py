"""Structured contracts between orchestrator and sub-agents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal[
    "trade_search",
    "encyclopedia",
    "build_design",
    "recommend",
    "decode_pob",
]

MatchQuality = Literal["exact", "degraded", "failed", "unknown"]


class TaskSpec(BaseModel):
    """What the orchestrator sends to a sub-agent (no full chat history)."""

    task_id: str
    agent: AgentName
    user_phrase: str = Field(description="Original user wording for this sub-task")
    payload: dict[str, Any] = Field(default_factory=dict)
    market: str = "cn"
    timeout_sec: float = 120.0
    priority: int = 0


class SkillAgentResult(BaseModel):
    """Structured output from a sub-agent back to the orchestrator."""

    task_id: str
    agent: AgentName
    ok: bool = True
    match_quality: MatchQuality = "unknown"
    summary: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    trade_data: dict[str, Any] | None = None
    recommend_data: dict[str, Any] | None = None
    latency_ms: int = 0
    error: str | None = None

    def to_synthesis_block(self) -> str:
        """Compact block for the orchestrator synthesis LLM."""
        lines = [
            f"### Sub-agent: {self.agent} (task_id={self.task_id})",
            f"ok={self.ok} match_quality={self.match_quality}",
        ]
        if self.warnings:
            lines.append("warnings: " + "; ".join(self.warnings))
        if self.summary:
            lines.append(self.summary)
        if self.trade_data:
            lines.append("trade_data: " + _short_json(self.trade_data))
        if self.facts and self.agent != "trade_search":
            lines.append("facts: " + _short_json(self.facts, max_len=4000))
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


class DispatchPlan(BaseModel):
    tasks: list[TaskSpec] = Field(default_factory=list)
    planning_note: str = ""
    session_turn_count: int = 0


def _short_json(obj: Any, max_len: int = 8000) -> str:
    import json

    text = json.dumps(obj, ensure_ascii=False)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text

class PlannerTaskEntry(BaseModel):
    """LLM raw output for a single planner task."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    query: str | None = None
    detail_count: int | None = None
    input: str | None = None
    question: str | None = None


class PlannerOutput(BaseModel):
    """LLM raw output root structure for the planner."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[PlannerTaskEntry] = Field(default_factory=list)
    reasoning: str | None = None
