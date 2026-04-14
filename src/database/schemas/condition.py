from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.database.models import Condition


def _normalize_config(value: Any) -> dict[str, Any]:
    if value is None: return {}
    if not isinstance(value, dict): raise ValueError("config must be a dict")
    return value


def _validate_repeatable_reward(repeatable: bool, reward: int | None) -> None:
    if repeatable and (reward is None or reward <= 0):
        raise ValueError("repeatable condition must have positive reward set")


class ConditionBase(BaseModel):
    giveaway_id: int
    action: str
    required: int = 1
    mandatory: bool = False
    repeatable: bool = False
    reward: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config", mode="before")
    @classmethod
    def validate_config(cls, value: Any) -> dict[str, Any]: return _normalize_config(value)

    @model_validator(mode="after")
    def validate_repeatable_reward(self) -> "ConditionBase":
        self.required, self.repeatable, self.reward = Condition.normalize_rules(
            self.action,
            required=self.required,
            repeatable=self.repeatable,
            reward=self.reward,
        )
        _validate_repeatable_reward(self.repeatable, self.reward)
        return self


class ConditionCreate(ConditionBase):
    pass


class ConditionUpdate(BaseModel):
    giveaway_id: int | None = None
    action: str | None = None
    required: int | None = None
    mandatory: bool | None = None
    repeatable: bool | None = None
    reward: int | None = None
    config: dict[str, Any] | None = None

    @field_validator("config", mode="before")
    @classmethod
    def validate_config(cls, value: Any) -> dict[str, Any] | None:
        if value is None: return None
        return _normalize_config(value)

    @model_validator(mode="after")
    def validate_repeatable_reward(self) -> "ConditionUpdate":
        if self.repeatable is True and "reward" in self.model_fields_set and (self.reward is None or self.reward <= 0):
            raise ValueError("repeatable condition must have positive reward set")
        return self


class ConditionRead(ConditionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
