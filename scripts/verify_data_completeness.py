#!/usr/bin/env python3
"""Verify EN/SC/TC GGPK-extracted data completeness.

Usage:
    python scripts/verify_data_completeness.py
    python scripts/verify_data_completeness.py --data-dir ./backend/data/poe2_data
    python scripts/verify_data_completeness.py --critical-only
"""
import argparse
import json
import os
import sys
from pathlib import Path

REQUIRED_LOCALES = ("en", "sc", "tc")

# Critical tables where TC absence/user-facing impact is highest.
CRITICAL_TABLES = {
    "Mods",
    "Stats",
    "PassiveSkills",
    "BaseItemTypes",
    "GrantedEffects",
    "GrantedEffectsPerLevel",
    "ItemVisualIdentity",
    "ActiveSkills",
    "SkillGems",
    "MonsterVarieties",
}


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def count_rows(path: Path):
    data = load_json(path)
    if data is None:
        return -1
    return len(data) if isinstance(data, list) else 1


def table_name_from_file(filename: str) -> str:
    if filename.endswith(".json"):
        return filename[:-5]
    return filename


def verify(data_dir: Path, critical_only: bool = False):
    locales = {lang: data_dir / lang for lang in REQUIRED_LOCALES}
    missing_dirs = [lang for lang, d in locales.items() if not d.is_dir()]
    if missing_dirs:
        print(f"ERROR: missing locale dirs: {missing_dirs}")
        sys.exit(2)

    en_files = sorted(p.name for p in locales["en"].glob("*.json"))
    if not en_files:
        print("ERROR: no EN json files found")
        sys.exit(2)

    # Choose tables to check
    if critical_only:
        targets = sorted(f"{t}.json" for t in CRITICAL_TABLES)
        targets = [f for f in targets if f in en_files]
    else:
        targets = en_files

    missing_tc = []
    missing_sc = []
    tc_empty = []
    sc_empty = []
    tc_low_ratio = []
    details = []

    for filename in targets:
        table = table_name_from_file(filename)
        en_count = count_rows(locales["en"] / filename)
        sc_count = count_rows(locales["sc"] / filename)
        tc_count = count_rows(locales["tc"] / filename)

        sc_exists = (locales["sc"] / filename).exists()
        tc_exists = (locales["tc"] / filename).exists()

        if not tc_exists:
            missing_tc.append(filename)
        if not sc_exists:
            missing_sc.append(filename)

        if tc_exists and tc_count == 0:
            tc_empty.append(filename)
        if sc_exists and sc_count == 0:
            sc_empty.append(filename)

        if tc_exists and en_count > 0 and tc_count > 0:
            ratio = tc_count / en_count
            if ratio < 0.5:
                tc_low_ratio.append((filename, ratio))

        details.append({
            "table": table,
            "en": en_count,
            "sc": sc_count if sc_exists else None,
            "tc": tc_count if tc_exists else None,
        })

    # Report
    has_failure = False

    if missing_tc:
        print(f"FAIL TC missing {len(missing_tc)} files (sample):")
        for f in missing_tc[:20]:
            print(f"  - {f}")
        if len(missing_tc) > 20:
            print(f"  ... and {len(missing_tc)-20} more")
        print("\nSuggested fix:")
        tables = sorted({table_name_from_file(f) for f in missing_tc})
        print(f"  python backend/scripts/ggpk/export_en_tc.py --tables {' '.join(tables)}")
        has_failure = True
    else:
        print("OK TC file coverage: complete")

    if missing_sc:
        print(f"FAIL SC missing {len(missing_sc)} files")
        for f in missing_sc:
            print(f"  - {f}")
        has_failure = True
    else:
        print("OK SC file coverage: complete")

    if tc_empty:
        print(f"FAIL TC empty tables: {tc_empty}")
        has_failure = True
    if sc_empty:
        print(f"FAIL SC empty tables: {sc_empty}")
        has_failure = True

    if tc_low_ratio:
        print(f"FAIL TC low row-count ratio (<0.5):")
        for f, r in tc_low_ratio:
            print(f"  - {f}: {r:.2f}")
        has_failure = True

    print(f"\nChecked {len(targets)} tables (critical_only={critical_only})")
    print(f"  EN files: {len(en_files)}")
    print(f"  TC missing: {len(missing_tc)}")
    print(f"  SC missing: {len(missing_sc)}")
    print(f"  TC empty: {len(tc_empty)}")
    print(f"  SC empty: {len(sc_empty)}")
    print(f"  TC low ratio: {len(tc_low_ratio)}")

    if has_failure:
        sys.exit(1)
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Verify GGPK data completeness")
    parser.add_argument("--data-dir", default=os.path.join("backend", "data", "poe2_data"))
    parser.add_argument("--critical-only", action="store_true")
    args = parser.parse_args()
    verify(Path(args.data_dir), critical_only=args.critical_only)


if __name__ == "__main__":
    main()
