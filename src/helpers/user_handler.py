import logging

from datetime import datetime
from html import escape
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram.utils.deep_linking import create_start_link

from config import ADMIN_TELEGRAM_IDS, UFA_TZ
from src.bot.keyboards import user_keyboards
from src.bot.states.user import UserConditionInput
from src.bot.texts import user_texts
from src.bot.texts.review_examples import REVIEW_LENGTH_EXAMPLES_TEXT
from src.condition import ConditionType
from src.database import get_session
from src.database.crud import (
    create_participant_record,
    get_condition,
    get_participant,
    get_participant_by_giveaway_user,
    get_participant_record_by_condition,
    get_user,
    list_giveaway_conditions,
    list_giveaways,
    list_records_by_participant,
    list_records_by_condition,
    update_participant_record,
    update_user,
)
from src.database.crud.user import ensure_user
from src.database.models import Condition
from src.database.schemas import ParticipantRecordCreate, ParticipantRecordUpdate, UserUpdate
from src.helpers.user import (
    _log_condition_check_crashed,
    _log_condition_check_finished,
    _log_condition_check_started,
    _propagate_photo_review,
    _review_email_from_config,
    _review_ids_from_config,
    _review_photo_from_config,
    is_valid_email,
    notify,
    process_text_condition,
    show_progress,
)

logger = logging.getLogger("user_router")


def _extract_referral_ids(record) -> list[int]:
    if record is None:
        return []
    raw_referrals = (record.config or {}).get("referrals", [])
    return sorted({int(value) for value in raw_referrals if str(value).isdigit()})


def _referral_complete_count(record) -> int:
    return len(_extract_referral_ids(record))


async def _mandatory_conditions_complete(
    session,
    *,
    giveaway_id: int,
    participant_id: int,
) -> bool:
    conditions = await list_giveaway_conditions(session, giveaway_id)
    mandatory_ids = [condition.id for condition in conditions if condition.mandatory]
    if not mandatory_ids: return True

    records = await list_records_by_participant(session, participant_id)
    passed_ids = {record.condition_id for record in records if record.passed}
    return all(condition_id in passed_ids for condition_id in mandatory_ids)


async def _ensure_optional_condition_unlocked(
    call: CallbackQuery,
    session,
    *,
    participant,
    condition,
) -> bool:
    if condition.mandatory:
        return True

    is_ready = await _mandatory_conditions_complete(
        session,
        giveaway_id=condition.giveaway_id,
        participant_id=participant.id,
    )
    if is_ready:
        return True

    await call.answer(user_texts.complete_mandatory_first, show_alert=True)
    return False


def _resolve_contact_user_id(message: Message) -> int | None:
    if message.contact is None:
        return None

    sender_user_id = int(message.chat.id)
    contact_user_id = int(message.contact.user_id) if isinstance(message.contact.user_id, int) else sender_user_id
    return sender_user_id if contact_user_id != sender_user_id else contact_user_id


