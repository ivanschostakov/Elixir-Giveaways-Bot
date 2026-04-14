from aiogram.fsm.state import State, StatesGroup


class UserConditionInput(StatesGroup):
    order_code = State()
    review_email = State()
