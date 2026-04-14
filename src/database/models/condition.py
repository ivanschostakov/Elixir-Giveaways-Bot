from typing import Any, ClassVar
from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base, IdPkMixin, TimestampMixin


class Condition(Base, IdPkMixin, TimestampMixin):
    __tablename__ = "conditions"

    ACTION_ALIASES: ClassVar[dict[str, str]] = {
        "join_self": "self_join",
        "join_ref": "ref_join",
    }
    YES_VALUES: ClassVar[set[str]] = {"yes", "y", "да", "д", "true", "1"}
    NO_VALUES: ClassVar[set[str]] = {"no", "n", "нет", "н", "false", "0"}

    giveaway_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("giveaways.id", ondelete="CASCADE"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    required: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    repeatable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    reward: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))

    giveaway: Mapped["Giveaway"] = relationship(back_populates="conditions")
    records: Mapped[list["ParticipantRecord"]] = relationship(
        back_populates="condition",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("NOT repeatable OR reward IS NOT NULL", name="ck_conditions_repeatable_reward"),
    )

    @staticmethod
    def is_self_join_action(action: str | None) -> bool:
        return action == "self_join"

    @classmethod
    def parse_action(cls, value: str | None) -> str | None:
        if value is None: return None
        normalized = value.strip().lower()
        if not normalized: return None
        return cls.ACTION_ALIASES.get(normalized, normalized)

    @classmethod
    def parse_yes_no(cls, value: str | None) -> bool | None:
        if value is None: return None
        normalized = value.strip().lower()
        if normalized in cls.YES_VALUES: return True
        if normalized in cls.NO_VALUES: return False
        return None

    @staticmethod
    def parse_positive_int(value: str | None) -> int | None:
        if value is None: return None
        try: parsed = int(value.strip())
        except (TypeError, ValueError): return None
        if parsed <= 0: return None
        return parsed

    @classmethod
    def can_configure_required(cls, action: str | None) -> bool:
        return not cls.is_self_join_action(action)

    @staticmethod
    def parse_repeat_limit(value: str | None) -> int | None:
        if value is None: raise ValueError("repeat limit is required")
        normalized = value.strip().lower()
        if normalized in {"inf", "infinity", "infinite", "∞", "none", "null", "-"}: return None
        parsed = int(normalized)
        if parsed < 1: raise ValueError("repeat limit must be >= 1")
        return parsed

    @classmethod
    def resolve_max_repeats(
        cls,
        action: str | None,
        repeatable: bool | None,
        config: dict[str, Any] | None,
        required: int | None = None,
    ) -> int | None:
        if cls.is_self_join_action(action): return 1
        minimum_repeats = max(int(required or 1), 1)

        raw_limit = (config or {}).get("max_repeats")
        if raw_limit is None:
            base_limit = None if bool(repeatable) else 1
            return None if base_limit is None else max(base_limit, minimum_repeats)
        try: parsed = int(raw_limit)
        except (TypeError, ValueError):
            base_limit = None if bool(repeatable) else 1
            return None if base_limit is None else max(base_limit, minimum_repeats)
        return max(parsed, minimum_repeats)

    @classmethod
    def normalize_rules(
        cls,
        action: str | None,
        *,
        required: int | None = None,
        repeatable: bool | None = None,
        reward: int | None = None,
    ) -> tuple[int, bool, int | None]:
        if required is None: normalized_required = 1
        else:
            try: normalized_required = max(int(required), 1)
            except (TypeError, ValueError): normalized_required = 1
        normalized_repeatable = bool(repeatable)
        normalized_reward = reward

        if cls.is_self_join_action(action):
            normalized_required = 1
            normalized_repeatable = False

        return normalized_required, normalized_repeatable, normalized_reward
