"""Lightweight knowledge graph tables for multi-hop RAG expansion."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.core.database import Base


class KbEntity(Base):
    """Normalized game entity linked to a representative knowledge chunk."""

    __tablename__ = "kb_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_key = Column(String(256), unique=True, nullable=False, index=True)
    entity_type = Column(String(32), nullable=False)  # skill/item/mod/gem/minion/mechanic/keyword
    name_en = Column(String(256), nullable=True)
    name_cn = Column(String(256), nullable=True)
    aliases = Column(Text, nullable=True)  # JSON array of alias strings
    chunk_id = Column(Integer, ForeignKey("knowledge_chunks.id"), nullable=True)
    league = Column(String(64), nullable=True)
    game_version = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KbEdge(Base):
    """Typed relationship between two kb_entities."""

    __tablename__ = "kb_edges"
    __table_args__ = (
        UniqueConstraint("src_entity_id", "dst_entity_id", "relation", name="uq_kb_edge"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    src_entity_id = Column(Integer, ForeignKey("kb_entities.id"), nullable=False, index=True)
    dst_entity_id = Column(Integer, ForeignKey("kb_entities.id"), nullable=False, index=True)
    relation = Column(String(32), nullable=False)  # mentions/grants/is_a/scales_with/provided_by
    weight = Column(Float, default=1.0)
    source_chunk_id = Column(Integer, ForeignKey("knowledge_chunks.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
