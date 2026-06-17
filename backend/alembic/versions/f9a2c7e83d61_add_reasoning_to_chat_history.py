"""Add reasoning column to chat_history

Revision ID: f9a2c7e83d61
Revises: e8f3a1b02c47
Create Date: 2026-06-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9a2c7e83d61"
down_revision: Union[str, Sequence[str], None] = "e8f3a1b02c47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add reasoning column to chat_history table.

    The chat_history table was created outside Alembic (via raw SQL in
    chat_agent._save_chat_history), so we guard with IF NOT EXISTS checks
    to handle both fresh and existing deployments safely.
    """
    # Ensure the table exists (idempotent — no-op if already present)
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id          SERIAL PRIMARY KEY,
            thread_id   VARCHAR(32) NOT NULL,
            role        VARCHAR(16) NOT NULL,
            content     TEXT NOT NULL,
            tool_calls  JSONB,
            reasoning   TEXT,
            created_at  TIMESTAMP DEFAULT NOW()
        )
    """)
    # Add reasoning column if table existed before but lacks the column
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'chat_history' AND column_name = 'reasoning'
            ) THEN
                ALTER TABLE chat_history ADD COLUMN reasoning TEXT;
            END IF;
        END $$;
    """)
    # Index for thread-based lookups
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_history_thread_id
        ON chat_history (thread_id)
    """)


def downgrade() -> None:
    """Remove reasoning column."""
    op.execute("ALTER TABLE chat_history DROP COLUMN IF EXISTS reasoning")
