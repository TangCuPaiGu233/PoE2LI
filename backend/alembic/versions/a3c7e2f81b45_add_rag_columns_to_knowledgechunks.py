"""Add build_id, chunk_type, and stale columns to knowledge_chunks

Revision ID: a3c7e2f81b45
Revises: 09304a65a604
Create Date: 2026-06-07 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c7e2f81b45'
down_revision: Union[str, Sequence[str], None] = '09304a65a604'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add RAG support columns to knowledge_chunks."""
    op.add_column('knowledge_chunks', sa.Column('build_id', sa.Integer(), nullable=True))
    op.add_column('knowledge_chunks', sa.Column('chunk_type', sa.String(length=32), nullable=True))
    op.add_column('knowledge_chunks', sa.Column('stale', sa.Boolean(), server_default='false', nullable=True))


def downgrade() -> None:
    """Downgrade schema — remove RAG support columns."""
    op.drop_column('knowledge_chunks', 'stale')
    op.drop_column('knowledge_chunks', 'chunk_type')
    op.drop_column('knowledge_chunks', 'build_id')
