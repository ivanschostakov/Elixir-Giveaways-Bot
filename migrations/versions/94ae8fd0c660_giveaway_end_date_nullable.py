"""giveaway_end_date_nullable

Revision ID: 94ae8fd0c660
Revises: 6c1b5d839e2a
Create Date: 2026-02-16 16:25:58.060136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '94ae8fd0c660'
down_revision: Union[str, Sequence[str], None] = '6c1b5d839e2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "giveaways",
        "end_date",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(sa.text("UPDATE giveaways SET end_date = start_date WHERE end_date IS NULL"))
    op.alter_column(
        "giveaways",
        "end_date",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
