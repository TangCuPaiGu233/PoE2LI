"""Game Data Knowledge Graph — BFS traversal query.

Loads resolved relation edges + raw table data, provides:
  - find_entity(query): fuzzy match entity by name/id in any table
  - expand(entity, max_hops=2): BFS expansion returning all related data
  - trace(entity): full relation tree from entity

Usage:
    from game_graph import GameGraph
    g = GameGraph(relations_path, data_dir)
    entity = g.find_entity("ground_slam")
    tree = g.expand(entity, max_hops=2)
    g.print_tree(tree)
"""
import json
import os
from collections import defaultdict, deque


class GameGraph:
    """In-memory knowledge graph for PoE2 game data with BFS traversal."""
    
    def __init__(self, relations_path, data_dir=None, locale="en"):
        """
        Args:
            relations_path: path to game_relations.json
            data_dir: optional path to locale data dir (e.g. en/) for raw data
            locale: "en" / "tc" / "sc"
        """
        self.locale = locale
        
        # Load relations
        with open(relations_path, "r", encoding="utf-8") as f:
            rel_data = json.load(f)
        
        self.edges = rel_data["edges"]
        self.fk_definitions = rel_data.get("fk_definitions", {})
        self.tables = rel_data["meta"]["tables"]
        
        # Build adjacency lists (bidirectional)
        self.forward = defaultdict(list)   # (table, key) -> [(relation, dst_table, dst_key)]
        self.backward = defaultdict(list)  # (table, key) -> [(relation, src_table, src_key)]
        
        for e in self.edges:
            src = (e["src_table"], e["src_key"])
            dst = (e["dst_table"], e["dst_key"])
            self.forward[src].append((e["relation"], dst[0], dst[1]))
            self.backward[dst].append((e["relation"], src[0], src[1]))
        
        # Build entity index for search
        self.entity_index = {}  # (table, key) -> {name_en, name_tc, name_sc, data}
        self._name_lookup = defaultdict(list)  # lowercase_name -> [(table, key)]
        
        if data_dir:
            self._load_data(data_dir, locale)
        
        print(f"Graph loaded: {len(self.forward)} source nodes, "
              f"{len(self.backward)} target nodes, {len(self.edges)} edges")
    
    def _load_data(self, data_dir, locale):
        """Load raw table data for name lookups."""
        for tname in self.tables:
            path = os.path.join(data_dir, f"{tname}.json")
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                records = json.load(f)
            
            # Build key -> record mapping (matching import logic)
            key_field = self._get_key_field(tname)
            for i, row in enumerate(records):
                if key_field and key_field in row and row[key_field] is not None:
                    val = row[key_field]
                    if isinstance(val, list):
                        key = f"{i}_{','.join(str(v) for v in val[:3])}"
                    else:
                        key = str(val)
                else:
                    key = str(i)
                
                # Extract display name
                name = self._extract_name(row, tname)
                self.entity_index[(tname, key)] = {
                    "name": name,
                    "row": row,
                }
                
                # Build name -> entity lookup
                if name:
                    self._name_lookup[name.lower()].append((tname, key))
                # Also index the key itself
                self._name_lookup[key.lower()].append((tname, key))
    
    def _get_key_field(self, table_name):
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
        return key_fields.get(table_name)
    
    def _extract_name(self, row, table_name):
        """Extract display name from a row."""
        for field in ["Name", "DisplayedName", "Id", "Text"]:
            if field in row and isinstance(row[field], str) and row[field].strip():
                return row[field].strip()
        return None
    
    def find_entity(self, query, table_filter=None):
        """Find entities matching a query string.
        
        Args:
            query: search string (name, id, or partial match)
            table_filter: optional table name to restrict search
        
        Returns: list of (table, key, name) tuples, sorted by relevance
        """
        q = query.lower().strip()
        results = []
        
        # Exact match first
        if q in self._name_lookup:
            for table, key in self._name_lookup[q]:
                if table_filter and table != table_filter:
                    continue
                info = self.entity_index.get((table, key), {})
                results.append((table, key, info.get("name", key), "exact"))
        
        # Partial match
        for name_lower, entities in self._name_lookup.items():
            if q in name_lower and q != name_lower:
                for table, key in entities:
                    if table_filter and table != table_filter:
                        continue
                    # Avoid duplicates
                    if not any(r[0] == table and r[1] == key for r in results):
                        info = self.entity_index.get((table, key), {})
                        results.append((table, key, info.get("name", key), "partial"))
        
        # Sort: exact first, then by table name
        results.sort(key=lambda x: (0 if x[3] == "exact" else 1, x[0]))
        return results
    
    def expand(self, table, key, max_hops=2, max_nodes=200):
        """BFS expansion from a starting entity.
        
        Args:
            table: source table name
            key: source row_key
            max_hops: maximum BFS depth
            max_nodes: safety limit on total nodes returned
        
        Returns: dict with:
            - root: (table, key, name)
            - nodes: {(table, key): {name, hop, data}}
            - edges: [(src_table, src_key, relation, dst_table, dst_key, hop)]
        """
        root = (table, key)
        visited = {root: 0}  # node -> hop distance
        queue = deque([(root, 0)])
        result_edges = []
        
        while queue and len(visited) < max_nodes:
            node, hop = queue.popleft()
            if hop >= max_hops:
                continue
            
            # Forward edges
            for relation, dst_table, dst_key in self.forward.get(node, []):
                result_edges.append((node[0], node[1], relation, dst_table, dst_key, hop + 1))
                dst = (dst_table, dst_key)
                if dst not in visited:
                    visited[dst] = hop + 1
                    queue.append((dst, hop + 1))
            
            # Backward edges (who references me?)
            for relation, src_table, src_key in self.backward.get(node, []):
                result_edges.append((src_table, src_key, relation, node[0], node[1], hop + 1))
                src = (src_table, src_key)
                if src not in visited:
                    visited[src] = hop + 1
                    queue.append((src, hop + 1))
        
        # Build node details
        nodes = {}
        for (t, k), hop in visited.items():
            info = self.entity_index.get((t, k), {})
            nodes[(t, k)] = {
                "name": info.get("name", k),
                "hop": hop,
            }
        
        root_info = self.entity_index.get(root, {})
        return {
            "root": (table, key, root_info.get("name", key)),
            "nodes": nodes,
            "edges": result_edges,
        }
    
    def print_tree(self, result, max_print=80):
        """Pretty-print expansion result."""
        root_table, root_key, root_name = result["root"]
        print(f"\n{'='*60}")
        print(f"  {root_table}: {root_key}")
        if root_name and root_name != root_key:
            print(f"  ({root_name})")
        print(f"{'='*60}")
        print(f"  Nodes: {len(result['nodes'])} | Edges: {len(result['edges'])}")
        print()
        
        # Group edges by hop
        by_hop = defaultdict(list)
        for e in result["edges"]:
            by_hop[e[5]].append(e)
        
        printed = 0
        for hop in sorted(by_hop.keys()):
            print(f"  ── Hop {hop} ──")
            for src_t, src_k, rel, dst_t, dst_k, h in by_hop[hop]:
                if printed >= max_print:
                    remaining = sum(len(v) for k, v in by_hop.items() if k >= hop) - (printed - sum(len(by_hop[h2]) for h2 in by_hop if h2 < hop))
                    print(f"  ... ({remaining} more edges)")
                    return
                # Determine direction
                if (src_t, src_k) == result["root"][:2]:
                    dst_info = self.entity_index.get((dst_t, dst_k), {})
                    dst_name = dst_info.get("name", dst_k)
                    name_str = f" ({dst_name})" if dst_name and dst_name != dst_k else ""
                    print(f"    → {rel} → {dst_t}:{dst_k}{name_str}")
                elif (dst_t, dst_k) == result["root"][:2]:
                    src_info = self.entity_index.get((src_t, src_k), {})
                    src_name = src_info.get("name", src_k)
                    name_str = f" ({src_name})" if src_name and src_name != src_k else ""
                    print(f"    ← {src_t}:{src_k}{name_str} ← {rel}")
                else:
                    src_info = self.entity_index.get((src_t, src_k), {})
                    dst_info = self.entity_index.get((dst_t, dst_k), {})
                    s_name = src_info.get("name", src_k)
                    d_name = dst_info.get("name", dst_k)
                    print(f"    {src_t}:{src_k} --{rel}--> {dst_t}:{dst_k}")
                printed += 1
            print()


