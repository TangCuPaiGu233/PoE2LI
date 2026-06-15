"""Deploy icon services + run poe2db backfill and entity catalog rebuild on NAS."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import base64
import time

from remote_ssh import DOCKER, NAS_ROOT, REPO_ROOT, configure_utf8_stdio, connect_nas, run

DEPLOY_FILES = (
    ("backend/app/services/entity_icon_service.py", "/app/app/services/entity_icon_service.py"),
    ("backend/app/services/entity_profile.py", "/app/app/services/entity_profile.py"),
    ("backend/app/services/entity_catalog_service.py", "/app/app/services/entity_catalog_service.py"),
    ("backend/app/services/entity_tooltip.py", "/app/app/services/entity_tooltip.py"),
    ("backend/app/services/retrieval_pipeline.py", "/app/app/services/retrieval_pipeline.py"),
    ("backend/app/api/entities.py", "/app/app/api/entities.py"),
    ("backend/scripts/backfill_poe2db_icon_gaps.py", "/app/scripts/backfill_poe2db_icon_gaps.py"),
    ("backend/scripts/build_entity_catalog.py", "/app/scripts/build_entity_catalog.py"),
)


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        for rel, remote in DEPLOY_FILES:
            local = REPO_ROOT / rel
            host_path = f"{NAS_ROOT}/{local.relative_to(REPO_ROOT).as_posix()}"
            data = base64.b64encode(local.read_bytes()).decode("ascii")
            run(client, f"mkdir -p $(dirname {host_path})")
            run(client, f"echo {data} | base64 -d > {host_path}", timeout=120)
            code, _, _ = run(client, f"{DOCKER} cp {host_path} poe2li-backend:{remote}")
            if code != 0:
                return code

        run(client, f"cd {NAS_ROOT} && {DOCKER} compose restart backend", timeout=180)
        time.sleep(10)

        run(
            client,
            f"{DOCKER} exec poe2li-backend python -u /app/scripts/backfill_poe2db_icon_gaps.py "
            f"--data-dir /app/data --delay 1.5",
            timeout=900,
        )
        run(
            client,
            f"{DOCKER} exec poe2li-backend python -u /app/scripts/build_entity_catalog.py "
            f"--data-dir /app/data",
            timeout=900,
        )
        run(
            client,
            f'{DOCKER} exec poe2li-backend python -c "'
            f"from app.services.entity_catalog_service import catalog_stats; "
            f'print(catalog_stats())"',
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
