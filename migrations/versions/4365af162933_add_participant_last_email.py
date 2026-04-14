"""add_participant_last_email

Revision ID: 4365af162933
Revises: 5a39fd3142dd
Create Date: 2026-02-19 10:22:07.636012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4365af162933'
down_revision: Union[str, Sequence[str], None] = '5a39fd3142dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("participants", sa.Column("last_email", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("participants", "last_email")
