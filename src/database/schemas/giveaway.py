from typing import Any
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, field_validator

from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

class GiveawayPrizeSchema(BaseModel):
    name: str
    amount: int


def _normalize_prizes(value: Any) -> dict[int, GiveawayPrizeSchema]:
    if not isinstance(value, dict):
        try: value = dict(value)
        except: raise ValueError("prizes must be a dict")
    normalized: dict[int, GiveawayPrizeSchema] = {}
    for key, prize in value.items():
        try: int_key = int(key)
        except (TypeError, ValueError) as exc: raise ValueError("prize keys must be integers") from exc
        if isinstance(prize, GiveawayPrizeSchema): normalized[int_key] = prize
        elif isinstance(prize, dict): normalized[int_key] = GiveawayPrizeSchema.model_validate(prize)
        else: raise ValueError("prize value must be an object with name and amount")

    print(normalized)
    return normalized


class GiveawayBase(BaseModel):
    name: str
    description: str | None = None
    notes: str | None = None
    prizes: dict[int, GiveawayPrizeSchema]
    start_date: date
    end_date: date | None = None
    active: bool = True

    @field_validator("prizes", mode="before")
    @classmethod
    def validate_prizes(cls, value: Any) -> dict[int, GiveawayPrizeSchema]:
        return _normalize_prizes(value)


class GiveawayCreate(GiveawayBase):
    pass


class GiveawayUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    prizes: dict[int, GiveawayPrizeSchema] | None = None
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None

    @field_validator("prizes", mode="before")
    @classmethod
    def validate_prizes(cls, value: Any) -> dict[int, GiveawayPrizeSchema] | None:
        if value is None: return None
        return _normalize_prizes(value)


class GiveawayRead(GiveawayBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
