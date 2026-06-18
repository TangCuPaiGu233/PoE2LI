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
    
    def __init__(self, relations_path, data_dir=None, locale="sc"):
        """
        Args:
            relations_path: path to game_relations.json
            data_dir: path to poe2_data base dir containing en/, tc/, sc/ subdirs
                      (or a single locale dir for backward compat)
            locale: preferred display locale for names (default "sc")
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
        """Load raw table data for name lookups.
        
        Supports two directory layouts:
          - Base dir: data_dir/{en,tc,sc}/*.json  (preferred)
          - Single locale dir: data_dir/*.json     (backward compat)
        """
        # Detect layout
        locales_to_load = []
        if os.path.isdir(os.path.join(data_dir, "en")):
            # Base directory layout — load all available locales
            for loc in ("en", "tc", "sc"):
                loc_dir = os.path.join(data_dir, loc)
                if os.path.isdir(loc_dir):
                    locales_to_load.append((loc, loc_dir))
        else:
            # Single locale directory
            locales_to_load.append((locale, data_dir))
        
        for loc, loc_dir in locales_to_load:
            for tname in self.tables:
                path = os.path.join(loc_dir, f"{tname}.json")
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                
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
                    
                    node_key = (tname, key)
                    name = self._extract_name(row, tname, locale=loc)
                    
                    if node_key not in self.entity_index:
                        self.entity_index[node_key] = {
                            "name_en": None, "name_tc": None, "name_sc": None,
                            "row": row,
                        }
                    
                    # Store locale-specific name
                    name_field = f"name_{loc}"
                    if name:
                        self.entity_index[node_key][name_field] = name
                    
                    # For backward compat, "name" = primary locale or first available
                    info = self.entity_index[node_key]
                    if not info.get("name"):
                        info["name"] = name
                    
                    # Index all locale names for search
                    if name:
                        self._name_lookup[name.lower()].append(node_key)
                    
                    # Also index the key itself (only once)
                    if loc == locales_to_load[0][0]:
                        self._name_lookup[key.lower()].append(node_key)
    
    def _get_key_field(self, table_name):
        key_fields = {
            # ── Original 25 ──
            "ActiveSkills": "Id", "SkillGems": "BaseItemType", "GemTags": "Id",
            "ActiveSkillType": "Id", "GrantedEffects": "Id", "GrantedEffectsPerLevel": None,
            "BaseItemTypes": "Id", "ItemClasses": "Id", "Tags": "Id",
            "Mods": "Id", "PassiveSkills": "Id", "Ascendancy": "Id",
            "AlternatePassiveSkills": "Id", "AlternatePassiveAdditions": "Id",
            "Stats": "Id", "StatDescriptions": "Id",
            "MonsterVarieties": "Id", "MonsterResistances": "Id",
            "MonsterArmours": "Id", "ItemExperiencePerLevel": None,
            "CharacterStartStates": "Id", "WorldAreas": "Id", "MapPins": "Id",
            "Words": None, "QuestFlags": "Id",
            # ── Expansion: high priority ──
            "CraftingBenchOptions": "Id", "CraftingBenchUnlockCategories": "Id",
            "CraftingBenchSortCategories": "Id", "BuffDefinitions": "Id",
            "FlavourText": "Id", "ModType": None, "ModFamily": "Id",
            "PassiveSkillTrees": "Id", "PassiveSkillMasteryEffects": "Id",
            "PassiveSkillMasteryGroups": "Id", "PassiveSkillStatCategories": "Id",
            "PassiveKeystoneList": "Passive", "SupportGems": "SkillGem",
            "ModGrantedSkills": None,
            # ── Expansion: medium priority ──
            "MapSeries": "Id", "MapSeriesTiers": None, "Maps": "BaseItemType",
            "AtlasNode": "Id", "AtlasNodeDefinition": "Id", "AtlasRegions": "Id",
            "UniqueMaps": None,
            "LeagueInfo": None, "LeagueFlag": "Id",
            "PantheonPanelLayout": "Id", "IncursionArchitect": None,
            "HeistNPCs": None, "HeistJobs": "Id",
            "HeistContracts": None, "HeistObjectives": "BaseItemType",
            "NPCs": "Id", "NPCMaster": "Id", "NPCConversations": "Id",
            "Achievements": "Id", "AchievementItems": "Id",
            "CurrencyItems": "BaseItemType",
            "HideoutNPCs": None, "Hideouts": None, "HideoutDoodads": None,
            "AbyssObjects": "Id",
            "BetrayalChoiceActions": "Id", "BetrayalTargets": "Id",
        }
        return key_fields.get(table_name)
    
    def _extract_name(self, row, table_name, locale=None):
        """Extract display name from a row.
        
        For Words table: SC/TC locales use Text2 (localized) instead of Text (always English).
        """
        # Words: SC/TC store Chinese in Text2, Text is always English
        if table_name == "Words" and locale in ("sc", "tc"):
            if "Text2" in row and isinstance(row["Text2"], str) and row["Text2"].strip():
                return row["Text2"].strip()
        for field in ["Name", "DisplayedName", "Id", "Text", "Description", "FullName"]:
            if field in row and isinstance(row[field], str) and row[field].strip():
                return row[field].strip()
        return None
    
    def _get_display_name(self, node_key):
        """Get display name string, preferring user's locale then fallbacks."""
        info = self.entity_index.get(node_key, {})
        # Build priority order: preferred locale first, then fallbacks
        locale_order = {"sc": ["name_sc", "name_tc", "name_en"],
                        "tc": ["name_tc", "name_sc", "name_en"],
                        "en": ["name_en", "name_tc", "name_sc"]}
        order = locale_order.get(self.locale, ["name_en", "name_tc", "name_sc"])
        
        names = []
        for field in order:
            n = info.get(field)
            if n and n not in names:
                names.append(n)
        if not names:
            return node_key[1]  # fallback to key
        return " / ".join(names)
    
    def find_entity(self, query, table_filter=None):
        """Find entities matching a query string.

        Args:
            query: search string (name, id, or partial match) — supports EN/TC/SC
            table_filter: optional table name to restrict search

        Returns: list of (table, key, display_name, match_type) tuples
        """
        q = query.lower().strip()
        results = []
        seen = set()

        def _add(table, key, match_type):
            if table_filter and table != table_filter:
                return
            if (table, key) not in seen:
                seen.add((table, key))
                results.append((table, key, self._get_display_name((table, key)), match_type))

        # 1) Exact match
        if q in self._name_lookup:
            for table, key in self._name_lookup[q]:
                _add(table, key, "exact")

        # 2) Whole-query partial match (query is substring of indexed name)
        for name_lower, entities in self._name_lookup.items():
            if q in name_lower and q != name_lower:
                for table, key in entities:
                    _add(table, key, "partial")

        # 3) Token-based match — split query into tokens and match individually
        tokens = self._tokenize(q)
        if tokens:
            for token in tokens:
                if len(token) < 2:
                    continue
                for name_lower, entities in self._name_lookup.items():
                    if token in name_lower and name_lower != q:
                        for table, key in entities:
                            _add(table, key, "token")

        # 4) Reverse partial — indexed name is substring of query
        #    (catches short names like "天赋" that appear in longer queries)
        for name_lower, entities in self._name_lookup.items():
            if len(name_lower) >= 2 and name_lower in q and name_lower != q:
                for table, key in entities:
                    _add(table, key, "reverse")

        # Sort: exact > partial > token > reverse, then by table name
        priority = {"exact": 0, "partial": 1, "token": 2, "reverse": 3}
        results.sort(key=lambda x: (priority.get(x[3], 9), x[0]))
        return results

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split query into meaningful tokens using jieba (lazy import)."""
        try:
            import jieba
            return [t.strip() for t in jieba.lcut(text) if len(t.strip()) >= 2]
        except ImportError:
            # Fallback: character bigrams for CJK, whitespace split for Latin
            tokens = text.split()
            # Also add CJK bigrams
            for i in range(len(text) - 1):
                if ord(text[i]) > 0x2E80:  # CJK range
                    tokens.append(text[i:i+2])
            return [t for t in tokens if len(t) >= 2]
    
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
            nodes[(t, k)] = {
                "name": self._get_display_name((t, k)),
                "hop": hop,
            }
        
        return {
            "root": (table, key, self._get_display_name(root)),
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
                # Use display names (SC/TC/EN)
                src_name = self._get_display_name((src_t, src_k))
                dst_name = self._get_display_name((dst_t, dst_k))
                src_label = f"{src_t}:{src_k}"
                dst_label = f"{dst_t}:{dst_k}"
                
                if (src_t, src_k) == result["root"][:2]:
                    name_suffix = f" ({dst_name})" if dst_name != dst_k else ""
                    print(f"    → {rel} → {dst_label}{name_suffix}")
                elif (dst_t, dst_k) == result["root"][:2]:
                    name_suffix = f" ({src_name})" if src_name != src_k else ""
                    print(f"    ← {src_label}{name_suffix} ← {rel}")
                else:
                    print(f"    {src_label} --{rel}--> {dst_label}")
                printed += 1
            print()


def main():
    """Demo: trace Ground Slam and show its full relation network."""
    import sys
    
    relations_path = sys.argv[1] if len(sys.argv) > 1 else "game_relations.json"
    data_dir = sys.argv[2] if len(sys.argv) > 2 else r"D:\PC_AI\Project\PoE2LI\backend\data\poe2_data"
    
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
