from datetime import datetime

from pydantic import BaseModel, field_validator


class WebsiteReviewConfig(BaseModel):
    start_date: datetime
    min_grade: int | None = None
    min_length: int | None = None

    @field_validator("min_grade", "min_length", mode="before")
    @classmethod
    def normalize_optional_int(cls, value: object) -> object:
        if value in ("", "-", None): return None
        return value

    @field_validator("min_grade")
    @classmethod
    def validate_min_grade(cls, value: int | None) -> int | None:
        if value is None: return value
        if not 0 <= value <= 5: raise ValueError("min_grade must be between 0 and 5")
        return value

    @field_validator("min_length")
    @classmethod
    def validate_min_length(cls, value: int | None) -> int | None:
        if value is None: return value
        if value < 0: raise ValueError("min_length must be non-negative")
        return value
