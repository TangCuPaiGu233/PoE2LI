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

# Parser registry — custom parsers for types needing DOM-specific logic
_CUSTOM_PARSERS = {
    "ascendancy": "ascendancy_parser",
    "class": "ascendancy_parser",  # same page as ascendancy
}

# Generic list parsers — use base_parser.parse_entity_list for all others
_GENERIC_PARSER_TYPES = {
    "skill", "support", "spirit_gem", "unique", "mod", "passive",
    "currency", "monster", "map_area", "tag", "quest", "crafting",
    "flask", "base_item",
}


def _parse_page(html: str, entity_type: str) -> dict:
    """Route to the appropriate parser for this entity type."""
    if entity_type in _CUSTOM_PARSERS:
        mod_name = _CUSTOM_PARSERS[entity_type]
        mod = __import__(f"parser.parsers.{mod_name}", fromlist=["parse_ascendancy_index"])
        return mod.parse_ascendancy_index(html)
    # Generic tab-pane list parser
    from parser.base_parser import parse_entity_list
    return parse_entity_list(html, entity_type, poe2_tab_only=True)


async def run_pipeline(entity_type: str | None = None, dry_run: bool = False):
    with open("config/entity_types.yaml") as f:
        config = yaml.safe_load(f)
    etypes = config["entity_types"]

    if entity_type:
        etypes = {entity_type: etypes[entity_type]}

    fetcher = Fetcher()

    # Stage A: Discovery + Parse
    logger.info("=== Stage A: Discovery + Parse ===")
    all_entities: list[dict] = []
    seen_entity_ids: set[str] = set()

    # Clear previous raw_edges
    Path("data/raw_edges.jsonl").write_text("", encoding="utf-8")

    for etype, spec in etypes.items():
        for index_url in spec.get("index_urls", []):
            logger.info("Processing %s from %s", etype, index_url)
            html = await fetcher.fetch(index_url)
            if not html:
                logger.warning("  Failed to fetch %s", index_url)
                continue
            parsed = _parse_page(html, etype)
            for ent_id, info in parsed.get("entities", {}).items():
                if ent_id not in seen_entity_ids:
                    seen_entity_ids.add(ent_id)
                    all_entities.append({
                        "entity_id": ent_id,
                        "entity_type": info.get("type", etype),
                        "name_en": ent_id.split(":", 1)[1],
                        "name_cn": info.get("name", ""),
                    })
            for edge in parsed.get("edges", []):
                edge["entity_type"] = etype
                with open("data/raw_edges.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(edge, ensure_ascii=False) + "\n")
            logger.info("  Got %d entities, %d edges", len(parsed.get("entities", {})), len(parsed.get("edges", [])))

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
