from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Vote, VoteHistory, Voting, VotingCandidate


async def create_voting(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    starts_at: datetime,
    ends_at: datetime,
    candidates: Sequence[tuple[str, str | None]],
) -> Voting:
    voting = Voting(name=name, description=description, starts_at=starts_at, ends_at=ends_at, active=True)
    session.add(voting)
    await session.flush()
    for position, (candidate_name, candidate_description) in enumerate(candidates, start=1):
        session.add(
            VotingCandidate(
                voting_id=voting.id,
                name=candidate_name,
                description=candidate_description,
                position=position,
                active=True,
            )
        )
    await session.commit()
    return await get_voting(session, voting.id)


async def get_voting(session: AsyncSession, voting_id: int) -> Voting | None:
    result = await session.execute(
        select(Voting)
        .where(Voting.id == voting_id)
        .options(selectinload(Voting.candidates))
    )
    return result.scalar_one_or_none()


async def list_votings(session: AsyncSession) -> list[Voting]:
    result = await session.execute(
        select(Voting).options(selectinload(Voting.candidates)).order_by(Voting.id.desc())
    )
    return list(result.scalars().all())


async def get_candidate(session: AsyncSession, voting_id: int, candidate_id: int) -> VotingCandidate | None:
    result = await session.execute(
        select(VotingCandidate).where(
            VotingCandidate.id == candidate_id,
            VotingCandidate.voting_id == voting_id,
            VotingCandidate.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_vote(session: AsyncSession, voting_id: int, user_id: int, *, for_update: bool = False) -> Vote | None:
    stmt = (
        select(Vote)
        .where(Vote.voting_id == voting_id, Vote.user_id == user_id)
        .options(selectinload(Vote.candidate), selectinload(Vote.voting).selectinload(Voting.candidates))
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def save_vote(
    session: AsyncSession,
    *,
    voting: Voting,
    candidate: VotingCandidate,
    user_id: int,
    reason: str,
) -> tuple[Vote, bool]:
    vote = await get_vote(session, voting.id, user_id, for_update=True)
    if vote is None:
        vote = Vote(
            voting_id=voting.id,
            candidate_id=candidate.id,
            user_id=user_id,
            reason=reason,
        )
        session.add(vote)
        await session.commit()
        await session.refresh(vote)
        return vote, False

    changed = vote.candidate_id != candidate.id or vote.reason != reason
    if changed:
        session.add(
            VoteHistory(
                vote_id=vote.id,
                previous_candidate_id=vote.candidate_id,
                new_candidate_id=candidate.id,
                previous_reason=vote.reason,
                new_reason=reason,
            )
        )
        vote.candidate_id = candidate.id
        vote.reason = reason
        vote.change_count = int(vote.change_count or 0) + 1
        await session.commit()
        await session.refresh(vote)
    return vote, changed


async def voting_result_counts(session: AsyncSession, voting_id: int) -> list[tuple[VotingCandidate, int]]:
    result = await session.execute(
        select(VotingCandidate, func.count(Vote.id))
        .outerjoin(Vote, Vote.candidate_id == VotingCandidate.id)
        .where(VotingCandidate.voting_id == voting_id)
        .group_by(VotingCandidate.id)
        .order_by(func.count(Vote.id).desc(), VotingCandidate.position)
    )
    return [(candidate, int(count)) for candidate, count in result.all()]


async def list_votes_for_export(session: AsyncSession, voting_id: int) -> list[Vote]:
    result = await session.execute(
        select(Vote)
        .where(Vote.voting_id == voting_id)
        .options(selectinload(Vote.user), selectinload(Vote.candidate))
        .order_by(Vote.created_at)
    )
    return list(result.scalars().all())


async def list_vote_history_for_export(session: AsyncSession, voting_id: int) -> list[VoteHistory]:
    result = await session.execute(
        select(VoteHistory)
        .join(Vote, Vote.id == VoteHistory.vote_id)
        .where(Vote.voting_id == voting_id)
        .options(
            selectinload(VoteHistory.vote).selectinload(Vote.user),
            selectinload(VoteHistory.previous_candidate),
            selectinload(VoteHistory.new_candidate),
        )
        .order_by(VoteHistory.created_at)
    )
    return list(result.scalars().all())
