import logging

from urllib.parse import parse_qs
from datetime import datetime, timezone

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

from config import ELIXIR_CHAT_ID, UFA_TZ
from src.bot.texts.review_examples import REVIEW_LENGTH_EXAMPLES_TEXT
from src.condition import RefJoin
from src.helpers import is_valid_email, notify, process_text_condition, show_giveaway, show_main_menu, show_progress
from src.bot.keyboards import user_keyboards
from src.bot.states.user import UserConditionInput
from src.bot.texts import user_texts
from src.database import get_session
from src.database.crud import (
    create_participant,
    get_condition,
    get_giveaway,
    get_participant,
    get_participant_by_giveaway_user,
)
from src.database.crud.user import ensure_user
from src.database.schemas import ParticipantCreate
from src.helpers.user_handler import (
    handle_confirm_ref_join_callback,
    handle_get_ref_link_callback,
    handle_pass_condition_callback,
    handle_pass_order_condition_callback,
    handle_pass_review_condition_callback,
    handle_recheck_review_condition_callback,
    process_winner_contact,
)

logger = logging.getLogger("user_router")
user_router = Router(name="user")


def _is_private_event(event: Message | CallbackQuery) -> bool:
    if isinstance(event, Message): return event.chat.type == ChatType.PRIVATE
    if isinstance(event, CallbackQuery): return bool(event.message and event.message.chat.type == ChatType.PRIVATE)
    return False


def _message_user_id(message: Message) -> int:
    return int(message.chat.id)


def _event_user_id(event: Message | CallbackQuery) -> int | None:
    if isinstance(event, Message):
        return _message_user_id(event)
    user = getattr(event, "from_user", None)
    if user is None:
        return None
    return int(user.id)


def _normalize_until_date(until_date) -> datetime | None:
    if until_date is None: return None
    if isinstance(until_date, datetime):
        if until_date.tzinfo is None: return until_date.replace(tzinfo=timezone.utc)
        return until_date.astimezone(UFA_TZ)
    try: return datetime.fromtimestamp(int(until_date), tz=timezone.utc)
    except (TypeError, ValueError): return None


async def _notify_endless_restriction(event: Message | CallbackQuery) -> None:
    bot = getattr(event, "bot", None)
    user_id = _event_user_id(event)
    if user_id is None or bot is None: return
    try: await bot.send_message(user_id, "😢 Сожалеем, Ваш аккаунт <b>ограничен в чате бессрочно</b>, доступ к розыгрышам закрыт. Обратитесь в поддержку @@Slim_peptide")
    except Exception: logger.exception("Failed to notify user about endless restriction | user_id=%s", user_id)
    if isinstance(event, CallbackQuery):
        try: await event.answer()
        except Exception: logger.exception("Failed to answer callback for endless restriction | user_id=%s", user_id)


async def _user_access_filter(event: Message | CallbackQuery) -> bool:
    if not _is_private_event(event): return False
    bot = getattr(event, "bot", None)
    user_id = _event_user_id(event)
    if user_id is None or bot is None: return False

    try: member = await bot.get_chat_member(ELIXIR_CHAT_ID, user_id)
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if "not found" in error_text: return True
        logger.exception("Failed to get chat member | user_id=%s", user_id)
        return True

    except Exception:
        logger.exception("Failed to get chat member | user_id=%s", user_id)
        return True

    status = getattr(member, "status", None)
    if status in {"member", "administrator", "creator", "left"}: return True
    if status in {"kicked", "banned"}:
        await _notify_endless_restriction(event)
        return False

    can_send_messages = getattr(member, "can_send_messages", True)
    if can_send_messages: return True
    until_date = _normalize_until_date(getattr(member, "until_date", None))
    print("until_date", until_date)
    if until_date is not None: return True

    await _notify_endless_restriction(event)
    return False


user_router.message.filter(_user_access_filter)
user_router.callback_query.filter(_user_access_filter)


