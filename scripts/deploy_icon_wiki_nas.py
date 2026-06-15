"""Deploy icon service + run poe2db backfill on NAS."""

import base64
import io
import sys
import time
from pathlib import Path

import paramiko

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

NAS = "192.168.110.26"
PORT = 2212
USER = "skc"
PASS = "SKChaidao@123"
DOCKER = "/usr/local/bin/docker"
NAS_ROOT = "/volume1/docker/PoE2LI"
REPO = Path(__file__).resolve().parent.parent

FILES = [
    (REPO / "backend/app/services/entity_icon_service.py", "/app/app/services/entity_icon_service.py"),
    (REPO / "backend/app/services/entity_profile.py", "/app/app/services/entity_profile.py"),
    (REPO / "backend/app/services/entity_catalog_service.py", "/app/app/services/entity_catalog_service.py"),
    (REPO / "backend/app/services/entity_tooltip.py", "/app/app/services/entity_tooltip.py"),
    (REPO / "backend/app/services/retrieval_pipeline.py", "/app/app/services/retrieval_pipeline.py"),
    (REPO / "backend/app/api/entities.py", "/app/app/api/entities.py"),
    (REPO / "backend/scripts/backfill_poe2db_icon_gaps.py", "/app/scripts/backfill_poe2db_icon_gaps.py"),
    (REPO / "backend/scripts/build_entity_catalog.py", "/app/scripts/build_entity_catalog.py"),
]


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 600) -> str:
    print(f"\n$ {cmd[:120]}")
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    if out.strip():
        print(out.rstrip()[-4000:])
    if err.strip():
        print("ERR:", err.rstrip()[-800:])
    return out


def main() -> int:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(NAS, PORT, USER, PASS, timeout=15)

    for local, remote in FILES:
        data = base64.b64encode(local.read_bytes()).decode("ascii")
        host_path = f"{NAS_ROOT}/{local.relative_to(REPO).as_posix()}"
        run(c, f"mkdir -p $(dirname {host_path})")
        run(c, f"echo {data} | base64 -d > {host_path}", timeout=120)
        run(c, f"{DOCKER} cp {host_path} poe2li-backend:{remote}")

    run(c, f"{DOCKER} compose -f {NAS_ROOT}/docker-compose.yml restart backend", timeout=180)
    time.sleep(10)

    run(
        c,
        f"{DOCKER} exec poe2li-backend python -u /app/scripts/backfill_poe2db_icon_gaps.py "
        f"--data-dir /app/data --delay 1.5",
        timeout=900,
    )

    run(
        c,
        f"{DOCKER} exec poe2li-backend python -u /app/scripts/build_entity_catalog.py "
        f"--data-dir /app/data",
        timeout=900,
    )

    run(
        c,
        f"{DOCKER} exec poe2li-backend python -c \""
        f"from app.services.entity_catalog_service import catalog_stats; "
        f"print(catalog_stats())\"",
    )
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
