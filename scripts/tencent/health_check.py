"""Quick Tencent VM health check (SSH)."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from remote_ssh import configure_utf8_stdio, connect_tencent, run


def main() -> int:
    configure_utf8_stdio()
    client = connect_tencent()
    try:
        for cmd in (
            "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | head -8",
            "curl -s -o /dev/null -w '127.0.0.1:3000 -> %{http_code}\\n' http://127.0.0.1:3000/ || true",
            "curl -s -o /dev/null -w '127.0.0.1:8000/health -> %{http_code}\\n' "
            "http://127.0.0.1:8000/health || true",
            "curl -s -o /dev/null -w '127.0.0.1:80 -> %{http_code}\\n' http://127.0.0.1/ 2>/dev/null | head -1 || true",
            "nginx -t 2>&1 | tail -2 || true",
        ):
            run(client, cmd, timeout=30)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
