"""Fetch and filter NAS chat/trade audit logs for local review."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import argparse
from pathlib import Path

from remote_ssh import DOCKER, REPO_ROOT, configure_utf8_stdio, connect_nas, run

DEFAULT_KEYWORDS = (
    "CHAT",
    "rag_search",
    "forced_rag",
    "tool_call",
    "keyword_plan",
    "entity_resolve",
    "trade_search",
    "resolve_trade_stat",
    "decode_pob",
)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Fetch filtered chat/trade logs from NAS")
    parser.add_argument("--tail", type=int, default=800)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "scripts" / "out" / "nas_chat_audit.txt",
    )
    parser.add_argument("--keyword", action="append", dest="keywords")
    args = parser.parse_args()
    keywords = tuple(args.keywords) if args.keywords else DEFAULT_KEYWORDS

    client = connect_nas()
    try:
        code, out, _ = run(
            client,
            f"{DOCKER} logs poe2li-backend --tail {args.tail} 2>&1",
            timeout=120,
        )
        if code != 0:
            return code
        raw_lines = out.splitlines()

        def matches(line: str) -> bool:
            return any(kw in line for kw in keywords)

        match_indices: set[int] = set()
        for i, line in enumerate(raw_lines):
            if matches(line):
                for j in range(max(0, i - 2), min(len(raw_lines), i + 3)):
                    match_indices.add(j)
        filtered = [raw_lines[i] for i in sorted(match_indices)]

        _, recent_chat, _ = run(
            client,
            f"{DOCKER} logs poe2li-backend --since 2h 2>&1 | "
            "grep -E 'CHAT|POST /api/chat' | tail -100",
            timeout=120,
        )
    finally:
        client.close()

    sections = [
        "=" * 80,
        f"FILTERED AUDIT (tail {args.tail}, keywords + 2 line context)",
        "=" * 80,
        "",
        *filtered,
        "",
        "=" * 80,
        "RECENT CHAT (last 2h: CHAT | POST /api/chat)",
        "=" * 80,
        "",
        recent_chat.rstrip(),
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"Wrote {len(filtered)} context lines from {len(raw_lines)} total -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
