from .order.website import WebsiteOrder
from .review.website import WebsiteReview
from .telegram.join import SelfJoin, RefJoin
from .base import BaseCondition

from enum import Enum

class ConditionType(Enum):
    website_order = WebsiteOrder
    website_review = WebsiteReview
    self_join = SelfJoin
    ref_join = RefJoin

__all__ = [
    "BaseCondition",
    "WebsiteOrder",
    "WebsiteReview",
    "SelfJoin", "RefJoin",
    "ConditionType",
]
