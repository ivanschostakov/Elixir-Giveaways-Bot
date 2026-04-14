from dataclasses import dataclass
from aiogram.types import CallbackQuery, Message

from src.condition.configs import RefJoinConfig, SelfJoinConfig, build_condition_payload
from src.database.models import Condition
from src.enums import VALID_MEMBER_STATUSES, JoinResult, FailResult, RefJoinResult
from src.condition.base import BaseCondition


def _resolve_actor_user_id(obj: CallbackQuery | Message) -> int:
    if isinstance(obj, Message):
        return int(obj.chat.id)
    return int(obj.from_user.id)


@dataclass
class SelfJoin(BaseCondition):
    chat_id: str
    _name = "␚ Подписка/вход"

    def __str__(self) -> str: return f"Канал/чат: {self.chat_id}"

    @staticmethod
    def parse_chat_id(raw: str) -> str:
        normalized = raw.strip()
        if not normalized: raise ValueError("chat_id cannot be empty")
        return normalized

    async def check(self, call: CallbackQuery) -> JoinResult | FailResult:
        user_id = _resolve_actor_user_id(call)
        try:
            user = await call.bot.get_chat_member(self.chat_id, user_id)
            if user.status not in VALID_MEMBER_STATUSES: return FailResult(404, f"Вы <b>не являетесь участником</b> в {self.chat_id}")
            else: return JoinResult(200, f"Вы <b>являетесь участником</b> в {self.chat_id}", self.reward or None, user_id, self.chat_id)

        except Exception as e:
            self.log.info(e)
            return FailResult(500, f"<b>Ошибка при проверке</b>\n{e}")

    @classmethod
    def from_orm(cls, orm_model: Condition) -> "SelfJoin":
        payload = build_condition_payload(cls, orm_model, SelfJoinConfig)
        return cls(logger=None, _name=cls._name, **payload)

@dataclass
class RefJoin(BaseCondition):
    chat_id: str
    _name = "🔗 Приглашение друзей"

    def __str__(self) -> str: return f"Канал/чат: {self.chat_id}"

    @staticmethod
    def parse_chat_id(raw: str) -> str:
        normalized = raw.strip()
        if not normalized: raise ValueError("chat_id cannot be empty")
        return normalized

    async def check(self, obj: CallbackQuery | Message, ref_id: int | None = None) -> RefJoinResult | FailResult:
        if ref_id is None: return FailResult(400, "реферальная ссылка недействительна: отсутствует ref_id")
        user_id = _resolve_actor_user_id(obj)
        try:
            user = await obj.bot.get_chat_member(self.chat_id, user_id)
            if user.status not in VALID_MEMBER_STATUSES: return FailResult(404, f"Вы <b>не являетесь участником</b> в {self.chat_id}")
            else: return RefJoinResult(200, f"Вы <b>являетесь участником</b> в {self.chat_id}", self.reward or None, user_id, self.chat_id, ref_id)

        except Exception as e:
            self.log.info(e)
            return FailResult(500, f"<b>Ошибка при проверке</b>\n{e}")

    @classmethod
    def from_orm(cls, orm_model: Condition) -> "RefJoin":
        payload = build_condition_payload(cls, orm_model, RefJoinConfig)
        return cls(logger=None, _name=cls._name, **payload)
