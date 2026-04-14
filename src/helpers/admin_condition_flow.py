import logging

from html import escape

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.keyboards import admin_keyboards
from src.bot.states import admin_states
from src.bot.texts import admin_texts
from src.helpers.common import _bool_word
from src.condition import ConditionType
from src.database import get_session
from src.database.crud import create_condition, get_giveaway, list_giveaway_conditions
from src.database.models import Condition, Giveaway
from src.database.schemas import ConditionCreate

logger = logging.getLogger("admin_router")


async def _reply_or_edit(message: Message, text: str, *, reply_markup=None) -> None:
    if message.from_user and message.bot and message.from_user.id == message.bot.id:
        await message.edit_text(text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


def _format_condition_text(condition: Condition) -> str:
    max_repeats = Condition.resolve_max_repeats(condition.action, condition.repeatable, condition.config, condition.required)
    repeat_limit_text = "∞" if max_repeats is None else str(max_repeats)
    required, repeatable, reward = Condition.normalize_rules(
        condition.action,
        required=condition.required,
        repeatable=condition.repeatable,
        reward=condition.reward,
    )
    common_info_parts = [
        f"Требуется выполнений: <b>{required}</b>",
        f"Обязательное: <b>{_bool_word(condition.mandatory)}</b>",
        f"Повторяемое: <b>{_bool_word(repeatable)}</b>",
        f"Лимит повторов: <b>{repeat_limit_text}</b>",
    ]
    if reward is not None:
        common_info_parts.append(f"Награда: <b>{reward}</b>")
    common_info = " · ".join(common_info_parts)
    try:
        runtime_cls = ConditionType[condition.action].value
        runtime_condition = runtime_cls.from_orm(condition)
        return (
            f"<b>{runtime_condition._name}</b>\n"
            f"{runtime_condition}\n"
            f"<i>{common_info}</i>"
        )
    except Exception:
        logger.exception("Failed to build runtime condition for condition_id=%s", condition.id)
        return (
            f"<b>{escape(condition.action)}</b>\n"
            f"Конфиг: <code>{escape(str(condition.config))}</code>\n"
            f"<i>{common_info}</i>"
        )


def conditions_back_markup(giveaway_id: int | None):
    if giveaway_id is None: return admin_keyboards.back_markup("main_menu")
    return admin_keyboards.back_markup(f"conditions:{giveaway_id}")


async def update_condition_config(state: FSMContext, **values) -> None:
    state_data = await state.get_data()
    current = dict(state_data.get("condition_config") or {})
    current.update(values)
    await state.update_data(condition_config=current)


async def normalize_condition_state_rules(state: FSMContext) -> tuple[str | None, int, bool, int | None, int | None]:
    state_data = await state.get_data()
    action = state_data.get("condition_action")
    raw_repeat_limit = state_data.get("condition_repeat_limit")
    if action == "self_join":
        repeat_limit = 1
    else:
        if raw_repeat_limit is None:
            repeat_limit = None if bool(state_data.get("condition_repeatable")) else 1
        else:
            try:
                repeat_limit = max(int(raw_repeat_limit), 1)
            except (TypeError, ValueError):
                repeat_limit = 1
    repeatable_input = action != "self_join" and (repeat_limit is None or repeat_limit > 1)
    required, repeatable, reward = Condition.normalize_rules(
        action,
        required=state_data.get("condition_required"),
        repeatable=repeatable_input,
        reward=state_data.get("condition_reward"),
    )
    if repeat_limit is not None:
        repeat_limit = max(repeat_limit, required)
    await state.update_data(
        condition_required=required,
        condition_repeatable=repeatable,
        condition_reward=reward,
        condition_repeat_limit=repeat_limit,
    )
    return action, required, repeatable, reward, repeat_limit


def build_conditions_screen_text(giveaway: Giveaway, conditions: list[Condition]) -> str:
    if not conditions:
        conditions_text = "Условия пока не добавлены."
    else:
        conditions_text = "\n\n".join(
            f"{index}. {_format_condition_text(condition)}"
            for index, condition in enumerate(conditions, start=1)
        )
    return f"<b>📑 Условия розыгрыша #{giveaway.id} — {escape(giveaway.name)}</b>\n\n{conditions_text}"


async def show_conditions_screen(message: Message, giveaway_id: int) -> bool:
    async with get_session() as session:
        giveaway = await get_giveaway(session, giveaway_id)
        if giveaway is None:
            await _reply_or_edit(message, admin_texts.DeleteGiveaway.not_found)
            return False
        conditions = await list_giveaway_conditions(session, giveaway_id)

    await _reply_or_edit(
        message,
        build_conditions_screen_text(giveaway, conditions),
        reply_markup=admin_keyboards.conditions_menu(giveaway_id),
    )
    return True


async def go_to_condition_specific_flow(message: Message, state: FSMContext) -> bool:
    state_data = await state.get_data()
    action = state_data.get("condition_action")
    giveaway_id = state_data.get("condition_giveaway_id")
    back_markup = conditions_back_markup(giveaway_id)
    back_call = f"conditions:{giveaway_id}" if giveaway_id is not None else "main_menu"

    if action == "website_order":
        await state.set_state(admin_states.CreateWebsiteOrderCondition.min_price)
        await _reply_or_edit(
            message,
            admin_texts.CreateCondition.order_min_price,
            reply_markup=admin_keyboards.condition_order_min_price(back_call=back_call),
        )
        return True

    if action == "website_review":
        await state.set_state(admin_states.CreateWebsiteReviewCondition.start_date)
        await _reply_or_edit(
            message,
            admin_texts.CreateCondition.review_start_date,
            reply_markup=admin_keyboards.skip("condition_review_start_date", back_call=back_call),
        )
        return True

    if action == "self_join":
        await state.set_state(admin_states.CreateSelfJoinCondition.chat_id)
        await _reply_or_edit(message, admin_texts.CreateCondition.join_username, reply_markup=back_markup)
        return True

    if action == "ref_join":
        await state.set_state(admin_states.CreateRefJoinCondition.chat_id)
        await _reply_or_edit(message, admin_texts.CreateCondition.join_username, reply_markup=back_markup)
        return True

    await _reply_or_edit(message, admin_texts.CreateCondition.action_error, reply_markup=back_markup)
    return False


async def go_to_condition_required_flow(message: Message, state: FSMContext) -> None:
    state_data = await state.get_data()
    action = state_data.get("condition_action")
    if not Condition.can_configure_required(action):
        await normalize_condition_state_rules(state)
        await go_to_condition_specific_flow(message, state)
        return

    giveaway_id = state_data.get("condition_giveaway_id")
    await state.set_state(admin_states.CreateCondition.required)
    await _reply_or_edit(message, admin_texts.CreateCondition.required, reply_markup=conditions_back_markup(giveaway_id))


async def finalize_condition_creation(message: Message, state: FSMContext) -> bool:
    state_data = await state.get_data()
    giveaway_id = state_data.get("condition_giveaway_id")
    if giveaway_id is None:
        await state.clear()
        await _reply_or_edit(message, admin_texts.CreateCondition.create_error)
        return False

    action, required, repeatable, reward, repeat_limit = await normalize_condition_state_rules(state)
    config = dict(state_data.get("condition_config") or {})
    config["max_repeats"] = repeat_limit
    payload = {
        "giveaway_id": int(giveaway_id),
        "action": action,
        "required": required,
        "mandatory": bool(state_data.get("condition_mandatory")),
        "repeatable": repeatable,
        "reward": reward,
        "config": config,
    }

    try:
        condition_create = ConditionCreate.model_validate(payload)
        async with get_session() as session:
            giveaway = await get_giveaway(session, int(giveaway_id))
            if giveaway is None:
                await state.clear()
                await _reply_or_edit(message, admin_texts.DeleteGiveaway.not_found)
                return False
            await create_condition(session, condition_create)
    except Exception:
        logger.exception("Failed to create condition for giveaway_id=%s", giveaway_id)
        await _reply_or_edit(message, admin_texts.CreateCondition.create_error, reply_markup=conditions_back_markup(giveaway_id))
        return False

    await state.clear()
    await message.answer(admin_texts.CreateCondition.created)
    return await show_conditions_screen(message, int(giveaway_id))
