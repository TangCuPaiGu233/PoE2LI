"""Import GGPK-extracted game data (EN/TC/SC) into the database.

Usage:
    python scripts/import_game_data.py --data-dir /app/poe2_data
    python scripts/import_game_data.py --data-dir /app/poe2_data --dry-run
    python scripts/import_game_data.py --data-dir /app/poe2_data --tables ActiveSkills Mods
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.game_data import GameDatum

# ── Table config: key field (for row_key) + display name field ──
TABLE_CONFIG = {
    # ── Original 25 ──
    "ActiveSkills":             {"key": "Id",            "name": "DisplayedName"},
    "SkillGems":                {"key": "BaseItemType",   "name": None},
    "GemTags":                  {"key": "Id",            "name": "Name"},
    "ActiveSkillType":          {"key": "Id",            "name": None},
    "GrantedEffects":           {"key": "Id",            "name": None},
    "GrantedEffectsPerLevel":   {"key": None,            "name": None},
    "BaseItemTypes":            {"key": "Id",            "name": "Name"},
    "ItemClasses":              {"key": "Id",            "name": "Name"},
    "Tags":                     {"key": "Id",            "name": None},
    "Mods":                     {"key": "Id",            "name": "Name"},
    "PassiveSkills":            {"key": "Id",            "name": "Name"},
    "Ascendancy":               {"key": "Id",            "name": "Name"},
    "AlternatePassiveSkills":   {"key": "Id",            "name": "Name"},
    "AlternatePassiveAdditions":{"key": "Id",            "name": None},
    "Stats":                    {"key": "Id",            "name": None},
    "StatDescriptions":         {"key": "Id",            "name": "Description"},
    "MonsterVarieties":         {"key": "Id",            "name": "Name"},
    "MonsterResistances":       {"key": "Id",            "name": None},
    "MonsterArmours":           {"key": "Id",            "name": None},
    "ItemExperiencePerLevel":   {"key": None,            "name": None},
    "CharacterStartStates":     {"key": "Id",            "name": "Name"},
    "WorldAreas":               {"key": "Id",            "name": "Name"},
    "MapPins":                  {"key": "Id",            "name": "Name"},
    "Words":                    {"key": "Id",            "name": "Text", "name_sc": "Text2", "name_tc": "Text2"},
    "QuestFlags":               {"key": "Id",            "name": None},
    # ── Expansion: high priority ──
    "CraftingBenchOptions":         {"key": "Id",            "name": None},
    "CraftingBenchUnlockCategories":{"key": "Id",            "name": None},
    "CraftingBenchSortCategories":  {"key": "Id",            "name": "Name"},
    "BuffDefinitions":              {"key": "Id",            "name": "Name"},
    "FlavourText":                  {"key": "Id",            "name": "Text"},
    "ModType":                      {"key": None,           "name": "Name"},
    "ModFamily":                    {"key": "Id",            "name": None},
    "PassiveSkillTrees":            {"key": "Id",            "name": "Name"},
    "PassiveSkillMasteryEffects":   {"key": "Id",            "name": None},
    "PassiveSkillMasteryGroups":    {"key": "Id",            "name": None},
    "PassiveSkillStatCategories":   {"key": "Id",            "name": "Name"},
    "PassiveKeystoneList":          {"key": "Passive",       "name": "DisplayText"},
    "SupportGems":                  {"key": "SkillGem",      "name": None},
    "ModGrantedSkills":             {"key": None,           "name": None},
    # ── Expansion: medium priority ──
    "MapSeries":                    {"key": "Id",            "name": "Name"},
    "MapSeriesTiers":               {"key": None,           "name": None},
    "Maps":                         {"key": "BaseItemType",  "name": None},
    "AtlasNode":                    {"key": "Id",            "name": None},
    "AtlasNodeDefinition":          {"key": "Id",            "name": None},
    "AtlasRegions":                 {"key": "Id",            "name": None},
    "UniqueMaps":                   {"key": None,           "name": "Name"},
    "LeagueInfo":                   {"key": None,           "name": "Description"},
    "LeagueFlag":                   {"key": "Id",            "name": None},
    "PantheonPanelLayout":          {"key": "Id",            "name": None},
    "IncursionArchitect":           {"key": None,           "name": None},
    "HeistNPCs":                    {"key": None,           "name": "Name"},
    "HeistJobs":                    {"key": "Id",            "name": "Name"},
    "HeistContracts":               {"key": None,           "name": None},
    "HeistObjectives":              {"key": "BaseItemType",  "name": "Name"},
    "NPCs":                         {"key": "Id",            "name": "Name"},
    "NPCMaster":                    {"key": "Id",            "name": None},
    "NPCConversations":             {"key": "Id",            "name": None},
    "Achievements":                 {"key": "Id",            "name": "Description"},
    "AchievementItems":             {"key": "Id",            "name": "Name"},
    "CurrencyItems":                {"key": "BaseItemType",  "name": "Description"},
    "HideoutNPCs":                  {"key": None,           "name": None},
    "Hideouts":                     {"key": None,           "name": None},
    "HideoutDoodads":               {"key": None,           "name": None},
    "AbyssObjects":                 {"key": "Id",            "name": None},
    "BetrayalChoiceActions":        {"key": "Id",            "name": None},
    "BetrayalTargets":              {"key": "Id",            "name": None},
}


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


def main():
    parser = argparse.ArgumentParser(description="Import GGPK game data (EN/TC/SC)")
    parser.add_argument("--data-dir", required=True,
                        help="Path to poe2_data dir containing en/, tc/, sc/ subdirs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tables", nargs="*", help="Specific tables (default: all)")
    parser.add_argument("--game-version", default="0.2.0")
    args = parser.parse_args()

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
