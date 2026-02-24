# state.py

from datetime import datetime
from config import MANAGERS

# Состояние для каждого менеджера — при старте автообновление ВЫКЛЮЧЕНО
state = {
    key: {
        "auto_update": False,
        "last_update_time": None,
        # известные отклики: load_id -> [response_id, ...]
        "known_responses": {},
        # инициализированы ли known_responses при первом запуске планировщика
        "responses_initialized": False,
    }
    for key in MANAGERS.keys()
}

# Активный менеджер для каждого chat_id (chat_id -> manager_key)
active_managers: dict[int, str] = {}


def get_active_manager(chat_id: int) -> str | None:
    return active_managers.get(chat_id)


def set_active_manager(chat_id: int, manager_key: str):
    active_managers[chat_id] = manager_key


def is_auto_update_enabled(manager_key: str) -> bool:
    return state[manager_key]["auto_update"]


def set_auto_update(manager_key: str, value: bool):
    state[manager_key]["auto_update"] = value


def toggle_auto_update(manager_key: str) -> bool:
    state[manager_key]["auto_update"] = not state[manager_key]["auto_update"]
    return state[manager_key]["auto_update"]


def set_last_update_time(manager_key: str):
    state[manager_key]["last_update_time"] = datetime.now()


def get_last_update_time(manager_key: str) -> datetime | None:
    return state[manager_key]["last_update_time"]


def get_known_responses(manager_key: str) -> dict:
    return state[manager_key]["known_responses"]


def add_known_response(manager_key: str, load_id: str, response_id: str):
    if load_id not in state[manager_key]["known_responses"]:
        state[manager_key]["known_responses"][load_id] = []
    state[manager_key]["known_responses"][load_id].append(response_id)


def is_responses_initialized(manager_key: str) -> bool:
    return state[manager_key]["responses_initialized"]


def set_responses_initialized(manager_key: str):
    state[manager_key]["responses_initialized"] = True
