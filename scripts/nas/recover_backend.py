"""One-shot: sync critical backend files to NAS container and restart (fix crash loop)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from remote_ssh import DOCKER, NAS_ROOT, REPO_ROOT, configure_utf8_stdio, connect_nas, run

# (repo-relative path, path inside poe2li-backend container)
SYNC_FILES = (
    ("backend/app/core/llm_config.py", "/app/app/core/llm_config.py"),
    (
        "backend/alembic/versions/e8f3a1b02c47_add_ref_text_zh_to_trade_stats.py",
        "/app/alembic/versions/e8f3a1b02c47_add_ref_text_zh_to_trade_stats.py",
    ),
)


def upload_file(client, rel: str, container_path: str) -> int:
    local = REPO_ROOT / rel
    host_path = f"{NAS_ROOT}/{rel.replace(chr(92), '/')}"
    payload = base64.b64encode(local.read_bytes()).decode("ascii")
    run(client, f"mkdir -p $(dirname {host_path})")
    code, _, _ = run(
        client,
        f"python3 -c \"import base64, pathlib; p=pathlib.Path('{host_path}'); "
        f"p.parent.mkdir(parents=True, exist_ok=True); "
        f"p.write_bytes(base64.b64decode('{payload}'))\"",
        timeout=120,
    )
    if code != 0:
        return code
    code, _, _ = run(client, f"{DOCKER} cp {host_path} poe2li-backend:{container_path}", timeout=120)
    return code


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        run(client, f"cd {NAS_ROOT} && git fetch origin && git reset --hard origin/main", timeout=120)
        for rel, dest in SYNC_FILES:
            print("sync", rel)
            code = upload_file(client, rel, dest)
            if code != 0:
                return code
        code, _, _ = run(client, f"{DOCKER} restart poe2li-backend", timeout=180)
        if code != 0:
            return code
        import time

        time.sleep(8)
        code, out, _ = run(
            client,
            f"{DOCKER} exec poe2li-backend python -c "
            "\"from app.core.llm_config import llm_message_text; print('llm_ok')\"",
            timeout=60,
        )
        if code != 0 or "llm_ok" not in out:
            print("import check failed")
            return 1
        run(client, f"{DOCKER} ps --filter name=poe2li-backend --format '{{{{.Status}}}}'", timeout=30)
    finally:
        client.close()
    print("backend recovered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
