from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config import UFA_TZ
from src.helpers.common import normalize_phone_number


def _first_cf_value(values: Any) -> Any:
    if not isinstance(values, list) or not values: return None
    v0 = values[0]
    if isinstance(v0, dict): return v0.get("value")
    return None

@dataclass
class Lead:
    id: int
    name: str | None
    price: int | None
    status_id: int | None

    created_at: datetime | int | None
    updated_at: datetime | int | None
    closed_at: datetime | int | None

    phone: str | None
    email: str | None

    is_deleted: bool
    _links: dict[str, Any] | None
    _embedded: dict[str, Any] | None

    def __post_init__(self):
        self.created_at = datetime.fromtimestamp(self.created_at, tz=timezone.utc).astimezone(UFA_TZ) if self.created_at else None
        self.updated_at = datetime.fromtimestamp(self.updated_at, tz=timezone.utc).astimezone(UFA_TZ) if self.updated_at else None
        self.closed_at = datetime.fromtimestamp(self.closed_at, tz=timezone.utc).astimezone(UFA_TZ) if self.closed_at else None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Lead":
        if not isinstance(d, dict): raise TypeError("Lead.from_dict expects dict")

        custom_fields: dict[str, Any] = {}
        for cf in (d.get("custom_fields_values") or []):
            if not isinstance(cf, dict): continue
            field_name = cf.get("field_name")
            if not field_name: continue
            fid = str(field_name).title().replace(" ", "")
            custom_fields[fid] = _first_cf_value(cf.get("values"))

        phone: str | None = None
        email: str | None = None

        emb = d.get("_embedded") if isinstance(d.get("_embedded"), dict) else None
        contacts = (emb.get("contacts") or []) if emb else []
        c0 = contacts[0] if isinstance(contacts, list) and contacts else None

        if isinstance(c0, dict):
            for cf in (c0.get("custom_fields_values") or []):
                if not isinstance(cf, dict): continue
                code = (cf.get("field_code") or "").upper()
                if code == "PHONE" and phone is None:
                    v = _first_cf_value(cf.get("values"))
                    phone = str(v) if v is not None else None
                if code == "EMAIL" and email is None:
                    v = _first_cf_value(cf.get("values"))
                    email = str(v) if v is not None else None

        lead = cls(
            id=int(d.get("id") or 0),
            name=d.get("name"),
            price=(int(d.get("price")) if str(d.get("price") or "").isdigit() else None),
            status_id=(int(d["status_id"]) if d.get("status_id") is not None else None),

            created_at=(int(d["created_at"]) if d.get("created_at") is not None else None),
            updated_at=(int(d["updated_at"]) if d.get("updated_at") is not None else None),
            closed_at=(int(d["closed_at"]) if d.get("closed_at") is not None else None),

            phone=normalize_phone_number(phone),
            email=email,

            is_deleted=bool(d.get("is_deleted")),
            _links=(d.get("_links") if isinstance(d.get("_links"), dict) else None),
            _embedded=emb,
        )
        return lead
