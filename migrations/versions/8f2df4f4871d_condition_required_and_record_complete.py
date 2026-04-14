"""condition required and participant record complete

Revision ID: 8f2df4f4871d
Revises: 43b9a5f2d1ac
Create Date: 2026-02-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f2df4f4871d"
down_revision: Union[str, Sequence[str], None] = "43b9a5f2d1ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "conditions",
        sa.Column("required", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "participant_records",
        sa.Column("complete", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("participant_records", "complete")
    op.drop_column("conditions", "required")
