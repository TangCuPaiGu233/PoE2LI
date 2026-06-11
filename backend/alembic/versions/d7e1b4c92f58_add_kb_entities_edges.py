"""Add kb_entities and kb_edges for knowledge graph expansion

Revision ID: d7e1b4c92f58
Revises: c5f2a8d91e03
Create Date: 2026-06-11 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e1b4c92f58"
down_revision: Union[str, Sequence[str], None] = "c5f2a8d91e03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kb_entities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_key", sa.String(length=256), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name_en", sa.String(length=256), nullable=True),
        sa.Column("name_cn", sa.String(length=256), nullable=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("chunk_id", sa.Integer(), nullable=True),
        sa.Column("league", sa.String(length=64), nullable=True),
        sa.Column("game_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_key"),
    )
    op.create_index("ix_kb_entities_entity_key", "kb_entities", ["entity_key"])

    op.create_table(
        "kb_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("src_entity_id", sa.Integer(), nullable=False),
        sa.Column("dst_entity_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("source_chunk_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["src_entity_id"], ["kb_entities.id"]),
        sa.ForeignKeyConstraint(["dst_entity_id"], ["kb_entities.id"]),
        sa.ForeignKeyConstraint(["source_chunk_id"], ["knowledge_chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("src_entity_id", "dst_entity_id", "relation", name="uq_kb_edge"),
    )
    op.create_index("ix_kb_edges_src_entity_id", "kb_edges", ["src_entity_id"])
    op.create_index("ix_kb_edges_dst_entity_id", "kb_edges", ["dst_entity_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_edges_dst_entity_id", table_name="kb_edges")
    op.drop_index("ix_kb_edges_src_entity_id", table_name="kb_edges")
    op.drop_table("kb_edges")
    op.drop_index("ix_kb_entities_entity_key", table_name="kb_entities")
    op.drop_table("kb_entities")
