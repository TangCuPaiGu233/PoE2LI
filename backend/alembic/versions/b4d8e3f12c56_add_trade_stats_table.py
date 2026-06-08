"""Add trade_stats table for vector-based trade stat matching

Revision ID: b4d8e3f12c56
Revises: a3c7e2f81b45
Create Date: 2026-06-08 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = 'b4d8e3f12c56'
down_revision: Union[str, Sequence[str], None] = 'a3c7e2f81b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trade_stats',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('stat_id', sa.String(length=128), nullable=False),
        sa.Column('ref_text', sa.Text(), nullable=False),
        sa.Column('stat_type', sa.String(length=16), nullable=True),
        sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trade_stats_stat_id', 'trade_stats', ['stat_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_trade_stats_stat_id', table_name='trade_stats')
    op.drop_table('trade_stats')
