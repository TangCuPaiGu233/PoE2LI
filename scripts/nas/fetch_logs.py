"""Fetch recent poe2li-backend logs from NAS."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import argparse

from remote_ssh import DOCKER, configure_utf8_stdio, connect_nas, run


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Fetch NAS backend docker logs")
    parser.add_argument("--tail", type=int, default=200, help="Number of log lines")
    parser.add_argument("--since", default="", help="docker logs --since value, e.g. 2h")
    args = parser.parse_args()

    since_flag = f" --since {args.since}" if args.since else ""
    cmd = f"{DOCKER} logs poe2li-backend{since_flag} --tail {args.tail} 2>&1"

    client = connect_nas()
    try:
        code, out, _ = run(client, cmd, timeout=120)
        if code != 0:
            return code
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
