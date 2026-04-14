import asyncio
import logging

from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from uuid import uuid4

from aiogram import Bot, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import ADMIN_TELEGRAM_IDS, UFA_TZ
from src.bot.keyboards import admin_keyboards, user_keyboards
from src.bot.states import admin_states
from src.bot.texts import admin_texts
from src.condition import ConditionType, RefJoin, SelfJoin, WebsiteOrder, WebsiteReview
from src.database import get_session
from src.database.crud import (
    clear_all_data,
    delete_condition,
    delete_giveaway,
    get_condition,
    get_giveaway,
    get_giveaway_with_relations,
    list_giveaway_conditions,
    list_giveaways,
    update_giveaway, list_users, get_user,
)
from src.database.models import Condition
from src.database.schemas import GiveawayUpdate
from src.helpers import (
    build_conditions_screen_text,
    conditions_back_markup,
    finalize_condition_creation,
    go_to_condition_required_flow,
    go_to_condition_specific_flow,
    normalize_condition_state_rules,
    update_condition_config, show_progress,
)
from src.helpers.admin import apply_giveaway_update, create_giveaway_from_state
from src.helpers.admin_handler import (
    _build_participants_excel,
    _classify_participants,
    _decide_winner_place_prompt,
    _format_prizes_block,
    _giveaway_start_as_datetime_iso,
    _normalize_winners,
    _parse_command_giveaway_id,
    _participants_export_caption,
    _pick_weighted_random_participant,
    _prize_for_place,
    _save_winner,
    _winners_user_ids_for_other_places,
)
from src.helpers.common import _build_prizes_payload, _parse_places, _parse_prizes, _parse_user_date_ddmm

admin_router = Router(name="admin")
admin_router.message.filter(lambda message: message.chat.type == ChatType.PRIVATE and message.from_user.id in ADMIN_TELEGRAM_IDS)
admin_router.callback_query.filter(lambda call: call.message.chat.type == ChatType.PRIVATE and call.from_user.id in ADMIN_TELEGRAM_IDS)
logger = logging.getLogger("admin_router")
SEND_USAGE_TEXT = "Ошибка команды: <code>/send тг_айди/all текст</code>"
SEND_SUCCESS_FILENAME = "success.txt"
SEND_ERROR_FILENAME = "error.txt"


@dataclass(slots=True)
class SendJob:
    send_id: str
    admin_chat_id: int
    admin_user_id: int
    text: str
    recipient_ids: list[int]
    success_ids: list[int] = field(default_factory=list)
    error_ids: list[int] = field(default_factory=list)
    cancel_requested: bool = False
    finished: bool = False
    task: asyncio.Task | None = None
    control_message_id: int | None = None


active_send_jobs: dict[str, SendJob] = {}
active_send_by_admin: dict[int, str] = {}


def _build_ids_file(ids: list[int]) -> bytes:
    if not ids:
        return b"\n"
    return ("\n".join(str(user_id) for user_id in ids) + "\n").encode("utf-8")


async def _finish_send_job(bot: Bot, job: SendJob, *, cancelled: bool) -> None:
    if job.finished: return
    job.finished = True

    active_send_jobs.pop(job.send_id, None)
    if active_send_by_admin.get(job.admin_user_id) == job.send_id:
        active_send_by_admin.pop(job.admin_user_id, None)

    if isinstance(job.control_message_id, int):
        try: await bot.edit_message_reply_markup(chat_id=job.admin_chat_id, message_id=job.control_message_id, reply_markup=None)
        except Exception: logger.info("Failed to clear send control keyboard | send_id=%s", job.send_id)

    status_text = "Рассылка остановлена." if cancelled else "Рассылка завершена."
    try:
        await bot.send_message(job.admin_chat_id, f"{status_text}\n\nУспешно: <b>{len(job.success_ids)}</b>\nОшибок: <b>{len(job.error_ids)}</b>")
        await bot.send_document(job.admin_chat_id, BufferedInputFile(_build_ids_file(job.success_ids), filename=SEND_SUCCESS_FILENAME), caption=f"{SEND_SUCCESS_FILENAME} ({len(job.success_ids)} ID)")
        await bot.send_document(job.admin_chat_id, BufferedInputFile(_build_ids_file(job.error_ids), filename=SEND_ERROR_FILENAME), caption=f"{SEND_ERROR_FILENAME} ({len(job.error_ids)} ID)")
    except Exception: logger.exception("Failed to deliver send logs to admin | send_id=%s", job.send_id)


async def _run_send_job(bot: Bot, job: SendJob) -> None:
    cancelled = False
    try:
        for user_id in job.recipient_ids:
            if job.cancel_requested:
                cancelled = True
                break
            try:
                await bot.send_message(user_id, job.text, parse_mode=None)
                job.success_ids.append(user_id)

            except Exception as exc:
                logger.info("Send failed | send_id=%s | user_id=%s | error=%s", job.send_id, user_id, exc)
                job.error_ids.append(user_id)
    except asyncio.CancelledError: cancelled = True
    except Exception:
        cancelled = True
        logger.exception("Broadcast worker crashed | send_id=%s", job.send_id)
    finally: await _finish_send_job(bot, job, cancelled=cancelled or job.cancel_requested)

@admin_router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    async with get_session() as session: giveaways = await list_giveaways(session)
    await message.answer(admin_texts.greetings, reply_markup=admin_keyboards.main_menu(giveaways))
    await state.clear()

@admin_router.message(Command("send"))
async def handle_send(message: Message, state: FSMContext, command: CommandObject):
    current_send_id = active_send_by_admin.get(message.from_user.id)
    if current_send_id in active_send_jobs: return await message.answer("У вас уже запущена рассылка. Сначала остановите текущую.")

    raw_args = (command.args or "").strip()
    if not raw_args: return await message.answer(SEND_USAGE_TEXT)

    args = raw_args.split(maxsplit=1)
    if len(args) < 2: return await message.answer(SEND_USAGE_TEXT)

    who, send_text = args[0].strip(), args[1].strip()
    if not send_text: return await message.answer(SEND_USAGE_TEXT)

    recipient_ids: list[int] = []
    if who == "all":
        async with get_session() as session: users = await list_users(session)
        seen_ids: set[int] = set()
        for user in users:
            user_id = int(user.id)
            if user_id <= 0 or user_id in seen_ids: continue
            seen_ids.add(user_id)
            recipient_ids.append(user_id)
        if not recipient_ids: return await message.answer("Нет пользователей для рассылки.")

    elif who.isdigit():
        user_id = int(who)
        if user_id <= 0: return await message.answer(SEND_USAGE_TEXT)
        async with get_session() as session: user = await get_user(session, user_id)
        if user is None: return await message.answer(f"Пользователь с айди {user_id} не был найден")
        recipient_ids = [user_id]
    else: return await message.answer(SEND_USAGE_TEXT)

    preview = send_text if len(send_text) <= 700 else f"{send_text[:700]}..."
    await state.clear()
    await state.set_state(admin_states.SendBroadcast.confirm_first)
    await state.update_data(send_recipient_ids=recipient_ids, send_text=send_text)
    return await message.answer("Подтверждение 1/2.\nПолучателей: <b>{len(recipient_ids)}</b>\n\nТекст:\n{escape(preview)}", reply_markup=admin_keyboards.send_confirmation(1))


