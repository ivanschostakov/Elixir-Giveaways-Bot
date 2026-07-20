from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pathlib import Path
from os import getenv


WORKING_DIR = Path(__file__).parent
LOGS_DIR = WORKING_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

ENV_FILE = WORKING_DIR / ".env"

load_dotenv(ENV_FILE)


def _get_int_env(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = getenv(name)
    try: value = int(raw) if raw is not None else default
    except (TypeError, ValueError): return default

    if min_value is not None and value < min_value: return default
    if max_value is not None and value > max_value: return default
    return value


def _get_bool_env(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None: return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}

GIVEAWAYS_BOT_TOKEN = getenv("GIVEAWAYS_BOT_TOKEN")
ADMIN_TELEGRAM_IDS = [int(i) for i in getenv("ADMIN_TELEGRAM_IDS").split(",")]
ELIXIR_CHAT_ID = int(getenv("ELIXIR_CHAT_ID"))

POSTGRES_DB = getenv("POSTGRES_DB")
POSTGRES_USER = getenv("POSTGRES_USER")
POSTGRES_PORT = int(getenv("POSTGRES_PORT"))
POSTGRES_HOST = getenv("POSTGRES_HOST")
POSTGRES_PASSWORD = getenv("POSTGRES_PASSWORD")

AMOCRM_ACCOUNT_ID     = getenv("AMOCRM_ACCOUNT_ID")
AMOCRM_BASE_URL       = getenv("AMOCRM_BASE_URL", "https://slimpeptide.amocrm.ru")
AMOCRM_ACCESS_TOKEN   = getenv("AMOCRM_ACCESS_TOKEN")

BITRIX24_BASE_URL = (getenv("BITRIX24_BASE_URL") or "https://elixirpeptide.ru").rstrip("/")
BITRIX24_ENDPOINT = getenv("BITRIX24_ENDPOINT") or "/local/api/giveaways.php"
BITRIX24_TOKEN = getenv("BITRIX24_TOKEN") or "8599029089:AAE2Nu4Jaj-Pox_8jWtlwD-XViQJD2wb4QU"

SMTP_USER = getenv("SMTP_USER")
SMTP_PASSWORD = getenv("SMTP_PASSWORD")

SYNC_DB_URL  = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"
ASYNC_DB_URL = f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DB}"

UFA_TZ = ZoneInfo("Asia/Yekaterinburg")
DATETIME_FORMAT = "%d.%m.%Y %H:%M"
DATE_FORMAT = "%d.%m"
PLACE_EMOJIS = {
    1: "🥇 ",
    2: "🥈 ",
    3: "🥉 "
}

DAILY_REMINDERS_ENABLED = _get_bool_env("DAILY_REMINDERS_ENABLED", True)
DAILY_REMINDER_HOUR = _get_int_env("DAILY_REMINDER_HOUR", 2, min_value=0, max_value=23)
DAILY_REMINDER_MINUTE = _get_int_env("DAILY_REMINDER_MINUTE", 59, min_value=0, max_value=59)

REMINDERS_ENABLED = _get_bool_env(
    "REMINDERS_ENABLED",
    _get_bool_env("WEEKLY_REMINDERS_ENABLED", DAILY_REMINDERS_ENABLED),
)
REMINDER_INTERVAL_DAYS = _get_int_env("REMINDER_INTERVAL_DAYS", 2, min_value=1)
REMINDER_HOUR = _get_int_env(
    "REMINDER_HOUR",
    _get_int_env("WEEKLY_REMINDER_HOUR", DAILY_REMINDER_HOUR, min_value=0, max_value=23),
    min_value=0,
    max_value=23,
)
REMINDER_MINUTE = _get_int_env(
    "REMINDER_MINUTE",
    _get_int_env("WEEKLY_REMINDER_MINUTE", DAILY_REMINDER_MINUTE, min_value=0, max_value=59),
    min_value=0,
    max_value=59,
)

WEEKLY_REMINDERS_ENABLED = REMINDERS_ENABLED
WEEKLY_REMINDER_HOUR = REMINDER_HOUR
WEEKLY_REMINDER_MINUTE = REMINDER_MINUTE
