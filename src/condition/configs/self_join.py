from pydantic import BaseModel, field_validator


class SelfJoinConfig(BaseModel):
    chat_id: str

    @field_validator("chat_id", mode="before")
    @classmethod
    def normalize_chat_id(cls, value: object) -> str:
        if value is None: raise ValueError("chat_id is required")
        normalized = str(value).strip()
        if not normalized: raise ValueError("chat_id cannot be empty")
        return normalized
