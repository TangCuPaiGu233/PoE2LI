"""Restart NAS backend after syncing to origin/main."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from remote_ssh import DOCKER, NAS_ROOT, configure_utf8_stdio, connect_nas, run


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        for cmd in (
            f"cd {NAS_ROOT} && git fetch origin && git reset --hard origin/main",
            f"cd {NAS_ROOT} && {DOCKER} compose restart backend",
            f"{DOCKER} ps --filter name=poe2li-backend --format '{{{{.Names}}}} {{{{.Status}}}}'",
        ):
            code, _, _ = run(client, cmd, timeout=180)
            if code != 0:
                return code
    finally:
        client.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
