from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.condition import ConditionType
from src.database.models import Condition
from src.database.models import Giveaway


def back(call: str): return InlineKeyboardButton(text="🔙 Назад", callback_data=call)


def back_markup(call: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[back(call)]])


def main_menu(giveaways: list[Giveaway]) -> InlineKeyboardMarkup:
    giveaway_buttons = [InlineKeyboardButton(text=f"{giveaway.name}", callback_data=f"view_giveaway:{giveaway.id}") for giveaway in giveaways]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новый розыгрыш", callback_data="create_giveaway")],
    ] + [giveaway_buttons[i:i+2] for i in range(0, len(giveaways), 2)])


def conditions_menu(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Добавить условие", callback_data=f"add_condition:{giveaway_id}"),
            InlineKeyboardButton(text="➖ Удалить условие", callback_data=f"remove_condition:{giveaway_id}"),
        ],
        [back(f"view_giveaway:{giveaway_id}")],
    ])


def edit_giveaway_menu(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏷️ Название", callback_data=f"edit_giveaway_field:{giveaway_id}:name"),
            InlineKeyboardButton(text="📝 Описание", callback_data=f"edit_giveaway_field:{giveaway_id}:description"),
        ],
        [
            InlineKeyboardButton(text="‼️ Примечания", callback_data=f"edit_giveaway_field:{giveaway_id}:notes"),
            InlineKeyboardButton(text="🎁 Призы", callback_data=f"edit_giveaway_field:{giveaway_id}:prizes"),
        ],
        [
            InlineKeyboardButton(text="⏳ Дата начала", callback_data=f"edit_giveaway_field:{giveaway_id}:start_date"),
            InlineKeyboardButton(text="⌛️ Дата окончания", callback_data=f"edit_giveaway_field:{giveaway_id}:end_date"),
        ],
        [back(f"view_giveaway:{giveaway_id}")],
    ])


def participants_menu(giveaway_id: int, *, show_all: bool) -> InlineKeyboardMarkup:
    toggle_button = (
        InlineKeyboardButton(text="🎯 Только проходящие", callback_data=f"view_participants:{giveaway_id}:winnable")
        if show_all
        else InlineKeyboardButton(text="👥 Показать всех", callback_data=f"view_participants:{giveaway_id}:all")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [toggle_button],
        [InlineKeyboardButton(text="⬇️ Скачать Excel", callback_data=f"download_participants_excel:{giveaway_id}")],
        [back(f"view_giveaway:{giveaway_id}")],
    ])


def winners_menu(giveaway_id: int, *, has_winners: bool) -> InlineKeyboardMarkup:
    draw_text = "🎲 Перевыбрать победителей" if has_winners else "🎯 Определить победителей"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=draw_text, callback_data=f"decide_winners:{giveaway_id}")],
        [back(f"view_giveaway:{giveaway_id}")],
    ])


def _condition_name(condition: Condition) -> str:
    try:
        return ConditionType[condition.action].value._name
    except Exception:
        return condition.action


def delete_condition_menu(giveaway_id: int, conditions: list[Condition]) -> InlineKeyboardMarkup:
    inline_keyboard = [
        [InlineKeyboardButton(text=f"{index}. {_condition_name(condition)}", callback_data=f"delete_condition:{giveaway_id}:{condition.id}")]
        for index, condition in enumerate(conditions, start=1)
    ]
    inline_keyboard.append([back(f"conditions:{giveaway_id}")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def condition_actions(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Подписка/вход", callback_data=f"condition_action:{giveaway_id}:self_join")],
        [InlineKeyboardButton(text="👥 Приглашение друга", callback_data=f"condition_action:{giveaway_id}:ref_join")],
        [InlineKeyboardButton(text="🛍️ Заказ на сайта", callback_data=f"condition_action:{giveaway_id}:website_order")],
        [InlineKeyboardButton(text="💬 Отзыв на сайте", callback_data=f"condition_action:{giveaway_id}:website_review")],
        [back(f"conditions:{giveaway_id}")],
    ])


def condition_yes_no(giveaway_id: int, callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"{callback_prefix}:{giveaway_id}:yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"{callback_prefix}:{giveaway_id}:no"),
        ],
        [back(f"conditions:{giveaway_id}")],
    ])


def condition_repeat_limit(giveaway_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data=f"condition_repeat_limit:{giveaway_id}:1"),
            InlineKeyboardButton(text="3", callback_data=f"condition_repeat_limit:{giveaway_id}:3"),
            InlineKeyboardButton(text="5", callback_data=f"condition_repeat_limit:{giveaway_id}:5"),
            InlineKeyboardButton(text="10", callback_data=f"condition_repeat_limit:{giveaway_id}:10"),
        ],
        [InlineKeyboardButton(text="∞", callback_data=f"condition_repeat_limit:{giveaway_id}:inf")],
        [back(f"conditions:{giveaway_id}")],
    ])


def skip(call: str, back_call: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data=f"skip:{call}")],
        [back(back_call)],
    ])


def condition_order_min_price(back_call: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="500₽", callback_data="condition_preset_order_min_price:500"),
            InlineKeyboardButton(text="1000₽", callback_data="condition_preset_order_min_price:1000"),
            InlineKeyboardButton(text="2000₽", callback_data="condition_preset_order_min_price:2000"),
        ],
        [
            InlineKeyboardButton(text="3000₽", callback_data="condition_preset_order_min_price:3000"),
            InlineKeyboardButton(text="5000₽", callback_data="condition_preset_order_min_price:5000"),
            InlineKeyboardButton(text="10000₽", callback_data="condition_preset_order_min_price:10000"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="skip:condition_order_min_price")],
        [back(back_call)],
    ])


def condition_review_min_length(back_call: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="50 символов", callback_data="condition_preset_review_min_length:50"),
            InlineKeyboardButton(text="100 символов", callback_data="condition_preset_review_min_length:100"),
            InlineKeyboardButton(text="180 символов", callback_data="condition_preset_review_min_length:180"),
        ],
        [InlineKeyboardButton(text="Пропустить", callback_data="skip:condition_review_min_length")],
        [back(back_call)],
    ])


def send_confirmation(step: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"send_confirm:{step}:yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"send_confirm:{step}:no"),
        ]
    ])


def cancel_send(send_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛔️ Остановить рассылку", callback_data=f"cancel_send:{send_id}")]
    ])
