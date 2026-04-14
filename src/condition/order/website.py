from datetime import datetime
from dataclasses import dataclass

from config import UFA_TZ, DATETIME_FORMAT
from src.condition.configs import WebsiteOrderConfig, build_condition_payload
from src.database.models import Condition
from src.enums import LeadResult, FailResult
from src.condition.base import BaseCondition


@dataclass
class WebsiteOrder(BaseCondition):
    min_price: float
    start_date: datetime

    _name = "🛍️ Заказ с сайта"

    def __post_init__(self):
        super().__post_init__()
        self.min_price = round(self.min_price, 2)
        if not self.start_date.tzinfo: self.start_date = self.start_date.replace(tzinfo=UFA_TZ)
        else: self.start_date = self.start_date.astimezone(UFA_TZ)

    def __str__(self) -> str:
        details: list[str] = []
        if self.min_price > 0:
            details.append(f"Минимальная сумма заказа: <b>{self.min_price:.2f}₽</b>")
        details.append(f"Проверка заказов с: <b>{self.start_date.strftime(DATETIME_FORMAT)}</b>")
        return "\n".join(details)

    @staticmethod
    def parse_min_price(raw: str) -> float:
        value = float(raw.strip().replace(",", "."))
        if value < 0:
            raise ValueError("min_price must be non-negative")
        return value

    @classmethod
    def parse_start_date(cls, raw: str) -> datetime:
        return cls.parse_user_datetime(raw)

    async def check(self, order_code: str | int) -> LeadResult | FailResult:
        from src.integrations.amocrm import amocrm
        order_code_text = str(order_code).strip()
        try:
            lead = await amocrm.get_lead(order_code_text, source="website")
        except LookupError:
            return FailResult(404, f"заказ <b>не был найден</b> по коду {order_code_text}")

        if lead.created_at is None:
            status_code = 400
            message = f"заказ <b>найден</b> по коду {order_code_text}, но у него <b>не указано время создания</b>"

        elif lead.created_at < self.start_date:
            status_code = 400
            message = (f"заказ <b>должен быть совершен не ранее {self.start_date.strftime(DATETIME_FORMAT)}</b> по Уфимскому времени\n"
                       f"<i>Время совершения заказа {order_code_text} — {lead.created_at.strftime(DATETIME_FORMAT)}</i>")

        elif lead.price is None:
            status_code = 400
            message = f"у заказа {order_code_text} <b>не указана сумма</b>, поэтому условие проверить нельзя"

        elif lead.price < self.min_price:
            status_code = 400
            message = f"стоимость данного заказа <b>меньше требуемой суммы в {self.min_price}₽</b>"

        else:
            status_code = 200
            message = f"заказ под номером {order_code_text} <b>успешно засчитан</b>"

        if status_code == 200:
            result = LeadResult(status_code=status_code, message=message, price=lead.price, reward=self.reward or None)

        else: result = FailResult(status_code, message)
        return result

    @classmethod
    def from_orm(cls, orm_model: Condition) -> "WebsiteOrder":
        payload = build_condition_payload(cls, orm_model, WebsiteOrderConfig)
        return cls(logger=None, _name=cls._name, **payload)
