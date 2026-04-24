from aiogram.fsm.state import State, StatesGroup


class LoginStates(StatesGroup):
    api_id = State()
    api_hash = State()
    phone = State()
    code = State()
    password = State()


class ChatStates(StatesGroup):
    waiting = State()


class TextStates(StatesGroup):
    waiting = State()


class SettingStates(StatesGroup):
    interval = State()
    jitter = State()
    cycle = State()
