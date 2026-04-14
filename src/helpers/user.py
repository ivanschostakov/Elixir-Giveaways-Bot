import asyncio
import logging
import re

from html import escape

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import user_keyboards
from src.bot.texts import user_texts
from src.condition import ConditionType
from src.database.crud.participant_record import upsert_participant_record
from src.database.models import Condition
from src.database import get_session
from src.database.crud import create_participant_record, get_condition, get_giveaway, get_participant_by_giveaway_user, get_participant_record_by_condition, list_giveaway_conditions, list_giveaways, list_records_by_condition, list_records_by_participant, update_participant_record
from src.database.crud.user import ensure_user
from src.database.schemas import ParticipantRecordCreate, ParticipantRecordUpdate
from src.enums.results import APIResult
from src.integrations.verification import send_verification_code

logger = logging.getLogger("user_router")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool: return bool(EMAIL_RE.fullmatch(value))
def _message_user_id(message: Message) -> int: return int(message.chat.id)


def _normalize_condition_log_value(value):
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {key: _normalize_condition_log_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize_condition_log_value(item) for item in value]
    return value


def _condition_log_context(condition: Condition, **context) -> str:
    fields = {
        "condition_id": condition.id,
        "action": condition.action,
        "giveaway_id": condition.giveaway_id,
        **context,
    }
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        normalized = _normalize_condition_log_value(value)
        if isinstance(normalized, str):
            parts.append(f"{key}={normalized!r}")
        else:
            parts.append(f"{key}={normalized}")
    return " | ".join(parts)


def _log_condition_check_started(logger: logging.Logger, condition: Condition, **context) -> None:
    logger.info("Condition check started | %s", _condition_log_context(condition, **context))


def _log_condition_check_finished(logger: logging.Logger, condition: Condition, result: APIResult, **context) -> None:
    logger.info(
        "Condition check finished | %s | success=%s | status_code=%s",
        _condition_log_context(condition, **context),
        getattr(result, "success", False),
        getattr(result, "status_code", None),
    )


def _log_condition_check_crashed(logger: logging.Logger, condition: Condition, **context) -> None:
    logger.exception("Condition check crashed | %s", _condition_log_context(condition, **context))


def _config_values(config: dict[str, object], key: str) -> list[str]:
    raw_values = config.get(key)
    if isinstance(raw_values, list):
        items = raw_values
    elif raw_values in (None, ""):
        items = []
    else:
        items = [raw_values]
    return [str(value).strip() for value in items if str(value).strip()]


def _normalized_config_values(config: dict[str, object], key: str) -> set[str]:
    return {value.lower() for value in _config_values(config, key)}


def _single_config_value(config: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        values = _config_values(config, key)
        if values:
            return values[-1]
    return None


def _review_email_from_config(config: dict[str, object]) -> str | None:
    email = _single_config_value(config, "email", "review_emails", "legacy_review_emails")
    if email is None:
        return None
    return email.lower()


def _config_bool_value(config: dict[str, object], *keys: str) -> bool:
    for key in keys:
        if key not in config:
            continue
        value = config.get(key)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)
    return False


def _review_photo_from_config(config: dict[str, object]) -> bool:
    return _config_bool_value(config, "photo", "photo_review")


def _review_ids_from_config(config: dict[str, object]) -> set[int]:
    return {int(value) for value in (config.get("review_ids") or []) if str(value).isdigit()}


def _merge_numeric_config_history(config: dict[str, object], key: str, values: list[int] | set[int]) -> None:
    merged = {int(value) for value in (config.get(key) or []) if str(value).isdigit()}
    merged.update(int(value) for value in values)
    config[key] = sorted(merged)


async def _resolve_order_lead_email(order_code: str) -> str | None:
    from src.integrations.amocrm import amocrm

    try: lead = await amocrm.get_lead(order_code, source="website")
    except LookupError: return None
    except Exception:
        logger.exception("Failed to resolve lead email for order code=%s", order_code)
        return None

    email = (lead.email or "").strip().lower()
    if not is_valid_email(email): return None
    return email


