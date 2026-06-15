#!/usr/bin/env python3
"""Materialize entity_catalog.json — run after KB ingest or wiki icon scrape.

Usage:
  python scripts/build_entity_catalog.py [--data-dir /app/data] [--types skill,item,ascendancy]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build entity catalog JSON")
    parser.add_argument("--data-dir", default=None, help="POE2LI data directory")
    parser.add_argument(
        "--types",
        default="skill,item,ascendancy",
        help="Comma-separated entity types to include",
    )
    args = parser.parse_args()

    if args.data_dir:
        import os

        os.environ["POE2LI_DATA_DIR"] = args.data_dir

    from app.core.database import SessionLocal
    from app.services.entity_icon_service import _data_dir
    from app.services.entity_profile import build_profile, entity_key
    from app.services.entity_resolver import _load_aliases

    allowed_types = {t.strip() for t in args.types.split(",") if t.strip()}
    aliases = _load_aliases()

    # Dedupe by (type, name_en); collect all CN aliases per entity
    by_en: dict[tuple[str, str], dict] = {}
    for cn, (en_name, etype, _conf, _src) in aliases.items():
        if etype not in allowed_types:
            continue
        k = (etype, en_name)
        if k not in by_en:
            by_en[k] = {"name_cn": cn, "aliases": [cn]}
        else:
            if cn not in by_en[k]["aliases"]:
                by_en[k]["aliases"].append(cn)
            if not by_en[k].get("name_cn"):
                by_en[k]["name_cn"] = cn

    data_root = _data_dir()
    entities: dict[str, dict] = {}
    stats: dict[str, int] = defaultdict(int)

    db = SessionLocal()
    try:
        total = len(by_en)
        for i, ((etype, name_en), meta) in enumerate(sorted(by_en.items()), 1):
            if i % 200 == 0 or i == total:
                logger.info("Building profiles %d/%d", i, total)
            profile = build_profile(
                db,
                etype,
                name_en,
                name_cn=meta.get("name_cn"),
                extra_aliases=meta.get("aliases"),
                data_dir=data_root,
            )
            row = profile.to_dict()
            entities[profile.entity_key] = row
            stats[etype] += 1
            if profile.description_cn and any("\u4e00" <= c <= "\u9fff" for c in profile.description_cn):
                stats["cn_desc"] += 1
            if profile.icon_local or profile.icon_url:
                stats["icon"] += 1
    finally:
        db.close()

    out_path = data_root / "entity_catalog.json"
    payload = {
        "version": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entity_count": len(entities),
        "stats": dict(stats),
        "entities": entities,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Wrote %s — %d entities (cn_desc=%d, icon=%d)",
        out_path,
        len(entities),
        stats["cn_desc"],
        stats["icon"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
