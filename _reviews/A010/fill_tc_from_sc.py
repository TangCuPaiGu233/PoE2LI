#!/usr/bin/env python3
"""Fill missing TC JSON files from SC directory.

Strategy: SC > no TC data.
- If TC file missing: copy SC -> TC
- If TC exists but significantly smaller than SC: merge missing keys from SC

Usage:
    python backend/scripts/ggpk/fill_tc_from_sc.py
    python backend/scripts/ggpk/fill_tc_from_sc.py --data-dir ./backend/data/poe2_data
    python backend/scripts/ggpk/fill_tc_from_sc.py --dry-run
"""
import argparse
import json
import os
import sys
import shutil
from pathlib import Path

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "poe2_data")

P0_TABLES = {
    "GrantedEffects",
    "GrantedEffectsPerLevel",
    "ItemVisualIdentity",
    "Stats",
    "SkillGems",
}

# Threshold: TC rows < this fraction of SC rows => consider TC insufficient
_TC_INSUFFICIENT_RATIO = 0.8


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def row_key(row, index, key_field=None):
    if key_field and key_field in row and row[key_field] is not None:
        val = row[key_field]
        if isinstance(val, list):
            return f"{index}_{','.join(str(v) for v in val[:3])}"
        return str(val)
    return str(index)


def build_index(records, key_field=None):
    idx = {}
    for i, row in enumerate(records):
        k = row_key(row, i, key_field)
        idx[k] = row
    return idx


def merge_records(tc_records, sc_records, key_field=None):
    """Merge SC records into TC records for missing keys."""
    if not isinstance(tc_records, list) or not isinstance(sc_records, list):
        return tc_records

    tc_idx = build_index(tc_records, key_field)
    sc_idx = build_index(sc_records, key_field)

    merged = list(tc_records)
    merged_keys = set(tc_idx.keys())

    added = 0
    for k, sc_row in sc_idx.items():
        if k not in merged_keys:
            merged.append(sc_row)
            added += 1

    return merged, added


def fill(data_dir: Path, dry_run: bool = False, sc_dir: Path | None = None, tc_dir: Path | None = None):
    sc_dir = sc_dir or (data_dir / "sc")
    tc_dir = tc_dir or (data_dir / "tc")

    if not sc_dir.is_dir():
        print(f"ERROR: SC dir not found: {sc_dir}")
        sys.exit(2)
    if not tc_dir.is_dir():
        print(f"ERROR: TC dir not found: {tc_dir}")
        sys.exit(2)

    sc_files = sorted(p.name for p in sc_dir.glob("*.json"))
    tc_files = sorted(p.name for p in tc_dir.glob("*.json"))

    copied = []
    merged = []
    skipped = []
    errors = []

    for filename in sc_files:
        sc_path = sc_dir / filename
        tc_path = tc_dir / filename
        table = filename[:-5] if filename.endswith(".json") else filename

        sc_data = load_json(sc_path)
        if sc_data is None:
            errors.append(f"{filename}: SC json invalid")
            continue

        if not tc_path.exists():
            if dry_run:
                copied.append((filename, "copy"))
            else:
                shutil.copy2(sc_path, tc_path)
                copied.append((filename, "copy"))
            continue

        tc_data = load_json(tc_path)
        if tc_data is None:
            if dry_run:
                copied.append((filename, "copy-invalid-tc"))
            else:
                shutil.copy2(sc_path, tc_path)
                copied.append((filename, "copy-invalid-tc"))
            continue

        sc_count = len(sc_data) if isinstance(sc_data, list) else 1
        tc_count = len(tc_data) if isinstance(tc_data, list) else 1

        if sc_count == 0:
            skipped.append((filename, "sc-empty"))
            continue

        if tc_count < max(1, int(sc_count * _TC_INSUFFICIENT_RATIO)):
            if dry_run:
                merged.append((filename, tc_count, sc_count))
            else:
                merged_data, added = merge_records(tc_data, sc_data)
                save_json(tc_path, merged_data)
                merged.append((filename, tc_count, len(merged_data), added))
            continue

        skipped.append((filename, f"tc-ok-{tc_count}/{sc_count}"))

    # Report
    print(f"SC dir: {sc_dir}")
    print(f"TC dir: {tc_dir}")
    print(f"SC files: {len(sc_files)}, TC files: {len(tc_files)}")
    print()

    if copied:
        print(f"Copied {len(copied)} files:")
        for item in copied:
            print(f"  {item[0]}: {item[1]}")

    if merged:
        print(f"Merged {len(merged)} files:")
        for item in merged:
            if len(item) == 4:
                print(f"  {item[0]}: {item[1]} -> {item[2]} rows (+{item[3]})")
            else:
                print(f"  {item[0]}: {item[1]} -> {item[2]} rows (dry-run)")

    if skipped:
        print(f"Skipped {len(skipped)} files:")
        for item in skipped[:20]:
            print(f"  {item[0]}: {item[1]}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped)-20} more")

    if errors:
        print(f"Errors {len(errors)}:")
        for e in errors:
            print(f"  {e}")

    # P0 summary
    p0_copied = [f for f, _ in copied if f[:-5] in P0_TABLES or f.replace(".json","") in P0_TABLES]
    p0_merged = [f for f, *_ in merged if f[:-5] in P0_TABLES or f.replace(".json","") in P0_TABLES]
    print()
    print(f"P0 copied: {p0_copied}")
    print(f"P0 merged: {p0_merged}")

    # Final count
    tc_count_after = len(list(tc_dir.glob("*.json"))) if tc_dir.exists() else 0
    print(f"\nTC file count after: {tc_count_after}")
    return copied, merged, skipped, errors


def main():
    parser = argparse.ArgumentParser(description="Fill missing TC data from SC")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fill(Path(args.data_dir), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
