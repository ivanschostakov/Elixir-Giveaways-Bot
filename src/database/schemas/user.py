from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    phone = phone.strip()
    return phone or None


class UserBase(BaseModel):
    ref_id: int | None = None
    phone: str | None = None
    first_name: str
    last_name: str | None = None
    blocked_until: datetime | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return _normalize_phone(value)


class UserCreate(UserBase):
    id: int


class UserUpdate(BaseModel):
    ref_id: int | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    blocked_until: datetime | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return _normalize_phone(value)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