async def process_winner_contact(message: Message, *, logger: logging.Logger) -> None:
    if message.contact is None:
        return

    contact = message.contact
    contact_user_id = _resolve_contact_user_id(message)
    if contact_user_id is None:
        return

    matched_giveaways: list[tuple[int, str, str]] = []
    async with get_session() as session:
        giveaways = await list_giveaways(session)
        changed = False
        for giveaway in giveaways:
            winners = giveaway.winners if isinstance(giveaway.winners, list) else []
            normalized_winners: list = []
            giveaway_changed = False
            for winner in winners:
                if not isinstance(winner, dict):
                    normalized_winners.append(winner)
                    continue

                winner_copy = dict(winner)
                try:
                    winner_user_id = int(winner_copy.get("user_id"))
                except Exception:
                    normalized_winners.append(winner_copy)
                    continue

                if winner_user_id == contact_user_id:
                    winner_copy["phone_shared"] = True
                    winner_copy["phone_number"] = contact.phone_number
                    winner_copy["phone_shared_at"] = datetime.now(tz=UFA_TZ).isoformat()
                    giveaway_changed = True
                    place = winner_copy.get("place")
                    matched_giveaways.append((int(giveaway.id), giveaway.name, str(place) if place is not None else "?"))

                normalized_winners.append(winner_copy)

            if giveaway_changed:
                giveaway.winners = normalized_winners
                changed = True

        if changed:
            await session.commit()

    if not matched_giveaways:
        await message.answer("Спасибо, контакт получен.", reply_markup=ReplyKeyboardRemove())
        return

    lines = [
        "📞 Победитель отправил номер телефона.",
        f"Telegram ID: <code>{contact_user_id}</code>",
        f"Телефон: <code>{escape(contact.phone_number)}</code>",
        "",
        "<b>Розыгрыши:</b>",
    ]
    for giveaway_id, giveaway_name, place in matched_giveaways:
        lines.append(f"• #{giveaway_id} {escape(giveaway_name)} — место {escape(place)}")
    admin_text = "\n".join(lines)

    for admin_id in ADMIN_TELEGRAM_IDS:
        try:
            first_name = getattr(message.chat, "first_name", None) or getattr(message.from_user, "first_name", None) or "Победитель"
            last_name = getattr(message.chat, "last_name", None) or getattr(message.from_user, "last_name", None) or ""
            await message.bot.send_message(admin_id, admin_text)
            await message.bot.send_contact(
                admin_id,
                phone_number=contact.phone_number,
                first_name=first_name,
                last_name=last_name,
            )
        except Exception:
            logger.exception("Failed to send winner contact to admin | admin_id=%s | user_id=%s", admin_id, contact_user_id)

    await message.answer("Спасибо! Номер телефона отправлен администраторам.", reply_markup=ReplyKeyboardRemove())


async def handle_pass_condition_callback(
    call: CallbackQuery,
    *,
    giveaway_id: int,
    condition_id: int,
    logger: logging.Logger,
):
    async with get_session() as session:
        await ensure_user(session, call)
        participant = await get_participant_by_giveaway_user(session, giveaway_id, call.from_user.id)
        if participant is None: return await call.answer(user_texts.need_join_first, show_alert=True)

        condition = await get_condition(session, condition_id)
        if condition is None or condition.giveaway_id != giveaway_id or condition.action != "self_join": return await call.answer("Это условие недоступно для проверки.", show_alert=True)
        if not await _ensure_optional_condition_unlocked(call, session, participant=participant, condition=condition):
            return
        check_context = {
            "user_id": call.from_user.id,
            "participant_id": participant.id,
        }

        try:
            runtime = ConditionType[condition.action].value.from_orm(condition)
            check_context["chat_id"] = getattr(runtime, "chat_id", None)
            _log_condition_check_started(logger, condition, **check_context)
            result = await runtime.check(call)
        except Exception:
            _log_condition_check_crashed(logger, condition, **check_context)
            return await call.answer("Не удалось проверить условие.", show_alert=True)

        _log_condition_check_finished(logger, condition, result, **check_context)
        if not getattr(result, "success", False):
            await notify(call.message, result.message, giveaway_id=giveaway_id)
            return await call.answer("Условие не выполнено.", show_alert=True)

        record = await get_participant_record_by_condition(session, participant.id, condition.id)
        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        completed_count = max(int(record.complete or 0), 0) if record is not None else 0
        if max_repeats is not None and completed_count >= max_repeats:
            return await call.answer(user_texts.already_counted, show_alert=True)

        new_complete = (record.complete if record else 0) + 1
        if max_repeats is not None:
            new_complete = min(new_complete, max_repeats)
        new_passed = new_complete >= 1
        new_config = dict(record.config or {}) if record is not None else {}

        if record is None:
            await create_participant_record(
                session,
                ParticipantRecordCreate(
                    participant_id=participant.id,
                    condition_id=condition.id,
                    passed=new_passed,
                    complete=new_complete,
                    config=new_config,
                ),
            )
        else:
            await update_participant_record(
                session,
                record,
                ParticipantRecordUpdate(passed=new_passed, complete=new_complete, config=new_config),
            )

    await notify(call.message, result.message, giveaway_id=giveaway_id)
    await show_progress(call.message, giveaway_id, call.from_user.id, edit=True)
    return await call.answer()


