"""Build unique_cn_en.json — bundled CN→EN map for all poe2db uniques.

Sources (later overrides earlier):
  1. app/services/poe2db_uniques.json (slug → EN guess)
  2. data/poe2db_uniques.jsonl (scraped canonical name_en)
"""
from __future__ import annotations

import json
import os
import sys
from urllib.parse import unquote

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR = os.path.join(ROOT, "data")
SERVICES_INDEX = os.path.join(ROOT, "app", "services", "poe2db_uniques.json")


def _en_from_slug(slug: str) -> str:
    path = slug.replace("/cn/", "").replace("/us/", "").strip("/")
    return unquote(path).replace("_", " ")


def _load_index() -> list[dict]:
    path = SERVICES_INDEX
    if not os.path.exists(path):
        path = os.path.join(DATA_DIR, "poe2db_uniques.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl_pairs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for jsonl_path in (
        os.path.join(DATA_DIR, "poe2db_uniques.jsonl"),
        "/app/data/poe2db_uniques.jsonl",
    ):
        if not os.path.exists(jsonl_path):
            continue
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                cn_raw = d.get("cn_data", "")
                if not cn_raw:
                    continue
                try:
                    cn = json.loads(cn_raw).get("name", "").strip()
                except Exception:
                    continue
                if cn:
                    out[cn] = {
                        "en": d.get("name_en", ""),
                        "path": d.get("item_path", ""),
                    }
    return out


def build() -> dict[str, dict]:
    pairs: dict[str, dict] = {}
    jsonl = _load_jsonl_pairs()

    for row in _load_index():
        cn = (row.get("name") or "").strip()
        slug = row.get("slug", "")
        path = slug.replace("/cn/", "").replace("/us/", "")
        if not cn or not path:
            continue
        en = _en_from_slug(slug)
        pairs[cn] = {
            "en": en,
            "path": path,
            "base_cn": row.get("base_type", ""),
            "source": "poe2db_index",
        }

    for cn, info in jsonl.items():
        if info.get("en"):
            pairs[cn] = {
                "en": info["en"],
                "path": info.get("path", pairs.get(cn, {}).get("path", "")),
                "base_cn": pairs.get(cn, {}).get("base_cn", ""),
                "source": "poe2db_jsonl",
            }

    return pairs


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DATA_DIR, "unique_cn_en.json")
    pairs = build()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    payload = {
        "version": 1,
        "total": len(pairs),
        "cn_to_en": pairs,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(pairs)} pairs → {out_path}")


if __name__ == "__main__":
    main()
