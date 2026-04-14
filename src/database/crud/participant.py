from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Condition, Giveaway, Participant, ParticipantRecord
from src.database.schemas.participant import ParticipantCreate, ParticipantUpdate


async def create_participant(session: AsyncSession, data: ParticipantCreate | dict[str, Any]) -> Participant:
    payload = data.model_dump() if isinstance(data, ParticipantCreate) else data
    participant = Participant(**payload)
    session.add(participant)
    await session.commit()
    await session.refresh(participant)
    return participant


async def get_participant(session: AsyncSession, participant_id: int) -> Participant | None: return await session.get(Participant, participant_id)
async def get_participant_with_relations(session: AsyncSession, participant_id: int) -> Participant | None:
    result = await session.execute(select(Participant).where(Participant.id == participant_id).options(selectinload(Participant.user), selectinload(Participant.giveaway), selectinload(Participant.records).selectinload(ParticipantRecord.condition)))
    return result.scalar_one_or_none()


async def get_participant_by_giveaway_user(session: AsyncSession, giveaway_id: int, user_id: int) -> Participant | None:
    result = await session.execute(select(Participant).where(Participant.giveaway_id == giveaway_id, Participant.user_id == user_id))
    return result.scalar_one_or_none()


async def list_participants(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[Participant]:
    stmt = select(Participant).order_by(Participant.id)
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_participants_with_relations(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[Participant]:
    stmt = (select(Participant).options(selectinload(Participant.user), selectinload(Participant.giveaway), selectinload(Participant.records).selectinload(ParticipantRecord.condition)).order_by(Participant.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_giveaway_participants(session: AsyncSession, giveaway_id: int, offset: int | None = None, limit: int | None = None) -> list[Participant]:
    stmt = (select(Participant).where(Participant.giveaway_id == giveaway_id).order_by(Participant.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_user_participations(session: AsyncSession, user_id: int, offset: int | None = None, limit: int | None = None) -> list[Participant]:
    stmt = (select(Participant).where(Participant.user_id == user_id).order_by(Participant.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_participant_tickets(session: AsyncSession, participant_id: int) -> int:
    participant_result = await session.execute(
        select(Participant)
        .where(Participant.id == participant_id)
        .options(
            selectinload(Participant.records).selectinload(ParticipantRecord.condition),
            selectinload(Participant.giveaway).selectinload(Giveaway.conditions),
        )
    )
    participant = participant_result.scalar_one_or_none()
    if participant is None:
        return 0

    records_map = {record.condition_id: record for record in (participant.records or [])}
    conditions = list((participant.giveaway.conditions or []) if participant.giveaway is not None else [])
    passed_conditions = 0
    reward_tickets = 0

    for condition in conditions:
        record = records_map.get(condition.id)
        if record is not None and record.passed:
            passed_conditions += 1
        if condition.reward is None or record is None:
            continue

        complete = max(int(record.complete or 0), 0)
        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        counted = complete if max_repeats is None else min(complete, max_repeats)
        if counted > 0:
            reward_tickets += counted * int(condition.reward)

    total_conditions = len(conditions)
    base_ticket = 1 if total_conditions == 0 or passed_conditions >= total_conditions else 0
    return base_ticket + max(reward_tickets, 0)


async def update_participant(session: AsyncSession, participant: Participant, data: ParticipantUpdate) -> Participant:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items(): setattr(participant, field, value)
    await session.commit()
    await session.refresh(participant)
    return participant


async def delete_participant(session: AsyncSession, participant: Participant) -> None:
    await session.delete(participant)
    await session.commit()
