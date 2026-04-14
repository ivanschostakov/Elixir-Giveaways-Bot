"""giveaway winners

Revision ID: 6c1b5d839e2a
Revises: f27de0e6b6fd
Create Date: 2026-02-14 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6c1b5d839e2a"
down_revision: Union[str, Sequence[str], None] = "f27de0e6b6fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "giveaways",
        sa.Column(
            "winners",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("giveaways", "winners")
