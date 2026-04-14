from typing import Any

from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Participant, User
from src.database.schemas.user import UserCreate, UserUpdate


async def create_user(session: AsyncSession, data: UserCreate | dict[str, Any]) -> User:
    payload = data.model_dump() if isinstance(data, UserCreate) else data
    user = User(**payload)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None: return await session.get(User, user_id)
async def get_user_with_relations(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id).options(selectinload(User.participants).selectinload(Participant.giveaway), selectinload(User.participants).selectinload(Participant.records)))
    return result.scalar_one_or_none()


async def get_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    result = await session.execute(select(User).where(User.phone == phone))
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[User]:
    stmt = select(User).order_by(User.id)
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_users_with_relations(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[User]:
    stmt = (select(User).options(selectinload(User.participants).selectinload(Participant.giveaway), selectinload(User.participants).selectinload(Participant.records)).order_by(User.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_user(session: AsyncSession, user: User, data: UserUpdate) -> User:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items(): setattr(user, field, value)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()


def _resolve_actor_payload(message_or_call: Message | CallbackQuery) -> tuple[int, str | None, str | None]:
    if isinstance(message_or_call, Message):
        user_id = int(message_or_call.chat.id)
        first_name = getattr(message_or_call.chat, "first_name", None)
        last_name = getattr(message_or_call.chat, "last_name", None)
        if message_or_call.from_user is not None:
            first_name = first_name or message_or_call.from_user.first_name
            last_name = last_name or message_or_call.from_user.last_name
        return user_id, first_name, last_name

    tg_user = message_or_call.from_user
    return int(tg_user.id), tg_user.first_name, tg_user.last_name


async def ensure_user(session, message_or_call: Message | CallbackQuery):
    user_id, first_name, last_name = _resolve_actor_payload(message_or_call)
    user = await get_user(session, user_id)
    if user is None: return await create_user(session, UserCreate(id=user_id, first_name=first_name, last_name=last_name))
    if user.first_name != first_name or user.last_name != last_name: return await update_user(session, user, UserUpdate(first_name=first_name, last_name=last_name))
    return user
