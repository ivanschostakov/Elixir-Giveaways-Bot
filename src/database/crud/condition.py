from typing import Any
from sqlalchemy import select, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Condition, ParticipantRecord
from src.database.schemas.condition import ConditionCreate, ConditionUpdate


def _validate_repeatable_reward(condition: Condition) -> None:
    if condition.repeatable and (condition.reward is None or condition.reward <= 0):
        raise ValueError("repeatable condition must have positive reward set")


async def create_condition(session: AsyncSession, data: ConditionCreate | dict[str, Any]) -> Condition:
    payload = data.model_dump() if isinstance(data, ConditionCreate) else data
    condition = Condition(**payload)
    _validate_repeatable_reward(condition)
    session.add(condition)
    await session.commit()
    await session.refresh(condition)
    return condition


async def get_condition(session: AsyncSession, condition_id: int) -> Condition | None: return await session.get(Condition, condition_id)
async def get_condition_with_relations(session: AsyncSession, condition_id: int) -> Condition | None:
    result = await session.execute(select(Condition).where(Condition.id == condition_id).options(selectinload(Condition.giveaway), selectinload(Condition.records).selectinload(ParticipantRecord.participant)))
    return result.scalar_one_or_none()


async def list_conditions(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[Condition]:
    stmt = select(Condition).order_by(Condition.id)
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_conditions_with_relations(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[Condition]:
    stmt = (select(Condition).options(selectinload(Condition.giveaway), selectinload(Condition.records).selectinload(ParticipantRecord.participant)).order_by(Condition.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_giveaway_conditions(session: AsyncSession, giveaway_id: int, offset: int | None = None, limit: int | None = None,) -> list[Condition]:
    stmt = select(Condition).where(Condition.giveaway_id == giveaway_id).order_by(Condition.id)
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_condition(session: AsyncSession, condition: Condition, data: ConditionUpdate) -> Condition:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items(): setattr(condition, field, value)
    _validate_repeatable_reward(condition)
    await session.commit()
    await session.refresh(condition)
    return condition


async def delete_condition(session: AsyncSession, condition: Condition) -> None:
    await session.delete(condition)
    await session.commit()
