#!/usr/bin/env python3
"""Fetch PoE2 trade item base types from intl + CN Trade API and build bilingual map.

Endpoint: GET /api/trade2/data/items

Entries only have `type` (display name). Alignment: same group `id`, zip by index
(up to min length). Groups with equal length (flask/jewel/wombgift) are exact.

Outputs:
  - trade_items_bilingual.json  — groups + flat items map
  - trade_items_en_cn.json      — en_to_cn, cn_to_en, cn_to_group lookups
  - base_en_cn.json             — backward-compat {version, source, en_to_cn}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import cloudscraper

INTL_ORIGIN = "https://www.pathofexile.com"
CN_ORIGIN = "https://poe.game.qq.com"
ITEMS_PATH = "/api/trade2/data/items"


def _scraper(origin: str, cookie_domain: str, poessid: str = "") -> cloudscraper.CloudScraper:
    sc = cloudscraper.create_scraper()
    sc.headers.update(
        {
            "Accept": "application/json",
            "Origin": origin,
            "Referer": f"{origin}/trade2/search/poe2/Standard",
        }
    )
    if poessid:
        sc.cookies.set("POESESSID", poessid, domain=cookie_domain)
    return sc


def fetch_items(origin: str, cookie_domain: str, poessid: str = "") -> dict:
    sc = _scraper(origin, cookie_domain, poessid)
    resp = sc.get(origin + ITEMS_PATH, timeout=90)
    resp.raise_for_status()
    return resp.json()


def _groups_by_id(data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for group in data.get("result") or []:
        gid = (group.get("id") or "").strip()
        if gid:
            out[gid] = group
    return out


def build_bilingual(intl_data: dict, cn_data: dict) -> dict:
    intl_groups = _groups_by_id(intl_data)
    cn_groups = _groups_by_id(cn_data)
    all_group_ids = sorted(set(intl_groups) | set(cn_groups))

    groups_out: list[dict] = []
    items: dict[str, dict] = {}
    en_to_cn: dict[str, str] = {}
    cn_to_en: dict[str, str] = {}
    cn_to_group: dict[str, str] = {}

    both = 0
    en_only = 0
    intl_total = 0
    cn_total = 0

    for gid in all_group_ids:
        gi = intl_groups.get(gid, {})
        gc = cn_groups.get(gid, {})
        label_en = (gi.get("label") or gid).strip()
        label_cn = (gc.get("label") or label_en).strip()
        ei = gi.get("entries") or []
        ec = gc.get("entries") or []
        intl_total += len(ei)
        cn_total += len(ec)

        entries: list[dict] = []
        for idx, (a, b) in enumerate(zip(ei, ec)):
            text_en = (a.get("type") or "").strip()
            text_cn = (b.get("type") or "").strip()
            item_key = f"{gid}|{text_en}"
            rec = {
                "key": item_key,
                "group_id": gid,
                "index": idx,
                "text_en": text_en,
                "text_cn": text_cn,
            }
            entries.append(rec)
            if text_en:
                items[item_key] = rec
            if text_en and text_cn:
                both += 1
                en_to_cn[text_en] = text_cn
                cn_to_en[text_cn] = text_en
                cn_to_group[text_cn] = gid

        for idx in range(len(ec), len(ei)):
            a = ei[idx]
            text_en = (a.get("type") or "").strip()
            if not text_en:
                continue
            item_key = f"{gid}|{text_en}"
            rec = {
                "key": item_key,
                "group_id": gid,
                "index": idx,
                "text_en": text_en,
                "text_cn": "",
            }
            entries.append(rec)
            items[item_key] = rec
            en_only += 1

        groups_out.append(
            {
                "id": gid,
                "label_en": label_en,
                "label_cn": label_cn,
                "intl_count": len(ei),
                "cn_count": len(ec),
                "aligned_count": min(len(ei), len(ec)),
                "entries": entries,
            }
        )

    return {
        "version": 2,
        "source": ITEMS_PATH.lstrip("/"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "groups": len(groups_out),
            "intl_entries": intl_total,
            "cn_entries": cn_total,
            "aligned_bilingual": both,
            "en_only_tail": en_only,
            "unique_en_to_cn": len(en_to_cn),
        },
        "groups": groups_out,
        "items": items,
        "lookups": {
            "en_to_cn": en_to_cn,
            "cn_to_en": cn_to_en,
            "cn_to_group": cn_to_group,
        },
    }


def write_outputs(payload: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    bilingual_path = out_dir / "trade_items_bilingual.json"
    with bilingual_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "version": payload["version"],
                "source": payload["source"],
                "fetched_at": payload["fetched_at"],
                "counts": payload["counts"],
                "groups": payload["groups"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    lookup_path = out_dir / "trade_items_en_cn.json"
    with lookup_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "version": payload["version"],
                "source": payload["source"],
                "fetched_at": payload["fetched_at"],
                "counts": payload["counts"],
                **payload["lookups"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    legacy_path = out_dir / "base_en_cn.json"
    with legacy_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "version": 2,
                "source": payload["source"],
                "fetched_at": payload["fetched_at"],
                "en_to_cn": payload["lookups"]["en_to_cn"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Wrote {bilingual_path}")
    print(f"Wrote {lookup_path} (en_to_cn={len(payload['lookups']['en_to_cn'])})")
    print(f"Wrote {legacy_path}")
    print("Counts:", json.dumps(payload["counts"], ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch bilingual PoE2 trade item bases")
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[1] / "data"),
    )
    args = parser.parse_args()

    cn_poessid = os.getenv("TRADE_CN_POESESSID", "")

    print("Fetching intl items...")
    intl_data = fetch_items(INTL_ORIGIN, "www.pathofexile.com")
    print("Fetching CN items...")
    cn_data = fetch_items(CN_ORIGIN, "poe.game.qq.com", cn_poessid)

    payload = build_bilingual(intl_data, cn_data)
    write_outputs(payload, Path(args.out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