async def _handle_text_condition_input_callback(
    call: CallbackQuery,
    state: FSMContext,
    *,
    giveaway_id: int,
    condition_id: int,
    expected_action: str,
    next_state,
    prompt_text: str,
    prompt_giveaway_id: int | None,
):
    async with get_session() as session:
        await ensure_user(session, call)
        participant = await get_participant_by_giveaway_user(session, giveaway_id, call.from_user.id)
        if participant is None:
            return await call.answer(user_texts.need_join_first, show_alert=True)

        condition = await get_condition(session, condition_id)
        if condition is None or condition.giveaway_id != giveaway_id or condition.action != expected_action:
            return await call.answer(user_texts.condition_not_available, show_alert=True)
        if not await _ensure_optional_condition_unlocked(call, session, participant=participant, condition=condition):
            return

        record = await get_participant_record_by_condition(session, participant.id, condition.id)
        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        completed_count = max(int(record.complete or 0), 0) if record is not None else 0
        if max_repeats is not None and completed_count >= max_repeats:
            return await call.answer(user_texts.already_counted, show_alert=True)

    await state.set_state(next_state)
    await state.update_data(condition_giveaway_id=giveaway_id, condition_id=condition_id)
    await notify(call.message, prompt_text, giveaway_id=prompt_giveaway_id, delete_after=120.0)
    return await call.answer()


async def handle_pass_order_condition_callback(
    call: CallbackQuery,
    state: FSMContext,
    *,
    giveaway_id: int,
    condition_id: int,
):
    return await _handle_text_condition_input_callback(
        call,
        state,
        giveaway_id=giveaway_id,
        condition_id=condition_id,
        expected_action="website_order",
        next_state=UserConditionInput.order_code,
        prompt_text=user_texts.order_code_prompt,
        prompt_giveaway_id=giveaway_id,
    )


async def handle_pass_review_condition_callback(call: CallbackQuery, state: FSMContext, *, giveaway_id: int, condition_id: int):
    async with get_session() as session:
        await ensure_user(session, call)
        participant = await get_participant_by_giveaway_user(session, giveaway_id, call.from_user.id)
        if participant is None: return await call.answer(user_texts.need_join_first, show_alert=True)

        condition = await get_condition(session, condition_id)
        if condition is None or condition.giveaway_id != giveaway_id or condition.action != "website_review": return await call.answer(user_texts.condition_not_available, show_alert=True)
        if not await _ensure_optional_condition_unlocked(call, session, participant=participant, condition=condition): return

        record = await get_participant_record_by_condition(session, participant.id, condition.id)
        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        completed_count = max(int(record.complete or 0), 0) if record is not None else 0
        if max_repeats is not None and completed_count >= max_repeats: return await call.answer(user_texts.already_counted, show_alert=True)

        saved_email = (participant.last_email or "").strip().lower()

    if is_valid_email(saved_email):
        await state.set_state(UserConditionInput.review_email)
        await state.update_data(condition_giveaway_id=giveaway_id, condition_id=condition_id)
        await process_text_condition(call.message, state, expected_action="website_review", config_key="email", submitted_value=saved_email)
        return await call.answer()

    await call.message.answer(REVIEW_LENGTH_EXAMPLES_TEXT)
    return await _handle_text_condition_input_callback(
        call,
        state,
        giveaway_id=giveaway_id,
        condition_id=condition_id,
        expected_action="website_review",
        next_state=UserConditionInput.review_email,
        prompt_text=user_texts.review_email_prompt,
        prompt_giveaway_id=None,
    )


