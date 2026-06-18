#!/usr/bin/env python3
"""Extract Simplified Chinese data from CN WeGame client's on-disk Bundles2.

The CN client stores bundles as plain files on disk (not inside a .ggpk archive).
Root data IS Simplified Chinese (no language subdirectories).

Usage:
    python extract_sc.py
    python extract_sc.py --bundles "D:\\WeGameApps\\...\\Bundles2" --output ./poe2_data
    python extract_sc.py --tables ActiveSkills.dat Mods.dat   # subset

Dependencies: PyPoE (pip install PyPoE)
"""
import argparse
import json
import os
import sys
import time
from io import BytesIO

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_BUNDLES = r"D:\WeGameApps\rail_apps\流放之路：降临(2002052)\Bundles2"
DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "poe2_data")

ALL_TABLES = [
    # ── Original 25 ──
    "ActiveSkills.dat", "SkillGems.dat", "GemTags.dat", "ActiveSkillType.dat",
    "GrantedEffects.dat", "GrantedEffectsPerLevel.dat",
    "BaseItemTypes.dat", "ItemClasses.dat", "Tags.dat", "Mods.dat",
    "PassiveSkills.dat", "Ascendancy.dat",
    "AlternatePassiveSkills.dat", "AlternatePassiveAdditions.dat",
    "Stats.dat", "StatDescriptions.dat",
    "MonsterVarieties.dat", "MonsterResistances.dat", "MonsterArmours.dat",
    "ItemExperiencePerLevel.dat", "CharacterStartStates.dat",
    "WorldAreas.dat", "MapPins.dat",
    "Words.dat", "QuestFlags.dat",
    # ── Expansion: high priority ──
    "CraftingBenchOptions.dat", "CraftingBenchUnlockCategories.dat",
    "CraftingBenchSortCategories.dat", "BuffDefinitions.dat",
    "FlavourText.dat", "ModType.dat", "ModFamily.dat",
    "PassiveSkillTrees.dat", "PassiveSkillMasteryEffects.dat",
    "PassiveSkillMasteryGroups.dat", "PassiveSkillStatCategories.dat",
    "PassiveKeystoneList.dat", "SupportGems.dat", "ModGrantedSkills.dat",
    # ── Expansion: medium priority ──
    "MapSeries.dat", "MapSeriesTiers.dat", "Maps.dat",
    "AtlasNode.dat", "AtlasNodeDefinition.dat", "AtlasRegions.dat",
    "UniqueMaps.dat",
    "LeagueInfo.dat", "LeagueFlag.dat",
    "PantheonPanelLayout.dat", "IncursionArchitect.dat",
    "HeistNPCs.dat", "HeistJobs.dat", "HeistContracts.dat", "HeistObjectives.dat",
    "NPCs.dat", "NPCMaster.dat", "NPCConversations.dat",
    "Achievements.dat", "AchievementItems.dat",
    "CurrencyItems.dat",
    "HideoutNPCs.dat", "Hideouts.dat", "HideoutDoodads.dat",
    "AbyssObjects.dat",
    "BetrayalChoiceActions.dat", "BetrayalTargets.dat",
]


def parse_dat(spec_key, raw, spec):
    """Parse a datc64 binary blob into a list of dicts."""
    from PyPoE.poe.file.dat import DatFile

    df = DatFile(spec_key, specification=spec)
    df.read(BytesIO(raw), x64=True)

    rows = []
    for rec in df.reader.table_data:
        row = {}
        for k in rec.keys():
            v = rec[k]
            if v is None:
                row[k] = None
            elif isinstance(v, (bool, int, float, str)):
                row[k] = v
            elif isinstance(v, bytes):
                row[k] = v.hex()
            elif isinstance(v, (list, tuple)):
                row[k] = [
                    x if isinstance(x, (int, float, str, bool, type(None))) else str(x)
                    for x in v
                ]
            else:
                try:
                    row[k] = str(v)
                except Exception:
                    row[k] = None
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description="Extract SC data from CN WeGame client")
    parser.add_argument("--bundles", default=DEFAULT_BUNDLES, help="Path to Bundles2 directory")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output base directory")
    parser.add_argument("--tables", nargs="*", help="Specific .dat tables (default: all 24)")
    args = parser.parse_args()

    from PyPoE.poe.file.bundle import Index
    from PyPoE.poe.file.specification import load
    from PyPoE.poe.file.specification import constants as spec_constants

    tables = args.tables or ALL_TABLES
    out_sc = os.path.join(args.output, "sc")
    os.makedirs(out_sc, exist_ok=True)
    index_path = os.path.join(args.bundles, "_.index.bin")

    start = time.time()

    # ── Load index ──
    print(f"[1] Loading CN index: {index_path}")
    if not os.path.exists(index_path):
        print(f"ERROR: Index not found at {index_path}")
        sys.exit(1)

    with open(index_path, "rb") as f:
        raw = f.read()
    idx = Index()
    idx.read(BytesIO(raw))
    print(f"    {len(idx.bundles)} bundles, {len(idx.files)} files")

    # Collect datc64 paths
    datc64_map = {}
    for dr in idx.directories.values():
        for fp in dr.paths:
            p = fp if isinstance(fp, str) else fp.decode()
            if p.lower().endswith(".datc64"):
                datc64_map[os.path.basename(p).lower()] = p
    print(f"    {len(datc64_map)} datc64 files found")

    spec = load(version=spec_constants.VERSION.POE2)
    spec_map = {sk.replace(".dat", ".datc64").lower(): sk for sk in spec}

    def extract(path):
        """Extract file from CN on-disk bundles."""
        try:
            fr = idx.get_file_record(path)
        except FileNotFoundError:
            return None
        br = fr.bundle
        if br.contents is None:
            # ggpk_path is "Bundles2/..." — strip prefix for disk path
            rel = br.ggpk_path.replace("Bundles2/", "", 1)
            disk_path = os.path.join(args.bundles, rel)
            if not os.path.exists(disk_path):
                return None
            with open(disk_path, "rb") as f:
                br.read(f.read())
        return fr.get_file()

    # ── Extract ──
    print(f"\n[2] Extracting {len(tables)} tables (Simplified Chinese)...")
    sc_stats = {}

    for tn in tables:
        d64 = tn.replace(".dat", ".datc64").lower()
        path = datc64_map.get(d64)
        sk = spec_map.get(d64)
        if not path or not sk:
            continue

        raw = extract(path)
        if raw is None:
            print(f"  FAIL {tn}: bundle not found on disk")
            continue

        try:
            rows = parse_dat(sk, raw, spec)
        except Exception as e:
            print(f"  ERROR {tn}: {e}")
            continue

        jn = tn.replace(".dat", ".json")
        with open(os.path.join(out_sc, jn), "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        sc_stats[tn] = len(rows)
        print(f"  OK  {tn}: {len(rows)} rows")

    # ── Summary ──
    print(f"\n[3] Done in {time.time() - start:.1f}s")
    print(f"    SC: {len(sc_stats)} tables, {sum(sc_stats.values()):,} records -> {out_sc}")


if __name__ == "__main__":
    main()
