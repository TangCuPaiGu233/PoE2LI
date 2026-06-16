#!/usr/bin/env python3
"""Smoke-test multi-agent orchestrator via /api/chat SSE (incremental read)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

DEFAULT_BASE = "http://192.168.110.26:8000"


def stream_chat(base: str, question: str, *, max_wait: float = 120.0) -> list[dict]:
    body = json.dumps({"messages": [{"role": "user", "content": question}]}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    events: list[dict] = []
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=max_wait) as resp:
        while True:
            if time.perf_counter() - t0 > max_wait:
                break
            line = resp.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text.startswith("data: "):
                continue
            try:
                ev = json.loads(text[6:])
            except json.JSONDecodeError:
                continue
            events.append(ev)
            et = ev.get("type")
            if et == "sub_agent_done":
                c = ev.get("content") or {}
                print(
                    f"  [sub_agent_done] {c.get('agent')} ok={c.get('ok')} "
                    f"quality={c.get('match_quality')} {c.get('latency_ms')}ms",
                    flush=True,
                )
            elif et == "thinking":
                print(f"  [thinking] {ev.get('content', '')}", flush=True)
            elif et == "trade_result":
                print("  [trade_result] received", flush=True)
            elif et == "done":
                break
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Test orchestrator chat SSE")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--question", "-q", action="append", dest="questions")
    parser.add_argument("--max-wait", type=float, default=120.0)
    args = parser.parse_args()

    questions = args.questions or [
        "火球术是什么技能",
        "帮我搜一条 +2 召唤技能等级的项链",
        "腰带怎么获得召唤物近战扩散效果，帮我搜一条",
    ]

    from app.orchestrator.planner import plan_dispatch

    print("=== Planner (local, no network) ===")
    for q in questions:
        plan = plan_dispatch(q)
        agents = [t.agent for t in plan.tasks]
        print(f"  Q: {q}")
        print(f"     -> agents={agents} note={plan.planning_note}")

    print("\n=== Live /api/chat (NAS) ===")
    for q in questions:
        print(f"\nQ: {q}")
        t0 = time.perf_counter()
        try:
            events = stream_chat(args.base, q, max_wait=args.max_wait)
            subs = [e for e in events if e.get("type") == "sub_agent_done"]
            ans = "".join(
                e.get("content", "") for e in events if e.get("type") == "answer"
            )
            print(f"  total={time.perf_counter()-t0:.1f}s sub_agents={len(subs)} answer_len={len(ans)}")
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    # Allow running from repo root without PYTHONPATH
    import os

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    backend = os.path.join(root, "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    raise SystemExit(main())
