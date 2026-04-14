from contextlib import asynccontextmanager
from datetime import datetime
from sqlalchemy import DateTime, func, BigInteger
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import ASYNC_DB_URL

class Base(DeclarativeBase): pass
class IdPkMixin: id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, index=True)
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

engine: AsyncEngine = create_async_engine(ASYNC_DB_URL, echo=False, pool_pre_ping=True)
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)

@asynccontextmanager
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        try: yield session
        except Exception:
            await session.rollback()
            raise
        finally: await session.close()
