"""rename website review record keys

Revision ID: 9fa2c7d9b561
Revises: 4365af162933
Create Date: 2026-03-19 00:00:00.000000

"""
import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9fa2c7d9b561"
down_revision: Union[str, Sequence[str], None] = "4365af162933"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _normalized_email(config: dict[str, Any]) -> str | None:
    direct_email = str(config.get("email") or "").strip().lower()
    if direct_email:
        return direct_email

    values: list[str] = []
    for key in ("review_emails", "legacy_review_emails"):
        raw = config.get(key)
        if isinstance(raw, list):
            items = raw
        elif raw in (None, ""):
            items = []
        else:
            items = [raw]
        for item in items:
            normalized = str(item).strip().lower()
            if normalized:
                values.append(normalized)
    return values[-1] if values else None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, config
            FROM participant_records
            WHERE
                config ? 'email'
                OR config ? 'review_emails'
                OR config ? 'legacy_review_emails'
                OR config ? 'photo'
                OR config ? 'photo_review'
            """
        )
    ).mappings().all()

    update_stmt = sa.text(
        """
        UPDATE participant_records
        SET config = CAST(:config AS JSONB), updated_at = NOW()
        WHERE id = :id
        """
    )

    for row in rows:
        record_id = int(row["id"])
        existing_config = dict(row.get("config") or {})
        updated_config = dict(existing_config)

        email = _normalized_email(updated_config)
        photo = _as_bool(updated_config.get("photo")) or _as_bool(updated_config.get("photo_review"))

        updated_config.pop("review_emails", None)
        updated_config.pop("legacy_review_emails", None)
        updated_config.pop("photo_review", None)

        if email:
            updated_config["email"] = email
        else:
            updated_config.pop("email", None)

        if any(key in existing_config for key in ("photo", "photo_review")):
            updated_config["photo"] = photo

        if updated_config == existing_config:
            continue

        bind.execute(
            update_stmt,
            {
                "id": record_id,
                "config": json.dumps(updated_config, ensure_ascii=False),
            },
        )


def downgrade() -> None:
    """Downgrade schema."""
    raise RuntimeError("Irreversible migration: website review participant record keys were normalized to single email/photo fields.")
