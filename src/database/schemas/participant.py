from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ParticipantBase(BaseModel):
    giveaway_id: int
    user_id: int
    last_email: str | None = None


class ParticipantCreate(ParticipantBase):
    pass


class ParticipantUpdate(BaseModel):
    giveaway_id: int | None = None
    user_id: int | None = None
    last_email: str | None = None


class ParticipantRead(ParticipantBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
