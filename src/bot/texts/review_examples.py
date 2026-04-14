REVIEW_EXAMPLE_50 = "Доставили быстро, упаковка хорошая, всё совпадает."
REVIEW_EXAMPLE_100 = "Заказ оформил быстро, доставили без задержек. Упаковка надёжная, поддержка ответила быстро, доволен."
REVIEW_EXAMPLE_180 = (
    "Заказывал впервые: оформление понятное, отправка быстрая, упаковка герметичная и аккуратная. "
    "Всё пришло целым, сервис на уровне. Поддержка помогла выбрать нужный вариант — спасибо!"
)

_EXAMPLES_BY_LENGTH: dict[int, str] = {
    50: REVIEW_EXAMPLE_50,
    100: REVIEW_EXAMPLE_100,
    180: REVIEW_EXAMPLE_180,
}

for length, text in _EXAMPLES_BY_LENGTH.items():
    if len(text) != length:
        raise ValueError(f"Review example length mismatch: expected {length}, got {len(text)}")

REVIEW_LENGTH_EXAMPLES_TEXT = (
    "<b>Примеры шаблонов по длине:</b>\n"
    f"50 символов:\n<code>{REVIEW_EXAMPLE_50}</code>\n\n"
    f"100 символов:\n<code>{REVIEW_EXAMPLE_100}</code>\n\n"
    f"180 символов:\n<code>{REVIEW_EXAMPLE_180}</code>"
)
