from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

def _to_int(v: Any, default: int = 0) -> int:
    try: return int(v)
    except Exception: return default

def _to_str(v: Any, default: str = "") -> str:
    if v is None: return default
    return str(v)

def _to_bool_yn(v: Any) -> bool: return _to_str(v).upper() == "Y"

def _to_dt(v: Any) -> Optional[datetime]:
    if v is None: return None
    if isinstance(v, datetime): return v
    s = _to_str(v).strip()
    if not s: return None
    try: return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception: return None

@dataclass(slots=True)
class Review:
    id: int
    id_element: int
    xml_id_element: str

    id_user: int
    rating: int

    title: str
    text: str
    answer: str

    add_fields_raw: str

    likes: int
    dislikes: int

    date_creation: Optional[datetime]
    date_change: Optional[datetime]

    moderated: bool
    moderated_by: Optional[int]

    active: bool
    recommended: bool
    anonymity: bool

    ip_user: str
    shows: int

    files: bool
    quote: str
    advantages: str
    flaws: str

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Review":
        return cls(
            id=_to_int(row.get("ID")),
            id_element=_to_int(row.get("ID_ELEMENT")),
            xml_id_element=_to_str(row.get("XML_ID_ELEMENT")),

            id_user=_to_int(row.get("ID_USER")),
            rating=_to_int(row.get("RATING")),

            title=_to_str(row.get("TITLE")),
            text=_to_str(row.get("TEXT")),
            answer=_to_str(row.get("ANSWER")),

            add_fields_raw=_to_str(row.get("ADD_FIELDS")),

            likes=_to_int(row.get("LIKES")),
            dislikes=_to_int(row.get("DISLIKES")),

            date_creation=_to_dt(row.get("DATE_CREATION")),
            date_change=_to_dt(row.get("DATE_CHANGE")),

            moderated=_to_bool_yn(row.get("MODERATED")),
            moderated_by=_to_int(row.get("MODERATED_BY")) if row.get("MODERATED_BY") not in (None, "") else None,

            active=_to_bool_yn(row.get("ACTIVE")),
            recommended=_to_bool_yn(row.get("RECOMMENDATED")),
            anonymity=_to_bool_yn(row.get("ANONYMITY")),

            ip_user=_to_str(row.get("IP_USER")),
            shows=_to_int(row.get("SHOWS")),

            files=_to_str(row.get("FILES")) != "N;",
            quote=_to_str(row.get("QUOTE")),
            advantages=_to_str(row.get("ADVANTAGES")),
            flaws=_to_str(row.get("FLAWS")),
        )


    @property
    def length(self): return len(self.text or "")
