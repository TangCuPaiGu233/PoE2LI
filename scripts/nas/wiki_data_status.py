"""Report wiki icon scrape progress on NAS data volume."""

from __future__ import annotations

import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from remote_ssh import NAS_ROOT, configure_utf8_stdio, connect_nas, run


def main() -> int:
    configure_utf8_stdio()
    client = connect_nas()
    try:
        cmds = [
            f"find {NAS_ROOT}/data/icons/wiki -name '*.png' 2>/dev/null | wc -l",
            f"du -sh {NAS_ROOT}/data/icons/wiki {NAS_ROOT}/data/wiki_icons 2>/dev/null",
            (
                f"for d in {NAS_ROOT}/data/icons/wiki/*/; do "
                'echo "$(basename $d): $(find $d -name \'*.png\' | wc -l)"; done'
            ),
            (
                f"wc -l {NAS_ROOT}/data/wiki_icons/manifest.jsonl "
                f"{NAS_ROOT}/data/wiki_icons/failures.jsonl 2>/dev/null"
            ),
            f"cat {NAS_ROOT}/data/wiki_icons/stats.json 2>/dev/null | head -c 2000",
        ]
        for cmd in cmds:
            print("===", cmd[:90])
            run(client, cmd, timeout=60)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
