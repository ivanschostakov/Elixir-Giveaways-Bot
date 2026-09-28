import logging
import re
from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError

from config import DATETIME_FORMAT, UFA_TZ
from src.bot.keyboards import voting_keyboards
from src.bot.states import voting_states
from src.database import get_session
from src.database.crud import get_candidate, get_vote, get_voting, save_vote
from src.database.crud.user import ensure_user


logger = logging.getLogger("voting_user_router")
voting_user_router = Router(name="voting_user")
voting_user_router.message.filter(lambda message: message.chat.type == ChatType.PRIVATE)
voting_user_router.callback_query.filter(
    lambda call: bool(call.message and call.message.chat.type == ChatType.PRIVATE)
)

VOTE_PAYLOAD_RE = re.compile(r"^vote_(\d+)_(\d+)$")
VOTE_START_RE = re.compile(r"^/start(?:@\w+)?\s+vote_\d+_\d+$")
MIN_REASON_LENGTH = 10
MAX_REASON_LENGTH = 1000


def _is_vote_start(message: Message) -> bool:
    return bool(VOTE_START_RE.fullmatch((message.text or "").strip()))


def _format_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UFA_TZ)
    return value.astimezone(UFA_TZ).strftime(DATETIME_FORMAT)


def _voting_unavailable_text(voting) -> str:
    now = datetime.now(tz=UFA_TZ)
    if not voting.active:
        return "Это голосование закрыто администратором."
    starts_at = voting.starts_at if voting.starts_at.tzinfo else voting.starts_at.replace(tzinfo=UFA_TZ)
    if now < starts_at.astimezone(UFA_TZ):
        return f"Голосование начнётся {_format_dt(voting.starts_at)}."
    return f"Голосование завершилось {_format_dt(voting.ends_at)}."


async def _begin_reason(
    message: Message,
    state: FSMContext,
    *,
    voting_id: int,
    candidate_id: int,
) -> None:
    async with get_session() as session:
        voting = await get_voting(session, voting_id)
        candidate = await get_candidate(session, voting_id, candidate_id)
        existing = await get_vote(session, voting_id, message.chat.id)

    if voting is None or candidate is None:
        await state.clear()
        await message.answer("Голосование или кандидат не найдены.")
        return
    if not voting.accepts_votes():
        await state.clear()
        await message.answer(_voting_unavailable_text(voting))
        return
    if existing is not None and not voting.allows_changes():
        await state.clear()
        await _show_existing_vote(message, existing)
        return

    await state.clear()
    await state.set_state(voting_states.VoteFlow.reason)
    await state.update_data(voting_id=voting.id, candidate_id=candidate.id)
    details = f"\n\n<i>{escape(candidate.description)}</i>" if candidate.description else ""
    await message.answer(
        f"Вы выбрали <b>{escape(candidate.name)}</b>.{details}\n\n"
        "Напишите, почему вы голосуете именно за этого администратора. "
        f"Причина должна содержать от {MIN_REASON_LENGTH} до {MAX_REASON_LENGTH} символов."
    )


async def _show_existing_vote(message: Message, vote) -> None:
    voting = vote.voting
    can_change = voting.allows_changes()
    if can_change:
        deadline = _format_dt(voting.change_deadline)
        footer = f"Изменить кандидата или причину можно до <b>{deadline}</b>."
    elif voting.accepts_votes():
        footer = "Период изменения голосов завершён. Ваш выбор зафиксирован."
    else:
        footer = "Голосование завершено. Ваш выбор зафиксирован."

    await message.answer(
        f"Вы уже проголосовали за <b>{escape(vote.candidate.name)}</b>.\n\n"
        f"Причина: <i>{escape(vote.reason)}</i>\n\n{footer}",
        reply_markup=voting_keyboards.existing_vote(vote, can_change=can_change),
    )


