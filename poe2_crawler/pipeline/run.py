"""Main pipeline: Discovery → Parse → Normalize → Load → Validate.

Usage:
    cd poe2_crawler
    python -m pipeline.run                         # full pipeline
    python -m pipeline.run --type ascendancy      # single entity type
    python -m pipeline.run --dry-run               # fetch + parse only, don't load
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("pipeline")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from crawler.fetcher import Fetcher
from discovery.discover import discover_all
from normalize.edge_normalizer import normalize_edges
from normalize.url_to_id import url_to_entity_id

# Parser registry — add new parsers here
PARSER_REGISTRY = {
    "ascendancy": "parser.parsers.ascendancy_parser",
    "class": "parser.parsers.ascendancy_parser",  # reuses same page
}


def _import_parser(parser_name: str):
    mod = __import__(PARSER_REGISTRY.get(parser_name, f"parser.parsers.{parser_name}_parser"),
                     fromlist=["parse_index"])
    return mod


async def run_pipeline(entity_type: str | None = None, dry_run: bool = False):
    with open("config/entity_types.yaml") as f:
        config = yaml.safe_load(f)
    etypes = config["entity_types"]

    if entity_type:
        etypes = {entity_type: etypes[entity_type]}

    fetcher = Fetcher()

    # Stage A: Discovery
    logger.info("=== Stage A: Discovery ===")
    all_entities: list[dict] = []
    for etype, spec in etypes.items():
        for index_url in spec.get("index_urls", []):
            html = await fetcher.fetch(index_url)
            if not html:
                continue
            # Run the registered parser
            parser_mod = _import_parser(spec.get("parser", "generic_parser"))
            parsed = parser_mod.parse_ascendancy_index(html) if "ascendancy" in etype else {}
            for ent_id, info in parsed.get("entities", {}).items():
                all_entities.append({
                    "entity_id": ent_id,
                    "entity_type": info.get("type", etype),
                    "name_en": ent_id.split(":", 1)[1],
                    "name_cn": info.get("name", ""),
                })
            for edge in parsed.get("edges", []):
                # Write to raw_edges
                edge["entity_type"] = etype
                with open("data/raw_edges.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    logger.info("Discovered %d entities, %d raw edges",
                len(all_entities),
                sum(1 for _ in Path("data/raw_edges.jsonl").open() if _.strip()) if Path("data/raw_edges.jsonl").exists() else 0)

    if dry_run:
        logger.info("Dry run — skipping load")
        await fetcher.close()
        return

    # Stage B: Normalize & Load edges
    logger.info("=== Stage B: Normalize & Load ===")
    raw_edges_path = Path("data/raw_edges.jsonl")
    if raw_edges_path.exists():
        raw_edges = []
        with open(raw_edges_path) as f:
            for line in f:
                if line.strip():
                    raw_edges.append(json.loads(line))
        normalized = normalize_edges(raw_edges)
        logger.info("Normalized %d edges", len(normalized))

        from loader.upsert import upsert_entities, upsert_edges
        e_count = upsert_entities(all_entities)
        edge_count = upsert_edges(normalized)
        logger.info("Loaded: %d new entities, %d new edges", e_count, edge_count)

    await fetcher.close()
    logger.info("Pipeline complete")


def main():
    parser = argparse.ArgumentParser(description="PoE2DB Crawler Pipeline")
    parser.add_argument("--type", help="Only process this entity type")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + parse only, no DB load")
    args = parser.parse_args()
    asyncio.run(run_pipeline(entity_type=args.type, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
