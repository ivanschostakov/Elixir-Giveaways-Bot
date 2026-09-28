from aiogram.fsm.state import State, StatesGroup


class VoteFlow(StatesGroup):
    reason = State()
    confirm = State()


class CreateVoting(StatesGroup):
    name = State()
    description = State()
    starts_at = State()
    ends_at = State()
    candidates = State()
