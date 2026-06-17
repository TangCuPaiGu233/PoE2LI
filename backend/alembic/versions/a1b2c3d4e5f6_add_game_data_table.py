"""add game_data table

Revision ID: a1b2c3d4e5f6
Revises: f9a2c7e83d61
Create Date: 2026-06-17
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f9a2c7e83d61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if table already exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "game_data" in inspector.get_table_names():
        return

    op.create_table(
        "game_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("row_key", sa.String(256), nullable=False),
        sa.Column("name_en", sa.String(256), nullable=True),
        sa.Column("name_tc", sa.String(256), nullable=True),
        sa.Column("name_sc", sa.String(256), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="ggpk"),
        sa.Column("game_version", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_game_data_table_name", "game_data", ["table_name"])
    op.create_index("ix_game_data_name_en", "game_data", ["name_en"])
    op.create_index("ix_game_data_name_tc", "game_data", ["name_tc"])
    op.create_index("ix_game_data_name_sc", "game_data", ["name_sc"])
    op.create_index("ix_game_data_table_key", "game_data", ["table_name", "row_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_game_data_table_key", table_name="game_data")
    op.drop_index("ix_game_data_name_sc", table_name="game_data")
    op.drop_index("ix_game_data_name_tc", table_name="game_data")
    op.drop_index("ix_game_data_name_en", table_name="game_data")
    op.drop_index("ix_game_data_table_name", table_name="game_data")
    op.drop_table("game_data")
