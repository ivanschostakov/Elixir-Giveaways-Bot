from dataclasses import dataclass, field

from config import (
    AMOCRM_BASE_URL,
    AMOCRM_ACCESS_TOKEN,
    AMOCRM_ACCOUNT_ID,
)
from src.integrations.amocrm.statuses import LossStatuses, WonStatuses


def _default_won_statuses() -> WonStatuses:
    return WonStatuses({
        "paid": 75784946,
        "packaged": 75784942,
        "package_sent": 76566302,
        "package_delivered": 76566306,
        "won": 142,
    })


def _default_loss_statuses() -> LossStatuses:
    return LossStatuses({
        "main": 81419122,
        "invoice_sent": 75784938,
        "waiting_reply": 74461446,
        "waiting_reply_2": 82756582,
        "canceled": 82657618,
        "return_refund": 143,
    })


@dataclass
class AmoCfg:
    pipeline_id: int = 9280278
    won_statuses: WonStatuses = field(default_factory=_default_won_statuses)
    loss_statuses: LossStatuses = field(default_factory=_default_loss_statuses)

    timeout: float = 30.0
    limit: int = 50
    max_pages: int = 20

    base_url: str = AMOCRM_BASE_URL
    access_token: str = AMOCRM_ACCESS_TOKEN
    account_id: str = AMOCRM_ACCOUNT_ID

    @property
    def won_statuses_list(self) -> list[int]: return self.won_statuses.to_list

    @property
    def loss_statuses_list(self) -> list[int]: return self.loss_statuses.to_list
