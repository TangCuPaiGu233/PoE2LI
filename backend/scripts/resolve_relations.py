"""Resolve all FK row-index references in game data to actual row_keys.

Reads EN JSON data + PyPoE spec → produces:
  1. game_relations.json  — all resolved edges
  2. Prints statistics

Usage:
    python resolve_relations.py --data-dir backend/data/poe2_data/en --output backend/data/poe2_data/game_relations.json
"""
import os
import sys
import json
import argparse
from collections import defaultdict

# Add PyPoE
from PyPoE.poe.file.specification import load, constants

OUR_TABLES = [
    "ActiveSkills", "SkillGems", "GemTags", "ActiveSkillType",
    "GrantedEffects", "GrantedEffectsPerLevel",
    "BaseItemTypes", "ItemClasses", "Tags",
    "Mods", "PassiveSkills", "Ascendancy",
    "AlternatePassiveSkills", "AlternatePassiveAdditions",
    "Stats", "MonsterVarieties", "MonsterResistances", "MonsterArmours",
    "ItemExperiencePerLevel", "CharacterStartStates",
    "WorldAreas", "MapPins", "Words", "QuestFlags",
]


def load_spec_fk():
    """Extract FK definitions from PyPoE spec for our 24 tables.
    Returns: {src_table: [{field, dst_table, is_array}]}
    """
    spec = load(version=constants.VERSION.POE2)
    
    spec_to_ours = {}
    for tname in OUR_TABLES:
        spec_name = f"{tname}.dat"
        if spec_name in spec:
            spec_to_ours[spec_name] = tname
    
    fk_map = defaultdict(list)
    
    for tname in OUR_TABLES:
        spec_name = f"{tname}.dat"
        if spec_name not in spec:
            continue
        t = spec[spec_name]
        d = t.as_dict()
        fields = d.get("fields", {})
        
        for field_name, field_info in fields.items():
            typ = field_info.get("type", "")
            key = field_info.get("key")
            if not key:
                continue
            if key in spec_to_ours:
                dst_table = spec_to_ours[key]
                is_array = "list" in typ
                fk_map[tname].append({
                    "field": field_name,
                    "dst_table": dst_table,
                    "is_array": is_array,
                })
    
    return dict(fk_map)