def main():
    """Demo: trace Ground Slam and show its full relation network."""
    import sys
    
    relations_path = sys.argv[1] if len(sys.argv) > 1 else "game_relations.json"
    data_dir = sys.argv[2] if len(sys.argv) > 2 else r"D:\PC_AI\Project\PoE2LI\backend\data\poe2_data\en"
    
    print("Building graph...")
    g = GameGraph(relations_path, data_dir)
    
    # Demo 1: Find "ground_slam"
    print("\n=== Search: 'ground_slam' ===")
    results = g.find_entity("ground_slam", table_filter="ActiveSkills")
    for table, key, name, match_type in results[:5]:
        print(f"  [{match_type}] {table}:{key} ({name})")
    
    if results:
        table, key, name, _ = results[0]
        print(f"\n=== Expand: {table}:{key} (2 hops) ===")
        tree = g.expand(table, key, max_hops=2)
        g.print_tree(tree)
    
    # Demo 2: Find a mod
    print("\n=== Search: 'Strength1' in Mods ===")
    results = g.find_entity("Strength1", table_filter="Mods")
    for table, key, name, match_type in results[:3]:
        print(f"  [{match_type}] {table}:{key} ({name})")
    
    if results:
        table, key, name, _ = results[0]
        tree = g.expand(table, key, max_hops=1)
        g.print_tree(tree, max_print=30)
    
    # Demo 3: Search by Chinese/English name
    print("\n=== Search: 'Blacksmith' ===")
    results = g.find_entity("Blacksmith")
    for table, key, name, match_type in results[:5]:
        print(f"  [{match_type}] {table}:{key} ({name})")


if __name__ == "__main__":
    main()
