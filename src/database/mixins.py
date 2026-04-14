from datetime import datetime

from sqlalchemy import DateTime, func, BigInteger
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

class IdPkMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, index=True)