from dataclasses import dataclass
from datetime import datetime

from config import DATETIME_FORMAT, UFA_TZ
from src.condition.configs import WebsiteReviewConfig, build_condition_payload
from src.database.models import Condition
from src.enums import ReviewResult, FailResult
from src.condition.base import BaseCondition
from src.integrations.bitrix24.exceptions import BitrixAPIError


@dataclass
class WebsiteReview(BaseCondition):
    min_grade: int | None
    min_length: int | None
    start_date: datetime

    _name = "💬 Отзыв на сайте"

    def __post_init__(self):
        super().__post_init__()
        if self.min_length is None:
            self.min_length = 0
        elif self.min_length < 0: raise ValueError("Minimum length must be non-negative")

        if self.min_grade is None: self.min_grade = 0
        elif not 0 <= self.min_grade <= 5: raise ValueError("Minimum grade must be in range between 0 and 5")

        if not self.start_date.tzinfo: self.start_date = self.start_date.replace(tzinfo=UFA_TZ)
        else: self.start_date = self.start_date.astimezone(UFA_TZ)

    def __str__(self) -> str:
        details: list[str] = []
        if self.min_grade > 0: details.append(f"Минимальная оценка: <b>{self.min_grade}</b>")
        if self.min_length > 0: details.append(f"Минимальная длина отзыва: <b>{self.min_length}</b>")
        details.append(f"Проверка отзывов с: <b>{self.start_date.strftime(DATETIME_FORMAT)}</b>")
        return "\n".join(details)

    def _review_requirements_text(self) -> str:
        requirements: list[str] = []
        if self.min_length > 0: requirements.append(f"от {self.min_length} символов")
        if self.min_grade > 0: requirements.append(f"с оценкой >= {self.min_grade}")
        requirements.append(f"написан от {self.start_date.strftime(DATETIME_FORMAT)} по Уфимскому времени")
        return ", ".join(requirements)

    @classmethod
    def parse_start_date(cls, raw: str) -> datetime:
        return cls.parse_user_datetime(raw)

    @staticmethod
    def parse_min_grade(raw: str) -> int:
        value = int(raw.strip())
        if not 0 <= value <= 5: raise ValueError("min_grade must be between 0 and 5")
        return value

    @staticmethod
    def parse_min_length(raw: str) -> int:
        value = int(raw.strip())
        if value < 0: raise ValueError("min_length must be non-negative")
        return value

    async def check(self, email: str, exclude_review_ids: set[int] | None = None) -> ReviewResult | FailResult:
        from src.integrations.bitrix24 import bitrix24
        try:
            id_user = await bitrix24.get_user_id_by_email(email)
        except BitrixAPIError as exc:
            if exc.error in {"not_found", "missing_user_id"}:
                status_code = 404
                message = f"пользователь <b>не был найден по почте {email}</b>"
                return FailResult(status_code, message)

            self.log.error(
                "Website review lookup failed | email=%s status=%s error=%s payload=%r",
                email,
                exc.status_code,
                exc.error,
                exc.payload,
            )
            return FailResult(503, "проверка отзывов на сайте временно недоступна. Попробуйте немного позже.")

        if not id_user:
            status_code = 404
            message = f"пользователь <b>не был найден по почте {email}</b>"
            return FailResult(status_code, message)

        else:
            try:
                reviews = await bitrix24.find_reviews(id_user, self.start_date, self.min_grade, self.min_length)
            except BitrixAPIError as exc:
                self.log.error(
                    "Website review search failed | email=%s user_id=%s status=%s error=%s payload=%r",
                    email,
                    id_user,
                    exc.status_code,
                    exc.error,
                    exc.payload,
                )
                return FailResult(503, "проверка отзывов на сайте временно недоступна. Попробуйте немного позже.")

            excluded = exclude_review_ids or set()
            review = next((r for r in reviews if r.id not in excluded and r.files), None)
            if not review: review = next((r for r in reviews if r.id not in excluded), None)
            if not review:
                status_code = 404
                requirements_text = self._review_requirements_text()
                if excluded: message = f"по данной почте <b>не найдено новых отзывов</b>, которые еще не были засчитаны в этом условии\n\nОтзыв должен быть <i>{requirements_text}</i>"
                else: message = f"по данной почте <b>не было найдено опубликованных отзывов</b>, совпадающих условиям розыгрыша\n\nОтзыв должен быть <i>{requirements_text}</i>"
                return FailResult(status_code, message)

            else:
                status_code = 200
                message = f"по данной почте был найден <b>совпадающий условиям розыгрыша отзыв</b> 🥳"
                if review.files: message += "\nОстальные обязательные условия <b>тоже засчитаны, так как ваш отзыв имел прикрепленные фотографии</b>"
                return ReviewResult(status_code, message, grade=review.rating, length=len(review.text), review_id=review.id, reward=self.reward or None, files=review.files)

    @classmethod
    def from_orm(cls, orm_model: Condition) -> "WebsiteReview":
        payload = build_condition_payload(cls, orm_model, WebsiteReviewConfig)
        return cls(logger=None, _name=cls._name, **payload)
