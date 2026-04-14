from datetime import date, datetime
from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import Boolean, Date, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config import DATE_FORMAT, PLACE_EMOJIS, UFA_TZ
from src.database import Base, IdPkMixin, TimestampMixin
from src.enums.giveaway_prize import GiveawayPrize


class Giveaway(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "giveaways"

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    prizes: Mapped[dict[int, GiveawayPrize]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    winners: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False, default=lambda: datetime.now(tz=UFA_TZ).date())
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    participants: Mapped[list["Participant"]] = relationship(back_populates="giveaway", cascade="all, delete-orphan")
    conditions: Mapped[list["Condition"]] = relationship(back_populates="giveaway",cascade="all, delete-orphan")

    def __str__(self) -> str:
        from src.database.schemas.giveaway import _normalize_prizes
        description = self.description or "Без описания"
        start_date_text = self.start_date.strftime(DATE_FORMAT)
        end_date_text = "Не указана"
        if self.end_date is not None:
            end_date_text = self.end_date.strftime(DATE_FORMAT)
        prizes_string = "".join(
            f"\n{PLACE_EMOJIS.get(place, '🏅 ')}{prize.name} <i>x{prize.amount}.</i>"
            for place, prize in _normalize_prizes(self.prizes.items()).items()
        )
        return (
            f"<b>🆔 <code>{self.id}</code>️\n{self.name}</b>\n\n{description}\n\n"
            f"⏳ Начало — {start_date_text}\n"
            f"⌛️ Конец — {end_date_text}\n"
            f"<i>По Уфимскому времени</i>"
            f"\n\n<b>🎁 ЧТО МОЖНО ВЫИГРАТЬ 🎁</b>"
            f"{prizes_string}\n\n"
            f"{'‼️ Пожалуйста, <b> обязательно осведомитесь с примечаниями к розыгрышу </b> перед участием' if self.notes else ""}".strip()
        )

    def user_str(self) -> str:
        from src.database.schemas.giveaway import _normalize_prizes
        description = self.description or "Без описания"
        start_date_text = self.start_date.strftime(DATE_FORMAT)
        end_date_text = "Не указана"
        if self.end_date is not None:
            end_date_text = self.end_date.strftime(DATE_FORMAT)
        prizes_string = "".join(
            f"\n{PLACE_EMOJIS.get(place, '🏅 ')}{prize.name} <i>x{prize.amount}.</i>"
            for place, prize in _normalize_prizes(self.prizes.items()).items()
        )
        return (
            f"<b>{self.name}</b>\n\n{description}\n\n"
            f"⏳ Начало — {start_date_text}\n"
            f"⌛️ Конец — {end_date_text}\n"
            f"<i>По Уфимскому времени</i>"
            f"\n\n<b>🎁 ЧТО МОЖНО ВЫИГРАТЬ 🎁</b>"
            f"{prizes_string}\n\n"
            f"{'‼️ Пожалуйста, <b>обязательно ознакомьтесь с примечаниями к розыгрышу</b> перед участием' if self.notes else ""}".strip()
        )
    def admin_keyboard(self) -> InlineKeyboardMarkup:
        from src.bot.keyboards.admin import back
        inline_keyboard = [
            [InlineKeyboardButton(text="👥 Участники", callback_data=f"view_participants:{self.id}"),
             InlineKeyboardButton(text="🔐 Закрыть" if self.active else "🔓 Открыть", callback_data=f"{'close' if self.active else 'open'}_giveaway:{self.id}")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data=f"edit_giveaway:{self.id}"),
             InlineKeyboardButton(text="📑 Условия", callback_data=f"conditions:{self.id}")],
            [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_giveaway:{self.id}")],
            [back("admin_menu")]
        ]

        if self.notes: inline_keyboard.insert(0, [InlineKeyboardButton(text="‼️ Примечания", callback_data=f"notes:{self.id}")])
        return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
