# state.py

from datetime import datetime
from config import MANAGERS

state = {
    key: {
        "auto_update": False,
        "last_update_time": None,
        "last_response_check": None,
    }
    for key in MANAGERS.keys()
}


def is_auto_update_enabled(manager_key: str) -> bool:
    return state[manager_key]["auto_update"]


def set_auto_update(manager_key: str, value: bool):
    state[manager_key]["auto_update"] = value


def set_last_update_time(manager_key: str):
    state[manager_key]["last_update_time"] = datetime.now()


def get_last_update_time(manager_key: str) -> datetime | None:
    return state[manager_key]["last_update_time"]


def get_last_response_check(manager_key: str) -> datetime | None:
    return state[manager_key]["last_response_check"]


def set_last_response_check(manager_key: str, dt: datetime):
    state[manager_key]["last_response_check"] = dt