@admin_router.message(admin_states.SendBroadcast.confirm_first, lambda message: not (message.text and message.text.startswith("/")))
@admin_router.message(admin_states.SendBroadcast.confirm_second, lambda message: not (message.text and message.text.startswith("/")))
async def handle_send_confirmation_message(message: Message):
    return await message.answer("Подтвердите запуск рассылки кнопкой под сообщением.")

@admin_router.message(Command("create_giveaway"))
async def handle_create_giveaway(message: Message, state: FSMContext):
    await state.set_state(admin_states.CreateGiveaway.name)
    await message.answer(admin_texts.CreateGiveaway.name, reply_markup=admin_keyboards.back_markup("main_menu"))

@admin_router.message(Command("clear_db"))
async def handle_clear_db(message: Message):
    async with get_session() as session: deleted_by_table = await clear_all_data(session)
    total_deleted = sum(deleted_by_table.values())
    details = "\n".join(f"{table_name}: {deleted_count}" for table_name, deleted_count in deleted_by_table.items())
    await message.answer(f"База очищена. Удалено записей: {total_deleted}")
    await message.answer(f"<code>{details}</code>")


@admin_router.message(Command("decide_winner"))
async def handle_decide_winner_command(message: Message, state: FSMContext, command: CommandObject):
    giveaway_id = _parse_command_giveaway_id(command)
    if giveaway_id is None: return await message.answer(admin_texts.DecideWinner.usage)

    async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
    if giveaway is None: return await message.answer(admin_texts.DeleteGiveaway.not_found)

    await state.clear()
    await state.set_state(admin_states.DecideWinner.place)
    await state.update_data(decide_winner_giveaway_id=giveaway_id)
    return await message.answer(_decide_winner_place_prompt(giveaway))


