#!/usr/bin/env python3
"""Extract stat descriptions from GGPK .csd files (all locales in one pass).

CSD files are UTF-16 LE text files containing stat-to-display-text mappings
with translations for all supported languages.

Output: 3 JSON files (en/tc/sc) compatible with import_game_data.py.

Usage:
    python extract_csd.py
    python extract_csd.py --ggpk "D:\\Games\\PoE2\\Content.ggpk"
"""
import argparse
import json
import os
import re
import sys
import time
from io import BytesIO

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_GGPK = r"C:\Program Files (x86)\Grinding Gear Games\Path of Exile 2 - poe2_production\Content.ggpk"
DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), "..", "..", "data", "poe2_data")

# Language mapping: CSD lang name -> locale code
LANG_MAP = {
    "English": "en",           # default (no lang block)
    "Traditional Chinese": "tc",
    "Simplified Chinese": "sc",
}


def parse_csd(text):
    """Parse a CSD file's text content into structured records.
    
    Returns: list of {id: str, en: str, tc: str, sc: str}
    """
    records = []
    lines = text.split("\n")
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Find "description" blocks
        if line == "description":
            i += 1
            if i >= len(lines):
                break
            
            # Parse stat IDs line: "<count> <id1> [<id2> ...]"
            stat_line = lines[i].strip()
            i += 1
            if i >= len(lines):
                break
            
            parts = stat_line.split()
            if not parts:
                continue
            try:
                num_stats = int(parts[0])
            except ValueError:
                continue
            stat_ids = parts[1:1 + num_stats]
            
            if not stat_ids:
                continue
            
            # Parse template count for default (English)
            tmpl_line = lines[i].strip() if i < len(lines) else ""
            i += 1
            try:
                num_templates = int(tmpl_line)
            except ValueError:
                num_templates = 0
            
            # Parse English templates
            en_templates = []
            for _ in range(num_templates):
                if i >= len(lines):
                    break
                t = lines[i].strip()
                i += 1
                # Extract text between quotes: '1 "text"' or '# "text"'
                m = re.search(r'"(.*)"', t)
                if m:
                    en_templates.append(m.group(1))
            
            # Use first template as primary (or join if multiple)
            en_text = en_templates[0] if en_templates else ""
            
            # Parse language blocks
            translations = {"en": en_text}
            
            while i < len(lines):
                line = lines[i].strip()
                
                # Check for lang block
                lang_match = re.match(r'lang\s+"(.+)"', line)
                if not lang_match:
                    break
                
                lang_name = lang_match.group(1)
                i += 1
                
                # Parse template count for this language
                tmpl_line = lines[i].strip() if i < len(lines) else ""
                i += 1
                try:
                    num_tmpl = int(tmpl_line)
                except ValueError:
                    num_tmpl = 0
                
                lang_templates = []
                for _ in range(num_tmpl):
                    if i >= len(lines):
                        break
                    t = lines[i].strip()
                    i += 1
                    m = re.search(r'"(.*)"', t)
                    if m:
                        lang_templates.append(m.group(1))
                
                lang_text = lang_templates[0] if lang_templates else ""
                
                # Map to locale code
                locale = LANG_MAP.get(lang_name)
                if locale and locale != "en":
                    translations[locale] = lang_text
            
            # Create one record per stat ID
            for sid in stat_ids:
                records.append({
                    "Id": sid,
                    "Description": translations.get("en", ""),
                    "Description_TC": translations.get("tc", ""),
                    "Description_SC": translations.get("sc", ""),
                })
        else:
            i += 1
    
    return records


