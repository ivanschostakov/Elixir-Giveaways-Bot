import asyncio
import logging

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import REMINDER_HOUR, REMINDER_INTERVAL_DAYS, REMINDER_MINUTE, UFA_TZ
from src.bot.keyboards import user_keyboards
from src.database import get_session
from src.database.crud import list_giveaways_with_relations

logger = logging.getLogger("reminders")
MAX_REMINDER_LINES = 5
# Fixed anchor keeps the every-N-days cadence stable across worker restarts.
REMINDER_ANCHOR_DATE = date(1970, 1, 1)


@dataclass(slots=True)
class ReminderItem:
    giveaway_id: int
    giveaway_name: str
    passed_count: int
    total_count: int
    end_date: date | None


def _is_interval_run_date(value: date) -> bool:
    return (value - REMINDER_ANCHOR_DATE).days % REMINDER_INTERVAL_DAYS == 0


def _next_reminder_run(now: datetime) -> datetime:
    scheduled = now.replace(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, second=0, microsecond=0)
    if scheduled > now and _is_interval_run_date(scheduled.date()): return scheduled

    candidate = scheduled
    while True:
        candidate += timedelta(days=1)
        if _is_interval_run_date(candidate.date()): return candidate


def _is_giveaway_active_today(giveaway, *, today: date) -> bool:
    if not giveaway.active: return False
    if giveaway.start_date is not None and giveaway.start_date > today: return False
    if giveaway.end_date is not None and giveaway.end_date < today: return False
    return True


def _collect_reminders(giveaways: list) -> dict[int, list[ReminderItem]]:
    reminders: dict[int, list[ReminderItem]] = {}
    for giveaway in giveaways:
        conditions = list(giveaway.conditions or [])
        if not conditions: continue

        total_count = len(conditions)
        for participant in giveaway.participants or []:
            records_map = {record.condition_id: record for record in (participant.records or [])}
            passed_count = 0
            for condition in conditions:
                record = records_map.get(condition.id)
                if record is not None and record.passed: passed_count += 1

            if passed_count >= total_count: continue

            user_id = int(participant.user_id)
            reminders.setdefault(user_id, []).append(ReminderItem(giveaway_id=int(giveaway.id), giveaway_name=str(giveaway.name), passed_count=passed_count, total_count=total_count, end_date=giveaway.end_date))

    return reminders


def _build_reminder_text(items: list[ReminderItem]) -> str:
    lines = [
        "🔥 Не откладывайте участие в розыгрышах: завершите условия и повысьте шансы на победу.",
        "",
    ]

    for index, item in enumerate(items[:MAX_REMINDER_LINES], start=1):
        remaining = max(item.total_count - item.passed_count, 0)
        lines.append(f"{index}. <b>{escape(item.giveaway_name)}</b> — <b>{item.passed_count}/{item.total_count}</b>, осталось: <b>{remaining}</b>")

    hidden_count = len(items) - MAX_REMINDER_LINES
    if hidden_count > 0: lines.append(f"…и еще <b>{hidden_count}</b> розыгрыш(а).")

    lines.append("")
    lines.append("Выберите розыгрыш ниже и продолжайте участие.")
    return "\n".join(lines)


async def send_reminders(bot: Bot) -> tuple[int, int]:
    today = datetime.now(tz=UFA_TZ).date()
    async with get_session() as session: giveaways = await list_giveaways_with_relations(session)

    active_giveaways = [giveaway for giveaway in giveaways if _is_giveaway_active_today(giveaway, today=today)]
    reminders = _collect_reminders(active_giveaways)
    if not reminders:
        logger.info("No users to remind today")
        return 0, 0

    sent_count = 0
    for user_id, items in reminders.items():
        sorted_items = sorted(items,key=lambda item: (item.end_date is None, item.end_date if item.end_date is not None else date.max, item.giveaway_id))
        try:
            await bot.send_message(user_id, _build_reminder_text(sorted_items), reply_markup=user_keyboards.daily_reminder([(item.giveaway_id, item.giveaway_name) for item in sorted_items]))
            sent_count += 1
        except TelegramForbiddenError: logger.info("Skipping reminder: bot blocked by user_id=%s", user_id)
        except TelegramBadRequest as exc: logger.info("Skipping reminder for user_id=%s: %s", user_id, exc)
        except Exception: logger.exception("Failed to send reminder to user_id=%s", user_id)

    return sent_count, len(reminders)


async def run_reminders(bot: Bot) -> None:
    logger.info(
        "Reminders worker started | interval_days=%s | schedule=%02d:%02d (%s)",
        REMINDER_INTERVAL_DAYS,
        REMINDER_HOUR,
        REMINDER_MINUTE,
        UFA_TZ.key,
    )
    try:
        while True:
            now = datetime.now(tz=UFA_TZ)
            scheduled = _next_reminder_run(now)
            sleep_seconds = max((scheduled - now).total_seconds(), 1.0)
            logger.info("Next reminder run at %s", scheduled.isoformat())
            await asyncio.sleep(sleep_seconds)

            try:
                sent_count, recipient_count = await send_reminders(bot)
                logger.info("Reminders finished | sent=%s | recipients=%s", sent_count, recipient_count)
            except Exception: logger.exception("Reminder run failed")
    except asyncio.CancelledError:
        logger.info("Reminders worker stopped")
        raise


# Backward-compatible aliases for older imports.
send_weekly_reminders = send_reminders
run_weekly_reminders = run_reminders
send_daily_reminders = send_reminders
run_daily_reminders = run_reminders
