"""Hotfix entity chip / tooltip files to NAS backend."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from remote_ssh import DOCKER, REPO_ROOT, configure_utf8_stdio, connect_nas, run

HOTFIX_FILES = (
    ("backend/app/services/entity_tooltip.py", "/app/app/services/entity_tooltip.py"),
    (
        "backend/app/services/entity_catalog_service.py",
        "/app/app/services/entity_catalog_service.py",
    ),
)


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        for rel, container_path in HOTFIX_FILES:
            local = REPO_ROOT / rel
            remote_tmp = f"/tmp/{local.name}"
            payload = base64.b64encode(local.read_bytes()).decode("ascii")
            upload = (
                "python3 - <<'PY'\n"
                "import base64\n"
                f"open('{remote_tmp}','wb').write(base64.b64decode('{payload}'))\n"
                "PY"
            )
            code, _, err = run(client, upload, timeout=120, echo=False)
            if code != 0:
                print(err)
                return code
            code, _, err = run(
                client,
                f"{DOCKER} cp {remote_tmp} poe2li-backend:{container_path}",
                timeout=120,
            )
            if code != 0:
                print(err)
                return code
            print("uploaded", rel)

        code, _, err = run(client, f"{DOCKER} restart poe2li-backend", timeout=180)
        if code != 0:
            print(err)
            return code
    finally:
        client.close()
    print("NAS entity chip hotfix ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
