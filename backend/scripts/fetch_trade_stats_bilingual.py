#!/usr/bin/env python3
"""Fetch PoE2 trade stat dictionary from intl + CN Trade API and build bilingual map.

Official endpoint (same on both realms):
  GET /api/trade2/data/stats

Entries are matched by stable stat_id (e.g. explicit.stat_3372524247).
CN realm requires TRADE_CN_POESESSID for some endpoints; stats endpoint works without auth on NAS.

Outputs:
  - trade_stats_bilingual.json  — full per-stat records {text_en, text_cn, stat_type, group_id}
  - trade_stats_en_cn.json      — {cn_to_id, id_to_cn, en_to_cn_by_id} lookup tables
  - trade_stats_condensed.json  — {stat_id: text_en} (regenerated for backward compat)

Usage:
  python backend/scripts/fetch_trade_stats_bilingual.py
  python backend/scripts/fetch_trade_stats_bilingual.py --out-dir backend/data
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
STATS_PATH = "/api/trade2/data/stats"


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


def _flatten(data: dict) -> dict[str, dict]:
    """stat_id → {text, stat_type, group_id}."""
    out: dict[str, dict] = {}
    for group in data.get("result") or []:
        group_id = group.get("id") or ""
        for entry in group.get("entries") or []:
            sid = entry.get("id")
            if not sid:
                continue
            text = (entry.get("text") or "").strip()
            stat_type = (entry.get("type") or "").strip()
            if not stat_type and "." in sid:
                stat_type = sid.split(".")[0]
            out[sid] = {
                "text": text,
                "stat_type": stat_type,
                "group_id": group_id,
            }
    return out


def fetch_stats(origin: str, cookie_domain: str, poessid: str = "") -> dict:
    sc = _scraper(origin, cookie_domain, poessid)
    url = origin + STATS_PATH
    resp = sc.get(url, timeout=90)
    resp.raise_for_status()
    return resp.json()


def build_bilingual(intl_data: dict, cn_data: dict) -> dict:
    en_map = _flatten(intl_data)
    cn_map = _flatten(cn_data)
    all_ids = sorted(set(en_map) | set(cn_map))

    stats: dict[str, dict] = {}
    cn_to_id: dict[str, str] = {}
    id_to_cn: dict[str, str] = {}
    en_to_cn_by_id: dict[str, str] = {}

    for sid in all_ids:
        en = en_map.get(sid, {})
        cn = cn_map.get(sid, {})
        text_en = en.get("text") or ""
        text_cn = cn.get("text") or ""
        stat_type = en.get("stat_type") or cn.get("stat_type") or (
            sid.split(".")[0] if "." in sid else "unknown"
        )
        stats[sid] = {
            "id": sid,
            "text_en": text_en,
            "text_cn": text_cn,
            "stat_type": stat_type,
            "group_id": en.get("group_id") or cn.get("group_id") or "",
        }
        if text_cn:
            id_to_cn[sid] = text_cn
            # Last-write wins on duplicate CN labels (rare for trade stats)
            cn_to_id[text_cn] = sid
        if text_en and text_cn:
            en_to_cn_by_id[sid] = text_cn

    matched = sum(1 for s in stats.values() if s["text_en"] and s["text_cn"])
    return {
        "version": 2,
        "source": STATS_PATH.lstrip("/"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "total_ids": len(stats),
            "intl": len(en_map),
            "cn": len(cn_map),
            "both": matched,
            "en_only": len(en_map) - matched,
            "cn_only": len(cn_map) - matched,
        },
        "stats": stats,
        "lookups": {
            "cn_to_id": cn_to_id,
            "id_to_cn": id_to_cn,
            "en_to_cn_by_id": en_to_cn_by_id,
        },
    }


def write_outputs(payload: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    bilingual_path = out_dir / "trade_stats_bilingual.json"
    with bilingual_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "version": payload["version"],
                "source": payload["source"],
                "fetched_at": payload["fetched_at"],
                "counts": payload["counts"],
                "stats": payload["stats"],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    lookup_path = out_dir / "trade_stats_en_cn.json"
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

    condensed = {
        sid: rec["text_en"]
        for sid, rec in payload["stats"].items()
        if rec.get("text_en")
    }
    condensed_path = out_dir / "trade_stats_condensed.json"
    with condensed_path.open("w", encoding="utf-8") as f:
        json.dump(condensed, f, ensure_ascii=False)

    print(f"Wrote {bilingual_path} ({len(payload['stats'])} stats)")
    print(f"Wrote {lookup_path} (cn_to_id={len(payload['lookups']['cn_to_id'])})")
    print(f"Wrote {condensed_path} ({len(condensed)} EN entries)")
    print("Counts:", json.dumps(payload["counts"], ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch bilingual PoE2 trade stats")
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parents[1] / "data"),
        help="Output directory for JSON files",
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    cn_poessid = os.getenv("TRADE_CN_POESESSID", "")

    print("Fetching intl stats...")
    intl_data = fetch_stats(INTL_ORIGIN, "www.pathofexile.com")
    print("Fetching CN stats...")
    cn_data = fetch_stats(CN_ORIGIN, "poe.game.qq.com", cn_poessid)

    payload = build_bilingual(intl_data, cn_data)
    write_outputs(payload, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
