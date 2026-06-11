"""Add links column to knowledge_chunks for concept graph pointers

Revision ID: c5f2a8d91e03
Revises: b4d8e3f12c56
Create Date: 2026-06-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5f2a8d91e03"
down_revision: Union[str, Sequence[str], None] = "b4d8e3f12c56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("knowledge_chunks")}
    if "links" not in columns:
        op.add_column("knowledge_chunks", sa.Column("links", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("knowledge_chunks")}
    if "links" in columns:
        op.drop_column("knowledge_chunks", "links")