async def handle_recheck_review_condition_callback(
    call: CallbackQuery,
    *,
    giveaway_id: int,
    condition_id: int,
    logger: logging.Logger,
):
    async with get_session() as session:
        await ensure_user(session, call)
        participant = await get_participant_by_giveaway_user(session, giveaway_id, call.from_user.id)
        if participant is None:
            return await call.answer(user_texts.need_join_first, show_alert=True)

        condition = await get_condition(session, condition_id)
        if condition is None or condition.giveaway_id != giveaway_id or condition.action != "website_review":
            return await call.answer(user_texts.condition_not_available, show_alert=True)

        record = await get_participant_record_by_condition(session, participant.id, condition.id)
        if record is None or not record.passed:
            return await call.answer(user_texts.condition_not_available, show_alert=True)

        saved_email = _review_email_from_config(record.config or {})
        if not saved_email or not is_valid_email(saved_email):
            return await call.answer(user_texts.condition_not_available, show_alert=True)
        check_context = {
            "user_id": call.from_user.id,
            "participant_id": participant.id,
            "submitted_value": saved_email,
            "recheck": True,
        }

        try:
            runtime = ConditionType[condition.action].value.from_orm(condition)
            _log_condition_check_started(logger, condition, **check_context)
            result = await runtime.check(saved_email)
        except Exception:
            _log_condition_check_crashed(logger, condition, **check_context)
            return await call.answer(user_texts.condition_check_error, show_alert=True)
        _log_condition_check_finished(logger, condition, result, **check_context)
        if not getattr(result, "success", False):
            await notify(call.message, result.message, giveaway_id=giveaway_id)
            return await call.answer()

        old_config = dict(record.config or {})
        new_config = dict(record.config or {})
        new_config["email"] = saved_email
        new_config.pop("review_emails", None)
        new_config.pop("legacy_review_emails", None)
        new_config["photo"] = _review_photo_from_config(new_config) or bool(getattr(result, "files", False))
        new_config.pop("photo_review", None)
        config_changed = new_config != old_config
        completed_missing_mandatory = 0

        if config_changed:
            await update_participant_record(
                session,
                record,
                ParticipantRecordUpdate(config=new_config),
            )

        if bool(getattr(result, "files", False)):
            completed_missing_mandatory = await _propagate_photo_review(
                session,
                giveaway_id=giveaway_id,
                participant_id=participant.id,
                source_condition_id=condition.id,
                email=saved_email,
                review_ids=_review_ids_from_config(new_config),
            )

        recheck_message = f"{result.message}\n\n<i>{user_texts.review_recheck_note}</i>"
        if completed_missing_mandatory > 0:
            recheck_message = f"{recheck_message}\n<i>{user_texts.review_recheck_mandatory_completed}</i>"
        elif not config_changed:
            recheck_message = f"{recheck_message}\n<i>{user_texts.review_recheck_no_changes}</i>"
        await notify(call.message, recheck_message, giveaway_id=giveaway_id)

    await show_progress(call.message, giveaway_id, call.from_user.id, edit=True)
    return await call.answer()


