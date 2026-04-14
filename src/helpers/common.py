import re
import phonenumbers

from datetime import date, datetime
from typing import Any, Optional

from config import UFA_TZ, DATETIME_FORMAT
from src.enums.giveaway_prize import GiveawayPrize


def normalize_phone_number(raw: str, default_regions: list[str] = ["AM", "RU", "UA", "BY", "AZ", "KZ", "KG", "MD", "TJ", "TM", "UZ", "GE"]) -> str | None:
    def _clean(x: str) -> str:
        x = x.strip()
        if x.startswith("+"): return "+" + re.sub(r"\D", "", x[1:])
        return re.sub(r"\D", "", x)

    s = _clean(raw)
    if not s: return None
    if s.startswith("+"):
        try:
            n = phonenumbers.parse(s, None)
            return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164) if phonenumbers.is_valid_number(n) else None
        except phonenumbers.NumberParseException: return None
    for region in default_regions:
        try:
            n = phonenumbers.parse(s, region)
            if phonenumbers.is_valid_number(n): return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException: continue

    return raw


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

def ufa_now() -> datetime:
    return datetime.now(tz=UFA_TZ)

def _parse_prizes(raw: str) -> dict[int, str]:
    prizes: dict[int, str] = {}
    for line in raw.strip().splitlines():
        parts = line.split(". ", maxsplit=1)
        if len(parts) != 2: raise ValueError
        place = int(parts[0])
        prize_name = parts[1].strip()
        if not prize_name: raise ValueError
        prizes[place] = prize_name
    if not prizes: raise ValueError
    return prizes

def _bool_word(value: bool) -> str: return "да" if value else "нет"


def _parse_places(raw: str) -> dict[int, int]:
    places: dict[int, int] = {}
    for line in raw.strip().splitlines():
        parts = line.split(". ", maxsplit=1)
        if len(parts) != 2: raise ValueError
        place = int(parts[0])
        amount = int(parts[1])
        if amount <= 0: raise ValueError
        places[place] = amount
    if not places: raise ValueError
    return places


def _parse_user_datetime(raw: str) -> datetime:
    parsed = datetime.strptime(raw.strip(), DATETIME_FORMAT)
    return parsed.replace(tzinfo=UFA_TZ)


def _parse_user_date_ddmm(raw: str) -> date:
    value = raw.strip()
    if not re.fullmatch(r"\d{1,2}\.\d{1,2}", value):
        raise ValueError("expected DD.MM")

    day_raw, month_raw = value.split(".", maxsplit=1)
    day = int(day_raw)
    month = int(month_raw)
    year = datetime.now(tz=UFA_TZ).year
    return date(year=year, month=month, day=day)


def _build_prizes_payload(prizes: dict[int, str], places: dict[int, int] | None) -> dict[int, GiveawayPrize]:
    place_amounts = places or {}
    return {
        place: GiveawayPrize(name=prize_name, amount=place_amounts.get(place, 1))
        for place, prize_name in prizes.items()
    }
