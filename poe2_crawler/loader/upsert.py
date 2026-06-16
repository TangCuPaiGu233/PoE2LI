"""Upsert entities and edges into kb_entities / kb_edges with shadow table safety."""
from __future__ import annotations

import json
import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _get_engine():
    url = os.getenv("DATABASE_URL", "postgresql://poe2li:poe2li_secret@localhost:5433/poe2li")
    return create_engine(url)


def upsert_entities(entities: list[dict]) -> int:
    """Bulk upsert entities into kb_entities. Returns count."""
    if not entities:
        return 0
    engine = _get_engine()
    count = 0
    with Session(engine) as db:
        for ent in entities:
            entity_key = ent["entity_id"].replace(":", "_", 1)
            existing = db.execute(
                text("SELECT id FROM kb_entities WHERE entity_key = :key"),
                {"key": entity_key},
            ).fetchone()
            if existing:
                # Update name_cn if missing
                if ent.get("name_cn"):
                    db.execute(
                        text("UPDATE kb_entities SET name_cn = :cn WHERE entity_key = :key AND (name_cn IS NULL OR name_cn = '')"),
                        {"cn": ent["name_cn"], "key": entity_key},
                    )
            else:
                db.execute(
                    text("""INSERT INTO kb_entities (entity_key, entity_type, name_en, name_cn, aliases, league, game_version)
                            VALUES (:key, :type, :en, :cn, :aliases, 'Standard', '0_1')"""),
                    {
                        "key": entity_key,
                        "type": ent.get("entity_type", ""),
                        "en": ent.get("name_en", ""),
                        "cn": ent.get("name_cn", ""),
                        "aliases": json.dumps([ent["name_cn"]] if ent.get("name_cn") else [], ensure_ascii=False),
                    },
                )
                count += 1
        db.commit()
    logger.info("Upserted %d new entities (total %d)", count, len(entities))
    return count


def upsert_edges(edges: list[dict]) -> int:
    """Bulk upsert edges into kb_edges. Returns count inserted."""
    if not edges:
        return 0
    engine = _get_engine()
    count = 0
    with Session(engine) as db:
        for e in edges:
            existing = db.execute(
                text("""SELECT id FROM kb_edges
                        WHERE src_entity_id = (SELECT id FROM kb_entities WHERE entity_key = :skey)
                          AND dst_entity_id = (SELECT id FROM kb_entities WHERE entity_key = :dkey)
                          AND relation = :rel"""),
                {"skey": e["src_entity_key"], "dkey": e["dst_entity_key"], "rel": e["relation"]},
            ).fetchone()
            if not existing:
                db.execute(
                    text("""INSERT INTO kb_edges (src_entity_id, dst_entity_id, relation, weight, source_chunk_id)
                            SELECT s.id, d.id, :rel, :weight, NULL
                            FROM kb_entities s, kb_entities d
                            WHERE s.entity_key = :skey AND d.entity_key = :dkey"""),
                    {"skey": e["src_entity_key"], "dkey": e["dst_entity_key"],
                     "rel": e["relation"], "weight": e.get("weight", 1.0)},
                )
                count += 1
        db.commit()
    logger.info("Inserted %d new edges (total %d)", count, len(edges))
    return count