@admin_router.message(admin_states.DecideWinner.place, lambda message: message.text and message.text.strip())
async def handle_decide_winner_place(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("decide_winner_giveaway_id")
    if not isinstance(giveaway_id, int):
        await state.clear()
        return await message.answer(admin_texts.DecideWinner.usage)

    place = Condition.parse_positive_int(message.text)
    if place is None: return await message.answer(admin_texts.DecideWinner.place_invalid)

    async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
    if giveaway is None:
        await state.clear()
        return await message.answer(admin_texts.DeleteGiveaway.not_found)

    prize_info = _prize_for_place(giveaway, place)
    if prize_info is None: return await message.answer(f"{admin_texts.DecideWinner.place_not_in_prizes}\n\n{_format_prizes_block(giveaway)}")
    prize_name, prize_amount = prize_info

    await state.update_data(decide_winner_place=place)
    await state.update_data(decide_winner_prize_name=prize_name, decide_winner_prize_amount=prize_amount)
    await state.set_state(admin_states.DecideWinner.winner)
    return await message.answer(admin_texts.DecideWinner.winner_prompt)


@admin_router.message(admin_states.DecideWinner.winner, lambda message: message.text and message.text.strip())
async def handle_decide_winner_user(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("decide_winner_giveaway_id")
    place = state_data.get("decide_winner_place")
    prize_name = state_data.get("decide_winner_prize_name")
    prize_amount = state_data.get("decide_winner_prize_amount")
    if not isinstance(giveaway_id, int) or not isinstance(place, int) or not isinstance(prize_name, str):
        await state.clear()
        return await message.answer(admin_texts.DecideWinner.usage)

    if not isinstance(prize_amount, int): prize_amount = 0

    async with get_session() as session:
        giveaway = await get_giveaway_with_relations(session, giveaway_id)
        if giveaway is None:
            await state.clear()
            return await message.answer(admin_texts.DeleteGiveaway.not_found)

        prize_info = _prize_for_place(giveaway, place)
        if prize_info is None:
            await state.set_state(admin_states.DecideWinner.place)
            return await message.answer(f"{admin_texts.DecideWinner.place_not_in_prizes}\n\n{_format_prizes_block(giveaway)}")

        prize_name, prize_amount = prize_info
        winners = _normalize_winners(giveaway.winners)
        busy_user_ids = _winners_user_ids_for_other_places(winners, place=place)

        winner_raw = message.text.strip()
        winner_source = "manual"
        winner_tickets: int | None = None
        if winner_raw.lower() in {"random", "radnom", "рандом"}:
            winner_source = "random"
            random_candidate = _pick_weighted_random_participant(giveaway, excluded_user_ids=busy_user_ids)
            if random_candidate is None: return await message.answer(admin_texts.DecideWinner.random_empty)
            winner_user_id, winner_tickets = random_candidate

        else:
            try: winner_user_id = int(winner_raw)
            except (TypeError, ValueError): return await message.answer(admin_texts.DecideWinner.winner_invalid)
            if winner_user_id <= 0: return await message.answer(admin_texts.DecideWinner.winner_invalid)
            if winner_user_id in busy_user_ids: return await message.answer(admin_texts.DecideWinner.winner_duplicate)

        _save_winner(giveaway, place=place, user_id=winner_user_id, prize_name=prize_name, selected_by_admin_id=message.from_user.id, source=winner_source, tickets=winner_tickets)
        await session.commit()
        await session.refresh(giveaway)

    await state.clear()
    request_sent = True
    try:
        giveaway_name = escape(giveaway.name)
        safe_prize_name = escape(prize_name)
        await message.bot.send_message(winner_user_id, f"🥳 Вы выбраны победителем розыгрыша <b>{giveaway_name}</b> за <b>{place}</b> место.\n"f"Вы выиграли: <b>{place}. {safe_prize_name} x{prize_amount}шт.</b>\n""Нажмите кнопку ниже и отправьте свой номер телефона.", reply_markup=user_keyboards.request_winner_phone())
    except Exception:
        request_sent = False
        logger.exception("Failed to send winner phone request | giveaway_id=%s | user_id=%s", giveaway_id, winner_user_id)

    lines = [admin_texts.DecideWinner.winner_saved.format(place=place, user_id=winner_user_id, prize_name=escape(prize_name))]
    if winner_source == "random":
        lines.append("Режим выбора: <b>random</b> (взвешенно по билетам).")
        if isinstance(winner_tickets, int): lines.append(f"Билетов у победителя: <b>{winner_tickets}</b>.")

    lines.append(admin_texts.DecideWinner.request_sent if request_sent else admin_texts.DecideWinner.request_failed)
    return await message.answer("\n".join(lines))


@admin_router.message(admin_states.DecideWinner.place)
async def handle_decide_winner_place_non_text(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("decide_winner_giveaway_id")
    if not isinstance(giveaway_id, int): return await message.answer(admin_texts.DecideWinner.place_prompt)
    async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
    if giveaway is None: return await message.answer(admin_texts.DecideWinner.place_prompt)
    return await message.answer(_decide_winner_place_prompt(giveaway))


@admin_router.message(admin_states.DecideWinner.winner)
async def handle_decide_winner_user_non_text(message: Message):
    return await message.answer(admin_texts.DecideWinner.winner_prompt)


@admin_router.message(admin_states.CreateGiveaway.name, lambda message: message.text and message.text.strip())
async def handle_giveaway_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(admin_states.CreateGiveaway.description)
    await message.answer(admin_texts.CreateGiveaway.description, reply_markup=admin_keyboards.back_markup("main_menu"))


@admin_router.message(admin_states.CreateGiveaway.description, lambda message: message.text and message.text.strip())
async def handle_giveaway_description(message: Message, state: FSMContext):
    await state.update_data(description=message.html_text.strip())
    await state.set_state(admin_states.CreateGiveaway.notes)
    await message.answer(admin_texts.CreateGiveaway.notes, reply_markup=admin_keyboards.skip("giveaway_notes"))


@admin_router.message(admin_states.CreateGiveaway.notes, lambda message: message.text and message.text.strip())
async def handle_giveaway_notes(message: Message, state: FSMContext):
    await state.update_data(notes=message.text.strip())
    await state.set_state(admin_states.CreateGiveaway.prizes)
    await message.answer(admin_texts.CreateGiveaway.prizes, reply_markup=admin_keyboards.back_markup("main_menu"))


@admin_router.message(admin_states.CreateGiveaway.prizes, lambda message: message.text and message.text.strip())
async def handle_giveaway_prizes(message: Message, state: FSMContext):
    try:
        prizes = _parse_prizes(message.text.strip())
        await state.update_data(prizes=prizes)
        await state.set_state(admin_states.CreateGiveaway.places)
        await message.answer(admin_texts.CreateGiveaway.places, reply_markup=admin_keyboards.skip("giveaway_places"))

    except Exception:
        logger.exception("Invalid giveaway prizes input")
        await message.answer(f"{admin_texts.CreateGiveaway.error}\n{admin_texts.CreateGiveaway.prizes}", reply_markup=admin_keyboards.back_markup("main_menu"))


@admin_router.message(admin_states.CreateGiveaway.places, lambda message: message.text and message.text.strip())
async def handle_giveaway_places(message: Message, state: FSMContext):
    try:
        places = _parse_places(message.text.strip())
        await state.update_data(places=places)
        await state.set_state(admin_states.CreateGiveaway.start_date)
        await message.answer(admin_texts.CreateGiveaway.start_date, reply_markup=admin_keyboards.back_markup("main_menu"))

    except Exception:
        logger.exception("Invalid giveaway places input")
        await message.answer(f"{admin_texts.CreateGiveaway.error}\n{admin_texts.CreateGiveaway.places}", reply_markup=admin_keyboards.skip("giveaway_places"))


@admin_router.message(admin_states.CreateGiveaway.start_date, lambda message: message.text and message.text.strip())
async def handle_giveaway_start_date(message: Message, state: FSMContext):
    try:
        start_date = _parse_user_date_ddmm(message.text.strip())
        await state.update_data(start_date=start_date)
        await state.set_state(admin_states.CreateGiveaway.end_date)
        await message.answer(admin_texts.CreateGiveaway.end_date, reply_markup=admin_keyboards.skip("giveaway_end_date"))

    except Exception:
        logger.exception("Invalid giveaway start_date input")
        await message.answer(f"{admin_texts.CreateGiveaway.error}\n{admin_texts.CreateGiveaway.start_date}", reply_markup=admin_keyboards.back_markup("main_menu"))


@admin_router.message(admin_states.CreateGiveaway.end_date, lambda message: message.text and message.text.strip())
async def handle_giveaway_end_date(message: Message, state: FSMContext):
    try:
        end_date = _parse_user_date_ddmm(message.text.strip())
        state_data = await state.get_data()
        start_date = state_data.get("start_date")
        if isinstance(start_date, date) and end_date < start_date:
            await message.answer(admin_texts.CreateGiveaway.error + "Дата окончания не может быть раньше даты начала.")
            return await message.answer(admin_texts.CreateGiveaway.end_date, reply_markup=admin_keyboards.skip("giveaway_end_date"))

        await state.update_data(end_date=end_date)
        giveaway = await create_giveaway_from_state(state)
        await message.answer(str(giveaway), reply_markup=giveaway.admin_keyboard())

    except Exception as e:
        logger.exception("Error while creating giveaway: %s", e)
        await message.answer(f"{admin_texts.CreateGiveaway.error}\n{admin_texts.CreateGiveaway.end_date}", reply_markup=admin_keyboards.skip("giveaway_end_date"))


@admin_router.message(admin_states.CreateCondition.action, lambda message: message.text and message.text.strip())
async def handle_condition_action(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    action = Condition.parse_action(message.text)
    if action is None or action not in ConditionType.__members__: return await message.answer(f"{admin_texts.CreateCondition.action_error}\n\n{admin_texts.CreateCondition.action}", reply_markup=conditions_back_markup(giveaway_id))
    await state.update_data(condition_action=action, condition_config={}, condition_reward=None, condition_required=1)
    await state.set_state(admin_states.CreateCondition.mandatory)
    return await message.answer(admin_texts.CreateCondition.mandatory, reply_markup=conditions_back_markup(giveaway_id))


@admin_router.message(admin_states.CreateCondition.mandatory, lambda message: message.text and message.text.strip())
async def handle_condition_mandatory(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    action = state_data.get("condition_action")
    mandatory = Condition.parse_yes_no(message.text)
    if mandatory is None: return await message.answer(admin_texts.CreateCondition.yes_no_error, reply_markup=conditions_back_markup(giveaway_id))
    await state.update_data(condition_mandatory=mandatory)
    if action == "self_join":
        await state.update_data(condition_repeatable=False, condition_repeat_limit=1)
        await state.set_state(admin_states.CreateCondition.reward)
        back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
        return await message.answer(admin_texts.CreateCondition.reward, reply_markup=admin_keyboards.skip("condition_reward", back_call=back_call))
    await state.set_state(admin_states.CreateCondition.repeatable)
    if giveaway_id is None:
        return await message.answer(admin_texts.CreateCondition.repeatable, reply_markup=conditions_back_markup(giveaway_id))
    return await message.answer(admin_texts.CreateCondition.repeatable, reply_markup=admin_keyboards.condition_repeat_limit(giveaway_id))


@admin_router.message(admin_states.CreateCondition.repeatable, lambda message: message.text and message.text.strip())
async def handle_condition_repeat_limit(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    action = state_data.get("condition_action")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try:
        repeat_limit = Condition.parse_repeat_limit(message.text)
    except Exception:
        if giveaway_id is None:
            return await message.answer(admin_texts.CreateCondition.repeatable, reply_markup=conditions_back_markup(giveaway_id))
        return await message.answer(admin_texts.CreateCondition.repeatable, reply_markup=admin_keyboards.condition_repeat_limit(giveaway_id))

    if action == "self_join":
        repeat_limit = 1
    repeatable = action != "self_join" and (repeat_limit is None or repeat_limit > 1)
    await state.update_data(condition_repeat_limit=repeat_limit, condition_repeatable=repeatable)
    await state.set_state(admin_states.CreateCondition.reward)
    return await message.answer(admin_texts.CreateCondition.reward, reply_markup=admin_keyboards.skip("condition_reward", back_call=back_call))


@admin_router.message(admin_states.CreateCondition.reward, lambda message: message.text and message.text.strip())
async def handle_condition_reward(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    reward = Condition.parse_positive_int(message.text)
    if reward is None: return await message.answer(admin_texts.CreateCondition.reward_error, reply_markup=admin_keyboards.skip("condition_reward", back_call=back_call))
    await state.update_data(condition_reward=reward)
    return await go_to_condition_required_flow(message, state)


@admin_router.message(admin_states.CreateCondition.required, lambda message: message.text and message.text.strip())
async def handle_condition_required(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    action = state_data.get("condition_action")
    if not Condition.can_configure_required(action):
        await normalize_condition_state_rules(state)
        return await go_to_condition_specific_flow(message, state)

    required = Condition.parse_positive_int(message.text)
    if required is None: return await message.answer(admin_texts.CreateCondition.required_error, reply_markup=conditions_back_markup(giveaway_id))
    await state.update_data(condition_required=required)
    return await go_to_condition_specific_flow(message, state)


@admin_router.message(admin_states.CreateWebsiteOrderCondition.min_price, lambda message: message.text and message.text.strip())
async def handle_condition_order_min_price(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: min_price = WebsiteOrder.parse_min_price(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.order_min_price, reply_markup=admin_keyboards.condition_order_min_price(back_call=back_call))
    await update_condition_config(state, min_price=min_price)
    await state.set_state(admin_states.CreateWebsiteOrderCondition.start_date)
    return await message.answer(admin_texts.CreateCondition.order_start_date, reply_markup=admin_keyboards.skip("condition_order_start_date", back_call=back_call))


@admin_router.message(admin_states.CreateWebsiteOrderCondition.start_date, lambda message: message.text and message.text.strip())
async def handle_condition_order_start_date(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: start_date = WebsiteOrder.parse_start_date(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.order_start_date, reply_markup=admin_keyboards.skip("condition_order_start_date", back_call=back_call))
    await update_condition_config(state, start_date=start_date.isoformat())
    return await finalize_condition_creation(message, state)


@admin_router.message(admin_states.CreateWebsiteReviewCondition.start_date, lambda message: message.text and message.text.strip())
async def handle_condition_review_start_date(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: start_date = WebsiteReview.parse_start_date(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.review_start_date, reply_markup=admin_keyboards.skip("condition_review_start_date", back_call=back_call))
    await update_condition_config(state, start_date=start_date.isoformat())
    await state.set_state(admin_states.CreateWebsiteReviewCondition.min_grade)
    return await message.answer(admin_texts.CreateCondition.review_min_grade, reply_markup=admin_keyboards.skip("condition_review_min_grade", back_call=back_call))


@admin_router.message(admin_states.CreateWebsiteReviewCondition.min_grade, lambda message: message.text and message.text.strip())
async def handle_condition_review_min_grade(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: min_grade = WebsiteReview.parse_min_grade(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.review_min_grade, reply_markup=admin_keyboards.skip("condition_review_min_grade", back_call=back_call))
    await update_condition_config(state, min_grade=min_grade)
    await state.set_state(admin_states.CreateWebsiteReviewCondition.min_length)
    return await message.answer(admin_texts.CreateCondition.review_min_length, reply_markup=admin_keyboards.condition_review_min_length(back_call=back_call))


@admin_router.message(admin_states.CreateWebsiteReviewCondition.min_length, lambda message: message.text and message.text.strip())
async def handle_condition_review_min_length(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: min_length = WebsiteReview.parse_min_length(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.review_min_length, reply_markup=admin_keyboards.condition_review_min_length(back_call=back_call))
    await update_condition_config(state, min_length=min_length)
    return await finalize_condition_creation(message, state)


@admin_router.message(admin_states.CreateSelfJoinCondition.chat_id, lambda message: message.text and message.text.strip())
async def handle_condition_self_join_chat_id(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    try: chat_id = SelfJoin.parse_chat_id(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.join_username, reply_markup=conditions_back_markup(giveaway_id))
    await update_condition_config(state, chat_id=chat_id)
    return await finalize_condition_creation(message, state)


@admin_router.message(admin_states.CreateRefJoinCondition.chat_id, lambda message: message.text and message.text.strip())
async def handle_condition_ref_join_chat_id(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    try: chat_id = RefJoin.parse_chat_id(message.text)
    except Exception: return await message.answer(admin_texts.CreateCondition.join_username, reply_markup=conditions_back_markup(giveaway_id))
    await update_condition_config(state, chat_id=chat_id)
    return await finalize_condition_creation(message, state)


@admin_router.message(admin_states.EditGiveaway.name, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_name(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    return await apply_giveaway_update(message, state, giveaway_id, GiveawayUpdate(name=message.text.strip()), back_call=back_call)


@admin_router.message(admin_states.EditGiveaway.description, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_description(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    description = (message.html_text or message.text).strip()
    return await apply_giveaway_update(message, state, giveaway_id, GiveawayUpdate(description=description), back_call=back_call)


@admin_router.message(admin_states.EditGiveaway.notes, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_notes(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    return await apply_giveaway_update(message, state, giveaway_id, GiveawayUpdate(notes=message.text.strip()), back_call=back_call)


@admin_router.message(admin_states.EditGiveaway.prizes, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_prizes(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: prizes = _parse_prizes(message.text.strip())
    except Exception: return await message.answer(f"{admin_texts.EditGiveaway.prizes_error}\n\n{admin_texts.EditGiveaway.prizes}", reply_markup=admin_keyboards.back_markup(back_call))
    await state.update_data(edit_prizes=prizes)
    await state.set_state(admin_states.EditGiveaway.places)
    return await message.answer(admin_texts.EditGiveaway.places, reply_markup=admin_keyboards.skip("edit_giveaway_places", back_call=back_call))


@admin_router.message(admin_states.EditGiveaway.places, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_places(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    prizes = state_data.get("edit_prizes")
    if not isinstance(prizes, dict) or not prizes:
        await state.clear()
        return await message.answer(admin_texts.EditGiveaway.update_error, reply_markup=admin_keyboards.back_markup("main_menu"))

    try: places = _parse_places(message.text.strip())
    except Exception: return await message.answer(f"{admin_texts.EditGiveaway.places_error}\n\n{admin_texts.EditGiveaway.places}", reply_markup=admin_keyboards.skip("edit_giveaway_places", back_call=back_call))
    return await apply_giveaway_update(message, state, giveaway_id, GiveawayUpdate(prizes=_build_prizes_payload(prizes, places)), back_call=back_call)


@admin_router.message(admin_states.EditGiveaway.start_date, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_start_date(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: start_date = _parse_user_date_ddmm(message.text.strip())
    except Exception: return await message.answer(admin_texts.EditGiveaway.start_date, reply_markup=admin_keyboards.back_markup(back_call))
    if giveaway_id is None:
        await state.clear()
        return await message.answer(admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))

    async with get_session() as session: giveaway = await get_giveaway(session, int(giveaway_id))
    if giveaway is None:
        await state.clear()
        return await message.answer(admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))

    if giveaway.end_date is not None and start_date > giveaway.end_date:
        await message.answer(admin_texts.EditGiveaway.date_start_error)
        return await message.answer(admin_texts.EditGiveaway.start_date, reply_markup=admin_keyboards.back_markup(back_call))

    return await apply_giveaway_update(message, state, giveaway_id, GiveawayUpdate(start_date=start_date), back_call=back_call)


@admin_router.message(admin_states.EditGiveaway.end_date, lambda message: message.text and message.text.strip())
async def handle_edit_giveaway_end_date(message: Message, state: FSMContext):
    state_data = await state.get_data()
    giveaway_id = state_data.get("edit_giveaway_id")
    back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
    try: end_date = _parse_user_date_ddmm(message.text.strip())
    except Exception: return await message.answer(admin_texts.EditGiveaway.end_date, reply_markup=admin_keyboards.skip("edit_giveaway_end_date", back_call=back_call))
    if giveaway_id is None:
        await state.clear()
        return await message.answer(admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))

    async with get_session() as session: giveaway = await get_giveaway(session, int(giveaway_id))
    if giveaway is None:
        await state.clear()
        return await message.answer(admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))

    if end_date < giveaway.start_date:
        await message.answer(admin_texts.EditGiveaway.date_end_error)
        return await message.answer(admin_texts.EditGiveaway.end_date, reply_markup=admin_keyboards.skip("edit_giveaway_end_date", back_call=back_call))

    return await apply_giveaway_update(message,state, giveaway_id, GiveawayUpdate(end_date=end_date), back_call=back_call)


@admin_router.message(admin_states.DeleteGiveaway.confirm, lambda message: message.text and message.text.strip())
async def handle_delete_giveaway_confirmation(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    if answer not in {"да", "нет"}: return await message.answer(admin_texts.DeleteGiveaway.invalid)
    state_data = await state.get_data()
    giveaway_id = state_data.get("delete_giveaway_id")
    if answer == "нет":
        await state.clear()
        await message.answer(admin_texts.DeleteGiveaway.cancelled)
        async with get_session() as session: giveaways = await list_giveaways(session)
        return await message.answer(admin_texts.greetings, reply_markup=admin_keyboards.main_menu(giveaways))

    if giveaway_id is None:
        await state.clear()
        return await message.answer(admin_texts.DeleteGiveaway.not_found)

    async with get_session() as session:
        giveaway = await get_giveaway(session, int(giveaway_id))
        if giveaway is None:
            await state.clear()
            return await message.answer(admin_texts.DeleteGiveaway.not_found)

        await delete_giveaway(session, giveaway)
        giveaways = await list_giveaways(session)

    await state.clear()
    return await message.answer(admin_texts.DeleteGiveaway.deleted+admin_texts.greetings, reply_markup=admin_keyboards.main_menu(giveaways))


@admin_router.callback_query(lambda call: call.data and call.data.startswith("skip"))
async def handle_skip_call(call: CallbackQuery, state: FSMContext):
    if not call.data: return await call.answer()
    current_state = await state.get_state()
    if not current_state: return await call.answer()
    state_data = await state.get_data()

    if current_state == admin_states.CreateGiveaway.notes.state:
        await state.update_data(notes=None)
        await state.set_state(admin_states.CreateGiveaway.prizes)
        await call.message.edit_text(admin_texts.CreateGiveaway.prizes, reply_markup=admin_keyboards.back_markup("main_menu"))

    elif current_state == admin_states.CreateGiveaway.places.state:
        prizes = state_data["prizes"]
        await state.update_data(places={int(prize_place): 1 for prize_place in prizes})
        await state.set_state(admin_states.CreateGiveaway.start_date)
        await call.message.edit_text(admin_texts.CreateGiveaway.start_date, reply_markup=admin_keyboards.back_markup("main_menu"))

    elif current_state == admin_states.CreateGiveaway.end_date.state:
        try:
            await state.update_data(end_date=None)
            giveaway = await create_giveaway_from_state(state)
            await call.message.edit_text(str(giveaway), reply_markup=giveaway.admin_keyboard())
        except Exception as e:
            logger.exception("Error while creating giveaway without end_date: %s", e)
            await call.message.edit_text(f"{admin_texts.CreateGiveaway.error}\n{admin_texts.CreateGiveaway.end_date}", reply_markup=admin_keyboards.skip("giveaway_end_date"))

    elif current_state == admin_states.CreateWebsiteOrderCondition.min_price.state:
        giveaway_id = state_data.get("condition_giveaway_id")
        back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
        await update_condition_config(state, min_price=0.0)
        await state.set_state(admin_states.CreateWebsiteOrderCondition.start_date)
        await call.message.edit_text(admin_texts.CreateCondition.order_start_date, reply_markup=admin_keyboards.skip("condition_order_start_date", back_call=back_call))

    elif current_state == admin_states.CreateWebsiteOrderCondition.start_date.state:
        giveaway_id = state_data.get("condition_giveaway_id")
        if giveaway_id is None:
            await state.clear()
            await call.message.edit_text(admin_texts.CreateCondition.create_error, reply_markup=admin_keyboards.back_markup("main_menu"))
            return await call.answer()

        async with get_session() as session:
            giveaway = await get_giveaway(session, int(giveaway_id))
            if giveaway is None:
                await state.clear()
                await call.message.edit_text(admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))
                return await call.answer()

        await update_condition_config(state, start_date=_giveaway_start_as_datetime_iso(giveaway.start_date))
        await finalize_condition_creation(call.message, state)

    elif current_state == admin_states.CreateWebsiteReviewCondition.start_date.state:
        giveaway_id = state_data.get("condition_giveaway_id")
        if giveaway_id is None:
            await state.clear()
            await call.message.edit_text(admin_texts.CreateCondition.create_error, reply_markup=admin_keyboards.back_markup("main_menu"))
            return await call.answer()

        async with get_session() as session:
            giveaway = await get_giveaway(session, int(giveaway_id))
            if giveaway is None:
                await state.clear()
                await call.message.edit_text(admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))
                return await call.answer()

        back_call = f"conditions:{giveaway_id}"
        await update_condition_config(state, start_date=_giveaway_start_as_datetime_iso(giveaway.start_date))
        await state.set_state(admin_states.CreateWebsiteReviewCondition.min_grade)
        await call.message.edit_text(admin_texts.CreateCondition.review_min_grade, reply_markup=admin_keyboards.skip("condition_review_min_grade", back_call=back_call))

    elif current_state == admin_states.CreateWebsiteReviewCondition.min_grade.state:
        giveaway_id = state_data.get("condition_giveaway_id")
        back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
        await update_condition_config(state, min_grade=None)
        await state.set_state(admin_states.CreateWebsiteReviewCondition.min_length)
        await call.message.edit_text(admin_texts.CreateCondition.review_min_length, reply_markup=admin_keyboards.condition_review_min_length(back_call=back_call))

    elif current_state == admin_states.CreateWebsiteReviewCondition.min_length.state:
        await update_condition_config(state, min_length=None)
        await finalize_condition_creation(call.message, state)

    elif current_state == admin_states.CreateCondition.reward.state:
        state_data = await state.get_data()
        giveaway_id = state_data.get("condition_giveaway_id")
        back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
        repeat_limit = state_data.get("condition_repeat_limit")
        action = state_data.get("condition_action")
        try: parsed_limit = int(repeat_limit) if repeat_limit is not None else None
        except (TypeError, ValueError): parsed_limit = None
        repeatable_requested = action != "self_join" and (parsed_limit is None or parsed_limit > 1)
        if repeatable_requested:
            await call.message.edit_text(admin_texts.CreateCondition.reward_error, reply_markup=admin_keyboards.skip("condition_reward", back_call=back_call))
            return await call.answer()

        await state.update_data(condition_reward=None)
        await go_to_condition_required_flow(call.message, state)

    elif current_state == admin_states.EditGiveaway.description.state:
        giveaway_id = state_data.get("edit_giveaway_id")
        back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
        await apply_giveaway_update(call.message, state, giveaway_id, GiveawayUpdate(description=None), back_call=back_call)

    elif current_state == admin_states.EditGiveaway.notes.state:
        giveaway_id = state_data.get("edit_giveaway_id")
        back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
        await apply_giveaway_update(call.message, state, giveaway_id, GiveawayUpdate(notes=None), back_call=back_call)

    elif current_state == admin_states.EditGiveaway.places.state:
        giveaway_id = state_data.get("edit_giveaway_id")
        back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
        prizes = state_data.get("edit_prizes")
        if not isinstance(prizes, dict) or not prizes:
            await state.clear()
            await call.message.edit_text(admin_texts.EditGiveaway.update_error, reply_markup=admin_keyboards.back_markup("main_menu"))
            return await call.answer()

        default_places = {int(prize_place): 1 for prize_place in prizes}
        await apply_giveaway_update(call.message, state, giveaway_id, GiveawayUpdate(prizes=_build_prizes_payload(prizes, default_places)), back_call=back_call)

    elif current_state == admin_states.EditGiveaway.end_date.state:
        giveaway_id = state_data.get("edit_giveaway_id")
        back_call = f"edit_giveaway:{giveaway_id}" if giveaway_id is not None else "main_menu"
        await apply_giveaway_update(call.message, state, giveaway_id, GiveawayUpdate(end_date=None), back_call=back_call)

    return await call.answer()

@admin_router.callback_query()
async def handle_admin_call(call: CallbackQuery, state: FSMContext):
    if not call.data: return await call.answer()
    data = call.data.split(":")
    if data[0] == "send_confirm":
        if len(data) != 3:
            return await call.answer()
        step, decision = data[1], data[2]

        if decision == "no":
            await state.clear()
            await call.message.edit_text("Рассылка отменена.")
            return await call.answer("Отменено")

        current_state = await state.get_state()
        state_data = await state.get_data()
        recipient_ids = state_data.get("send_recipient_ids")
        send_text = state_data.get("send_text")
        if not isinstance(recipient_ids, list) or not all(isinstance(item, int) for item in recipient_ids) or not isinstance(send_text, str):
            await state.clear()
            return await call.answer("Нет данных для рассылки. Запустите /send заново.", show_alert=True)

        preview = send_text if len(send_text) <= 700 else f"{send_text[:700]}..."
        if step == "1":
            if current_state != admin_states.SendBroadcast.confirm_first.state:
                return await call.answer("Это подтверждение уже устарело.", show_alert=True)
            await state.set_state(admin_states.SendBroadcast.confirm_second)
            await call.message.edit_text(
                "Подтверждение 2/2.\n"
                f"Получателей: <b>{len(recipient_ids)}</b>\n\n"
                f"Текст:\n{escape(preview)}",
                reply_markup=admin_keyboards.send_confirmation(2),
            )
            return await call.answer()

        if step == "2":
            if current_state != admin_states.SendBroadcast.confirm_second.state:
                return await call.answer("Это подтверждение уже устарело.", show_alert=True)

            current_send_id = active_send_by_admin.get(call.from_user.id)
            if current_send_id in active_send_jobs:
                await state.clear()
                return await call.answer("У вас уже запущена рассылка.", show_alert=True)

            send_id = uuid4().hex[:8]
            job = SendJob(
                send_id=send_id,
                admin_chat_id=call.message.chat.id,
                admin_user_id=call.from_user.id,
                text=send_text,
                recipient_ids=recipient_ids,
            )
            active_send_jobs[send_id] = job
            active_send_by_admin[call.from_user.id] = send_id
            await state.clear()

            started_message = await call.message.answer(
                "рассылка успешно запущена ",
                reply_markup=admin_keyboards.cancel_send(send_id),
            )
            job.control_message_id = started_message.message_id
            job.task = asyncio.create_task(_run_send_job(call.bot, job))

            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return await call.answer("Рассылка запущена")

        return await call.answer()

    elif data[0] == "cancel_send":
        if len(data) != 2:
            return await call.answer()
        send_id = data[1]
        job = active_send_jobs.get(send_id)
        if job is None:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return await call.answer("Рассылка уже завершена.", show_alert=True)

        if call.from_user.id != job.admin_user_id:
            return await call.answer("Эту рассылку может остановить только админ, который ее запустил.", show_alert=True)

        if job.cancel_requested:
            return await call.answer("Остановка уже запрошена.")

        job.cancel_requested = True
        if job.task is not None and not job.task.done():
            job.task.cancel()

        try:
            await call.message.edit_text("Остановка рассылки запрошена…")
        except Exception:
            pass
        return await call.answer("Останавливаю рассылку...")

    elif data[0] == "view_giveaway":
        await state.clear()
        giveaway_id = int(data[1])
        async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
        await call.message.edit_text(str(giveaway), reply_markup=giveaway.admin_keyboard())

    elif data[0] == "notes":
        giveaway_id = int(data[1])
        async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
        notes_text = giveaway.notes or "Примечаний нет."
        await call.message.edit_text(notes_text, reply_markup=admin_keyboards.back_markup(f"view_giveaway:{giveaway_id}"))

    elif data[0] in {"view_winners", "decide_winners"}:
        return await call.answer("Используйте команду /decide_winner <giveaway_id>.", show_alert=True)

    elif data[0] == "view_participants":
        giveaway_id = int(data[1])
        await state.clear()
        async with get_session() as session: giveaway = await get_giveaway_with_relations(session, giveaway_id)
        if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
        winnable_participants, not_winnable_participants, _, _ = _classify_participants(giveaway)
        passed_count = len(winnable_participants)
        all_count = passed_count + len(not_winnable_participants)
        xlsx = _build_participants_excel(giveaway)
        export_date = datetime.now(tz=UFA_TZ).strftime("%Y-%m-%d")
        filename = f"participants_{giveaway_id}_{export_date}.xlsx"
        await call.message.answer_document(BufferedInputFile(xlsx, filename=filename), caption=_participants_export_caption(giveaway, passed_count, all_count))
        return await call.answer()

    elif data[0] == "download_participants_excel":
        giveaway_id = int(data[1])
        async with get_session() as session: giveaway = await get_giveaway_with_relations(session, giveaway_id)
        if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
        winnable_participants, not_winnable_participants, _, _ = _classify_participants(giveaway)
        passed_count = len(winnable_participants)
        all_count = passed_count + len(not_winnable_participants)
        xlsx = _build_participants_excel(giveaway)
        export_date = datetime.now(tz=UFA_TZ).strftime("%Y-%m-%d")
        filename = f"participants_{giveaway_id}_{export_date}.xlsx"
        await call.message.answer_document(BufferedInputFile(xlsx, filename=filename), caption=_participants_export_caption(giveaway, passed_count, all_count))
        return await call.answer("Excel файл отправлен.")

    elif data[0] == "conditions":
        giveaway_id = int(data[1])
        await state.clear()
        async with get_session() as session:
            giveaway = await get_giveaway(session, giveaway_id)
            if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
            conditions = await list_giveaway_conditions(session, giveaway_id)

        await call.message.edit_text(build_conditions_screen_text(giveaway, conditions), reply_markup=admin_keyboards.conditions_menu(giveaway_id))

    elif data[0] == "edit_giveaway":
        giveaway_id = int(data[1])
        await state.clear()
        async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
        await call.message.edit_text(admin_texts.EditGiveaway.menu, reply_markup=admin_keyboards.edit_giveaway_menu(giveaway_id))
        return await call.answer()

    elif data[0] == "edit_giveaway_field":
        giveaway_id = int(data[1])
        field = data[2]
        async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None:
            await state.clear()
            return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)

        await state.update_data(edit_giveaway_id=giveaway_id)
        if field == "name":
            await state.set_state(admin_states.EditGiveaway.name)
            await call.message.edit_text(admin_texts.EditGiveaway.name, reply_markup=admin_keyboards.back_markup(f"edit_giveaway:{giveaway_id}"))

        elif field == "description":
            await state.set_state(admin_states.EditGiveaway.description)
            await call.message.edit_text(admin_texts.EditGiveaway.description, reply_markup=admin_keyboards.skip("edit_giveaway_description", back_call=f"edit_giveaway:{giveaway_id}"))

        elif field == "notes":
            await state.set_state(admin_states.EditGiveaway.notes)
            await call.message.edit_text(admin_texts.EditGiveaway.notes, reply_markup=admin_keyboards.skip("edit_giveaway_notes", back_call=f"edit_giveaway:{giveaway_id}"))

        elif field == "prizes":
            await state.set_state(admin_states.EditGiveaway.prizes)
            await call.message.edit_text(admin_texts.EditGiveaway.prizes, reply_markup=admin_keyboards.back_markup(f"edit_giveaway:{giveaway_id}"))

        elif field == "start_date":
            await state.set_state(admin_states.EditGiveaway.start_date)
            await call.message.edit_text(admin_texts.EditGiveaway.start_date, reply_markup=admin_keyboards.back_markup(f"edit_giveaway:{giveaway_id}"))

        elif field == "end_date":
            await state.set_state(admin_states.EditGiveaway.end_date)
            await call.message.edit_text(admin_texts.EditGiveaway.end_date, reply_markup=admin_keyboards.skip("edit_giveaway_end_date", back_call=f"edit_giveaway:{giveaway_id}"))

        else: return await call.answer(admin_texts.EditGiveaway.update_error, show_alert=True)
        return await call.answer()

    elif data[0] == "add_condition":
        giveaway_id = int(data[1])
        async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None:
            await state.clear()
            return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)

        await state.clear()
        await state.set_state(admin_states.CreateCondition.action)
        await state.update_data(condition_giveaway_id=giveaway_id, condition_config={}, condition_reward=None, condition_required=1)
        await call.message.edit_text(admin_texts.CreateCondition.action, reply_markup=admin_keyboards.condition_actions(giveaway_id))

    elif data[0] == "condition_action":
        giveaway_id = int(data[1])
        action = data[2]
        if action not in ConditionType.__members__: return await call.answer(admin_texts.CreateCondition.action_error, show_alert=True)
        await state.update_data(condition_giveaway_id=giveaway_id, condition_action=action, condition_config={}, condition_reward=None, condition_required=1)
        await state.set_state(admin_states.CreateCondition.mandatory)
        await call.message.edit_text(admin_texts.CreateCondition.mandatory, reply_markup=admin_keyboards.condition_yes_no(giveaway_id, "condition_mandatory"))

    elif data[0] == "condition_mandatory":
        giveaway_id = int(data[1])
        mandatory = data[2] == "yes"
        state_data = await state.get_data()
        action = state_data.get("condition_action")
        await state.update_data(condition_giveaway_id=giveaway_id, condition_mandatory=mandatory)
        if action == "self_join":
            await state.update_data(condition_repeatable=False, condition_repeat_limit=1)
            await state.set_state(admin_states.CreateCondition.reward)
            await call.message.edit_text(admin_texts.CreateCondition.reward, reply_markup=admin_keyboards.skip("condition_reward", back_call=f"conditions:{giveaway_id}"))
            return await call.answer()
        await state.set_state(admin_states.CreateCondition.repeatable)
        await call.message.edit_text(admin_texts.CreateCondition.repeatable, reply_markup=admin_keyboards.condition_repeat_limit(giveaway_id))

    elif data[0] == "condition_repeat_limit":
        giveaway_id = int(data[1])
        state_data = await state.get_data()
        action = state_data.get("condition_action")
        try:
            repeat_limit = Condition.parse_repeat_limit(data[2])
        except Exception:
            return await call.answer(admin_texts.CreateCondition.create_error, show_alert=True)
        if action == "self_join":
            repeat_limit = 1
        repeatable = action != "self_join" and (repeat_limit is None or repeat_limit > 1)
        await state.update_data(condition_giveaway_id=giveaway_id, condition_repeat_limit=repeat_limit, condition_repeatable=repeatable)
        await state.set_state(admin_states.CreateCondition.reward)
        await call.message.edit_text(admin_texts.CreateCondition.reward, reply_markup=admin_keyboards.skip("condition_reward", back_call=f"conditions:{giveaway_id}"))

    elif data[0] == "condition_repeatable":
        giveaway_id = int(data[1])
        repeatable = data[2] == "yes"
        repeat_limit = None if repeatable else 1
        await state.update_data(condition_giveaway_id=giveaway_id, condition_repeat_limit=repeat_limit, condition_repeatable=repeatable)
        await state.set_state(admin_states.CreateCondition.reward)
        await call.message.edit_text(admin_texts.CreateCondition.reward, reply_markup=admin_keyboards.skip("condition_reward", back_call=f"conditions:{giveaway_id}"))

    elif data[0] == "condition_preset_order_min_price":
        state_data = await state.get_data()
        giveaway_id = state_data.get("condition_giveaway_id")
        back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"
        try: min_price = WebsiteOrder.parse_min_price(data[1])
        except Exception: return await call.answer(admin_texts.CreateCondition.create_error, show_alert=True)
        await update_condition_config(state, min_price=min_price)
        await state.set_state(admin_states.CreateWebsiteOrderCondition.start_date)
        await call.message.edit_text(admin_texts.CreateCondition.order_start_date, reply_markup=admin_keyboards.skip("condition_order_start_date", back_call=back_call))

    elif data[0] == "condition_preset_review_min_length":
        try: min_length = WebsiteReview.parse_min_length(data[1])
        except Exception: return await call.answer(admin_texts.CreateCondition.create_error, show_alert=True)
        await update_condition_config(state, min_length=min_length)
        await finalize_condition_creation(call.message, state)

    elif data[0] == "remove_condition":
        giveaway_id = int(data[1])
        await state.clear()
        async with get_session() as session:
            giveaway = await get_giveaway(session, giveaway_id)
            if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
            conditions = await list_giveaway_conditions(session, giveaway_id)

        if not conditions: return await call.answer(admin_texts.DeleteCondition.empty, show_alert=True)
        await call.message.edit_text(admin_texts.DeleteCondition.choose, reply_markup=admin_keyboards.delete_condition_menu(giveaway_id, conditions))
        return await call.answer()

    elif data[0] == "delete_condition":
        giveaway_id = int(data[1])
        condition_id = int(data[2])
        await state.clear()
        async with get_session() as session:
            giveaway = await get_giveaway(session, giveaway_id)
            if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
            condition = await get_condition(session, condition_id)
            if condition is None or condition.giveaway_id != giveaway_id: return await call.answer(admin_texts.DeleteCondition.not_found, show_alert=True)
            await delete_condition(session, condition)
            conditions = await list_giveaway_conditions(session, giveaway_id)

        await call.message.edit_text(build_conditions_screen_text(giveaway, conditions), reply_markup=admin_keyboards.conditions_menu(giveaway_id))
        return await call.answer(admin_texts.DeleteCondition.deleted)

    elif data[0] == "delete_giveaway":
        giveaway_id = int(data[1])
        async with get_session() as session: giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None:
            await state.clear()
            return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)

        await state.set_state(admin_states.DeleteGiveaway.confirm)
        await state.update_data(delete_giveaway_id=giveaway_id)
        await call.message.answer(admin_texts.DeleteGiveaway.confirm(giveaway.name))

    elif data[0] in {"open_giveaway", "close_giveaway"}:
        giveaway_id = int(data[1])
        make_active = data[0] == "open_giveaway"
        async with get_session() as session:
            giveaway = await get_giveaway(session, giveaway_id)
            if giveaway is None: return await call.answer(admin_texts.DeleteGiveaway.not_found, show_alert=True)
            giveaway = await update_giveaway(session, giveaway, GiveawayUpdate(active=make_active))

        await call.message.edit_text(str(giveaway), reply_markup=giveaway.admin_keyboard())

    elif data[0] == "create_giveaway":
        await state.set_state(admin_states.CreateGiveaway.name)
        await call.message.edit_text(admin_texts.CreateGiveaway.name, reply_markup=admin_keyboards.back_markup("main_menu"))

    elif data[0] == "admin_menu":
        await state.clear()
        async with get_session() as session: giveaways = await list_giveaways(session)
        await call.message.edit_text(admin_texts.greetings, reply_markup=admin_keyboards.main_menu(giveaways))

    return await call.answer(call.data)
