"""separate_website_order_and_review_again

Revision ID: 5a39fd3142dd
Revises: 505074661731
Create Date: 2026-02-19 10:04:19.787217

"""
import json
from datetime import datetime, timezone
from typing import Any
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a39fd3142dd'
down_revision: Union[str, Sequence[str], None] = '505074661731'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_int(value: Any, *, default: int | None = None) -> int | None:
    if value in (None, "", "-"):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _should_split(config: dict[str, Any]) -> bool:
    return any(key in config for key in ("unified_order_review", "review_start_date", "min_grade", "min_length"))


def _build_review_config(order_config: dict[str, Any]) -> dict[str, Any]:
    fallback_start = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
    start_date = (
        order_config.get("review_start_date")
        or order_config.get("start_date")
        or fallback_start
    )
    config: dict[str, Any] = {
        "start_date": start_date,
        "min_grade": _as_int(order_config.get("min_grade"), default=None),
        "min_length": _as_int(order_config.get("min_length"), default=None),
    }
    if "max_repeats" in order_config:
        config["max_repeats"] = order_config.get("max_repeats")
    return config


def _clean_order_config(order_config: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(order_config)
    cleaned.pop("review_start_date", None)
    cleaned.pop("min_grade", None)
    cleaned.pop("min_length", None)
    cleaned.pop("unified_order_review", None)
    return cleaned


def _normalize_emails(values: list[Any] | Any) -> list[str]:
    if not isinstance(values, list):
        return []
    emails = {
        str(value).strip().lower()
        for value in values
        if str(value).strip()
    }
    return sorted(emails)


def upgrade() -> None:
    """Split merged website_order + review data back into two conditions."""
    bind = op.get_bind()

    order_conditions = bind.execute(
        sa.text(
            """
            SELECT id, giveaway_id, required, mandatory, repeatable, reward, config
            FROM conditions
            WHERE action = 'website_order'
            ORDER BY id
            """
        )
    ).mappings().all()

    select_review_by_giveaway_stmt = sa.text(
        """
        SELECT id, required, config
        FROM conditions
        WHERE giveaway_id = :giveaway_id AND action = 'website_review'
        ORDER BY id
        LIMIT 1
        """
    )

    insert_review_condition_stmt = sa.text(
        """
        INSERT INTO conditions (giveaway_id, action, required, mandatory, repeatable, reward, config)
        VALUES (
            :giveaway_id,
            'website_review',
            :required,
            :mandatory,
            :repeatable,
            :reward,
            CAST(:config AS JSONB)
        )
        RETURNING id, required
        """
    )

    update_condition_config_stmt = sa.text(
        """
        UPDATE conditions
        SET config = CAST(:config AS JSONB), updated_at = NOW()
        WHERE id = :id
        """
    )

    select_order_records_stmt = sa.text(
        """
        SELECT id, participant_id, complete, config
        FROM participant_records
        WHERE condition_id = :condition_id
        """
    )

    select_review_record_stmt = sa.text(
        """
        SELECT id, passed, complete, config
        FROM participant_records
        WHERE participant_id = :participant_id AND condition_id = :condition_id
        LIMIT 1
        """
    )

    insert_review_record_stmt = sa.text(
        """
        INSERT INTO participant_records (participant_id, condition_id, passed, complete, config)
        VALUES (:participant_id, :condition_id, :passed, :complete, CAST(:config AS JSONB))
        """
    )

    update_review_record_stmt = sa.text(
        """
        UPDATE participant_records
        SET
            passed = :passed,
            complete = :complete,
            config = CAST(:config AS JSONB),
            updated_at = NOW()
        WHERE id = :id
        """
    )

    update_order_record_stmt = sa.text(
        """
        UPDATE participant_records
        SET config = CAST(:config AS JSONB), updated_at = NOW()
        WHERE id = :id
        """
    )

    for order_condition in order_conditions:
        order_condition_id = int(order_condition["id"])
        order_config = dict(order_condition.get("config") or {})
        if not _should_split(order_config):
            continue

        review_config = _build_review_config(order_config)
        giveaway_id = int(order_condition["giveaway_id"])

        review_condition = bind.execute(
            select_review_by_giveaway_stmt,
            {"giveaway_id": giveaway_id},
        ).mappings().first()

        if review_condition is None:
            created = bind.execute(
                insert_review_condition_stmt,
                {
                    "giveaway_id": giveaway_id,
                    "required": int(order_condition.get("required") or 1),
                    "mandatory": bool(order_condition.get("mandatory")),
                    "repeatable": bool(order_condition.get("repeatable")),
                    "reward": order_condition.get("reward"),
                    "config": json.dumps(review_config, ensure_ascii=False),
                },
            ).mappings().first()
            if created is None:
                continue
            review_condition_id = int(created["id"])
            review_required = int(created.get("required") or 1)
        else:
            review_condition_id = int(review_condition["id"])
            review_required = int(review_condition.get("required") or 1)
            existing_review_config = dict(review_condition.get("config") or {})
            merged_review_config = dict(existing_review_config)
            for key, value in review_config.items():
                if merged_review_config.get(key) in (None, "", "-") and value not in (None, "", "-"):
                    merged_review_config[key] = value
            if merged_review_config != existing_review_config:
                bind.execute(
                    update_condition_config_stmt,
                    {
                        "id": review_condition_id,
                        "config": json.dumps(merged_review_config, ensure_ascii=False),
                    },
                )

        order_records = bind.execute(
            select_order_records_stmt,
            {"condition_id": order_condition_id},
        ).mappings().all()

        for order_record in order_records:
            record_config = dict(order_record.get("config") or {})
            review_emails = _normalize_emails(
                (record_config.get("review_emails") or []) + (record_config.get("legacy_review_emails") or [])
            )

            cleaned_order_record_config = dict(record_config)
            cleaned_order_record_config.pop("review_emails", None)
            cleaned_order_record_config.pop("legacy_review_emails", None)
            if cleaned_order_record_config != record_config:
                bind.execute(
                    update_order_record_stmt,
                    {
                        "id": int(order_record["id"]),
                        "config": json.dumps(cleaned_order_record_config, ensure_ascii=False),
                    },
                )

            if not review_emails:
                continue

            participant_id = int(order_record["participant_id"])
            existing_review_record = bind.execute(
                select_review_record_stmt,
                {"participant_id": participant_id, "condition_id": review_condition_id},
            ).mappings().first()

            if existing_review_record is None:
                complete = len(review_emails)
                passed = complete >= max(review_required, 1)
                bind.execute(
                    insert_review_record_stmt,
                    {
                        "participant_id": participant_id,
                        "condition_id": review_condition_id,
                        "passed": passed,
                        "complete": complete,
                        "config": json.dumps({"review_emails": review_emails}, ensure_ascii=False),
                    },
                )
            else:
                existing_config = dict(existing_review_record.get("config") or {})
                existing_emails = _normalize_emails(existing_config.get("review_emails") or [])
                merged_emails = sorted(set(existing_emails) | set(review_emails))
                existing_complete = _as_int(existing_review_record.get("complete"), default=0) or 0
                merged_complete = max(existing_complete, len(merged_emails))
                merged_passed = bool(existing_review_record.get("passed")) or merged_complete >= max(review_required, 1)
                bind.execute(
                    update_review_record_stmt,
                    {
                        "id": int(existing_review_record["id"]),
                        "passed": merged_passed,
                        "complete": merged_complete,
                        "config": json.dumps({"review_emails": merged_emails}, ensure_ascii=False),
                    },
                )

        cleaned_order_config = _clean_order_config(order_config)
        if cleaned_order_config != order_config:
            bind.execute(
                update_condition_config_stmt,
                {
                    "id": order_condition_id,
                    "config": json.dumps(cleaned_order_config, ensure_ascii=False),
                },
            )


def downgrade() -> None:
    """Downgrade schema."""
    raise RuntimeError("Irreversible migration: separated website_review conditions cannot be merged back safely.")
