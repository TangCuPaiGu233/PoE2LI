"""NAS PoE2LI health check.

Checks:
- Backend API docs page at http://127.0.0.1:8000/docs
- Frontend root page at http://127.0.0.1:3000/

Exit codes:
0 - both checks passed
1 - one or more checks failed
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import argparse

from remote_ssh import DOCKER, configure_utf8_stdio, connect_nas, run

CHECKS = [
    ("backend_docs", "curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs", "200"),
    ("frontend_root", "curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/", "200"),
]

def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="NAS PoE2LI health check")
    parser.add_argument("--timeout", type=int, default=10, help="Per-check timeout in seconds")
    args = parser.parse_args()

    client = connect_nas(timeout=args.timeout)
    try:
        failed = []
        for name, cmd, expected in CHECKS:
            code, out, err = run(client, cmd, timeout=args.timeout, echo=False)
            actual = out.strip()
            ok = code == 0 and expected in actual
            status = "OK" if ok else "FAIL"
            print(f"[{status}] {name}: expected={expected}, actual={actual}")
            if not ok:
                failed.append(name)
                if err.strip():
                    print(err.strip()[-400:])
        if failed:
            print(f"FAILED checks: {', '.join(failed)}")
            return 1
        print("All checks passed.")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
