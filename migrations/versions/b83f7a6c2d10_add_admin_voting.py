"""add administrator voting

Revision ID: b83f7a6c2d10
Revises: 9fa2c7d9b561
Create Date: 2026-09-09 11:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b83f7a6c2d10"
down_revision: Union[str, Sequence[str], None] = "9fa2c7d9b561"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "votings",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_votings_dates"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_votings_id"), "votings", ["id"], unique=False)

    op.create_table(
        "voting_candidates",
        sa.Column("voting_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["voting_id"], ["votings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voting_id", "name", name="uq_voting_candidates_name"),
        sa.UniqueConstraint("voting_id", "position", name="uq_voting_candidates_position"),
    )
    op.create_index(op.f("ix_voting_candidates_id"), "voting_candidates", ["id"], unique=False)
    op.create_index(op.f("ix_voting_candidates_voting_id"), "voting_candidates", ["voting_id"], unique=False)

    op.create_table(
        "votes",
        sa.Column("voting_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["voting_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voting_id"], ["votings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("voting_id", "user_id", name="uq_votes_voting_user"),
    )
    op.create_index(op.f("ix_votes_candidate_id"), "votes", ["candidate_id"], unique=False)
    op.create_index(op.f("ix_votes_id"), "votes", ["id"], unique=False)
    op.create_index(op.f("ix_votes_user_id"), "votes", ["user_id"], unique=False)
    op.create_index(op.f("ix_votes_voting_id"), "votes", ["voting_id"], unique=False)

    op.create_table(
        "vote_history",
        sa.Column("vote_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("new_candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_reason", sa.Text(), nullable=False),
        sa.Column("new_reason", sa.Text(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["new_candidate_id"], ["voting_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_candidate_id"], ["voting_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vote_id"], ["votes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vote_history_id"), "vote_history", ["id"], unique=False)
    op.create_index(op.f("ix_vote_history_vote_id"), "vote_history", ["vote_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_vote_history_vote_id"), table_name="vote_history")
    op.drop_index(op.f("ix_vote_history_id"), table_name="vote_history")
    op.drop_table("vote_history")
    op.drop_index(op.f("ix_votes_voting_id"), table_name="votes")
    op.drop_index(op.f("ix_votes_user_id"), table_name="votes")
    op.drop_index(op.f("ix_votes_id"), table_name="votes")
    op.drop_index(op.f("ix_votes_candidate_id"), table_name="votes")
    op.drop_table("votes")
    op.drop_index(op.f("ix_voting_candidates_voting_id"), table_name="voting_candidates")
    op.drop_index(op.f("ix_voting_candidates_id"), table_name="voting_candidates")
    op.drop_table("voting_candidates")
    op.drop_index(op.f("ix_votings_id"), table_name="votings")
    op.drop_table("votings")
