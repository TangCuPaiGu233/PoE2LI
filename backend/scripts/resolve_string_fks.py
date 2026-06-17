"""Resolve string-based FK references that PyPoE already resolved from row indices to IDs.

These are fields typed 'ref|string' in spec where the string value IS an ID in another table.
E.g. ActiveSkills.GrantedEffect = "ground_slam_effect" → GrantedEffects.Id

Usage:
    python resolve_string_fks.py --data-dir ../data/poe2_data/en --relations ../data/poe2_data/game_relations.json
"""
import json
import os
import argparse
from collections import defaultdict

# Known string-based cross-references (field_name → target_table)
STRING_FK_HEURISTICS = {
    "ActiveSkills": {
        "GrantedEffect": "GrantedEffects",
    },
    "GrantedEffects": {
        "RegularVariant": "GrantedEffects",
    },
    "MonsterVarieties": {
        "BaseMonsterTypeIndex": "MonsterVarieties",
    },
    "PassiveSkills": {
        "Group": "PassiveSkills",
    },
}

KEY_FIELDS = {
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

OUR_TABLES = list(KEY_FIELDS.keys())


def load_table_keys(data_dir, table_name):
    """Load a table and return {Id_value: row_key} mapping."""
    path = os.path.join(data_dir, f"{table_name}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)
    
    id_to_index = {}
    for i, row in enumerate(records):
        if "Id" in row and row["Id"] is not None:
            id_to_index[str(row["Id"])] = i
    
    kf = KEY_FIELDS.get(table_name)
    index_to_key = {}
    for i, row in enumerate(records):
        if kf and kf in row and row[kf] is not None:
            val = row[kf]
            if isinstance(val, list):
                index_to_key[i] = f"{i}_{','.join(str(v) for v in val[:3])}"
            else:
                index_to_key[i] = str(val)
        else:
            index_to_key[i] = str(i)
    
    result = {}
    for id_val, idx in id_to_index.items():
        if idx in index_to_key:
            result[id_val] = index_to_key[idx]
    return result


def resolve_string_fks(data_dir, tables):
    """Find and resolve string-based FK references. Returns additional edges."""
    table_id_keys = {}
    for tname in tables:
        table_id_keys[tname] = load_table_keys(data_dir, tname)
    
    additional_edges = []
    for src_table, field_map in STRING_FK_HEURISTICS.items():
        src_path = os.path.join(data_dir, f"{src_table}.json")
        if not os.path.exists(src_path):
            continue
        with open(src_path, "r", encoding="utf-8") as f:
            src_records = json.load(f)
        
        src_key_field = KEY_FIELDS.get(src_table, "Id")
        for field_name, dst_table in field_map.items():
            dst_keys = table_id_keys.get(dst_table, {})
            if not dst_keys:
                continue
            resolved = 0
            for row_i, row in enumerate(src_records):
                if field_name not in row or row[field_name] is None:
                    continue
                val = str(row[field_name])
                if val in dst_keys:
                    if src_key_field in row and row[src_key_field] is not None:
                        src_key = str(row[src_key_field])
                    else:
                        src_key = str(row_i)
                    dst_key = dst_keys[val]
                    additional_edges.append({
                        "src_table": src_table,
                        "src_key": src_key,
                        "dst_table": dst_table,
                        "dst_key": dst_key,
                        "relation": field_name,
                    })
                    resolved += 1
            print(f"  String FK: {src_table}.{field_name} → {dst_table}: {resolved} resolved")
    return additional_edges


def main():
    parser = argparse.ArgumentParser(description="Resolve string-based FK references")
    parser.add_argument("--data-dir", required=True, help="Path to en/ dir with JSON files")
    parser.add_argument("--relations", default=None, help="Path to game_relations.json (will be updated in-place)")
    args = parser.parse_args()

    rel_path = args.relations or os.path.join(os.path.dirname(args.data_dir), "game_relations.json")

    print("Resolving string-based FK references...")
    extra_edges = resolve_string_fks(args.data_dir, OUR_TABLES)
    print(f"\nTotal additional edges: {len(extra_edges)}")
    
    with open(rel_path, "r", encoding="utf-8") as f:
        rel_data = json.load(f)
    
    old_count = len(rel_data["edges"])
    rel_data["edges"].extend(extra_edges)
    rel_data["meta"]["total_edges"] = len(rel_data["edges"])
    
    with open(rel_path, "w", encoding="utf-8") as f:
        json.dump(rel_data, f, ensure_ascii=False)
    
    print(f"Merged: {old_count} + {len(extra_edges)} = {len(rel_data['edges'])} total edges")


if __name__ == "__main__":
    main()
