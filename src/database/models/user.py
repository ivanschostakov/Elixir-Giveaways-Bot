from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True, autoincrement=False)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True, default=None)
    phone: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True, default=None)

    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    participants: Mapped[list["Participant"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )