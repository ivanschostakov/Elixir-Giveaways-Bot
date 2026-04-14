from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_config(value: Any) -> dict[str, Any]:
    if value is None: return {}
    if not isinstance(value, dict): raise ValueError("config must be a dict")
    return value


class ParticipantRecordBase(BaseModel):
    participant_id: int
    condition_id: int
    passed: bool = False
    complete: int = 0
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config", mode="before")
    @classmethod
    def validate_config(cls, value: Any) -> dict[str, Any]: return _normalize_config(value)


class ParticipantRecordCreate(ParticipantRecordBase): pass
class ParticipantRecordUpdate(BaseModel):
    participant_id: int | None = None
    condition_id: int | None = None
    passed: bool | None = None
    complete: int | None = None
    config: dict[str, Any] | None = None

    @field_validator("config", mode="before")
    @classmethod
    def validate_config(cls, value: Any) -> dict[str, Any] | None:
        if value is None: return None
        return _normalize_config(value)


class ParticipantRecordRead(ParticipantRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
