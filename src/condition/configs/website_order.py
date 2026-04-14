from datetime import datetime

from pydantic import BaseModel, field_validator


class WebsiteOrderConfig(BaseModel):
    min_price: float
    start_date: datetime

    @field_validator("min_price", mode="before")
    @classmethod
    def normalize_min_price(cls, value: object) -> object:
        if value in ("", "-", None): return 0.0
        return value

    @field_validator("min_price")
    @classmethod
    def validate_min_price(cls, value: float) -> float:
        if value < 0: raise ValueError("min_price must be non-negative")
        return value