def extract_from_ggpk(ggpk_path, output_dir):
    """Extract all .csd files from GGPK and parse them."""
    from PyPoE.poe.file.ggpk import GGPKFile
    from PyPoE.poe.file.bundle import Index
    
    start = time.time()
    
    # Load GGPK
    print(f"[1] Loading GGPK: {ggpk_path}")
    ggpk = GGPKFile()
    ggpk.read(ggpk_path)
    ggpk.directory_build()
    
    # Find bundle index
    idx_node = None
    bundle_nodes = {}
    
    def find_index(**kwargs):
        nonlocal idx_node
        n = kwargs.get("node")
        if n and hasattr(n, "get_path") and n.get_path() == "Bundles2/_.index.bin":
            idx_node = n
    
    def cache_bundles(**kwargs):
        n = kwargs.get("node")
        if n and hasattr(n, "get_path"):
            p = n.get_path()
            if p.endswith(".bundle.bin"):
                bundle_nodes[p] = n
    
    ggpk.directory.walk(find_index)
    ggpk.directory.walk(cache_bundles)
    
    if idx_node is None:
        print("ERROR: Could not find Bundles2/_.index.bin")
        sys.exit(1)
    
    raw = idx_node.record.extract()
    raw_bytes = raw.read() if hasattr(raw, "read") else raw
    idx = Index()
    idx.read(BytesIO(raw_bytes))
    
    # Find all .csd files under data/statdescriptions/
    csd_paths = []
    for dr in idx.directories.values():
        for fp in dr.paths:
            p = fp if isinstance(fp, str) else fp.decode()
            if p.lower().startswith("data/statdescriptions/") and p.lower().endswith(".csd"):
                csd_paths.append(p)
    
    print(f"    Found {len(csd_paths)} .csd files")
    
    # Extract and parse each file
    all_records = {}  # stat_id -> {en, tc, sc}
    files_ok = 0
    files_err = 0
    
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
    
    print(f"\n[2] Extracting and parsing .csd files...")
    for path in sorted(csd_paths):
        try:
            raw_content = extract_file(path)
            if raw_content is None:
                files_err += 1
                continue
            text = raw_content.decode("utf-16")
            records = parse_csd(text)
            
            for rec in records:
                sid = rec["Id"]
                if sid not in all_records:
                    all_records[sid] = {
                        "Id": sid,
                        "Description": rec["Description"],
                        "Description_TC": rec.get("Description_TC", ""),
                        "Description_SC": rec.get("Description_SC", ""),
                    }
                else:
                    # Merge: prefer non-empty translations
                    if rec["Description"] and not all_records[sid]["Description"]:
                        all_records[sid]["Description"] = rec["Description"]
                    if rec.get("Description_TC") and not all_records[sid]["Description_TC"]:
                        all_records[sid]["Description_TC"] = rec["Description_TC"]
                    if rec.get("Description_SC") and not all_records[sid]["Description_SC"]:
                        all_records[sid]["Description_SC"] = rec["Description_SC"]
            
            files_ok += 1
        except Exception as e:
            files_err += 1
            print(f"  ERROR {os.path.basename(path)}: {e}")
    
    print(f"    Parsed: {files_ok} OK, {files_err} errors")
    print(f"    Unique stat descriptions: {len(all_records)}")
    
    # Write output: 3 locale files (same keys, different Description fields)
    out_en = os.path.join(output_dir, "en")
    out_tc = os.path.join(output_dir, "tc")
    out_sc = os.path.join(output_dir, "sc")
    os.makedirs(out_en, exist_ok=True)
    os.makedirs(out_tc, exist_ok=True)
    os.makedirs(out_sc, exist_ok=True)
    
    records_list = sorted(all_records.values(), key=lambda r: r["Id"])
    
    # EN file: Description = English text
    en_records = [{"Id": r["Id"], "Description": r["Description"]} for r in records_list]
    en_path = os.path.join(out_en, "StatDescriptions.json")
    with open(en_path, "w", encoding="utf-8") as f:
        json.dump(en_records, f, ensure_ascii=False, indent=2)
    
    # TC file: Description = Traditional Chinese text (fallback to EN if empty)
    tc_records = [
        {"Id": r["Id"], "Description": r.get("Description_TC") or r["Description"]}
        for r in records_list
    ]
    tc_path = os.path.join(out_tc, "StatDescriptions.json")
    with open(tc_path, "w", encoding="utf-8") as f:
        json.dump(tc_records, f, ensure_ascii=False, indent=2)
    
    # SC file: Description = Simplified Chinese text (fallback to EN if empty)
    sc_records = [
        {"Id": r["Id"], "Description": r.get("Description_SC") or r["Description"]}
        for r in records_list
    ]
    sc_path = os.path.join(out_sc, "StatDescriptions.json")
    with open(sc_path, "w", encoding="utf-8") as f:
        json.dump(sc_records, f, ensure_ascii=False, indent=2)
    
    elapsed = time.time() - start
    
    # Stats
    has_tc = sum(1 for r in records_list if r.get("Description_TC"))
    has_sc = sum(1 for r in records_list if r.get("Description_SC"))
    
    print(f"\n[3] Done in {elapsed:.1f}s")
    print(f"    EN: {len(en_records)} records -> {en_path}")
    print(f"    TC: {len(tc_records)} records ({has_tc} native, {len(tc_records) - has_tc} EN fallback) -> {tc_path}")
    print(f"    SC: {len(sc_records)} records ({has_sc} native, {len(sc_records) - has_sc} EN fallback) -> {sc_path}")
    
    # Print some samples
    print(f"\n    Sample entries:")
    for r in records_list[:5]:
        en = r["Description"]
        tc = r.get("Description_TC", "")
        sc = r.get("Description_SC", "")
        print(f"      {r['Id']}")
        print(f"        EN: {en}")
        if tc:
            print(f"        TC: {tc}")
        if sc:
            print(f"        SC: {sc}")


def main():
    parser = argparse.ArgumentParser(description="Extract stat descriptions from GGPK .csd files")
    parser.add_argument("--ggpk", default=DEFAULT_GGPK, help="Path to Content.ggpk")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output base directory")
    args = parser.parse_args()
    
    extract_from_ggpk(args.ggpk, args.output)


if __name__ == "__main__":
    main()
