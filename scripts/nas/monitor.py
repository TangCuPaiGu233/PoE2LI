"""NAS PoE2LI monitoring.

Repeatedly runs healthcheck and prints results to stdout.
Designed to be invoked by cron or a scheduled task.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from remote_ssh import DOCKER, configure_utf8_stdio, connect_nas, run

CHECKS = [
    ("backend_docs", "curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs", "200"),
    ("frontend_root", "curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/", "200"),
]


def check_once(client) -> tuple[bool, list[str]]:
    failed = []
    for name, cmd, expected in CHECKS:
        code, out, err = run(client, cmd, timeout=10, echo=False)
        actual = out.strip()
        ok = code == 0 and expected in actual
        failed.append(f"{name}={actual}:{ok}")
        if not ok and err.strip():
            failed.append(f"{name}_err={err.strip()[-200:]}")
    return all(":True" in item for item in failed), failed


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="NAS PoE2LI monitoring")
    parser.add_argument("--repeat", type=int, default=0, help="Repeat N times; 0=once")
    parser.add_argument("--interval", type=int, default=60, help="Repeat interval in seconds")
    args = parser.parse_args()

    client = connect_nas(timeout=15)
    try:
        for i in range(max(1, args.repeat + 1)):
            ok, results = check_once(client)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            status = "OK" if ok else "FAIL"
            print(f"{ts} {status} " + " | ".join(results), flush=True)
            if args.repeat > 0 and i < args.repeat:
                import time

                time.sleep(args.interval)
        return 0 if ok else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
