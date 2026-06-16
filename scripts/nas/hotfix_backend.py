"""Emergency: docker cp backend service files into NAS container and restart.

Use when NAS git is on main but you need to test unpushed backend changes quickly.
"""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import base64

from remote_ssh import DOCKER, REPO_ROOT, configure_utf8_stdio, connect_nas, run

HOTFIX_FILES = (
    ("backend/app/core/llm_config.py", "/app/app/core/llm_config.py"),
    ("backend/app/services/trade_agent.py", "/app/app/services/trade_agent.py"),
    ("backend/app/services/trade_concepts.py", "/app/app/services/trade_concepts.py"),
    ("backend/app/services/chat_tools.py", "/app/app/services/chat_tools.py"),
    ("backend/app/services/chat_agent.py", "/app/app/services/chat_agent.py"),
    ("backend/app/services/multi_affix_compare.py", "/app/app/services/multi_affix_compare.py"),
    ("backend/app/services/chat_async_util.py", "/app/app/services/chat_async_util.py"),
    ("backend/app/services/chat_stream_lifecycle.py", "/app/app/services/chat_stream_lifecycle.py"),
    ("backend/app/services/chat_item_profile.py", "/app/app/services/chat_item_profile.py"),
    ("backend/app/services/trade_service.py", "/app/app/services/trade_service.py"),
    ("backend/app/services/chat_response_guard.py", "/app/app/services/chat_response_guard.py"),
    ("backend/app/services/trade_stats_index.py", "/app/app/services/trade_stats_index.py"),
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
            code, _, _ = run(client, upload, timeout=120, echo=False)
            if code != 0:
                return code
            code, _, _ = run(
                client,
                f"{DOCKER} cp {remote_tmp} poe2li-backend:{container_path}",
                timeout=120,
            )
            if code != 0:
                return code
            print("uploaded", rel)

        code, _, _ = run(client, f"{DOCKER} restart poe2li-backend", timeout=180)
        if code != 0:
            return code
    finally:
        client.close()
    print("NAS backend hotfix ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
