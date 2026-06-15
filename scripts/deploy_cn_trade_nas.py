"""Sync NAS to origin/main and rebuild backend + frontend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from remote_ssh import DOCKER, NAS_ROOT, configure_utf8_stdio, connect_nas, run

GIT_REF = os.getenv("NAS_GIT_REF", "main")


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        cmds = [
            f"cd {NAS_ROOT} && git fetch origin",
            f"cd {NAS_ROOT} && git checkout -f {GIT_REF} && git reset --hard origin/{GIT_REF}",
            f"cd {NAS_ROOT} && {DOCKER} compose build backend frontend",
            f"cd {NAS_ROOT} && {DOCKER} compose up -d backend frontend",
            (
                f'{DOCKER} exec poe2li-backend python -c "'
                f"from app.services.trade_realm import search_api_url; "
                f'print(search_api_url(\'cn\'))"'
            ),
        ]
        for cmd in cmds:
            code, _, _ = run(client, cmd, timeout=900)
            if code != 0:
                print(f"FAILED exit={code}")
                return code
    finally:
        client.close()
    print("\nDeploy OK. Ensure TRADE_CN_POESESSID is set in NAS .env if using CN trade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