@user_router.message(CommandStart(deep_link=True, deep_link_encoded=True))
async def handle_start_deeplink(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    message_user_id = _message_user_id(message)
    logger.info(
        "Referral deep link received | user_id=%s | raw_args=%s",
        message_user_id,
        command.args,
    )
    try:
        parsed = parse_qs(command.args)
        condition_id, participant_id = parsed.pop("condition_id")[0], parsed.pop("participant_id")[0]
        condition_id, participant_id = int(condition_id), int(participant_id)
        logger.info(
            "Referral deep link parsed | user_id=%s | condition_id=%s | participant_id=%s",
            message_user_id,
            condition_id,
            participant_id,
        )
    except Exception as e:
        logger.exception(f"Failed to handle start deeplink | user_id=%s,\n{e}", message_user_id)
        await message.answer(user_texts.ref_link_invalid)
        return await handle_start(message, state)

    async with get_session() as session:
        await ensure_user(session, message)
        condition = await get_condition(session, condition_id)
        participant = await get_participant(session, participant_id)
        logger.info(
            "Referral deep link context loaded | user_id=%s | condition_exists=%s | participant_exists=%s | condition_action=%s | condition_giveaway_id=%s | participant_giveaway_id=%s | inviter_user_id=%s",
            message_user_id,
            condition is not None,
            participant is not None,
            getattr(condition, "action", None),
            getattr(condition, "giveaway_id", None),
            getattr(participant, "giveaway_id", None),
            getattr(participant, "user_id", None),
        )

    if condition is None or participant is None or condition.action != "ref_join" or participant.giveaway_id != condition.giveaway_id:
        logger.warning(
            "Referral deep link denied: invalid link context | user_id=%s | condition_id=%s | participant_id=%s",
            message_user_id,
            condition_id,
            participant_id,
        )
        await message.answer(user_texts.ref_link_invalid)
        return await show_main_menu(message, message)

    if participant.user_id == message_user_id:
        logger.warning(
            "Referral deep link denied: self referral | user_id=%s | condition_id=%s | participant_id=%s",
            message_user_id,
            condition_id,
            participant_id,
        )
        await message.answer(user_texts.ref_self)
        return await show_main_menu(message, message)

    condition = RefJoin.from_orm(condition)
    logger.info(
        "Referral deep link accepted | user_id=%s | condition_id=%s | participant_id=%s | chat_id=%s",
        message_user_id,
        condition_id,
        participant_id,
        condition.chat_id,
    )
    return await message.answer(user_texts.ref_confirm_text, reply_markup=user_keyboards.confirm_ref_join(condition_id, participant_id, condition.chat_id))


@user_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    await show_main_menu(message, message)


@user_router.message(lambda message: message.contact is not None)
async def handle_winner_contact(message: Message):
    return await process_winner_contact(message, logger=logger)


@user_router.callback_query()
async def handle_user_call(call: CallbackQuery, state: FSMContext):
    if not call.data: return await call.answer()
    data = call.data.split(":")
    if data[0] == "user_main_menu":
        await show_main_menu(call.message, call, edit=True)
        return await call.answer()

    elif data[0] == "view_giveaway":
        try: giveaway_id = int(data[1])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        await show_giveaway(call.message, giveaway_id, call.from_user.id, edit=True)
        return await call.answer()

    elif data[0] == "notes":
        try: giveaway_id = int(data[1])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        async with get_session() as session:
            giveaway = await get_giveaway(session, giveaway_id)
            if giveaway is None or not giveaway.active: return await call.answer(user_texts.giveaway_not_found, show_alert=True)

        await call.message.edit_text(giveaway.notes or "Примечаний нет.", reply_markup=user_keyboards.back_to_giveaway(giveaway_id))
        return await call.answer()

    elif data[0] == "join":
        try: giveaway_id = int(data[1])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        async with get_session() as session:
            await ensure_user(session, call)
            giveaway = await get_giveaway(session, giveaway_id)
            if giveaway is None or not giveaway.active: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
            participant = await get_participant_by_giveaway_user(session, giveaway_id, call.from_user.id)
            if participant is None: await create_participant(session, ParticipantCreate(giveaway_id=giveaway_id, user_id=call.from_user.id))

        await show_giveaway(call.message, giveaway_id, call.from_user.id, edit=True)
        return await call.answer(user_texts.join_success, show_alert=True)

    elif data[0] == "view_progress":
        try: giveaway_id = int(data[1])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        ok = await show_progress(call.message, giveaway_id, call.from_user.id, edit=True)
        if not ok: return await call.answer(user_texts.need_join_first, show_alert=True)
        return await call.answer()

    elif data[0] == "condition_unavailable": return await call.answer("Это условие пока не поддерживает проверку кнопкой.", show_alert=True)
    elif data[0] == "pass_condition":
        try:
            giveaway_id = int(data[1])
            condition_id = int(data[2])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        return await handle_pass_condition_callback(call, giveaway_id=giveaway_id, condition_id=condition_id, logger=logger)

    elif data[0] == "pass_order_condition":
        try:
            giveaway_id = int(data[1])
            condition_id = int(data[2])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        return await handle_pass_order_condition_callback(call, state, giveaway_id=giveaway_id, condition_id=condition_id)

    elif data[0] == "pass_review_condition":
        try:
            giveaway_id = int(data[1])
            condition_id = int(data[2])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        return await handle_pass_review_condition_callback(call, state, giveaway_id=giveaway_id, condition_id=condition_id)

    elif data[0] == "recheck_review_condition":
        try:
            giveaway_id = int(data[1])
            condition_id = int(data[2])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        return await handle_recheck_review_condition_callback(call, giveaway_id=giveaway_id, condition_id=condition_id, logger=logger)

    elif data[0] == "get_ref_link":
        try:
            giveaway_id = int(data[1])
            condition_id = int(data[2])
        except Exception: return await call.answer(user_texts.giveaway_not_found, show_alert=True)
        return await handle_get_ref_link_callback(call, giveaway_id=giveaway_id, condition_id=condition_id)

    elif data[0] == "confirm_ref_join":
        try:
            condition_id = int(data[1])
            participant_id = int(data[2])
        except Exception: return await call.answer(user_texts.ref_link_invalid, show_alert=True)
        return await handle_confirm_ref_join_callback(call, condition_id=condition_id, participant_id=participant_id, logger=logger)

    return await call.answer()


@user_router.message(UserConditionInput.order_code, lambda message: message.text and message.text.strip())
async def handle_order_code_input(message: Message, state: FSMContext):
    order_code = message.text.strip()
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    condition_id = state_data.get("condition_id")
    if not isinstance(giveaway_id, int) or not isinstance(condition_id, int):
        await state.clear()
        return await notify(message, user_texts.condition_context_expired)

    return await process_text_condition(
        message,
        state,
        expected_action="website_order",
        config_key="order_codes",
        submitted_value=order_code,
    )

@user_router.message(UserConditionInput.review_email, lambda message: message.text and message.text.strip())
async def handle_review_email_input(message: Message, state: FSMContext):
    email = message.text.strip().lower()
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    condition_id = state_data.get("condition_id")
    if not isinstance(giveaway_id, int): giveaway_id = None
    if not is_valid_email(email): return await notify(message, user_texts.review_email_invalid)
    if not isinstance(giveaway_id, int) or not isinstance(condition_id, int):
        await state.clear()
        return await notify(message, user_texts.condition_context_expired)
    return await process_text_condition(message, state, expected_action="website_review", config_key="email", submitted_value=email)


@user_router.message(UserConditionInput.order_code)
async def handle_order_code_non_text(message: Message):
    return await notify(message, user_texts.order_code_prompt, giveaway_id=None, delete_after=120.0)


@user_router.message(UserConditionInput.review_email)
async def handle_review_email_non_text(message: Message):
    await message.answer(REVIEW_LENGTH_EXAMPLES_TEXT)
    return await notify(message, user_texts.review_email_prompt, giveaway_id=None, delete_after=120.0)
