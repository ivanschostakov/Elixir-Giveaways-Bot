from typing import Any
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import DATE_FORMAT, PLACE_EMOJIS
from .condition import ConditionRead
from .giveaway import GiveawayPrizeSchema, GiveawayRead
from .participant import ParticipantRead
from .participant_record import ParticipantRecordRead
from .user import UserRead


class GiveawayReadWithRelations(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    notes: str | None = None
    prizes: dict[int, GiveawayPrizeSchema]
    start_date: date
    end_date: date | None = None
    active: bool
    created_at: datetime
    updated_at: datetime

    conditions: list[ConditionRead] = Field(default_factory=list)
    participants: list[ParticipantRead] = Field(default_factory=list)

    def __str__(self) -> str:
        description = self.description or "Без описания"
        start_date_text = self.start_date.strftime(DATE_FORMAT)
        end_date_text = "Не указана"
        if self.end_date is not None:
            end_date_text = self.end_date.strftime(DATE_FORMAT)
        prizes_string = "".join(
            f"\n{PLACE_EMOJIS.get(place, '🏅 ')}{prize.name} <i>x{prize.amount}шт.</i>"
            for place, prize in self.prizes.items()
        )
        return (
            f"<b>🎉 РОЗЫГРЫШ №{self.id} ✨️\n{self.name}</b>\n\n{description}\n\n"
            f"⏳ Начало — {start_date_text}\n"
            f"⌛️ Конец — {end_date_text}\n"
            f"📅 <i>По Уфимскому времени</i>"
            f"\n\n<b>🎁 ЧТО МОЖНО ВЫИГРАТЬ 🎁</b>"
            f"{prizes_string}\n\n"
            f"{'‼️ Пожалуйста, <b> обязательно осведомитесь с примечаниями к розыгрышу </b> перед участием' if self.notes else ""}".strip()
        )

    @property
    def admin_keyboard(self) -> InlineKeyboardMarkup:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            []
        ])
        if self.notes: keyboard.inline_keyboard.append([InlineKeyboardButton(text="📝 Примечания", callback_data=f"view_notes:{self.id}")])


    def _keyboard(self, joined: bool | None = False) -> InlineKeyboardMarkup:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        if self.notes: keyboard.inline_keyboard.append([InlineKeyboardButton(text="📝 Примечания", callback_data=f"view_notes:{self.id}")])
        if joined: keyboard.inline_keyboard.append([InlineKeyboardButton(text="👀 Проверить прогресс", callback_data=f"view_progress:{self.id}")])
        else: keyboard.inline_keyboard.append([InlineKeyboardButton(text="🚪 Принять участие", callback_data=f"join:{self.id}")])
        return keyboard

    async def send(self, message: Message, joined: bool = False) -> bool:
        await message.answer(str(self), reply_markup=self._keyboard(joined))
        return True


class UserReadWithRelations(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ref_id: int | None = None
    phone: str | None = None
    first_name: str
    last_name: str | None = None
    blocked_until: datetime | None = None
    created_at: datetime
    updated_at: datetime

    participants: list[ParticipantRead] = Field(default_factory=list)


class ConditionReadWithRelations(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    giveaway_id: int
    action: str
    required: int = 1
    mandatory: bool = False
    repeatable: bool = False
    reward: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    giveaway: GiveawayRead | None = None
    records: list[ParticipantRecordRead] = Field(default_factory=list)


class ParticipantReadWithRelations(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    giveaway_id: int
    user_id: int
    last_email: str | None = None
    created_at: datetime
    updated_at: datetime

    user: UserRead | None = None
    giveaway: GiveawayRead | None = None
    records: list[ParticipantRecordRead] = Field(default_factory=list)


class ParticipantRecordReadWithRelations(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    participant_id: int
    condition_id: int
    passed: bool = False
    complete: int = 0
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    participant: ParticipantRead | None = None
    condition: ConditionRead | None = None
