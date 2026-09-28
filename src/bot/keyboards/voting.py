from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.database.models import Vote, Voting


def vote_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить голос", callback_data="vote:confirm")],
        [InlineKeyboardButton(text="✏️ Изменить причину", callback_data="vote:rewrite")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="vote:cancel")],
    ])


def existing_vote(vote: Vote, *, can_change: bool) -> InlineKeyboardMarkup | None:
    if not can_change:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Изменить кандидата", callback_data=f"vote:candidates:{vote.voting_id}")],
        [InlineKeyboardButton(text="✏️ Изменить причину", callback_data=f"vote:edit_reason:{vote.voting_id}")],
    ])


def candidates(voting: Voting, *, current_candidate_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=candidate.name, callback_data=f"vote:choose:{voting.id}:{candidate.id}")]
        for candidate in voting.candidates
        if candidate.active and candidate.id != current_candidate_id
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="vote:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_votings(votings: list[Voting]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"#{voting.id} · {voting.name}", callback_data=f"vadmin:view:{voting.id}")]
        for voting in votings
    ])


def admin_voting(voting: Voting) -> InlineKeyboardMarkup:
    toggle_action = "close" if voting.active else "open"
    toggle_text = "🔒 Закрыть" if voting.active else "🔓 Открыть"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Результаты", callback_data=f"vadmin:results:{voting.id}"),
            InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"vadmin:links:{voting.id}"),
        ],
        [
            InlineKeyboardButton(text="⬇️ Excel", callback_data=f"vadmin:export:{voting.id}"),
            InlineKeyboardButton(text=toggle_text, callback_data=f"vadmin:{toggle_action}:{voting.id}"),
        ],
        [InlineKeyboardButton(text="⬅️ К голосованиям", callback_data="vadmin:list")],
    ])
