"""condition mandatory repeatable reward

Revision ID: f27de0e6b6fd
Revises: 8f2df4f4871d
Create Date: 2026-02-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f27de0e6b6fd"
down_revision: Union[str, Sequence[str], None] = "8f2df4f4871d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "conditions",
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "conditions",
        sa.Column("repeatable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "conditions",
        sa.Column("reward", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_conditions_repeatable_reward",
        "conditions",
        "NOT repeatable OR reward IS NOT NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_conditions_repeatable_reward", "conditions", type_="check")
    op.drop_column("conditions", "reward")
    op.drop_column("conditions", "repeatable")
    op.drop_column("conditions", "mandatory")
