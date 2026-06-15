"""Emergency: copy local chat image UI files to NAS and rebuild frontend.

Prefer `python deploy_nas.py` after merging to main. Use this when you need
a targeted frontend hotfix without a full git reset.
"""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import base64

from remote_ssh import DOCKER, NAS_ROOT, REPO_ROOT, configure_utf8_stdio, connect_nas, run

CHAT_IMAGE_FILES = (
    "frontend/src/lib/chatImage.ts",
    "frontend/src/components/chat/ChatMessageImage.tsx",
    "frontend/src/components/chat/ChatMarkdown.tsx",
    "frontend/src/app/chat/page.tsx",
    "frontend/src/app/globals.css",
)


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        for rel in CHAT_IMAGE_FILES:
            local = REPO_ROOT / rel
            remote = f"{NAS_ROOT}/{rel.replace(chr(92), '/')}"
            payload = base64.b64encode(local.read_bytes()).decode("ascii")
            cmd = (
                "python3 - <<'PY'\n"
                "import base64, pathlib\n"
                f"p = pathlib.Path('{remote}')\n"
                "p.parent.mkdir(parents=True, exist_ok=True)\n"
                f"p.write_bytes(base64.b64decode('{payload}'))\n"
                "print('wrote', p, 'bytes', p.stat().st_size)\n"
                "PY"
            )
            print(">", rel)
            code, _, _ = run(client, cmd, timeout=120)
            if code != 0:
                return code

        build_cmd = (
            f"cd {NAS_ROOT} && {DOCKER} compose build --no-cache frontend "
            f"&& {DOCKER} compose up -d --force-recreate frontend"
        )
        code, _, _ = run(client, build_cmd, timeout=900)
        if code != 0:
            return code
    finally:
        client.close()
    print("NAS frontend hotfix ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
