"""Backfill poecdn icons for wiki scrape failures via poe2db.tw.

Reads wiki_icons/failures.jsonl (url_missing + recoverable no_primary),
downloads official poecdn PNGs into icons/fallback/{etype}/, updates entity_icons.json.

Usage:
  python backend/scripts/backfill_poe2db_icon_gaps.py --data-dir /app/data
  python backend/scripts/backfill_poe2db_icon_gaps.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_icons")


def resolve_data_dir(override: str | None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("POE2LI_DATA_DIR")
    if env:
        return Path(env)
    for p in (Path("/app/data"), ROOT.parent / "data", ROOT / "data"):
        if p.is_dir():
            return p
    return ROOT / "data"


def etype_for_row(row: dict) -> str:
    wiki_type = row.get("entity_type") or "item"
    if wiki_type in ("support", "spirit", "meta_skill", "lineage_support"):
        return "skill"
    if wiki_type in ("jewel", "flask", "charm", "omen", "waystone"):
        return "item"
    if wiki_type in ("asc_notable", "asc_minor", "keystone", "notable", "asc_basic"):
        return "skill"
    if wiki_type == "class":
        return "ascendancy"
    return wiki_type


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill poecdn icons for wiki failures")
    parser.add_argument("--data-dir", default="", help="Data root (default: /app/data or repo/data)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between poe2db fetches")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--status",
        default="url_missing",
        help="Comma-separated failure statuses to backfill (default: url_missing)",
    )
    args = parser.parse_args()

    data_dir = resolve_data_dir(args.data_dir or None)
    failures_path = data_dir / "wiki_icons" / "failures.jsonl"
    icons_json = data_dir / "entity_icons.json"
    fallback_root = data_dir / "icons" / "fallback"

    if not failures_path.is_file():
        logger.error("Missing %s", failures_path)
        return 1

    from app.services.entity_icon_service import (
        _cache_key,
        _poe2db_slug,
        proxy_icon_bytes,
        resolve_icon_url,
    )

    want_status = {s.strip() for s in args.status.split(",") if s.strip()}
    rows = [json.loads(line) for line in failures_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = [
        r
        for r in rows
        if r.get("status") in want_status
        and r.get("title")
        and not str(r.get("title", "")).startswith("User:")
    ]
    if args.limit:
        targets = targets[: args.limit]
    logger.info("Backfill targets: %d (from %d failures)", len(targets), len(rows))

    cache: dict[str, str] = {}
    if icons_json.is_file():
        try:
            raw = json.loads(icons_json.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cache = {str(k).lower(): str(v) for k, v in raw.items() if v}
        except json.JSONDecodeError:
            pass

    ok = skip = fail = 0
    for row in targets:
        title = row["title"]
        etype = etype_for_row(row)
        slug = _poe2db_slug(title)
        dest = fallback_root / etype / f"{slug}.png"
        if dest.is_file():
            logger.info("skip existing %s", dest.relative_to(data_dir))
            skip += 1
            continue

        url = resolve_icon_url(title, etype, allow_fetch=True)
        if not url:
            logger.warning("no poecdn url: %s (%s)", title, etype)
            fail += 1
            time.sleep(args.delay)
            continue

        if args.dry_run:
            logger.info("dry-run %s -> %s", title, url[:80])
            ok += 1
            continue

        body, _ = proxy_icon_bytes(url)
        if not body:
            logger.warning("download failed: %s", title)
            fail += 1
            time.sleep(args.delay)
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        cache[_cache_key(title, etype)] = url
        cache[title.lower()] = url
        cache[slug.lower()] = url
        logger.info("saved %s (%d bytes)", dest.relative_to(data_dir), len(body))
        ok += 1
        time.sleep(args.delay)

    if not args.dry_run and ok:
        icons_json.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Updated %s (%d keys)", icons_json, len(cache))

    logger.info("Done ok=%d skip=%d fail=%d", ok, skip, fail)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
