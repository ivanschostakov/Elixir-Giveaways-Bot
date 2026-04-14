from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from logging import Logger, getLogger

from config import DATETIME_FORMAT, UFA_TZ
from src.database.models import Condition
from src.enums.results import APIResult


@dataclass
class BaseCondition(ABC):
    id: int
    giveaway_id: int
    action: str
    mandatory: bool
    repeatable: bool
    reward: int | None

    logger: Logger | None
    _name: str

    def __post_init__(self):
        if not self.logger: self.logger = self.logger = getLogger(f"{self.__class__.__module__}.{self.__class__.__name__} #{self.id}")
        if self.action == "self_join":
            self.repeatable = False
        if self.repeatable and self.reward is None:
            raise ValueError("Repeatable condition must have reward set")

    @property
    def log(self): return self.logger

    @staticmethod
    def parse_user_datetime(raw: str) -> datetime:
        parsed = datetime.strptime(raw.strip(), DATETIME_FORMAT)
        return parsed.replace(tzinfo=UFA_TZ)

    @abstractmethod
    async def check(self, *args, **kwargs) -> APIResult: ...

    @classmethod
    @abstractmethod
    def from_orm(cls, orm_model: Condition) -> "BaseCondition": ...
