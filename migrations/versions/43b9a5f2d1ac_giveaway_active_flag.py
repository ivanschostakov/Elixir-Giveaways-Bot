"""giveaway active flag

Revision ID: 43b9a5f2d1ac
Revises: cd6988460967
Create Date: 2026-02-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "43b9a5f2d1ac"
down_revision: Union[str, Sequence[str], None] = "cd6988460967"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "giveaways",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("giveaways", "active")