def _schedule_message_delete(message: Message, delete_after: float) -> None:
    async def _delete_later() -> None:
        await asyncio.sleep(delete_after)
        try: await message.delete()
        except Exception: logger.debug("Failed to delete message_id=%s", getattr(message, "message_id", None))

    asyncio.create_task(_delete_later())


async def notify(message: Message, text: str, *, giveaway_id: int | None = None, delete_after: float | None = 30.0) -> Message:
    reply_markup = user_keyboards.back_to_giveaway(giveaway_id) if giveaway_id is not None else None
    sent = await message.answer(text, reply_markup=reply_markup)
    if delete_after is not None and delete_after > 0: _schedule_message_delete(sent, delete_after)
    return sent


def _condition_name(action: str) -> str:
    runtime = ConditionType.__members__.get(action)
    if runtime is None: return action
    return runtime.value._name


def _condition_details_for_user(condition: Condition) -> str | None:
    runtime = ConditionType.__members__.get(condition.action)
    if runtime is None: return None
    try: runtime_condition = runtime.value.from_orm(condition)
    except Exception:
        logger.exception("Failed to build runtime condition details | condition_id=%s", condition.id)
        return None
    details = str(runtime_condition).strip()
    return details or None

async def _send_email_verification(message: Message, state: FSMContext, *, email: str, next_state, extra_data: dict[str, str]) -> None:
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    if not isinstance(giveaway_id, int): giveaway_id = None

    try: verification_code = await send_verification_code(email)
    except Exception:
        logger.exception("Failed to send verification code | email=%s", email)
        await notify(message, user_texts.verification_send_error, giveaway_id=giveaway_id)
        return

    await state.set_state(next_state)
    await state.update_data(
        verification_email=email,
        verification_code_expected=verification_code,
        verification_attempts=0,
        **extra_data,
    )
    await notify(message, f"{user_texts.verification_code_sent.format(email=escape(email))}\n{user_texts.verification_code_prompt}", delete_after=120.0, giveaway_id=giveaway_id)


async def _propagate_photo_review(
    session,
    *,
    giveaway_id: int,
    participant_id: int,
    source_condition_id: int,
    email: str | None,
    review_ids: set[int],
) -> int:
    mandatory_conditions = [condition for condition in await list_giveaway_conditions(session, giveaway_id) if condition.mandatory]
    updated_count = 0
    for mandatory_condition in mandatory_conditions:
        if mandatory_condition.id == source_condition_id:
            continue

        mandatory_record = await get_participant_record_by_condition(session, participant_id, mandatory_condition.id)
        if mandatory_record is not None and mandatory_record.passed:
            continue

        merged_config = dict(mandatory_record.config or {}) if mandatory_record is not None else {}
        merged_config["photo"] = True
        merged_config.pop("photo_review", None)
        merged_config.pop("review_emails", None)
        if email:
            merged_config["email"] = email
        if review_ids:
            _merge_numeric_config_history(merged_config, "review_ids", review_ids)

        if mandatory_record:
            await update_participant_record(
                session,
                mandatory_record,
                ParticipantRecordUpdate(
                    passed=True,
                    complete=mandatory_condition.required,
                    config=merged_config,
                ),
            )
        else:
            await create_participant_record(
                session,
                ParticipantRecordCreate(
                    participant_id=participant_id,
                    condition_id=mandatory_condition.id,
                    passed=True,
                    complete=mandatory_condition.required,
                    config=merged_config,
                ),
            )
        updated_count += 1

    return updated_count