async def handle_get_ref_link_callback(call: CallbackQuery, *, giveaway_id: int, condition_id: int):
    logger.info(
        "Referral link requested | user_id=%s | giveaway_id=%s | condition_id=%s",
        call.from_user.id,
        giveaway_id,
        condition_id,
    )
    async with get_session() as session:
        await ensure_user(session, call)
        participant = await get_participant_by_giveaway_user(session, giveaway_id, call.from_user.id)
        if participant is None:
            logger.warning(
                "Referral link denied: participant missing | user_id=%s | giveaway_id=%s | condition_id=%s",
                call.from_user.id,
                giveaway_id,
                condition_id,
            )
            return await call.answer(user_texts.need_join_first, show_alert=True)

        condition = await get_condition(session, condition_id)
        if condition is None or condition.giveaway_id != giveaway_id or condition.action != "ref_join":
            logger.warning(
                "Referral link denied: invalid condition | user_id=%s | giveaway_id=%s | condition_id=%s | condition_exists=%s | actual_giveaway_id=%s | action=%s",
                call.from_user.id,
                giveaway_id,
                condition_id,
                condition is not None,
                getattr(condition, "giveaway_id", None),
                getattr(condition, "action", None),
            )
            return await call.answer("Реферальное условие не найдено.", show_alert=True)
        if not await _ensure_optional_condition_unlocked(call, session, participant=participant, condition=condition):
            logger.info(
                "Referral link denied: optional condition locked | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s",
                call.from_user.id,
                participant.id,
                giveaway_id,
                condition_id,
            )
            return None

        record = await get_participant_record_by_condition(session, participant.id, condition.id)
        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        completed_count = _referral_complete_count(record)
        if record is not None and max(int(record.complete or 0), 0) != completed_count:
            logger.warning(
                "Referral link count mismatch detected | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s | stored_complete=%s | referrals_count=%s",
                call.from_user.id,
                participant.id,
                giveaway_id,
                condition_id,
                max(int(record.complete or 0), 0),
                completed_count,
            )
            normalized_passed = completed_count >= max(condition.required, 1)
            await update_participant_record(
                session,
                record,
                ParticipantRecordUpdate(passed=normalized_passed, complete=completed_count),
            )
            logger.info(
                "Referral link record normalized | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s | normalized_complete=%s | normalized_passed=%s",
                call.from_user.id,
                participant.id,
                giveaway_id,
                condition_id,
                completed_count,
                normalized_passed,
            )
        logger.info(
            "Referral link prerequisites loaded | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s | record_exists=%s | completed_count=%s | max_repeats=%s",
            call.from_user.id,
            participant.id,
            giveaway_id,
            condition_id,
            record is not None,
            completed_count,
            max_repeats,
        )
        if max_repeats is not None and completed_count >= max_repeats:
            logger.info(
                "Referral link denied: max repeats reached | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s | completed_count=%s | max_repeats=%s",
                call.from_user.id,
                participant.id,
                giveaway_id,
                condition_id,
                completed_count,
                max_repeats,
            )
            return await call.answer(user_texts.already_counted, show_alert=True)

    url = await create_start_link(call.bot, payload=f"condition_id={condition_id}&participant_id={participant.id}", encode=True)
    logger.info(
        "Referral link generated | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s",
        call.from_user.id,
        participant.id,
        giveaway_id,
        condition_id,
    )
    await call.message.answer(
        f"{user_texts.ref_link_text.replace('*', escape(url))}",
        reply_markup=user_keyboards.ref_link_menu(url, giveaway_id),
    )
    logger.info(
        "Referral link delivered | user_id=%s | participant_id=%s | giveaway_id=%s | condition_id=%s",
        call.from_user.id,
        participant.id,
        giveaway_id,
        condition_id,
    )
    return await call.answer()


