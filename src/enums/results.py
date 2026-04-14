from dataclasses import dataclass

@dataclass
class APIResult:
    status_code: int
    message: str

@dataclass
class FailResult(APIResult):
    success = False
    def __post_init__(self):
        if not self.status_code // 100 in [4 , 5]: raise ValueError("Status code must be in range [400; 600)")
        self.message = f"😢 Сожалеем, {self.message}"

@dataclass
class SuccessResult(APIResult):
    success = True
    def __post_init__(self):
        if self.status_code // 100 != 2: raise ValueError("Status code must be in range [200; 300)")
        self.message = f"🎉 Поздравляем, {self.message}"

@dataclass
class ConditionCheckResult(SuccessResult):
    reward: int | None

    def __post_init__(self):
        super().__post_init__()
        if self.reward: self.message += f"\n<i>🎟️ За успешное выполнение условия вам насчитано {self.reward} билет(а/ов) 🥳</i>"

@dataclass
class LeadResult(ConditionCheckResult):
    price: int
    action: str = "lead"

@dataclass
class ReviewResult(ConditionCheckResult):
    grade: int
    length: int
    review_id: int | None = None
    files: bool = False
    action: str = "review"

@dataclass
class JoinResult(ConditionCheckResult):
    user_id: int
    chat_id: str

@dataclass
class RefJoinResult(JoinResult):
    ref_id: int