async def _show_voting_entry(message: Message, *, voting_id: int, user_id: int) -> None:
    async with get_session() as session:
        voting = await get_voting(session, voting_id)
        vote = await get_vote(session, voting_id, user_id)

    if voting is None:
        await message.answer("Голосование не найдено.")
        return
    if vote is not None:
        await _show_existing_vote(message, vote)
        return
    if not voting.accepts_votes():
        await message.answer(_voting_unavailable_text(voting))
        return

    description = f"\n\n{escape(voting.description)}" if voting.description else ""
    await message.answer(
        f"🏆 <b>{escape(voting.name)}</b>{description}\n\n"
        "Выберите администратора, за которого хотите проголосовать:",
        reply_markup=voting_keyboards.candidates(voting),
    )


@voting_user_router.message(CommandStart(deep_link=True), _is_vote_start)
async def handle_vote_start(message: Message, command: CommandObject, state: FSMContext):
    match = VOTE_PAYLOAD_RE.fullmatch((command.args or "").strip())
    if match is None:
        return
    voting_id, candidate_id = map(int, match.groups())
    await state.clear()
    async with get_session() as session:
        await ensure_user(session, message)
        voting = await get_voting(session, voting_id)
        candidate = await get_candidate(session, voting_id, candidate_id)
        vote = await get_vote(session, voting_id, message.chat.id)

    if voting is None or candidate is None:
        return await message.answer("Ссылка для голосования недействительна.")
    if vote is not None:
        return await _show_existing_vote(message, vote)
    if not voting.accepts_votes():
        return await message.answer(_voting_unavailable_text(voting))
    return await _begin_reason(
        message,
        state,
        voting_id=voting_id,
        candidate_id=candidate_id,
    )


@voting_user_router.callback_query(F.data.startswith("vote:"))
async def handle_vote_callback(call: CallbackQuery, state: FSMContext):
    data = (call.data or "").split(":")
    action = data[1] if len(data) > 1 else ""

    if action == "open" and len(data) == 3:
        try:
            voting_id = int(data[2])
        except ValueError:
            return await call.answer("Некорректное голосование.", show_alert=True)
        await state.clear()
        await call.answer()
        return await _show_voting_entry(
            call.message,
            voting_id=voting_id,
            user_id=call.from_user.id,
        )

    if action == "cancel":
        await state.clear()
        if call.message:
            await call.message.answer("Действие отменено.")
        return await call.answer()

    if action == "rewrite":
        state_data = await state.get_data()
        voting_id = state_data.get("voting_id")
        candidate_id = state_data.get("candidate_id")
        if not isinstance(voting_id, int) or not isinstance(candidate_id, int):
            await state.clear()
            return await call.answer("Сессия устарела. Откройте ссылку голосования ещё раз.", show_alert=True)
        await state.set_state(voting_states.VoteFlow.reason)
        await call.message.answer("Напишите новую причину голосования.")
        return await call.answer()

    if action == "candidates" and len(data) == 3:
        voting_id = int(data[2])
        async with get_session() as session:
            voting = await get_voting(session, voting_id)
            vote = await get_vote(session, voting_id, call.from_user.id)
        if voting is None or vote is None:
            return await call.answer("Голос не найден.", show_alert=True)
        if not voting.allows_changes():
            return await call.answer("Период изменения голосов завершён.", show_alert=True)
        await call.message.answer(
            "Выберите нового кандидата:",
            reply_markup=voting_keyboards.candidates(voting, current_candidate_id=vote.candidate_id),
        )
        return await call.answer()

    if action == "choose" and len(data) == 4:
        voting_id, candidate_id = int(data[2]), int(data[3])
        await call.answer()
        return await _begin_reason(
            call.message,
            state,
            voting_id=voting_id,
            candidate_id=candidate_id,
        )

    if action == "edit_reason" and len(data) == 3:
        voting_id = int(data[2])
        async with get_session() as session:
            vote = await get_vote(session, voting_id, call.from_user.id)
        if vote is None:
            return await call.answer("Голос не найден.", show_alert=True)
        if not vote.voting.allows_changes():
            return await call.answer("Период изменения голосов завершён.", show_alert=True)
        await state.clear()
        await state.set_state(voting_states.VoteFlow.reason)
        await state.update_data(voting_id=voting_id, candidate_id=vote.candidate_id)
        await call.message.answer("Напишите новую причину голосования.")
        return await call.answer()

    if action == "confirm":
        state_data = await state.get_data()
        voting_id = state_data.get("voting_id")
        candidate_id = state_data.get("candidate_id")
        reason = state_data.get("reason")
        if not isinstance(voting_id, int) or not isinstance(candidate_id, int) or not isinstance(reason, str):
            await state.clear()
            return await call.answer("Сессия устарела. Откройте ссылку голосования ещё раз.", show_alert=True)

        try:
            async with get_session() as session:
                await ensure_user(session, call)
                voting = await get_voting(session, voting_id)
                candidate = await get_candidate(session, voting_id, candidate_id)
                existing = await get_vote(session, voting_id, call.from_user.id)
                if voting is None or candidate is None:
                    await state.clear()
                    return await call.answer("Голосование или кандидат не найдены.", show_alert=True)
                if not voting.accepts_votes():
                    await state.clear()
                    return await call.answer(_voting_unavailable_text(voting), show_alert=True)
                if existing is not None and not voting.allows_changes():
                    await state.clear()
                    return await call.answer("Период изменения голосов завершён.", show_alert=True)
                _, changed = await save_vote(
                    session,
                    voting=voting,
                    candidate=candidate,
                    user_id=call.from_user.id,
                    reason=reason,
                )
        except IntegrityError:
            logger.exception("Concurrent vote submission | voting_id=%s user_id=%s", voting_id, call.from_user.id)
            await state.clear()
            return await call.answer("Голос уже был сохранён. Откройте ссылку ещё раз.", show_alert=True)

        await state.clear()
        verb = "изменён" if existing is not None and changed else "принят"
        await call.message.answer(
            f"✅ Ваш голос за <b>{escape(candidate.name)}</b> {verb}.\n\nСпасибо за участие!"
        )
        return await call.answer()

    return await call.answer()


