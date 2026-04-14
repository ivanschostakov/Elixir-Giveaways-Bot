from typing import Any
from dataclasses import fields, dataclass
from pydantic import BaseModel

from src.database.models import Condition


def build_condition_payload(condition_cls: type[dataclass], orm_model: Condition, config_cls: type[BaseModel]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in fields(condition_cls):
        name = field.name
        if name.startswith("_") or name == "logger": continue
        if hasattr(orm_model, name): payload[name] = getattr(orm_model, name)

    config = config_cls.model_validate(orm_model.config or {})
    payload.update(config.model_dump())
    return payload
