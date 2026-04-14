"""giveaway dates to date

Revision ID: b5276b5d8e2e
Revises: 94ae8fd0c660
Create Date: 2026-02-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5276b5d8e2e"
down_revision: Union[str, Sequence[str], None] = "94ae8fd0c660"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "giveaways",
        "start_date",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        nullable=False,
        postgresql_using="(start_date AT TIME ZONE 'Asia/Yekaterinburg')::date",
    )
    op.alter_column(
        "giveaways",
        "end_date",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        nullable=True,
        postgresql_using="(end_date AT TIME ZONE 'Asia/Yekaterinburg')::date",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "giveaways",
        "start_date",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        nullable=False,
        postgresql_using="(start_date::timestamp AT TIME ZONE 'Asia/Yekaterinburg')",
    )
    op.alter_column(
        "giveaways",
        "end_date",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        nullable=True,
        postgresql_using="(end_date::timestamp AT TIME ZONE 'Asia/Yekaterinburg')",
    )
