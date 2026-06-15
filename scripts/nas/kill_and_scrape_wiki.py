"""Force-kill stuck wiki scrapers on NAS, then start exactly one fresh run."""

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
REMOTE = f"{NAS_ROOT}/backend/scripts/scrape_poe2wiki_icons.py"
HOST_LOG = f"{NAS_ROOT}/data/wiki_icons/host.log"


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        run(
            client,
            f"{DOCKER} top poe2li-backend -eo pid,cmd | grep scrape_poe2wiki_icons || echo none",
        )
        print("Restarting backend to clear stuck scrapers...")
        run(client, f"cd {NAS_ROOT} && {DOCKER} compose restart backend", timeout=180)
        time.sleep(8)
        run(
            client,
            f"{DOCKER} top poe2li-backend -eo pid,cmd | grep scrape_poe2wiki_icons || echo cleared",
        )

        data = base64.b64encode(LOCAL_SCRIPT.read_bytes()).decode("ascii")
        run(client, f"mkdir -p {NAS_ROOT}/backend/scripts")
        run(client, f"echo {data} | base64 -d > {REMOTE}", timeout=180)
        run(client, f"{DOCKER} cp {REMOTE} poe2li-backend:/app/scripts/scrape_poe2wiki_icons.py")
        run(client, f"{DOCKER} exec poe2li-backend rm -f /app/data/wiki_icons/scrape.lock")

        code, _, _ = run(
            client,
            f"nohup {DOCKER} exec poe2li-backend python -u /app/scripts/scrape_poe2wiki_icons.py "
            f"--data-dir /app/data --resume --delay 2.5 >> {HOST_LOG} 2>&1 &",
            timeout=60,
        )
        if code != 0:
            return code
    finally:
        client.close()
    print(f"Started scrape; host log: {HOST_LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
