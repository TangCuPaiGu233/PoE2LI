#!/usr/bin/env python3
"""PoE2 Game Data Graph Query CLI.

Query any entity and see its full relation network.

Usage:
    python query_graph.py "ground_slam"
    python query_graph.py "ground_slam" --hops 3 --max 50
    python query_graph.py "Strength1" --table Mods
    python query_graph.py "Blacksmith" --search
"""
import sys
import os
import argparse

# Default paths (adjust for your environment)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RELATIONS = os.path.join(SCRIPT_DIR, "..", "data", "poe2_data", "game_relations.json")
DEFAULT_DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data", "poe2_data", "en")


def main():
    parser = argparse.ArgumentParser(description="PoE2 Game Data Graph Query")
    parser.add_argument("query", help="Entity name, ID, or search term")
    parser.add_argument("--hops", type=int, default=2, help="BFS max hops (default: 2)")
    parser.add_argument("--max", type=int, default=100, help="Max nodes to return (default: 100)")
    parser.add_argument("--table", help="Restrict to specific table")
    parser.add_argument("--search", action="store_true", help="Search mode: just find matches, no expansion")
    parser.add_argument("--relations", default=DEFAULT_RELATIONS, help="Path to game_relations.json")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Path to EN data dir")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Import game_graph module
    sys.path.insert(0, SCRIPT_DIR)
    from game_graph import GameGraph

    # Load graph
    print("Loading graph...", file=sys.stderr)
    g = GameGraph(args.relations, args.data_dir)

    # Search
    results = g.find_entity(args.query, table_filter=args.table)

    if not results:
        print(f"No results for '{args.query}'")
        sys.exit(1)

    if args.search:
        print(f"\nSearch results for '{args.query}':")
        for table, key, name, match_type in results[:20]:
            name_str = f" ({name})" if name and name != key else ""
            print(f"  [{match_type}] {table}:{key}{name_str}")
        if len(results) > 20:
            print(f"  ... and {len(results) - 20} more")
        return

    # Expand first result
    table, key, name, _ = results[0]
    print(f"\nExpanding: {table}:{key} ({name})", file=sys.stderr)

    tree = g.expand(table, key, max_hops=args.hops, max_nodes=args.max)

    if args.json:
        import json
        # Convert to JSON-serializable format
        output = {
            "root": {"table": tree["root"][0], "key": tree["root"][1], "name": tree["root"][2]},
            "stats": {"nodes": len(tree["nodes"]), "edges": len(tree["edges"])},
            "nodes": {},
            "edges": [],
        }
        for (t, k), info in tree["nodes"].items():
            output["nodes"][f"{t}:{k}"] = {"name": info["name"], "hop": info["hop"]}
        for e in tree["edges"]:
            output["edges"].append({
                "src": f"{e[0]}:{e[1]}",
                "relation": e[2],
                "dst": f"{e[3]}:{e[4]}",
                "hop": e[5],
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        g.print_tree(tree, max_print=args.max)


if __name__ == "__main__":
    main()
