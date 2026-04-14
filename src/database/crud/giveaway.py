from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Condition, Giveaway, Participant, ParticipantRecord
from src.database.schemas.giveaway import GiveawayCreate, GiveawayUpdate


async def create_giveaway(session: AsyncSession, data: GiveawayCreate | dict[str, Any]) -> Giveaway:
    payload = data.model_dump() if isinstance(data, GiveawayCreate) else data
    giveaway = Giveaway(**payload)
    session.add(giveaway)
    await session.commit()
    await session.refresh(giveaway)
    return giveaway

async def get_giveaway(session: AsyncSession, giveaway_id: int) -> Giveaway | None: return await session.get(Giveaway, giveaway_id)
async def get_giveaway_with_relations(session: AsyncSession, giveaway_id: int) -> Giveaway | None:
    result = await session.execute(select(Giveaway).where(Giveaway.id == giveaway_id).options(selectinload(Giveaway.conditions).selectinload(Condition.records), selectinload(Giveaway.participants).selectinload(Participant.user), selectinload(Giveaway.participants).selectinload(Participant.records).selectinload(ParticipantRecord.condition)))
    return result.scalar_one_or_none()


async def list_giveaways(session: AsyncSession, *, offset: int | None = None, limit: int | None = None) -> list[Giveaway]:
    stmt = select(Giveaway).order_by(Giveaway.id)
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_giveaways_with_relations(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[Giveaway]:
    stmt = (select(Giveaway).options(selectinload(Giveaway.conditions).selectinload(Condition.records), selectinload(Giveaway.participants).selectinload(Participant.user), selectinload(Giveaway.participants).selectinload(Participant.records).selectinload(ParticipantRecord.condition)).order_by(Giveaway.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_giveaway(session: AsyncSession, giveaway: Giveaway, data: GiveawayUpdate) -> Giveaway:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items(): setattr(giveaway, field, value)
    await session.commit()
    await session.refresh(giveaway)
    return giveaway


async def delete_giveaway(session: AsyncSession, giveaway: Giveaway) -> None:
    await session.delete(giveaway)
    await session.commit()
