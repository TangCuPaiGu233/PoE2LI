"""Agent evaluation harness — sends eval_set.json questions to chat API, scores results.

Usage:
    python backend/tests/eval_agent.py                    # run all, print report
    python backend/tests/eval_agent.py --id build_001     # run single question
    python backend/tests/eval_agent.py --category build   # run category

Output: JSON report to backend/data/eval_results/{timestamp}.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Config ────────────────────────────────────────────────────

_DEFAULT_API_URL = "http://192.168.110.26:8000/api/chat"
api_url = os.getenv("EVAL_API_URL", _DEFAULT_API_URL)
EVAL_SET_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval_set.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "eval_results")
TIMEOUT_SEC = int(os.getenv("EVAL_TIMEOUT_SEC", "120"))
REQUEST_DELAY_SEC = int(os.getenv("EVAL_REQUEST_DELAY_SEC", "3"))

# PoE1-only entities that should never appear in PoE2 answers (extra safety net)
_POE1_BLACKLIST: set[str] = {
    "unearth", "minion mastery", "minion pact", "bone construct",
    "bone offering", "flesh offering", "spirit offering", "raise zombie",
    "summon skeletons", "marauder", "ranger", "duelist", "templar",
    "shadow", "scion", "juggernaut", "berserker", "chieftain",
    "necromancer", "elementalist", "occultist", "deadeye", "pathfinder",
    "raider", "saboteur", "trickster", "assassin", "guardian",
    "hierophant", "inquisitor", "champion", "gladiator", "slayer",
}


# ── Helpers ────────────────────────────────────────────────────

def load_eval_set(path: str | None = None) -> list[dict]:
    path = path or EVAL_SET_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("eval_set.json must be a JSON array")
    return data


def send_chat(messages: list[dict], *, endpoint: str) -> dict[str, Any]:
    """Send one chat request via SSE, return structured result."""
    body = json.dumps({"messages": messages}).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    t0 = time.perf_counter()
    answer_parts: list[str] = []
    tool_calls: list[dict] = []
    events: list[dict] = []
    errors: list[str] = []

    try:
        response = urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT_SEC)
        for line in response:
            line = line.decode(errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            events.append(ev)
            etype = ev.get("type", "")
            if etype == "answer":
                answer_parts.append(str(ev.get("content", "")))
            elif etype == "tool_use":
                c = ev.get("content", {})
                tool_calls.append({"name": c.get("name", "?"), "args": c.get("arguments", {})})
            elif etype == "tool_result":
                pass  # track separately if needed
            elif etype == "entity_warnings":
                warnings = ev.get("content", [])
                if isinstance(warnings, list):
                    for w in warnings:
                        if isinstance(w, dict):
                            errors.append(f"entity_warn:{w.get('name','?')}/{w.get('risk','?')}")
    except Exception as e:
        errors.append(f"request_error: {e}")

    latency_ms = round((time.perf_counter() - t0) * 1000)
    answer = "".join(answer_parts)
    answer_lower = answer.lower()

    return {
        "latency_ms": latency_ms,
        "answer": answer,
        "answer_lower": answer_lower,
        "tool_calls": tool_calls,
        "tool_call_count": len(tool_calls),
        "tool_names": [tc["name"] for tc in tool_calls],
        "errors": errors,
        "events": events,
    }


def score_result(
    result: dict,
    question: dict,
) -> dict[str, Any]:
    """Score one result against expected criteria."""
    answer = result["answer_lower"]
    tool_count = result["tool_call_count"]
    max_calls = question.get("max_tool_calls", 3)
    expected = [e.lower() for e in question.get("expected_entities", [])]
    forbidden = [e.lower() for e in question.get("forbidden_entities", [])]
    forbidden_extended = list(set(forbidden) | _POE1_BLACKLIST)

    # ── Hallucination check ──
    hallucination_hits: list[str] = []
    for entity in forbidden_extended:
        if entity in answer:
            hallucination_hits.append(entity)

    # ── Entity recall ──
    recalled: list[str] = []
    missed: list[str] = []
    for entity in expected:
        if entity in answer:
            recalled.append(entity)
        else:
            missed.append(entity)

    # ── Pass/fail ──
    passed_tools = tool_count <= max_calls
    passed_hallu = len(hallucination_hits) == 0
    passed_recall = len(expected) == 0 or len(missed) <= len(expected) * 0.5
    overall = passed_tools and passed_hallu

    return {
        "id": question["id"],
        "category": question.get("category", "?"),
        "query": question["messages"][-1]["content"][:80],
        "latency_ms": result["latency_ms"],
        "tool_call_count": tool_count,
        "tool_names": result["tool_names"],
        "max_tool_calls": max_calls,
        "passed_tools": passed_tools,
        "hallucination_hits": hallucination_hits,
        "passed_hallu": passed_hallu,
        "recalled": recalled,
        "missed": missed,
        "recall_rate": round(len(recalled) / max(len(expected), 1), 2),
        "passed_recall": passed_recall,
        "passed": overall,
        "errors": result["errors"],
        "answer_preview": result["answer"][:300],
    }


def run_eval(
    eval_set: list[dict],
    *,
    api_url: str,
    filter_id: str | None = None,
    filter_category: str | None = None,
) -> dict[str, Any]:
    """Run evaluation and return report."""
    questions = eval_set
    if filter_id:
        questions = [q for q in eval_set if q["id"] == filter_id]
    if filter_category:
        questions = [q for q in eval_set if q.get("category") == filter_category]

    if not questions:
        return {"error": "no questions matched filters"}

    scores: list[dict] = []
    start_time = time.perf_counter()

    for i, q in enumerate(questions):
        qid = q["id"]
        print(f"[{i+1}/{len(questions)}] {qid}: {q['messages'][-1]['content'][:60]} ...", end=" ", flush=True)
        try:
            result = send_chat(q["messages"], endpoint=api_url)
        except Exception as e:
            result = {
                "latency_ms": 0, "answer": "", "answer_lower": "",
                "tool_calls": [], "tool_call_count": 0, "tool_names": [],
                "errors": [str(e)], "events": [],
            }

        score = score_result(result, q)
        scores.append(score)

        status = "PASS" if score["passed"] else "FAIL"
        print(f"{status} {score['tool_call_count']}tools {score['latency_ms']}ms "
              f"hallu={score['hallucination_hits']} recall={score['recall_rate']}")

        if i < len(questions) - 1:
            time.sleep(REQUEST_DELAY_SEC)

    total_elapsed = round(time.perf_counter() - start_time, 1)
    passed = [s for s in scores if s["passed"]]
    failed = [s for s in scores if not s["passed"]]

    # ── Aggregate metrics ──
    latencies = [s["latency_ms"] for s in scores if s["latency_ms"] > 0]
    tool_counts = [s["tool_call_count"] for s in scores]
    total_hallu_hits = sum(len(s["hallucination_hits"]) for s in scores)
    total_answers_with_hallu = sum(1 for s in scores if s["hallucination_hits"])
    total_expected = sum(len(q.get("expected_entities", [])) for q in questions)
    total_recalled = sum(len(s["recalled"]) for s in scores)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "api_url": api_url,
        "total_questions": len(questions),
        "total_elapsed_s": total_elapsed,
        "pass_count": len(passed),
        "fail_count": len(failed),
        "pass_rate": round(len(passed) / max(len(scores), 1), 3),
        "metrics": {
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "latency_avg_ms": round(sum(latencies) / max(len(latencies), 1)),
            "tool_calls_avg": round(sum(tool_counts) / max(len(tool_counts), 1), 1),
            "tool_calls_total": sum(tool_counts),
            "hallu_rate": round(total_answers_with_hallu / max(len(scores), 1), 3),
            "hallu_total_hits": total_hallu_hits,
            "recall_rate": round(total_recalled / max(total_expected, 1), 3),
        },
        "by_category": _by_category(scores),
        "scores": scores,
        "failed_summary": [
            {"id": s["id"], "hallu": s["hallucination_hits"], "tools": s["tool_call_count"],
             "recall": s["recall_rate"], "errors": s["errors"]}
            for s in failed
        ],
    }

    # ── Save ──
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(RESULTS_DIR, f"eval_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {out_path}")

    return report


def _percentile(sorted_data: list[int], p: int) -> int:
    if not sorted_data:
        return 0
    data = sorted(sorted_data)
    idx = int(len(data) * p / 100)
    return data[min(idx, len(data) - 1)]


def _by_category(scores: list[dict]) -> dict:
    cats: dict[str, list] = {}
    for s in scores:
        cats.setdefault(s["category"], []).append(s)
    return {
        cat: {
            "count": len(items),
            "pass_rate": round(sum(1 for s in items if s["passed"]) / max(len(items), 1), 2),
            "avg_tool_calls": round(sum(s["tool_call_count"] for s in items) / max(len(items), 1), 1),
            "avg_latency_ms": round(sum(s["latency_ms"] for s in items) / max(len(items), 1)),
        }
        for cat, items in cats.items()
    }


# ── CLI ────────────────────────────────────────────────────────

def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description="PoE2LI Agent Evaluation")
    parser.add_argument("--id", help="Run single question by id")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--api-url", default=api_url, help="Chat API endpoint")
    parser.add_argument("--eval-set", default=EVAL_SET_PATH, help="Path to eval set JSON")
    parser.add_argument("--json", action="store_true", help="Output report as JSON to stdout")
    args = parser.parse_args()

    endpoint = args.api_url
    eval_set = load_eval_set(args.eval_set)
    print(f"Loaded {len(eval_set)} questions from {args.eval_set}")
    print(f"Target: {endpoint}")
    print()

    report = run_eval(eval_set, api_url=endpoint, filter_id=args.id, filter_category=args.category)

    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "scores"}, ensure_ascii=False, indent=2))
        return

    m = report["metrics"]
    print(f"\n{'='*60}")
    print(f"EVAL REPORT  |  {report['total_questions']} questions  |  {report['total_elapsed_s']}s elapsed")
    print(f"{'='*60}")
    print(f"  Pass rate:       {report['pass_rate']:.0%} ({report['pass_count']}/{report['total_questions']})")
    print(f"  Hallu rate:      {m['hallu_rate']:.0%} ({m['hallu_total_hits']} hits, {report['total_questions']} answers)")
    print(f"  Recall rate:     {m['recall_rate']:.0%}")
    print(f"  Avg tool calls:  {m['tool_calls_avg']} (total: {m['tool_calls_total']})")
    print(f"  P50 latency:     {m['latency_p50_ms']}ms")
    print(f"  P95 latency:     {m['latency_p95_ms']}ms")
    print(f"  Avg latency:     {m['latency_avg_ms']}ms")
    print(f"\n  By category:")
    for cat, stats in report["by_category"].items():
        print(f"    {cat:20s}  pass={stats['pass_rate']:.0%}  tools={stats['avg_tool_calls']}  latency={stats['avg_latency_ms']}ms")
    if report["failed_summary"]:
        print(f"\n  Failed ({len(report['failed_summary'])}):")
        for f in report["failed_summary"]:
            print(f"    {f['id']}: hallu={f['hallu']} tools={f['tools']} recall={f['recall']} errors={f['errors']}")


if __name__ == "__main__":
    main()
