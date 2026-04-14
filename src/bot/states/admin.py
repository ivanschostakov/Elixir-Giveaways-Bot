from aiogram.fsm.state import State, StatesGroup


class CreateGiveaway(StatesGroup):
    name = State()
    description = State()
    start_date = State()
    end_date = State()
    notes = State()
    prizes = State()
    places = State()


class CreateWebsiteOrderCondition(StatesGroup):
    min_price = State()
    start_date = State()


class CreateWebsiteReviewCondition(StatesGroup):
    start_date = State()
    min_grade = State()
    min_length = State()


class CreateSelfJoinCondition(StatesGroup):
    chat_id = State()


class CreateRefJoinCondition(StatesGroup):
    chat_id = State()


class CreateCondition(StatesGroup):
    action = State()
    mandatory = State()
    repeatable = State()
    reward = State()
    required = State()


class DeleteGiveaway(StatesGroup):
    confirm = State()


class EditGiveaway(StatesGroup):
    name = State()
    description = State()
    notes = State()
    prizes = State()
    places = State()
    start_date = State()
    end_date = State()


class SendBroadcast(StatesGroup):
    confirm_first = State()
    confirm_second = State()


class DecideWinner(StatesGroup):
    place = State()
    winner = State()