async def process_text_condition(message: Message, state: FSMContext, *, expected_action: str, config_key: str, submitted_value: str) -> None:
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    condition_id = state_data.get("condition_id")
    message_user_id = _message_user_id(message)
    if not isinstance(giveaway_id, int) or not isinstance(condition_id, int):
        await state.clear()
        return await notify(message, user_texts.condition_context_expired)

    async with get_session() as session:
        await ensure_user(session, message)
        participant = await get_participant_by_giveaway_user(session, giveaway_id, message_user_id)
        if participant is None:
            await state.clear()
            return await notify(message, user_texts.need_join_first, giveaway_id=giveaway_id)

        condition = await get_condition(session, condition_id)
        if condition is None or condition.giveaway_id != giveaway_id or condition.action != expected_action:
            await state.clear()
            return await notify(message, user_texts.condition_not_available, giveaway_id=giveaway_id)

        if not condition.mandatory:
            conditions = await list_giveaway_conditions(session, giveaway_id)
            mandatory_ids = [item.id for item in conditions if item.mandatory]
            if mandatory_ids:
                participant_records = await list_records_by_participant(session, participant.id)
                passed_ids = {item.condition_id for item in participant_records if item.passed}
                if not all(condition_id in passed_ids for condition_id in mandatory_ids):
                    await state.clear()
                    return await notify(message, user_texts.complete_mandatory_first, giveaway_id=giveaway_id)

        if expected_action == "website_order":
            cached_email = await _resolve_order_lead_email(submitted_value)
            if cached_email and participant.last_email != cached_email:
                participant.last_email = cached_email
                await session.commit()

        record = await get_participant_record_by_condition(session, participant.id, condition.id)
        max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
        completed_count = max(int(record.complete or 0), 0) if record is not None else 0
        if max_repeats is not None and completed_count >= max_repeats:
            await state.clear()
            await notify(message, user_texts.already_counted, giveaway_id=giveaway_id)
            return await show_progress(message, giveaway_id, message_user_id)

        config = dict(record.config or {}) if record is not None else {}
        normalized = submitted_value.strip().lower()
        seen = _normalized_config_values(config, config_key)
        allow_duplicate_value = expected_action == "website_review" and condition.repeatable
        if normalized in seen and not allow_duplicate_value: return await notify(message, user_texts.already_counted, giveaway_id=giveaway_id)
        if expected_action == "website_order":
            condition_records = await list_records_by_condition(session, condition.id)
            for condition_record in condition_records:
                if record is not None and condition_record.id == record.id: continue
                used_order_codes = (condition_record.config or {}).get("order_codes", [])
                used = {str(value).strip().lower() for value in used_order_codes if str(value).strip()}
                if normalized in used: return await notify(message, user_texts.order_code_already_used, giveaway_id=giveaway_id)
        if expected_action == "website_review":
            condition_records = await list_records_by_condition(session, condition.id)
            for condition_record in condition_records:
                if record is not None and condition_record.id == record.id: continue
                used_review_email = _review_email_from_config(condition_record.config or {})
                if normalized == used_review_email:
                    await state.clear()
                    await notify(message, user_texts.review_email_already_used, giveaway_id=giveaway_id)
                    return await show_progress(message, giveaway_id, message_user_id)

        used_review_ids: set[int] = _review_ids_from_config(config) if expected_action == "website_review" else set()
        check_context = {
            "user_id": message_user_id,
            "participant_id": participant.id,
            "submitted_value": submitted_value,
        }
        if expected_action == "website_review" and condition.repeatable and used_review_ids:
            check_context["exclude_review_ids"] = used_review_ids

        try:
            runtime = ConditionType[condition.action].value.from_orm(condition)
            _log_condition_check_started(logger, condition, **check_context)
            if expected_action == "website_review": result = await runtime.check(submitted_value, exclude_review_ids=used_review_ids if condition.repeatable else None)
            else: result = await runtime.check(submitted_value)

        except Exception:
            _log_condition_check_crashed(logger, condition, **check_context)
            return await notify(message, user_texts.condition_check_error, giveaway_id=giveaway_id)

        _log_condition_check_finished(logger, condition, result, **check_context)
        await notify(message, result.message, giveaway_id=giveaway_id)
        if not getattr(result, "success", False): return

        review_id = getattr(result, "review_id", None)
        if expected_action == "website_review" and condition.repeatable:
            if not isinstance(review_id, int) or review_id <= 0:
                logger.error("Repeatable review condition did not return review_id | condition_id=%s", condition_id)
                return await notify(message, user_texts.condition_check_error, giveaway_id=giveaway_id)

            if review_id in used_review_ids: return await notify(message, user_texts.already_counted, giveaway_id=giveaway_id)
        if isinstance(review_id, int) and review_id > 0:
            _merge_numeric_config_history(config, "review_ids", used_review_ids | {review_id})
            used_review_ids = _review_ids_from_config(config)

        if expected_action == "website_review":
            config["email"] = normalized
            config.pop("review_emails", None)
            config.pop("legacy_review_emails", None)
        else:
            history = _config_values(config, config_key)
            if normalized not in seen:
                history.append(submitted_value)
            config[config_key] = history

        has_photo_review = bool(getattr(result, "files", False))
        config["photo"] = _review_photo_from_config(config) or has_photo_review
        config.pop("photo_review", None)

        if has_photo_review:
            await _propagate_photo_review(
                session,
                giveaway_id=giveaway_id,
                participant_id=participant.id,
                source_condition_id=condition_id,
                email=_review_email_from_config(config),
                review_ids=used_review_ids,
            )
        new_complete = (record.complete if record else 0) + 1
        if max_repeats is not None: new_complete = min(new_complete, max_repeats)
        new_passed = new_complete >= max(condition.required, 1)

        await upsert_participant_record(session, participant_id=participant.id, condition_id=condition_id, passed=new_passed, complete=new_complete, config=config)

    await state.clear()
    await show_progress(message, giveaway_id, message_user_id)


