from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from src.database.schemas import GiveawayRead, GiveawayReadWithRelations


def view_giveaway(giveaway: GiveawayRead | GiveawayReadWithRelations) -> InlineKeyboardMarkup: return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=giveaway.name, callback_data=f"view_giveaway:{giveaway.id}")]])
def main_menu(giveaways: list[GiveawayRead | GiveawayReadWithRelations]) -> InlineKeyboardMarkup: return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=giveaway.name, callback_data=f"view_giveaway:{giveaway.id}")] for giveaway in giveaways])
def giveaway_menu(giveaway_id: int, *, joined: bool, has_notes: bool) -> InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineKeyboardButton]] = []
    if has_notes: inline_keyboard.append([InlineKeyboardButton(text="📝 Примечания", callback_data=f"notes:{giveaway_id}")])
    if joined: inline_keyboard.append([InlineKeyboardButton(text="👀 Проверить прогресс", callback_data=f"view_progress:{giveaway_id}")])
    else: inline_keyboard.append([InlineKeyboardButton(text="🚪 Принять участие", callback_data=f"join:{giveaway_id}")])
    inline_keyboard.append([InlineKeyboardButton(text="⬅️ К списку розыгрышей", callback_data="user_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def back_to_giveaway(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К розыгрышу", callback_data=f"view_giveaway:{giveaway_id}")],
    ])


def progress_menu(giveaway_id: int, rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(text=text, callback_data=cb)] for text, cb in rows]
    keyboard.append([InlineKeyboardButton(text="⬅️ К розыгрышу", callback_data=f"view_giveaway:{giveaway_id}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ К списку розыгрышей", callback_data="user_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def daily_reminder(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for giveaway_id, giveaway_name in items[:5]:
        title = (giveaway_name or "").strip() or f"Розыгрыш #{giveaway_id}"
        if len(title) > 30:
            title = title[:29] + "…"
        keyboard.append([InlineKeyboardButton(text=f"📊 {title}", callback_data=f"view_progress:{giveaway_id}")])
    keyboard.append([InlineKeyboardButton(text="🎁 К списку розыгрышей", callback_data="user_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def ref_link_menu(url: str, giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Открыть ссылку", url=url)],
        [InlineKeyboardButton(text="⬅️ К прогрессу", callback_data=f"view_progress:{giveaway_id}")],
    ])


def confirm_ref_join(condition_id: int, participant_id: int, chat_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Подписаться", url=f"https://t.me/{chat_id.removeprefix('@')}" if not (chat_id.startswith("https://t.me/") and "@" not in chat_id) else chat_id)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=f"confirm_ref_join:{condition_id}:{participant_id}")],
    ])


def request_winner_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
