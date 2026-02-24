# ati_client.py

import httpx
import json
import os
from config import MANAGERS

ATI_BASE_URL = "https://api.ati.su"

_CITIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cities.json")
_CITY_NAMES: dict[str, str] = {}

try:
    with open(_CITIES_FILE, "r", encoding="utf-8") as f:
        _CITY_NAMES = json.load(f)
    print(f"[Cities] Загружено {len(_CITY_NAMES)} городов из cities.json")
except FileNotFoundError:
    print("[Cities] ВНИМАНИЕ: cities.json не найден! Запусти fetch_cities.py")
except Exception as e:
    print(f"[Cities] Ошибка загрузки cities.json: {e}")


def get_headers(manager_key: str) -> dict:
    return {
        "Authorization": f"Bearer {MANAGERS[manager_key]['access_token']}",
        "Content-Type": "application/json",
    }


def city_name(city_id) -> str:
    if city_id is None:
        return "—"
    return _CITY_NAMES.get(str(city_id), f"г.{city_id}")


def parse_load(load: dict) -> dict:
    load_id = load.get("Id", "")
    load_number = load.get("LoadNumber", "")

    loading = load.get("Loading") or {}
    from_city = city_name(loading.get("CityId"))

    unloading = load.get("Unloading") or {}
    to_city = city_name(unloading.get("CityId"))

    cargo = load.get("Cargo") or {}
    weight = cargo.get("Weight")
    if weight is None:
        cargos_list = loading.get("LoadingCargos") or []
        if cargos_list:
            weight = cargos_list[0].get("Weight")
    weight = weight if weight is not None else "—"

    cargo_name = cargo.get("CargoTypeName") or cargo.get("Name") or ""
    if not cargo_name:
        cargos_list = loading.get("LoadingCargos") or []
        if cargos_list:
            cargo_name = cargos_list[0].get("Name", "")

    can_renew = load.get("CanBeRenewed", False)
    renew_restriction = load.get("RenewRestriction") or ""
    contact_id = load.get("ContactId1")
    response_count = load.get("OfferCount", 0) or 0

    return {
        "id": str(load_id),
        "load_number": load_number,
        "from_city": from_city,
        "to_city": to_city,
        "weight": weight,
        "can_renew": can_renew,
        "renew_restriction": renew_restriction,
        "cargo_name": cargo_name,
        "contact_id": contact_id,
        "response_count": response_count,
    }


async def get_my_loads(manager_key: str) -> list:
    """Получить грузы конкретного менеджера (фильтрация по contact_id)"""
    url = f"{ATI_BASE_URL}/v1.0/loads"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=get_headers(manager_key))

    if response.status_code != 200:
        print(f"[ATI] Ошибка получения грузов: {response.status_code} {response.text}")
        return []

    data = response.json()
    all_loads = data if isinstance(data, list) else data.get("loads", [])

    manager_contact_id = MANAGERS[manager_key].get("contact_id")
    if manager_contact_id is not None:
        filtered = [l for l in all_loads if l.get("ContactId1") == manager_contact_id]
        return filtered

    return all_loads


async def get_load_responses(manager_key: str, load_id: str) -> list:
    """Получить встречные предложения по конкретному грузу"""
    url = f"{ATI_BASE_URL}/v1.0/loads/{load_id}/responses"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=get_headers(manager_key))

    print(f"[ATI] get_load_responses {load_id}: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        items = data if isinstance(data, list) else (data.get("responses") or data.get("items") or [])
        return items
    print(f"[ATI] get_load_responses {load_id} error: {response.status_code}")
    return []


async def renew_load(manager_key: str, load_id: str) -> dict:
    """Обновить (поднять) груз — PUT /v1.0/loads/{id}/renew"""
    url = f"{ATI_BASE_URL}/v1.0/loads/{load_id}/renew"
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=get_headers(manager_key))
    print(f"[ATI] renew_load {load_id}: {response.status_code}")
    if response.status_code in (200, 204):
        return {"success": True, "load_id": load_id}
    elif response.status_code == 429:
        return {"success": False, "load_id": load_id, "reason": "Слишком много запросов"}
    else:
        try:
            data = response.json()
            reason = data.get("Reason") or data.get("reason") or data.get("error") or response.text
        except Exception:
            reason = response.text
        return {"success": False, "load_id": load_id, "reason": reason}


async def get_new_responses(manager_key: str) -> list:
    """Получить новые встречные предложения: GET /v1.0/loads/new-responses"""
    url = f"{ATI_BASE_URL}/v1.0/loads/new-responses"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=get_headers(manager_key))
    print(f"[ATI] get_new_responses: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        if isinstance(data, list):
            return data
        return data.get("responses", data.get("counter_offers", []))
    return []