async def show_main_menu(message: Message, actor: Message | CallbackQuery, *, edit: bool = False) -> None:
    async with get_session() as session:
        await ensure_user(session, actor)
        giveaways = [giveaway for giveaway in await list_giveaways(session) if giveaway.active]

    text = user_texts.main_menu if giveaways else user_texts.no_giveaways
    reply_markup = user_keyboards.main_menu(giveaways) if giveaways else None
    if edit:
        await message.edit_text(text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_giveaway(message: Message, giveaway_id: int, user_id: int, *, edit: bool = False) -> bool:
    async with get_session() as session:
        giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None or not giveaway.active:
            if edit: await message.edit_text(user_texts.giveaway_not_found)
            else: await message.answer(user_texts.giveaway_not_found)
            return False

        participant = await get_participant_by_giveaway_user(session, giveaway_id, user_id)

    reply_markup = user_keyboards.giveaway_menu(giveaway_id, joined=participant is not None, has_notes=bool(giveaway.notes))
    if edit:
        await message.edit_text(giveaway.user_str(), reply_markup=reply_markup)
        return True
    await message.answer(giveaway.user_str(), reply_markup=reply_markup)
    return True


async def show_progress(message: Message, giveaway_id: int, user_id: int, *, edit: bool = False) -> bool:
    async with get_session() as session:
        giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None or not giveaway.active:
            if edit: await message.edit_text(user_texts.giveaway_not_found)
            else: await message.answer(user_texts.giveaway_not_found)
            return False

        participant = await get_participant_by_giveaway_user(session, giveaway_id, user_id)
        if participant is None:
            #if edit: await message.edit_text(user_texts.need_join_first)
            #else: await message.answer(user_texts.need_join_first)
            return False

        conditions = await list_giveaway_conditions(session, giveaway_id)
        records = await list_records_by_participant(session, participant.id)

    if not conditions:
        if edit: await message.edit_text(user_texts.progress_empty)
        else: await message.answer(user_texts.progress_empty)
        return True

    records_map = {record.condition_id: record for record in records}
    text_lines = [f"<b>📊 Прогресс — {escape(giveaway.name)}</b>"]
    rows: list[tuple[str, str]] = []
    mandatory_conditions = [condition for condition in conditions if condition.mandatory]
    additional_conditions = [condition for condition in conditions if not condition.mandatory]
    mandatory_ready = all(records_map.get(condition.id) and records_map[condition.id].passed for condition in mandatory_conditions)

    def _append_condition_line(condition, index: int, *, is_mandatory: bool) -> None:
        record = records_map.get(condition.id)
        complete = record.complete if record else 0
        required = 1 if condition.action == "self_join" else max(condition.required, 1)
        passed = bool(record and record.passed)
        status_emoji = "✅" if passed else "❌"
        text_lines.append(f"{index}. {status_emoji} <b>{_condition_name(condition.action)}</b> <i>{complete}/{required}</i>")
        details = _condition_details_for_user(condition)
        if details:
            for detail_line in details.splitlines():
                normalized_line = detail_line.strip()
                if normalized_line: text_lines.append(f"   <i>↳ {normalized_line}</i>")

        button_status = "✅" if passed else "❌"
        title = _condition_name(condition.action)
        group_prefix = "⚠️ " if is_mandatory else "➕ "
        button_title = f"{group_prefix} {title}"
        if not is_mandatory and not mandatory_ready: button_title = f"🔒 {button_title}"

        callback_data: str
        if len(title) > 45:
            title = title[:44] + "…"
            button_title = f"{group_prefix} {title}"
            if not is_mandatory and not mandatory_ready: button_title = f"🔒 {button_title}"

        if condition.action == "self_join": callback_data = f"pass_condition:{giveaway_id}:{condition.id}"
        elif condition.action == "ref_join": callback_data = f"get_ref_link:{giveaway_id}:{condition.id}"
        elif condition.action == "website_order": callback_data = f"pass_order_condition:{giveaway_id}:{condition.id}"
        elif condition.action == "website_review": callback_data = f"pass_review_condition:{giveaway_id}:{condition.id}"
        else:
            callback_data = f"condition_unavailable:{giveaway_id}:{condition.id}"
            button_title = f"{button_title} (скоро)"

        rows.append((f"{button_status} {button_title}", callback_data))
        if condition.action == "website_review" and passed and record is not None and _review_email_from_config(record.config or {}):
            rows.append(("🔄 Перепроверить отзыв", f"recheck_review_condition:{giveaway_id}:{condition.id}"))

    text_lines.append("")
    text_lines.append("<b>Обязательные условия:</b>")
    if not mandatory_conditions: text_lines.append("Нет обязательных условий.")
    else:
        for index, condition in enumerate(mandatory_conditions, start=1): _append_condition_line(condition, index, is_mandatory=True)

    text_lines.append("")
    text_lines.append("<b>Дополнительные условия:</b>")
    if not additional_conditions: text_lines.append("Нет дополнительных условий.")
    else:
        for index, condition in enumerate(additional_conditions, start=1): _append_condition_line(condition, index, is_mandatory=False)

    if additional_conditions and not mandatory_ready:
        text_lines.append("")
        text_lines.append("<i>Дополнительные условия откроются после выполнения всех обязательных.</i>")

    text_lines.append("")
    text_lines.append("<i>Чтобы участвовать в розыгрыше, нужно выполнить все обязательные условия. Дополнительные условия нужны для получения дополнительных билетов и повышения шансов на победу.</i>")
    if any(c.action == "website_review" for c in mandatory_conditions): text_lines.append("Так же, если Вы оставляли отзыв с фотографией 🖼️, то <b>все обязательные условия будут засчитаны автоматически</b>")

    text = "\n".join(text_lines)
    reply_markup = user_keyboards.progress_menu(giveaway_id, rows)
    if edit:
        await message.edit_text(text, reply_markup=reply_markup)
        return True

    await message.answer(text, reply_markup=reply_markup)
    return True
