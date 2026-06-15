"""Quick NAS trade realm / POESESSID sanity checks."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from remote_ssh import DOCKER, configure_utf8_stdio, connect_nas, run


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        checks = [
            (
                "league",
                f'{DOCKER} exec poe2li-backend python -c '
                '"from app.services.trade_realm import resolve_league; print(resolve_league(\'cn\'))"',
            ),
            (
                "resolve_headhunter",
                f'{DOCKER} exec poe2li-backend python -c '
                '"from app.services.trade_service import resolve_trade_unique_name; '
                'print(resolve_trade_unique_name(\'\\u730e\\u9996\'))"',
            ),
            (
                "poesessid_len",
                f'{DOCKER} exec poe2li-backend python -c '
                '"import os; print(len(os.getenv(\'TRADE_CN_POESESSID\',\'\') or \'\'))"',
            ),
        ]
        for label, cmd in checks:
            code, out, err = run(client, cmd, timeout=60, echo=False)
            print(f"{label}: {out.strip()}")
            if err.strip():
                print(f"  stderr: {err.strip()[:300]}")
            if code != 0:
                return code
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
