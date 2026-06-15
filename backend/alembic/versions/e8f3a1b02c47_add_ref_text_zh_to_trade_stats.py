"""Add ref_text_zh to trade_stats for CN stat labels."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e8f3a1b02c47"
down_revision: Union[str, Sequence[str], None] = "d7e1b4c92f58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trade_stats", sa.Column("ref_text_zh", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("trade_stats", "ref_text_zh")