@voting_user_router.message(voting_states.VoteFlow.reason, F.text)
async def handle_vote_reason(message: Message, state: FSMContext):
    reason = " ".join((message.text or "").split())
    if len(reason) < MIN_REASON_LENGTH:
        return await message.answer(f"Причина слишком короткая. Напишите не менее {MIN_REASON_LENGTH} символов.")
    if len(reason) > MAX_REASON_LENGTH:
        return await message.answer(f"Причина слишком длинная. Допустимо не более {MAX_REASON_LENGTH} символов.")

    state_data = await state.get_data()
    voting_id = state_data.get("voting_id")
    candidate_id = state_data.get("candidate_id")
    if not isinstance(voting_id, int) or not isinstance(candidate_id, int):
        await state.clear()
        return await message.answer("Сессия устарела. Откройте ссылку голосования ещё раз.")

    async with get_session() as session:
        voting = await get_voting(session, voting_id)
        candidate = await get_candidate(session, voting_id, candidate_id)
        existing = await get_vote(session, voting_id, message.chat.id)
    if voting is None or candidate is None:
        await state.clear()
        return await message.answer("Голосование или кандидат не найдены.")
    if not voting.accepts_votes() or (existing is not None and not voting.allows_changes()):
        await state.clear()
        return await message.answer("Срок голосования или изменения голоса уже завершён.")

    await state.update_data(reason=reason)
    await state.set_state(voting_states.VoteFlow.confirm)
    await message.answer(
        f"Проверьте ваш голос:\n\n"
        f"Кандидат: <b>{escape(candidate.name)}</b>\n"
        f"Причина: <i>{escape(reason)}</i>",
        reply_markup=voting_keyboards.vote_preview(),
    )


@voting_user_router.message(voting_states.VoteFlow.reason)
async def handle_vote_reason_non_text(message: Message):
    await message.answer("Причину нужно отправить текстовым сообщением.")
