"""Tests for knowledge graph entity/edge extraction and expansion."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.build import KnowledgeChunk
from app.models.knowledge_graph import KbEdge, KbEntity
from app.services.knowledge_graph_service import (
    expand_via_graph,
    extract_edges_from_text,
    sync_chunk_graph,
    upsert_entity,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_chunk(db, content: dict, chunk_type: str = "skill") -> KnowledgeChunk:
    kc = KnowledgeChunk(
        content=json.dumps(content, ensure_ascii=False),
        chunk_type=chunk_type,
        source="poe2db",
        stale=False,
    )
    db.add(kc)
    db.commit()
    db.refresh(kc)
    return kc


def test_sync_chunk_graph_creates_entity_and_mentions(db):
    chunk = _make_chunk(db, {
        "name_en": "Raise Zombie",
        "search_text": "Summons minions that fight for you. Minion skill.",
        "chunk_id": "skill_raise_zombie",
    })
    entity = sync_chunk_graph(db, chunk)
    db.commit()

    assert entity is not None
    assert entity.entity_type == "skill"
    assert db.query(KbEntity).count() >= 2  # skill + minion concept
    assert db.query(KbEdge).filter(KbEdge.relation == "mentions").count() >= 1


def test_expand_via_graph_returns_linked_chunks(db):
    skill_chunk = _make_chunk(db, {
        "name_en": "Summon Skeleton",
        "search_text": "Creates skeleton minions. Minion skill level bonus.",
    })
    wiki_chunk = _make_chunk(db, {
        "name_en": "Minion",
        "search_text": "Minions are allies that fight for you.",
    }, chunk_type="wiki")

    skill_entity = upsert_entity(
        db, "skill:Summon_Skeleton", "skill", name_en="Summon Skeleton", chunk_id=skill_chunk.id,
    )
    minion_entity = upsert_entity(
        db, "concept:minion", "mechanic", name_en="minion", chunk_id=wiki_chunk.id,
    )
    db.add(KbEdge(
        src_entity_id=skill_entity.id,
        dst_entity_id=minion_entity.id,
        relation="mentions",
        weight=1.0,
        source_chunk_id=skill_chunk.id,
    ))
    db.commit()

    expanded = expand_via_graph(db, [skill_chunk.id], max_hops=1, max_results=3)
    assert len(expanded) == 1
    assert expanded[0]["chunk_type"] == "wiki"
    assert "via_graph" in expanded[0]


def test_extract_edges_from_text_trade_concept(db):
    src = upsert_entity(db, "item:test_amulet", "item", name_en="Test Amulet")
    db.commit()
    count = extract_edges_from_text(
        db, src,
        "Amulet with +2 to Level of all Minion Skills",
        chunk_id=1,
    )
    db.commit()
    assert count >= 1
    effect = db.query(KbEntity).filter(KbEntity.entity_key.like("effect:%")).first()
    assert effect is not None
