from typing import Any
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Condition, Participant, ParticipantRecord
from src.database.schemas.participant_record import ParticipantRecordCreate, ParticipantRecordUpdate


async def create_participant_record(session: AsyncSession, data: ParticipantRecordCreate | dict[str, Any]) -> ParticipantRecord:
    payload = data.model_dump() if isinstance(data, ParticipantRecordCreate) else data
    participant_record = ParticipantRecord(**payload)
    session.add(participant_record)
    await session.commit()
    await session.refresh(participant_record)
    return participant_record


async def get_participant_record(session: AsyncSession, participant_record_id: int) -> ParticipantRecord | None: return await session.get(ParticipantRecord, participant_record_id)
async def get_participant_record_with_relations(session: AsyncSession, participant_record_id: int) -> ParticipantRecord | None:
    result = await session.execute(select(ParticipantRecord).where(ParticipantRecord.id == participant_record_id).options(selectinload(ParticipantRecord.participant).selectinload(Participant.user), selectinload(ParticipantRecord.participant).selectinload(Participant.giveaway), selectinload(ParticipantRecord.condition).selectinload(Condition.giveaway)))
    return result.scalar_one_or_none()


async def get_participant_record_by_condition(session: AsyncSession, participant_id: int, condition_id: int) -> ParticipantRecord | None:
    result = await session.execute(select(ParticipantRecord).where(ParticipantRecord.participant_id == participant_id, ParticipantRecord.condition_id == condition_id))
    return result.scalar_one_or_none()


async def list_participant_records(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[ParticipantRecord]:
    stmt = select(ParticipantRecord).order_by(ParticipantRecord.id)
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_participant_records_with_relations(session: AsyncSession, offset: int | None = None, limit: int | None = None) -> list[ParticipantRecord]:
    stmt = (select(ParticipantRecord).options(selectinload(ParticipantRecord.participant).selectinload(Participant.user), selectinload(ParticipantRecord.participant).selectinload(Participant.giveaway), selectinload(ParticipantRecord.condition).selectinload(Condition.giveaway)).order_by(ParticipantRecord.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_records_by_participant(session: AsyncSession, participant_id: int, offset: int | None = None, limit: int | None = None) -> list[ParticipantRecord]:
    stmt = (select(ParticipantRecord).where(ParticipantRecord.participant_id == participant_id).order_by(ParticipantRecord.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_records_by_condition(session: AsyncSession, condition_id: int, offset: int | None = None, limit: int | None = None) -> list[ParticipantRecord]:
    stmt = (select(ParticipantRecord).where(ParticipantRecord.condition_id == condition_id).order_by(ParticipantRecord.id))
    if offset: stmt = stmt.offset(offset)
    if limit: stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_participant_record(session: AsyncSession, participant_record: ParticipantRecord, data: ParticipantRecordUpdate) -> ParticipantRecord:
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items(): setattr(participant_record, field, value)
    await session.commit()
    await session.refresh(participant_record)
    return participant_record


async def delete_participant_record(session: AsyncSession, participant_record: ParticipantRecord) -> None:
    await session.delete(participant_record)
    await session.commit()


async def upsert_participant_record(session: AsyncSession, *, participant_id: int, condition_id: int, passed: bool, complete: int, config: dict) -> None:
    stmt = insert(ParticipantRecord).values(participant_id=participant_id, condition_id=condition_id, passed=passed, complete=complete, config=config)
    stmt = stmt.on_conflict_do_update(index_elements=[ParticipantRecord.participant_id, ParticipantRecord.condition_id], set_={"passed": passed, "complete": complete, "config": config})
    await session.execute(stmt)
    await session.commit()