async def handle_confirm_ref_join_callback(
    call: CallbackQuery,
    *,
    condition_id: int,
    participant_id: int,
    logger: logging.Logger,
):
    logger.info(
        "Referral confirmation started | user_id=%s | condition_id=%s | participant_id=%s",
        call.from_user.id,
        condition_id,
        participant_id,
    )
    async with get_session() as session:
        await ensure_user(session, call)
        condition = await get_condition(session, condition_id)
        ref_participant = await get_participant(session, participant_id)
        if condition is None or ref_participant is None or condition.action != "ref_join" or ref_participant.giveaway_id != condition.giveaway_id:
            logger.warning(
                "Referral confirmation denied: invalid deep link | user_id=%s | condition_id=%s | participant_id=%s | condition_exists=%s | participant_exists=%s | condition_action=%s | condition_giveaway_id=%s | participant_giveaway_id=%s",
                call.from_user.id,
                condition_id,
                participant_id,
                condition is not None,
                ref_participant is not None,
                getattr(condition, "action", None),
                getattr(condition, "giveaway_id", None),
                getattr(ref_participant, "giveaway_id", None),
            )
            return await call.answer(user_texts.ref_link_invalid, show_alert=True)

        logger.info(
            "Referral confirmation context resolved | user_id=%s | inviter_user_id=%s | inviter_participant_id=%s | giveaway_id=%s",
            call.from_user.id,
            ref_participant.user_id,
            ref_participant.id,
            condition.giveaway_id,
        )

        if ref_participant.user_id == call.from_user.id:
            logger.warning(
                "Referral confirmation denied: self referral | user_id=%s | condition_id=%s | participant_id=%s",
                call.from_user.id,
                condition_id,
                participant_id,
            )
            return await call.answer(user_texts.ref_self, show_alert=True)

        check_context = {
            "user_id": call.from_user.id,
            "participant_id": participant.id,
            "inviter_user_id": ref_participant.user_id,
            "ref_id": ref_participant.user_id,
        }
        try:
            runtime = ConditionType[condition.action].value.from_orm(condition)
            check_context["chat_id"] = getattr(runtime, "chat_id", None)
            _log_condition_check_started(logger, condition, **check_context)
            result = await runtime.check(call, ref_id=ref_participant.user_id)
        except Exception:
            _log_condition_check_crashed(logger, condition, **check_context)
            return await call.answer("Не удалось проверить условие.", show_alert=True)

        _log_condition_check_finished(logger, condition, result, **check_context)
        if not getattr(result, "success", False):
            logger.info(
                "Referral confirmation denied: subscription check failed | user_id=%s | inviter_user_id=%s | condition_id=%s",
                call.from_user.id,
                ref_participant.user_id,
                condition_id,
            )
            await notify(call.message, result.message, giveaway_id=condition.giveaway_id)
            return await call.answer("Условие не выполнено.", show_alert=True)

        condition_records = await list_records_by_condition(session, condition.id)
        logger.info(
            "Referral records loaded for duplicate scan | user_id=%s | inviter_user_id=%s | condition_id=%s | total_records=%s",
            call.from_user.id,
            ref_participant.user_id,
            condition_id,
            len(condition_records),
        )
        for condition_record in condition_records:
            if condition_record.participant_id == ref_participant.id: continue
            raw_other_referrals = (condition_record.config or {}).get("referrals", [])
            other_referrals = {int(value) for value in raw_other_referrals if str(value).isdigit()}
            if call.from_user.id in other_referrals:
                logger.warning(
                    "Referral confirmation denied: user already bound to another inviter record | user_id=%s | inviter_user_id=%s | conflicting_participant_id=%s | condition_id=%s",
                    call.from_user.id,
                    ref_participant.user_id,
                    condition_record.participant_id,
                    condition_id,
                )
                await notify(call.message, user_texts.ref_already_bound, giveaway_id=condition.giveaway_id)
                return await call.answer()

        record = await get_participant_record_by_condition(session, ref_participant.id, condition.id)
        referrals = _extract_referral_ids(record)
        completed_count = len(referrals)
        if record is not None and max(int(record.complete or 0), 0) != completed_count:
            logger.warning(
                "Referral inviter count mismatch detected | user_id=%s | inviter_user_id=%s | inviter_participant_id=%s | condition_id=%s | stored_complete=%s | referrals_count=%s",
                call.from_user.id,
                ref_participant.user_id,
                ref_participant.id,
                condition_id,
                max(int(record.complete or 0), 0),
                completed_count,
            )
            normalized_passed = completed_count >= max(condition.required, 1)
            await update_participant_record(
                session,
                record,
                ParticipantRecordUpdate(passed=normalized_passed, complete=completed_count),
            )
            logger.info(
                "Referral inviter record normalized | user_id=%s | inviter_user_id=%s | inviter_participant_id=%s | condition_id=%s | normalized_complete=%s | normalized_passed=%s",
                call.from_user.id,
                ref_participant.user_id,
                ref_participant.id,
                condition_id,
                completed_count,
                normalized_passed,
            )
        logger.info(
            "Referral inviter record loaded | user_id=%s | inviter_user_id=%s | inviter_participant_id=%s | condition_id=%s | record_exists=%s | completed_count=%s | referrals_count=%s",
            call.from_user.id,
            ref_participant.user_id,
            ref_participant.id,
            condition_id,
            record is not None,
            completed_count,
            len(referrals),
        )

        if call.from_user.id in referrals:
            logger.info(
                "Referral confirmation denied: duplicate referral | user_id=%s | inviter_user_id=%s | condition_id=%s",
                call.from_user.id,
                ref_participant.user_id,
                condition_id,
            )
            await notify(call.message, user_texts.ref_duplicate, giveaway_id=condition.giveaway_id)
            return await call.answer()

        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        if max_repeats is not None and completed_count >= max_repeats:
            logger.info(
                "Referral confirmation denied: inviter max repeats reached | user_id=%s | inviter_user_id=%s | condition_id=%s | completed_count=%s | max_repeats=%s",
                call.from_user.id,
                ref_participant.user_id,
                condition_id,
                completed_count,
                max_repeats,
            )
            return await call.answer(user_texts.already_counted, show_alert=True)

        invited_user = await get_user(session, call.from_user.id)
        if invited_user is not None and invited_user.ref_id is not None and invited_user.ref_id != ref_participant.user_id:
            logger.warning(
                "Referral confirmation denied: user already bound in users table | user_id=%s | current_ref_id=%s | requested_ref_id=%s | condition_id=%s",
                call.from_user.id,
                invited_user.ref_id,
                ref_participant.user_id,
                condition_id,
            )
            await notify(call.message, user_texts.ref_already_bound, giveaway_id=condition.giveaway_id)
            return await call.answer()

        referrals = sorted(set(referrals + [call.from_user.id]))
        config = dict(record.config or {}) if record is not None else {}
        config["referrals"] = referrals

        new_complete = len(referrals)
        if max_repeats is not None:
            new_complete = min(new_complete, max_repeats)
        new_passed = new_complete >= max(condition.required, 1)
        logger.info(
            "Referral confirmation will persist record | user_id=%s | inviter_user_id=%s | inviter_participant_id=%s | condition_id=%s | previous_complete=%s | new_complete=%s | new_passed=%s | referrals_count=%s",
            call.from_user.id,
            ref_participant.user_id,
            ref_participant.id,
            condition_id,
            completed_count,
            new_complete,
            new_passed,
            len(config["referrals"]),
        )

        if record is None:
            logger.info(
                "Referral confirmation creating inviter record | user_id=%s | inviter_participant_id=%s | condition_id=%s",
                call.from_user.id,
                ref_participant.id,
                condition_id,
            )
            await create_participant_record(session, ParticipantRecordCreate(participant_id=ref_participant.id, condition_id=condition.id, passed=new_passed, complete=new_complete, config=config))
        else:
            logger.info(
                "Referral confirmation updating inviter record | user_id=%s | inviter_participant_id=%s | condition_id=%s | record_id=%s",
                call.from_user.id,
                ref_participant.id,
                condition_id,
                record.id,
            )
            await update_participant_record(session, record, ParticipantRecordUpdate(passed=new_passed, complete=new_complete, config=config))
        if invited_user is not None and invited_user.ref_id is None:
            logger.info(
                "Referral confirmation binding invited user | user_id=%s | ref_id=%s | condition_id=%s",
                call.from_user.id,
                ref_participant.user_id,
                condition_id,
            )
            await update_user(session, invited_user, UserUpdate(ref_id=ref_participant.user_id))

    logger.info(
        "Referral confirmation completed | user_id=%s | inviter_user_id=%s | condition_id=%s",
        call.from_user.id,
        ref_participant.user_id,
        condition_id,
    )
    await notify(call.message, result.message, giveaway_id=condition.giveaway_id)
    return await call.answer("Условие засчитано.", show_alert=True)


__all__ = [
    "handle_confirm_ref_join_callback",
    "handle_get_ref_link_callback",
    "handle_pass_condition_callback",
    "handle_pass_order_condition_callback",
    "handle_pass_review_condition_callback",
    "process_winner_contact",
]
