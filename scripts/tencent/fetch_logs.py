"""Fetch filtered Tencent backend chat/trade logs."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import argparse

from remote_ssh import REPO_ROOT, configure_utf8_stdio, connect_tencent, run


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "scripts" / "out" / "tencent_logs.txt",
    )
    args = parser.parse_args()

    client = connect_tencent()
    sections: list[str] = []
    try:
        for cmd in (
            "docker logs poe2li-backend --since 2h 2>&1 | "
            "grep -E 'CHAT|trade_search|trade_agent|Error|WARNING|failed|Intent|Plan |POST to|tool_call' | tail -80",
            "docker logs poe2li-backend --since 2h 2>&1 | tail -40",
        ):
            sections.append("=" * 70)
            sections.append(cmd)
            sections.append("=" * 70)
            _, out, _ = run(client, cmd, timeout=60, echo=False)
            sections.append(out.rstrip())
    finally:
        client.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
