from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import UFA_TZ
from src.database import Base, IdPkMixin, TimestampMixin


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UFA_TZ)
    return value.astimezone(UFA_TZ)


class Voting(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "votings"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    candidates: Mapped[list["VotingCandidate"]] = relationship(
        back_populates="voting",
        cascade="all, delete-orphan",
        order_by="VotingCandidate.position",
    )
    votes: Mapped[list["Vote"]] = relationship(back_populates="voting", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ck_votings_dates"),)

    @property
    def change_deadline(self) -> datetime:
        return _aware(self.ends_at) - timedelta(days=3)

    def accepts_votes(self, now: datetime | None = None) -> bool:
        current = _aware(now or datetime.now(tz=UFA_TZ))
        return bool(self.active and _aware(self.starts_at) <= current < _aware(self.ends_at))

    def allows_changes(self, now: datetime | None = None) -> bool:
        current = _aware(now or datetime.now(tz=UFA_TZ))
        return self.accepts_votes(current) and current < self.change_deadline


class VotingCandidate(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "voting_candidates"

    voting_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("votings.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    voting: Mapped["Voting"] = relationship(back_populates="candidates")
    votes: Mapped[list["Vote"]] = relationship(back_populates="candidate")

    __table_args__ = (
        UniqueConstraint("voting_id", "position", name="uq_voting_candidates_position"),
        UniqueConstraint("voting_id", "name", name="uq_voting_candidates_name"),
    )


class Vote(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "votes"

    voting_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("votings.id", ondelete="CASCADE"), index=True, nullable=False)
    candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("voting_candidates.id", ondelete="RESTRICT"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    voting: Mapped["Voting"] = relationship(back_populates="votes")
    candidate: Mapped["VotingCandidate"] = relationship(back_populates="votes")
    user: Mapped["User"] = relationship()
    history: Mapped[list["VoteHistory"]] = relationship(back_populates="vote", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("voting_id", "user_id", name="uq_votes_voting_user"),)


class VoteHistory(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "vote_history"

    vote_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("votes.id", ondelete="CASCADE"), index=True, nullable=False)
    previous_candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("voting_candidates.id", ondelete="RESTRICT"), nullable=False)
    new_candidate_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("voting_candidates.id", ondelete="RESTRICT"), nullable=False)
    previous_reason: Mapped[str] = mapped_column(Text, nullable=False)
    new_reason: Mapped[str] = mapped_column(Text, nullable=False)

    vote: Mapped["Vote"] = relationship(back_populates="history")
    previous_candidate: Mapped["VotingCandidate"] = relationship(foreign_keys=[previous_candidate_id])
    new_candidate: Mapped["VotingCandidate"] = relationship(foreign_keys=[new_candidate_id])
