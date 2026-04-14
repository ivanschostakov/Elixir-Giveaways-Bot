from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship, mapped_column

from src.database import Base, IdPkMixin, TimestampMixin


class Participant(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "participants"

    giveaway_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("giveaways.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    last_email: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["User"] = relationship(back_populates="participants")
    giveaway: Mapped["Giveaway"] = relationship(back_populates="participants")
    records: Mapped[list["ParticipantRecord"]] = relationship(
        back_populates="participant",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("giveaway_id", "user_id", name="uq_participants_giveaway_user"),
    )
