"""unify website order and review conditions

Revision ID: 505074661731
Revises: b5276b5d8e2e
Create Date: 2026-02-18 15:24:16.321966

"""
from collections import defaultdict
from datetime import datetime, timezone
import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '505074661731'
down_revision: Union[str, Sequence[str], None] = 'b5276b5d8e2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _first_non_empty(values: list[Any]) -> Any:
    for value in values:
        if value not in (None, "", "-"):
            return value
    return None


def _as_int(value: Any, *, default: int | None = None) -> int | None:
    if value in (None, "", "-"):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, *, default: float = 0.0) -> float:
    if value in (None, "", "-"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_record_config(configs: list[dict[str, Any] | None]) -> dict[str, Any]:
    order_codes: set[str] = set()
    legacy_review_emails: set[str] = set()

    for config in configs:
        data = dict(config or {})
        for value in data.get("order_codes", []) or []:
            normalized = str(value).strip()
            if normalized:
                order_codes.add(normalized)

        for value in data.get("review_emails", []) or []:
            normalized = str(value).strip()
            if normalized:
                legacy_review_emails.add(normalized)

        for value in data.get("legacy_review_emails", []) or []:
            normalized = str(value).strip()
            if normalized:
                legacy_review_emails.add(normalized)

    merged: dict[str, Any] = {"order_codes": sorted(order_codes)}
    if legacy_review_emails:
        merged["legacy_review_emails"] = sorted(legacy_review_emails)
    return merged


def upgrade() -> None:
    """Upgrade data to a single website_order condition."""
    bind = op.get_bind()

    condition_rows = bind.execute(
        sa.text(
            """
            SELECT id, giveaway_id, action, required, mandatory, repeatable, reward, config
            FROM conditions
            WHERE action IN ('website_order', 'website_review')
            ORDER BY giveaway_id, id
            """
        )
    ).mappings().all()

    rows_by_giveaway: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in condition_rows:
        rows_by_giveaway[int(row["giveaway_id"])].append(dict(row))

    select_records_stmt = sa.text(
        """
        SELECT participant_id, condition_id, passed, complete, config
        FROM participant_records
        WHERE condition_id IN :condition_ids
        """
    ).bindparams(sa.bindparam("condition_ids", expanding=True))

    delete_records_stmt = sa.text(
        """
        DELETE FROM participant_records
        WHERE condition_id IN :condition_ids
        """
    ).bindparams(sa.bindparam("condition_ids", expanding=True))

    delete_conditions_stmt = sa.text(
        """
        DELETE FROM conditions
        WHERE id IN :condition_ids
        """
    ).bindparams(sa.bindparam("condition_ids", expanding=True))

    upsert_record_stmt = sa.text(
        """
        INSERT INTO participant_records (participant_id, condition_id, passed, complete, config)
        VALUES (:participant_id, :condition_id, :passed, :complete, CAST(:config AS JSONB))
        ON CONFLICT (participant_id, condition_id)
        DO UPDATE SET
            passed = EXCLUDED.passed OR participant_records.passed,
            complete = GREATEST(participant_records.complete, EXCLUDED.complete),
            config = EXCLUDED.config,
            updated_at = NOW()
        """
    )

    for _, rows in rows_by_giveaway.items():
        order_conditions = [row for row in rows if row["action"] == "website_order"]
        review_conditions = [row for row in rows if row["action"] == "website_review"]
        if not review_conditions:
            continue

        target = order_conditions[0] if order_conditions else review_conditions[0]
        target_id = int(target["id"])

        related_conditions = [target] + review_conditions if order_conditions else review_conditions
        related_ids = [int(condition["id"]) for condition in related_conditions]
        review_ids = [int(condition["id"]) for condition in review_conditions]

        order_start_values = [
            (condition.get("config") or {}).get("start_date")
            for condition in order_conditions
        ]
        review_start_values = [
            (condition.get("config") or {}).get("review_start_date")
            for condition in review_conditions
        ] + [
            (condition.get("config") or {}).get("start_date")
            for condition in review_conditions
        ]

        target_config = dict(target.get("config") or {})
        fallback_start = datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()
        start_date = _first_non_empty(order_start_values + [target_config.get("start_date")] + review_start_values) or fallback_start
        review_start_date = _first_non_empty([target_config.get("review_start_date")] + review_start_values + [start_date]) or start_date

        min_price = _first_non_empty(
            [(condition.get("config") or {}).get("min_price") for condition in order_conditions]
            + [target_config.get("min_price")]
        )
        min_grade = _first_non_empty(
            [target_config.get("min_grade")]
            + [(condition.get("config") or {}).get("min_grade") for condition in review_conditions]
        )
        min_length = _first_non_empty(
            [target_config.get("min_length")]
            + [(condition.get("config") or {}).get("min_length") for condition in review_conditions]
        )

        merged_config = dict(target_config)
        merged_config["min_price"] = _as_float(min_price, default=0.0)
        merged_config["start_date"] = start_date
        merged_config["review_start_date"] = review_start_date
        merged_config["min_grade"] = _as_int(min_grade, default=None)
        merged_config["min_length"] = _as_int(min_length, default=None)
        merged_config["unified_order_review"] = True

        merged_required = max(_as_int(condition.get("required"), default=1) or 1 for condition in related_conditions)
        merged_mandatory = any(bool(condition.get("mandatory")) for condition in related_conditions)
        merged_repeatable = any(bool(condition.get("repeatable")) for condition in related_conditions)
        merged_reward = _first_non_empty([condition.get("reward") for condition in related_conditions])
        if merged_repeatable and merged_reward is None:
            merged_reward = 1

        bind.execute(
            sa.text(
                """
                UPDATE conditions
                SET
                    action = 'website_order',
                    required = :required,
                    mandatory = :mandatory,
                    repeatable = :repeatable,
                    reward = :reward,
                    config = CAST(:config AS JSONB),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {
                "id": target_id,
                "required": merged_required,
                "mandatory": merged_mandatory,
                "repeatable": merged_repeatable,
                "reward": merged_reward,
                "config": json.dumps(merged_config, ensure_ascii=False),
            },
        )

        record_rows = bind.execute(
            select_records_stmt,
            {"condition_ids": related_ids},
        ).mappings().all()
        records_by_participant: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for record in record_rows:
            records_by_participant[int(record["participant_id"])].append(dict(record))

        for participant_id, participant_records in records_by_participant.items():
            merged_complete = max(_as_int(record.get("complete"), default=0) or 0 for record in participant_records)
            merged_passed = any(bool(record.get("passed")) for record in participant_records)
            merged_record_config = _normalize_record_config(
                [record.get("config") for record in participant_records]
            )
            bind.execute(
                upsert_record_stmt,
                {
                    "participant_id": participant_id,
                    "condition_id": target_id,
                    "passed": merged_passed,
                    "complete": merged_complete,
                    "config": json.dumps(merged_record_config, ensure_ascii=False),
                },
            )

        remove_condition_ids = [condition_id for condition_id in review_ids if condition_id != target_id]
        if remove_condition_ids:
            bind.execute(delete_records_stmt, {"condition_ids": remove_condition_ids})
            bind.execute(delete_conditions_stmt, {"condition_ids": remove_condition_ids})

        if target.get("action") == "website_review":
            bind.execute(
                sa.text(
                    """
                    UPDATE conditions
                    SET action = 'website_order', updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": target_id},
            )


def downgrade() -> None:
    """Downgrade schema."""
    raise RuntimeError("Irreversible migration: website_review conditions were merged into website_order.")