def load_table_data(data_dir, table_name):
    """Load a table's EN JSON data."""
    path = os.path.join(data_dir, f"{table_name}.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_row_key(row, index, table_name):
    """Get the row_key for a record, matching the import script logic."""
    # Use TABLE_CONFIG from import_game_data.py
    key_fields = {
        "ActiveSkills": "Id", "SkillGems": "BaseItemType", "GemTags": "Id",
        "ActiveSkillType": "Id", "GrantedEffects": "Id", "GrantedEffectsPerLevel": None,
        "BaseItemTypes": "Id", "ItemClasses": "Id", "Tags": "Id",
        "Mods": "Id", "PassiveSkills": "Id", "Ascendancy": "Id",
        "AlternatePassiveSkills": "Id", "AlternatePassiveAdditions": "Id",
        "Stats": "Id", "MonsterVarieties": "Id", "MonsterResistances": "Id",
        "MonsterArmours": "Id", "ItemExperiencePerLevel": None,
        "CharacterStartStates": "Id", "WorldAreas": "Id", "MapPins": "Id",
        "Words": "Id", "QuestFlags": "Id",
    }
    key_field = key_fields.get(table_name)
    if key_field and key_field in row and row[key_field] is not None:
        val = row[key_field]
        if isinstance(val, list):
            return f"{index}_{','.join(str(v) for v in val[:3])}"
        return str(val)
    return str(index)


def build_row_index(records, table_name):
    """Build [row_key_0, row_key_1, ...] positional index for a table."""
    return [get_row_key(row, i, table_name) for i, row in enumerate(records)]


def resolve_fk_value(value, dst_index, is_array):
    """Resolve a FK field value to row_key(s).
    
    Returns: list of resolved row_keys (empty if unresolvable)
    """
    if value is None:
        return []
    
    if is_array:
        if not isinstance(value, list):
            value = [value]
        resolved = []
        for v in value:
            if isinstance(v, int) and 0 <= v < len(dst_index):
                resolved.append(dst_index[v])
            elif isinstance(v, str) and v in set(dst_index):
                # String ID that matches a row_key directly
                resolved.append(v)
        return resolved
    else:
        if isinstance(value, int) and 0 <= value < len(dst_index):
            return [dst_index[value]]
        elif isinstance(value, str) and value in set(dst_index):
            return [value]
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="Path to en/ dir with JSON files")
    parser.add_argument("--output", default="game_relations.json")
    args = parser.parse_args()
    
    print("Loading PyPoE spec for FK definitions...")
    fk_map = load_spec_fk()
    total_fk_fields = sum(len(v) for v in fk_map.values())
    print(f"  Found {total_fk_fields} FK fields across {len(fk_map)} tables")
    
    print(f"\nLoading table data from {args.data_dir}...")
    table_data = {}
    table_index = {}  # table_name -> [row_key_0, row_key_1, ...]
    for tname in OUR_TABLES:
        records = load_table_data(args.data_dir, tname)
        table_data[tname] = records
        table_index[tname] = build_row_index(records, tname)
        print(f"  {tname}: {len(records)} records")
    
    print(f"\nResolving FK relationships...")
    edges = []
    stats = defaultdict(int)
    
    for src_table, fk_fields in fk_map.items():
        records = table_data.get(src_table, [])
        if not records:
            continue
        
        src_index = table_index[src_table]
        
        for fk in fk_fields:
            field = fk["field"]
            dst_table = fk["dst_table"]
            is_array = fk["is_array"]
            dst_idx = table_index.get(dst_table, [])
            
            if not dst_idx:
                continue
            
            resolved_count = 0
            for row_i, row in enumerate(records):
                if field not in row:
                    continue
                value = row[field]
                resolved_keys = resolve_fk_value(value, dst_idx, is_array)
                
                for dst_key in resolved_keys:
                    src_key = src_index[row_i]
                    edges.append({
                        "src_table": src_table,
                        "src_key": src_key,
                        "dst_table": dst_table,
                        "dst_key": dst_key,
                        "relation": field,
                    })
                    resolved_count += 1
            
            stats[f"{src_table}.{field} → {dst_table}"] = resolved_count
    
    # Print statistics
    print(f"\n=== Resolution Statistics ===")
    print(f"Total edges resolved: {len(edges)}")
    print(f"\nTop 20 FK fields by edge count:")
    sorted_stats = sorted(stats.items(), key=lambda x: -x[1])
    for field_path, count in sorted_stats[:20]:
        print(f"  {field_path}: {count:,} edges")
    
    print(f"\n=== Edges per source table ===")
    edge_by_src = defaultdict(int)
    for e in edges:
        edge_by_src[e["src_table"]] += 1
    for t in sorted(edge_by_src.keys()):
        print(f"  {t}: {edge_by_src[t]:,}")
    
    print(f"\n=== Edges per target table (reverse) ===")
    edge_by_dst = defaultdict(int)
    for e in edges:
        edge_by_dst[e["dst_table"]] += 1
    for t in sorted(edge_by_dst.keys()):
        print(f"  {t}: {edge_by_dst[t]:,}")
    
    # Save edges
    output = {
        "meta": {
            "total_edges": len(edges),
            "fk_fields": total_fk_fields,
            "tables": OUR_TABLES,
        },
        "fk_definitions": {k: v for k, v in fk_map.items()},
        "edges": edges,
    }
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"\nSaved {len(edges):,} edges to {args.output} ({os.path.getsize(args.output) / 1024 / 1024:.1f} MB)")
    
    # Sample: trace "ground_slam"
    print(f"\n=== Sample: Ground Slam relation trace ===")
    slam_edges = [e for e in edges if e["src_key"] == "ground_slam" or e["dst_key"] == "ground_slam"]
    for e in slam_edges[:20]:
        direction = "→" if e["src_key"] == "ground_slam" else "←"
        if direction == "→":
            print(f"  ground_slam --{e['relation']}--> {e['dst_table']}:{e['dst_key']}")
        else:
            print(f"  {e['src_table']}:{e['src_key']} --{e['relation']}--> ground_slam")
    if len(slam_edges) > 20:
        print(f"  ... and {len(slam_edges) - 20} more")


if __name__ == "__main__":
    main()
