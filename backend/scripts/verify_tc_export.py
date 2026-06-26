#!/usr/bin/env python3
"""Verify TC export completeness against EN baseline.

Checks:
- File counts: tc/ should match en/ core tables
- P0 tables exist and non-empty
- Row count ratios: tc/en per table
- Key fields presence in core tables
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

P0_TABLES = {
    "Mods.json": ["Name"],
    "Stats.json": ["Id"],
    "PassiveSkills.json": ["Name"],
    "BaseItemTypes.json": ["Name"],
    "GrantedEffects.json": ["Name"],
    "GrantedEffectsPerLevel.json": ["Id"],
    "ItemVisualIdentity.json": ["ItemVisualIdentityKey"],
    "ActiveSkills.json": ["DisplayedName"],
    "SkillGems.json": ["Name"],
    "MonsterVarieties.json": ["Name"],
}


def load_json(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_table(tc_path: Path, en_path: Path, required_fields: list[str]):
    tc = load_json(tc_path)
    en = load_json(en_path)
    if en is None:
        return {"status": "skip", "reason": "en missing"}
    if tc is None:
        return {"status": "fail", "reason": "tc missing", "en_rows": len(en) if isinstance(en, list) else 0}
    if not isinstance(tc, list) or not isinstance(en, list):
        return {"status": "skip", "reason": "non-list payload"}
    tc_rows = len(tc)
    en_rows = len(en)
    ratio = tc_rows / en_rows if en_rows else 0.0
    field_ok = True
    missing_fields = []
    if required_fields and tc_rows > 0:
        sample = tc[: min(50, tc_rows)]
        for field in required_fields:
            bad = sum(1 for r in sample if not isinstance(r, dict) or not r.get(field))
            if bad:
                field_ok = False
                missing_fields.append(f"{field}({bad}/{len(sample)})")
    return {
        "status": "ok" if ratio >= 0.5 and field_ok else "warn" if ratio >= 0.2 else "fail",
        "tc_rows": tc_rows,
        "en_rows": en_rows,
        "ratio": round(ratio, 3),
        "fields": "ok" if field_ok else ",".join(missing_fields),
    }


def main():
    parser = argparse.ArgumentParser(description="Verify TC export completeness")
    parser.add_argument("--data-dir", required=True, help="poe2_data dir containing en/ and tc/")
    parser.add_argument("--min-ratio", type=float, default=0.5, help="Minimum tc/en ratio for core tables")
    args = parser.parse_args()

    en_dir = Path(args.data_dir) / "en"
    tc_dir = Path(args.data_dir) / "tc"
    if not en_dir.is_dir() or not tc_dir.is_dir():
        print(f"ERROR: en/tc dirs missing under {args.data_dir}")
        sys.exit(2)

    en_files = sorted(en_dir.glob("*.json"))
    tc_files = {p.name: p for p in tc_dir.glob("*.json")}
    missing = [p.name for p in en_files if p.name not in tc_files]
    results = {}
    for en_path in en_files:
        name = en_path.name
        required = P0_TABLES.get(name, [])
        tc_path = tc_files.get(name)
        res = check_table(tc_path, en_path, required)
        results[name] = res

    print(f"EN files: {len(en_files)}")
    print(f"TC files: {len(tc_files)}")
    print(f"Missing files: {len(missing)}")
    if missing:
        for m in missing[:20]:
            print(f"  MISSING: {m}")
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more")

    fails = [k for k, v in results.items() if v["status"] == "fail"]
    warns = [k for k, v in results.items() if v["status"] == "warn"]
    print(f"FAIL: {len(fails)}, WARN: {len(warns)}, OK: {len(results) - len(fails) - len(warns)}")
    for k in fails:
        v = results[k]
        print(f"  FAIL {k}: en={v.get('en_rows',0)} tc={v.get('tc_rows',0)} ratio={v.get('ratio',0)} fields={v.get('fields','')}")
    for k in warns[:20]:
        v = results[k]
        print(f"  WARN {k}: en={v.get('en_rows',0)} tc={v.get('tc_rows',0)} ratio={v.get('ratio',0)} fields={v.get('fields','')}")

    if fails:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
