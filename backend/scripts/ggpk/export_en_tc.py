#!/usr/bin/env python3
"""Export EN + TC game data from international PoE2 client's Content.ggpk.

Extracts datc64 tables using PyPoE and exports as JSON.
- EN from data/balance/ (base English)
- TC from data/balance/traditional chinese/ (Traditional Chinese override)

Usage:
    python export_en_tc.py
    python export_en_tc.py --ggpk "D:\\Games\\PoE2\\Content.ggpk" --output ./poe2_data
    python export_en_tc.py --tables ActiveSkills.dat Mods.dat   # subset

Dependencies: PyPoE (pip install PyPoE)
"""
import argparse
import json
import os
import sys
import time
from io import BytesIO

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_GGPK = r"C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2 - poe2_production\Content.ggpk"
DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "poe2_data")

ALL_TABLES = [
    "ActiveSkills.dat", "SkillGems.dat", "GemTags.dat", "ActiveSkillType.dat",
    "GrantedEffects.dat", "GrantedEffectsPerLevel.dat",
    "BaseItemTypes.dat", "ItemClasses.dat", "Tags.dat", "Mods.dat",
    "PassiveSkills.dat", "Ascendancy.dat",
    "AlternatePassiveSkills.dat", "AlternatePassiveAdditions.dat",
    "Stats.dat",
    "MonsterVarieties.dat", "MonsterResistances.dat", "MonsterArmours.dat",
    "ItemExperiencePerLevel.dat", "CharacterStartStates.dat",
    "WorldAreas.dat", "MapPins.dat",
    "Words.dat", "QuestFlags.dat",
]

LANG_PREFIXES = {
    "french", "german", "korean", "russian", "spanish",
    "portuguese", "thai", "japanese", "traditional chinese",
}


def parse_dat(table_name, raw, spec):
    """Parse a datc64 binary blob into a list of dicts."""
    from PyPoE.poe.file.dat import DatFile

    if table_name not in spec:
        return None
    try:
        df = DatFile(table_name, specification=spec)
        df.read(BytesIO(raw), x64=True)
    except Exception:
        return None

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
    parser = argparse.ArgumentParser(description="Export EN + TC data from GGPK")
    parser.add_argument("--ggpk", default=DEFAULT_GGPK, help="Path to Content.ggpk")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output base directory")
    parser.add_argument("--tables", nargs="*", help="Specific .dat tables (default: all 24)")
    args = parser.parse_args()

    from PyPoE.poe.file.ggpk import GGPKFile
    from PyPoE.poe.file.bundle import Index
    from PyPoE.poe.file.specification import load
    from PyPoE.poe.file.specification import constants as spec_constants

    tables = args.tables or ALL_TABLES
    out_en = os.path.join(args.output, "en")
    out_tc = os.path.join(args.output, "tc")
    os.makedirs(out_en, exist_ok=True)
    os.makedirs(out_tc, exist_ok=True)

    start = time.time()

    # ── Load GGPK ──
    print(f"[1] Loading GGPK: {args.ggpk}")
    ggpk = GGPKFile()
    ggpk.read(args.ggpk)
    ggpk.directory_build()

    # Find bundle index
    idx_node = None

    def find_index(**kwargs):
        nonlocal idx_node
        n = kwargs.get("node")
        if n and hasattr(n, "get_path") and n.get_path() == "Bundles2/_.index.bin":
            idx_node = n

    ggpk.directory.walk(find_index)
    if idx_node is None:
        print("ERROR: Could not find Bundles2/_.index.bin in GGPK")
        sys.exit(1)

    raw = idx_node.record.extract()
    raw_bytes = raw.read() if hasattr(raw, "read") else raw
    idx = Index()
    idx.read(BytesIO(raw_bytes))

    # Cache bundle nodes
    bundle_nodes = {}

    def cache_bundles(**kwargs):
        n = kwargs.get("node")
        if n and hasattr(n, "get_path"):
            p = n.get_path()
            if p.endswith(".bundle.bin"):
                bundle_nodes[p] = n

    ggpk.directory.walk(cache_bundles)

    # Collect EN and TC file paths
    en_paths, tc_paths = {}, {}
    for dr in idx.directories.values():
        for fp in dr.paths:
            p = fp if isinstance(fp, str) else fp.decode()
            if not p.lower().endswith(".datc64"):
                continue
            bn = os.path.basename(p).lower()
            if p.lower().startswith("data/balance/traditional chinese/"):
                tc_paths[bn] = p
            elif p.lower().startswith("data/balance/"):
                sub = p.split("/")[2].lower() if len(p.split("/")) > 3 else ""
                if sub not in LANG_PREFIXES:
                    en_paths[bn] = p

    print(f"    EN paths: {len(en_paths)}, TC paths: {len(tc_paths)}")

    spec = load(version=spec_constants.VERSION.POE2)

    def extract_file(path):
        try:
            fr = idx.get_file_record(path)
        except FileNotFoundError:
            return None
        br = fr.bundle
        if br.contents is None:
            bn = bundle_nodes.get(br.ggpk_path)
            if bn is None:
                return None
            rd = bn.record.extract()
            if hasattr(rd, "read"):
                rd = rd.read()
            br.read(rd)
        return fr.get_file()

    # ── Export ──
    print(f"\n[2] Exporting {len(tables)} tables...")
    en_stats, tc_stats = {}, {}

    for tn in tables:
        key = tn.replace(".dat", ".datc64").lower()
        jn = tn.replace(".dat", ".json")

        # EN
        en_raw = extract_file(en_paths[key]) if key in en_paths else None
        en_recs = parse_dat(tn, en_raw, spec) if en_raw else None
        if en_recs:
            with open(os.path.join(out_en, jn), "w", encoding="utf-8") as f:
                json.dump(en_recs, f, ensure_ascii=False, indent=2)
            en_stats[tn] = len(en_recs)

        # TC
        tc_raw = extract_file(tc_paths[key]) if key in tc_paths else None
        tc_recs = parse_dat(tn, tc_raw, spec) if tc_raw else None
        if tc_recs:
            with open(os.path.join(out_tc, jn), "w", encoding="utf-8") as f:
                json.dump(tc_recs, f, ensure_ascii=False, indent=2)
            tc_stats[tn] = len(tc_recs)

        tags = []
        if en_recs:
            tags.append(f"EN:{len(en_recs)}")
        if tc_recs:
            tags.append(f"TC:{len(tc_recs)}")
        print(f"  {'OK' if tags else 'SKIP'}  {tn}: {', '.join(tags) if tags else 'not found'}")

    # ── Summary ──
    print(f"\n[3] Done in {time.time() - start:.1f}s")
    print(f"    EN: {len(en_stats)} tables, {sum(en_stats.values()):,} records -> {out_en}")
    print(f"    TC: {len(tc_stats)} tables, {sum(tc_stats.values()):,} records -> {out_tc}")


if __name__ == "__main__":
    main()
