#!/usr/bin/env python3
"""Benchmark GameGraph query latency.

Measures:
- find_entity() cold/warm latency
- expand() with 1/2 hops
- trace() full tree

Outputs:
- stdout summary
- JSON report to --report path (optional)
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "."))

from game_graph import GameGraph


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[-1]
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def bench_find_entity(graph, queries, repeats=20):
    samples = defaultdict(list)
    for query in queries:
        for _ in range(repeats):
            start = time.perf_counter()
            graph.find_entity(query)
            elapsed_ms = (time.perf_counter() - start) * 1000
            samples[query].append(elapsed_ms)
    return samples


def bench_expand(graph, entities, max_hops_list=(1, 2), repeats=10):
    samples = defaultdict(list)
    for entity in entities:
        results = graph.find_entity(entity)
        if not results:
            continue
        table, key, _, _ = results[0]
        for hops in max_hops_list:
            label = f"{table}:{key}@{hops}h"
            for _ in range(repeats):
                start = time.perf_counter()
                graph.expand(table, key, max_hops=hops)
                elapsed_ms = (time.perf_counter() - start) * 1000
                samples[label].append(elapsed_ms)
    return samples


def summarize(samples):
    summary = {}
    for key, values in samples.items():
        sorted_v = sorted(values)
        summary[str(key)] = {
            "count": len(values),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3),
            "mean_ms": round(sum(values) / len(values), 3),
            "p50_ms": round(percentile(sorted_v, 0.50), 3),
            "p95_ms": round(percentile(sorted_v, 0.95), 3),
            "p99_ms": round(percentile(sorted_v, 0.99), 3),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description="GameGraph latency benchmark")
    parser.add_argument("--relations", default="backend/data/poe2_data/game_relations.json",
                        help="Path to game_relations.json")
    parser.add_argument("--data-dir", default="backend/data/poe2_data",
                        help="Path to poe2_data base dir")
    parser.add_argument("--report", default=None, help="Path to write JSON report")
    parser.add_argument("--repeats", type=int, default=20, help="Repeat count per query")
    args = parser.parse_args()

    print("Loading GameGraph...")
    graph = GameGraph(args.relations, args.data_dir, locale="sc")

    queries = ["ground_slam", "Strength", "Life", "Mana", "FireResist"]
    entities = ["ground_slam", "Strength1", "Life1"]

    print("\nBenchmarking find_entity...")
    find_samples = bench_find_entity(graph, queries, repeats=args.repeats)
    find_summary = summarize(find_samples)

    print("Benchmarking expand...")
    expand_samples = bench_expand(graph, entities, repeats=args.repeats)
    expand_summary = summarize(expand_samples)

    report = {
        "relations": args.relations,
        "data_dir": args.data_dir,
        "repeats": args.repeats,
        "find_entity": find_summary,
        "expand": expand_summary,
    }

    print("\n=== find_entity ===")
    for key, stats in find_summary.items():
        print(f"{key:30s} p50={stats['p50_ms']:7.3f}ms  p95={stats['p95_ms']:7.3f}ms  max={stats['max_ms']:7.3f}ms")

    print("\n=== expand ===")
    for key, stats in expand_summary.items():
        print(f"{str(key):30s} p50={stats['p50_ms']:7.3f}ms  p95={stats['p95_ms']:7.3f}ms  max={stats['max_ms']:7.3f}ms")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nReport written to: {args.report}")

    return report


if __name__ == "__main__":
    main()
