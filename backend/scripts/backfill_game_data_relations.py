#!/usr/bin/env python3
"""Backfill kb_entities / kb_edges from game_relations.json.

Usage:
    python scripts/backfill_game_data_relations.py --relations backend/data/poe2_data/game_relations.json
    python scripts/backfill_game_data_relations.py --relations backend/data/poe2_data/game_relations.json --dry-run
    python scripts/backfill_game_data_relations.py --relations backend/data/poe2_data/game_relations.json --game-version 0.2.0
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.knowledge_graph import KbEntity, KbEdge


def load_relations(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def infer_entity_type(table_name):
    mapping = {
        "ActiveSkills": "skill",
        "SkillGems": "gem",
        "Mods": "mod",
        "Stats": "stat",
        "PassiveSkills": "passive",
        "BaseItemTypes": "item",
        "MonsterVarieties": "monster",
        "WorldAreas": "area",
        "NPCs": "npc",
    }
    return mapping.get(table_name, "entity")


def backfill(relations_path, game_version=None, dry_run=False, batch_size=500):
    rel = load_relations(relations_path)
    edges = rel.get("edges", [])
    tables = rel.get("meta", {}).get("tables", [])

    entity_index = {}  # (table, key) -> entity_id
    entity_objects = []
    edge_objects = []

    # Build entities from edge endpoints
    seen_entities = {}
    for e in edges:
        src = (e["src_table"], e["src_key"])
        dst = (e["dst_table"], e["dst_key"])
        for node_key in (src, dst):
            if node_key not in seen_entities:
                table, key = node_key
                seen_entities[node_key] = {
                    "entity_key": f"{table}:{key}",
                    "entity_type": infer_entity_type(table),
                    "name_en": key,
                    "name_cn": None,
                    "game_version": game_version,
                }

    # Deduplicate by entity_key
    unique_entities = {}
    for node_key, meta in seen_entities.items():
        ek = meta["entity_key"]
        if ek not in unique_entities:
            unique_entities[ek] = meta

    print(f"Entities to backfill: {len(unique_entities)}")
    print(f"Edges to backfill: {len(edges)}")

    if dry_run:
        print("[DRY] Would insert entities/edges.")
        return {"entities": len(unique_entities), "edges": len(edges)}

    session = SessionLocal()
    try:
        # Delete existing relations sourced from game_relations for this version
        query = session.query(KbEntity).filter(KbEntity.game_version == game_version)
        if game_version:
            existing_entities = query.all()
            for ent in existing_entities:
                session.delete(ent)
            session.flush()

        # Insert entities
        for i, meta in enumerate(unique_entities.values(), start=1):
            obj = KbEntity(
                entity_key=meta["entity_key"],
                entity_type=meta["entity_type"],
                name_en=meta["name_en"],
                name_cn=meta["name_cn"],
                aliases=None,
                chunk_id=None,
                league=None,
                game_version=meta["game_version"],
            )
            entity_objects.append(obj)
            entity_index[meta["entity_key"]] = obj
            if i % batch_size == 0:
                session.add_all(entity_objects)
                session.flush()
                entity_objects = []

        if entity_objects:
            session.add_all(entity_objects)
            session.flush()

        # Build entity_key -> id mapping
        entity_key_to_id = {ent.entity_key: ent.id for ent in session.query(KbEntity).filter(KbEntity.game_version == game_version).all()}

        # Insert edges
        for i, e in enumerate(edges, start=1):
            src_key = f"{e['src_table']}:{e['src_key']}"
            dst_key = f"{e['dst_table']}:{e['dst_key']}"
            src_id = entity_key_to_id.get(src_key)
            dst_id = entity_key_to_id.get(dst_key)
            if src_id is None or dst_id is None:
                continue
            obj = KbEdge(
                src_entity_id=src_id,
                dst_entity_id=dst_id,
                relation=e.get("relation", "related"),
                weight=1.0,
                source_chunk_id=None,
            )
            edge_objects.append(obj)
            if i % batch_size == 0:
                session.add_all(edge_objects)
                session.flush()
                edge_objects = []

        if edge_objects:
            session.add_all(edge_objects)
            session.flush()

        session.commit()
        return {"entities": len(entity_key_to_id), "edges": len(edge_objects)}
    except Exception as exc:
        session.rollback()
        raise exc
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill kb_entities/kb_edges from game_relations.json")
    parser.add_argument("--relations", required=True, help="Path to game_relations.json")
    parser.add_argument("--game-version", default=None, help="Game version tag")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    result = backfill(args.relations, game_version=args.game_version, dry_run=args.dry_run, batch_size=args.batch_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
