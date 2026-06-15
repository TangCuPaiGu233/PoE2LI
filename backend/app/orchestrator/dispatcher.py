"""Parallel sub-agent dispatch with concurrency limit and per-task timeout."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from app.orchestrator.runners import run_task
from app.orchestrator.schemas import SkillAgentResult, TaskSpec

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENCY = int(os.getenv("ORCHESTRATOR_MAX_PARALLEL", "12"))


async def dispatch_parallel(
    tasks: list[TaskSpec],
    *,
    user_msg: str,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    on_task_done: Callable[[SkillAgentResult], Awaitable[None]] | None = None,
) -> list[SkillAgentResult]:
    """Run all tasks concurrently; barrier when all complete (or timeout/fail)."""
    if not tasks:
        return []

    sem = asyncio.Semaphore(max(1, max_concurrency))
    results: list[SkillAgentResult] = []

    async def _one(spec: TaskSpec) -> SkillAgentResult:
        async with sem:
            try:
                result = await asyncio.wait_for(
                    run_task(spec, user_msg=user_msg),
                    timeout=spec.timeout_sec,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[ORCH] task %s agent=%s timed out after %.0fs",
                    spec.task_id,
                    spec.agent,
                    spec.timeout_sec,
                )
                result = SkillAgentResult(
                    task_id=spec.task_id,
                    agent=spec.agent,
                    ok=False,
                    match_quality="failed",
                    error=f"timeout after {spec.timeout_sec}s",
                )
            if on_task_done:
                await on_task_done(result)
            return result

    gathered = await asyncio.gather(*[_one(t) for t in tasks], return_exceptions=True)
    for i, item in enumerate(gathered):
        if isinstance(item, BaseException):
            spec = tasks[i]
            logger.exception("[ORCH] task %s raised", spec.task_id)
            results.append(
                SkillAgentResult(
                    task_id=spec.task_id,
                    agent=spec.agent,
                    ok=False,
                    match_quality="failed",
                    error=str(item),
                ),
            )
        else:
            results.append(item)
    return results
