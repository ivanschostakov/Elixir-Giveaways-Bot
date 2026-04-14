from typing import Any
from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from src.database import Base, IdPkMixin, TimestampMixin


class ParticipantRecord(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "participant_records"

    participant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("participants.id", ondelete="CASCADE"), index=True, nullable=False)
    condition_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conditions.id", ondelete="CASCADE"), index=True, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    complete: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    participant: Mapped["Participant"] = relationship(back_populates="records")
    condition: Mapped["Condition"] = relationship(back_populates="records")

    @property
    def action(self) -> str | None:
        if self.condition is None: return None
        return self.condition.action

    @property
    def times_complete(self) -> int | None: return self.complete // self.condition.required if self.condition else None

    __table_args__ = (
        UniqueConstraint("participant_id", "condition_id", name="uq_participant_condition"),
    )
