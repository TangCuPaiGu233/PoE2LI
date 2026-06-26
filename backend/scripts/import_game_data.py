"""Import GGPK-extracted game data (EN/TC/SC) into the database.

Usage:
    python scripts/import_game_data.py --data-dir /app/poe2_data
    python scripts/import_game_data.py --data-dir /app/poe2_data --dry-run
    python scripts/import_game_data.py --data-dir /app/poe2_data --tables ActiveSkills Mods
    python scripts/import_game_data.py --data-dir /app/poe2_data --validate
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.game_data import GameDatum

# ── Import shared registry and build TABLE_CONFIG ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "ggpk"))
from table_registry import ALL_TABLES as _REG_TABLES, KEY_FIELDS as _REG_KEYS

# Name field overrides for well-known tables (display name column).
# New tables use name=None; get_display_name() fallback chain handles them.
_NAME_OVERRIDES = {
    "ActiveSkills": "DisplayedName", "GemTags": "Name", "BaseItemTypes": "Name",
    "ItemClasses": "Name", "Mods": "Name", "PassiveSkills": "Name",
    "Ascendancy": "Name", "AlternatePassiveSkills": "Name",
    "StatDescriptions": "Description", "MonsterVarieties": "Name",
    "CharacterStartStates": "Name", "WorldAreas": "Name", "MapPins": "Name",
    "Words": "Text", "CraftingBenchSortCategories": "Name",
    "BuffDefinitions": "Name", "FlavourText": "Text", "ModType": "Name",
    "PassiveSkillTrees": "Name", "PassiveSkillStatCategories": "Name",
    "PassiveKeystoneList": "DisplayText",
    "MapSeries": "Name", "UniqueMaps": "Name", "LeagueInfo": "Description",
    "HeistNPCs": "Name", "HeistJobs": "Name", "HeistObjectives": "Name",
    "NPCs": "Name", "Achievements": "Description", "AchievementItems": "Name",
    "CurrencyItems": "Description",
    # Words locale overrides
    "Words_sc": "Text2", "Words_tc": "Text2",
}

# Tables where TC coverage is critical for user-facing features.
# Missing or very sparse TC data should emit an explicit warning.
_TC_CRITICAL_TABLES = {
    "Mods", "Stats", "PassiveSkills", "BaseItemTypes",
    "GrantedEffects", "GrantedEffectsPerLevel", "ItemVisualIdentity",
    "ActiveSkills", "SkillGems", "MonsterVarieties",
}
_TC_CRITICAL_MIN_RATIO = 0.2

TABLE_CONFIG = {}
for _t in _REG_TABLES:
    _key = _REG_KEYS.get(_t)
    _name = _NAME_OVERRIDES.get(_t)
    _cfg = {"key": _key, "name": _name}
    # Add locale-specific name overrides
    if f"{_t}_sc" in _NAME_OVERRIDES:
        _cfg["name_sc"] = _NAME_OVERRIDES[f"{_t}_sc"]
    if f"{_t}_tc" in _NAME_OVERRIDES:
        _cfg["name_tc"] = _NAME_OVERRIDES[f"{_t}_tc"]
    TABLE_CONFIG[_t] = _cfg


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_row_key(row, index, config):
    key_field = config.get("key")
    if key_field and key_field in row and row[key_field] is not None:
        val = row[key_field]
        if isinstance(val, list):
            return f"{index}_{','.join(str(v) for v in val[:3])}"
        return str(val)
    return str(index)


def get_display_name(row, config, locale=None):
    if not row:
        return None
    # Locale-specific field override (e.g. name_sc, name_tc)
    name_field = None
    if locale and config.get(f"name_{locale}"):
        name_field = config[f"name_{locale}"]
    else:
        name_field = config.get("name")
    if name_field and name_field in row:
        val = row[name_field]
        if isinstance(val, str) and val.strip():
            return val.strip()
    for fallback in ["Name", "DisplayedName", "Id", "Text"]:
        if fallback in row and isinstance(row[fallback], str) and row[fallback].strip():
            return row[fallback].strip()
    return None


def build_key_index(records, config):
    """Build {row_key: record} mapping from a list of records."""
    idx = {}
    for i, row in enumerate(records):
        key = get_row_key(row, i, config)
        idx[key] = row
    return idx


def import_table(session, table_name, en_records, tc_records, sc_records, config, game_version, dry_run=False):
    """Import a single table, merging EN/TC/SC by row_key."""
    # TC critical-table coverage guard
    en_count = len(en_records) if en_records else 0
    tc_count = len(tc_records) if tc_records else 0
    if table_name in _TC_CRITICAL_TABLES and not dry_run:
        ratio = tc_count / en_count if en_count else 0.0
        if ratio < _TC_CRITICAL_MIN_RATIO:
            print(f"  WARN  {table_name}: TC coverage low ({tc_count}/{en_count} = {ratio:.2f})")
        else:
            print(f"  TC OK {table_name}: {tc_count}/{en_count} = {ratio:.2f}")

    # Use EN as the base, build key indexes for TC and SC
    en_key_idx = build_key_index(en_records, config) if en_records else {}
    tc_key_idx = build_key_index(tc_records, config) if tc_records else {}
    sc_key_idx = build_key_index(sc_records, config) if sc_records else {}

    # Collect all unique row keys (EN is authoritative for key set)
    all_keys = list(en_key_idx.keys())
    # Add SC-only keys (CN client may have extra items)
    for k in sc_key_idx:
        if k not in en_key_idx:
            all_keys.append(k)
    for k in tc_key_idx:
        if k not in en_key_idx and k not in sc_key_idx:
            all_keys.append(k)

    rows = []
    for row_key in all_keys:
        en_row = en_key_idx.get(row_key, {})
        tc_row = tc_key_idx.get(row_key, {})
        sc_row = sc_key_idx.get(row_key, {})

        merged = {"en": en_row}
        if tc_row:
            merged["tc"] = tc_row
        if sc_row:
            merged["sc"] = sc_row

        rows.append({
            "table_name": table_name,
            "row_key": row_key,
            "name_en": get_display_name(en_row, config, "en"),
            "name_tc": get_display_name(tc_row, config, "tc"),
            "name_sc": get_display_name(sc_row, config, "sc"),
            "data": merged,
            "source": "ggpk",
            "game_version": game_version,
        })

    if dry_run:
        print(f"  [DRY] {table_name}: {len(rows)} rows")
        if rows:
            s = rows[0]
            print(f"    Sample: key={s['row_key']}")
            print(f"      EN={s['name_en']}  TC={s['name_tc']}  SC={s['name_sc']}")
        return len(rows)

    # Delete existing, then insert
    session.query(GameDatum).filter_by(table_name=table_name, source="ggpk").delete()

    batch_size = 500
    inserted = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        objects = [
            GameDatum(
                table_name=r["table_name"],
                row_key=r["row_key"],
                name_en=r["name_en"],
                name_tc=r["name_tc"],
                name_sc=r["name_sc"],
                data=r["data"],
                source=r["source"],
                game_version=r["game_version"],
            )
            for r in batch
        ]
        session.add_all(objects)
        session.flush()
        inserted += len(batch)

    return inserted


def validate_data_dir(data_dir, tables=None):
    """Validate EN/TC/SC JSON completeness for a data directory.

    Returns a structured report without touching the database.
    """
    en_dir = os.path.join(data_dir, "en")
    tc_dir = os.path.join(data_dir, "tc")
    sc_dir = os.path.join(data_dir, "sc")

    tables = tables or list(TABLE_CONFIG.keys())
    report = {
        "data_dir": data_dir,
        "en_dir": en_dir,
        "tc_dir": tc_dir,
        "sc_dir": sc_dir,
        "tables_checked": 0,
        "tables_ok": 0,
        "tables_missing": [],
        "tables_incomplete": [],
        "tables_missing_tc": [],
        "tables_with_tc": [],
        "locale_stats": {"en": 0, "tc": 0, "sc": 0},
        "critical_warnings": [],
    }

    en_exists = os.path.isdir(en_dir)
    tc_exists = os.path.isdir(tc_dir)
    sc_exists = os.path.isdir(sc_dir)

    report["en_exists"] = en_exists
    report["tc_exists"] = tc_exists
    report["sc_exists"] = sc_exists

    if not en_exists:
        report["tables_missing"].append("EN directory missing")
        return report

    for table_name in tables:
        if table_name not in TABLE_CONFIG:
            continue

        jn = f"{table_name}.json"
        en_path = os.path.join(en_dir, jn)
        en = load_json(en_path)
        if en is None:
            report["tables_missing"].append(table_name)
            continue

        report["tables_checked"] += 1
        report["locale_stats"]["en"] += len(en)

        tc = load_json(os.path.join(tc_dir, jn)) if tc_exists else None
        sc = load_json(os.path.join(sc_dir, jn)) if sc_exists else None

        if tc:
            report["locale_stats"]["tc"] += len(tc)
        if sc:
            report["locale_stats"]["sc"] += len(sc)

        has_tc = bool(tc)
        if has_tc:
            report["tables_with_tc"].append(table_name)
        else:
            report["tables_missing_tc"].append(table_name)

        en_count = len(en)
        tc_count = len(tc) if tc else 0
        sc_count = len(sc) if sc else 0

        if en_count and tc_count and tc_count < en_count:
            report["tables_incomplete"].append({
                "table": table_name,
                "en_count": en_count,
                "tc_count": tc_count,
                "sc_count": sc_count,
            })

    report["tables_ok"] = (
        report["tables_checked"]
        - len(report["tables_missing"])
        - len(report["tables_incomplete"])
    )
    return report


def print_validation_report(report):
    """Pretty-print validation report to stdout."""
    print("Validation Report")
    print(f"  data_dir : {report['data_dir']}")
    print(f"  EN       : {report['en_dir']} ({'OK' if report['en_exists'] else 'MISSING'})")
    print(f"  TC       : {report['tc_dir']} ({'OK' if report['tc_exists'] else 'MISSING'})")
    print(f"  SC       : {report['sc_dir']} ({'OK' if report['sc_exists'] else 'MISSING'})")
    print()
    print(f"tables_checked       : {report['tables_checked']}")
    print(f"tables_ok            : {report['tables_ok']}")
    print(f"tables_missing_tc    : {len(report['tables_missing_tc'])}")
    print(f"locale rows          : EN={report['locale_stats']['en']:,} TC={report['locale_stats']['tc']:,} SC={report['locale_stats']['sc']:,}")
    print()

    if report["tables_missing"]:
        print("Missing tables/files:")
        for item in report["tables_missing"]:
            print(f"  - {item}")
        print()

    if report["tables_missing_tc"]:
        print("Tables missing TC data:")
        for item in report["tables_missing_tc"]:
            print(f"  - {item}")
        print()

    if report["tables_incomplete"]:
        print("Tables with incomplete TC coverage:")
        for item in report["tables_incomplete"]:
            print(f"  - {item['table']}: EN={item['en_count']:,} TC={item['tc_count']:,} SC={item['sc_count']:,}")
        print()

    if report["critical_warnings"]:
        print("Critical warnings:")
        for item in report["critical_warnings"]:
            print(f"  - {item['table']}: {item['reason']}")
        print()


def write_validation_report(report, path):
    """Write validation report as JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Import GGPK game data (EN/TC/SC)")
    parser.add_argument("--data-dir", required=True,
                        help="Path to poe2_data dir containing en/, tc/, sc/ subdirs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tables", nargs="*", help="Specific tables (default: all)")
    parser.add_argument("--game-version", default="0.2.0")
    parser.add_argument("--validate", action="store_true",
                        help="Validate data completeness without importing")
    parser.add_argument("--validate-report", default=None,
                        help="Path to write validation report JSON")
    args = parser.parse_args()

    if args.validate:
        report = validate_data_dir(args.data_dir, args.tables)
        print_validation_report(report)
        if args.validate_report:
            write_validation_report(report, args.validate_report)
            print(f"Report written to: {args.validate_report}")
        sys.exit(0)

    en_dir = os.path.join(args.data_dir, "en")
    tc_dir = os.path.join(args.data_dir, "tc")
    sc_dir = os.path.join(args.data_dir, "sc")

    if not os.path.isdir(en_dir):
        print(f"ERROR: English data dir not found: {en_dir}")
        sys.exit(1)

    tables = args.tables or list(TABLE_CONFIG.keys())

    print(f"Importing game data from: {args.data_dir}")
    print(f"  EN: {en_dir} ({'OK' if os.path.isdir(en_dir) else 'MISSING'})")
    print(f"  TC: {tc_dir} ({'OK' if os.path.isdir(tc_dir) else 'MISSING'})")
    print(f"  SC: {sc_dir} ({'OK' if os.path.isdir(sc_dir) else 'MISSING'})")
    print(f"  Tables: {len(tables)}")
    print(f"  Version: {args.game_version}")
    if args.dry_run:
        print("  MODE: DRY RUN")
    print()

    session = SessionLocal()
    try:
        total_rows = 0
        total_tables = 0

        for table_name in tables:
            if table_name not in TABLE_CONFIG:
                print(f"  SKIP {table_name}: no config")
                continue

            config = TABLE_CONFIG[table_name]
            jn = f"{table_name}.json"

            en = load_json(os.path.join(en_dir, jn))
            tc = load_json(os.path.join(tc_dir, jn)) if os.path.isdir(tc_dir) else None
            sc = load_json(os.path.join(sc_dir, jn)) if os.path.isdir(sc_dir) else None

            if en is None and tc is None and sc is None:
                print(f"  SKIP {table_name}: no data")
                continue

            en = en or []
            count = import_table(session, table_name, en, tc, sc,
                                 config, args.game_version, args.dry_run)

            if not args.dry_run:
                session.commit()

            locales = []
            if en: locales.append("EN")
            if tc: locales.append("TC")
            if sc: locales.append("SC")
            print(f"  OK  {table_name}: {count} rows [{'+'.join(locales)}]")
            total_rows += count
            total_tables += 1

        if not args.dry_run:
            print(f"\nDone: {total_rows:,} rows, {total_tables} tables.")
        else:
            print(f"\n[DRY] Would import {total_rows:,} rows, {total_tables} tables.")

    except Exception as e:
        session.rollback()
        print(f"\nERROR: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
