import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.keyboards import admin_keyboards
from src.bot.texts import admin_texts
from src.helpers.common import _build_prizes_payload
from src.database import get_session
from src.database.crud import create_giveaway, get_giveaway, update_giveaway
from src.database.models import Giveaway
from src.database.schemas import GiveawayCreate, GiveawayUpdate

logger = logging.getLogger("admin_router")


async def _reply_or_edit(message: Message, text: str, *, reply_markup=None) -> None:
    if message.from_user and message.bot and message.from_user.id == message.bot.id:
        await message.edit_text(text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def create_giveaway_from_state(state: FSMContext) -> Giveaway:
    state_data = await state.get_data()
    giveaway_create = GiveawayCreate.model_validate(
        {
            "name": state_data["name"],
            "description": state_data.get("description"),
            "notes": state_data.get("notes"),
            "prizes": _build_prizes_payload(state_data["prizes"], state_data.get("places")),
            "start_date": state_data["start_date"],
            "end_date": state_data.get("end_date"),
        }
    )

    async with get_session() as session: giveaway_model = await create_giveaway(session, giveaway_create)
    await state.clear()
    return giveaway_model


async def apply_giveaway_update(message: Message, state: FSMContext, giveaway_id: int | None, payload: GiveawayUpdate, back_call: str) -> bool:
    if giveaway_id is None:
        await state.clear()
        await _reply_or_edit(message, admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))
        return False

    try:
        async with get_session() as session:
            giveaway = await get_giveaway(session, int(giveaway_id))
            if giveaway is None:
                await state.clear()
                await _reply_or_edit(message, admin_texts.DeleteGiveaway.not_found, reply_markup=admin_keyboards.back_markup("main_menu"))
                return False

            giveaway = await update_giveaway(session, giveaway, payload)
    except Exception:
        logger.exception("Failed to update giveaway_id=%s", giveaway_id)
        await _reply_or_edit(message, admin_texts.EditGiveaway.update_error, reply_markup=admin_keyboards.back_markup(back_call))
        return False

    await state.clear()
    await message.answer(admin_texts.EditGiveaway.updated)
    await _reply_or_edit(message, str(giveaway), reply_markup=giveaway.admin_keyboard())
    return True
