"""Upload wiki icon scraper to NAS and start/resume scrape in backend container."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import base64
import time

from remote_ssh import DOCKER, NAS_ROOT, REPO_ROOT, configure_utf8_stdio, connect_nas, run

LOCAL_SCRIPT = REPO_ROOT / "backend" / "scripts" / "scrape_poe2wiki_icons.py"
REMOTE_SCRIPT = f"{NAS_ROOT}/backend/scripts/scrape_poe2wiki_icons.py"


def main() -> int:
    configure_utf8_stdio()
    if not LOCAL_SCRIPT.is_file():
        print(f"Missing {LOCAL_SCRIPT}")
        return 1

    client = connect_nas()
    try:
        data = base64.b64encode(LOCAL_SCRIPT.read_bytes()).decode("ascii")
        run(client, f"mkdir -p {NAS_ROOT}/backend/scripts")
        code, _, _ = run(client, f"echo {data} | base64 -d > {REMOTE_SCRIPT}", timeout=120)
        if code != 0:
            return code

        run(client, f"mkdir -p {NAS_ROOT}/data/wiki_icons {NAS_ROOT}/data/icons/wiki")
        code, _, _ = run(
            client,
            f"{DOCKER} cp {REMOTE_SCRIPT} poe2li-backend:/app/scripts/scrape_poe2wiki_icons.py",
        )
        if code != 0:
            return code

        _, cache_out, _ = run(
            client,
            f"{DOCKER} exec poe2li-backend test -f /app/data/wiki_icons/pages_cache.json "
            "&& echo yes || echo no",
        )
        if "yes" not in cache_out:
            print("Building pages_cache.json (~20 min)...")
            code, _, _ = run(
                client,
                f"{DOCKER} exec poe2li-backend python -u /app/scripts/scrape_poe2wiki_icons.py "
                "--data-dir /app/data --refresh-pages --collect-only --delay 2.5",
                timeout=3600,
            )
            if code != 0:
                return code

        run(client, f"{DOCKER} exec poe2li-backend pkill -f scrape_poe2wiki_icons.py || true")
        code, _, _ = run(
            client,
            f"{DOCKER} exec -d poe2li-backend python -u /app/scripts/scrape_poe2wiki_icons.py "
            "--data-dir /app/data --resume --delay 2.5",
        )
        if code != 0:
            return code
    finally:
        client.close()

    print("Scrape running detached in poe2li-backend.")
    print("Log: docker exec poe2li-backend tail -f /app/data/wiki_icons/scrape.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
