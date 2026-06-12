"""One-shot icon pipeline diagnostic (run inside backend container)."""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from pathlib import Path


def test(url: str) -> None:
    try:
        r = urllib.request.urlopen(url, timeout=15)
        body = r.read()
        print(url, "OK", r.status, len(body), r.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as e:
        print(url, "HTTP", e.code, e.read()[:200])
    except Exception as e:
        print(url, "ERR", type(e).__name__, e)


def main() -> None:
    import sys

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    name = "%E7%BA%B3%E5%90%89%E5%B0%94%E7%9A%84%E5%AE%A1%E5%88%A4"
    test(f"http://localhost:8000/api/entities/icon?name={name}")
    test(f"http://localhost:8000/api/entities/icon-image?name={name}")

    icons = Path("/app/data/icons/item")
    if icons.is_dir():
        print("local files", [str(f) for f in icons.glob("Nazir*")][:3])
    else:
        print("no icons dir", icons)

    from app.services.entity_icon_service import (
        proxy_icon_bytes,
        resolve_icon_url,
        resolve_local_icon,
    )
    from app.services.entity_tooltip import _resolve_entity

    cn = "纳吉尔的审判"
    resolved = _resolve_entity(cn)
    print("resolved entity", resolved)
    url = resolve_icon_url("Nazir's Judgement", "item", name_cn=cn, allow_fetch=False)
    print("resolved url", bool(url), (url or "")[:80])
    local = resolve_local_icon("Nazir's Judgement", "item", name_cn=cn)
    print("local", local)
    if url:
        body, ctype = proxy_icon_bytes(url)
        print("proxy", bool(body), ctype, len(body or b""))
    print("HTTP_PROXY", os.environ.get("HTTP_PROXY", ""))


if __name__ == "__main__":
    main()
