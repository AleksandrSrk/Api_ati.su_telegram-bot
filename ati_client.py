# =============================================
# ati_client.py
# Работа с API ATI.SU
# =============================================

import httpx
import json
import os
from config import MANAGERS

ATI_BASE_URL = "https://api.ati.su"
TIMEOUT = 20.0

# =============================================
# Загрузка городов
# =============================================

_CITIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cities.json")
_CITY_NAMES: dict[str, str] = {}

try:
    with open(_CITIES_FILE, "r", encoding="utf-8") as f:
        _CITY_NAMES = json.load(f)
    print(f"[Cities] Загружено {len(_CITY_NAMES)} городов")
except FileNotFoundError:
    print("[Cities] ВНИМАНИЕ: cities.json не найден!")
except Exception as e:
    print(f"[Cities] Ошибка загрузки cities.json: {e}")


# =============================================
# Общие утилиты
# =============================================

def get_headers(manager_key: str) -> dict:
    return {
        "Authorization": f"Bearer {MANAGERS[manager_key]['access_token']}",
        "Content-Type": "application/json",
    }


def city_name(city_id) -> str:
    if city_id is None:
        return "—"
    return _CITY_NAMES.get(str(city_id), f"г.{city_id}")


# =============================================
# Груз в архив
# =============================================
async def delete_load(manager_key: str, load_id: str) -> dict:
    url = f"{ATI_BASE_URL}/v1.0/loads/{load_id}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.delete(url, headers=get_headers(manager_key))
    except httpx.RequestError as e:
        return {"success": False, "reason": str(e)}

    if response.status_code in (200, 204):
        return {"success": True}

    return {
        "success": False,
        "reason": response.text
    }
# =============================================
# Парсинг груза
# =============================================

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

    return {
        "id": str(load_id),
        "load_number": load_number,
        "from_city": from_city,
        "to_city": to_city,
        "weight": weight,
        "can_renew": load.get("CanBeRenewed", False),
        "renew_restriction": load.get("RenewRestriction") or "",
        "contact_id": load.get("ContactId1"),
        "response_count": load.get("OfferCount", 0) or 0,
        "cargo_name": cargo_name,
    }


# =============================================
# Безопасный JSON
# =============================================

async def safe_json(response: httpx.Response):
    try:
        return response.json()
    except Exception:
        print(f"[ATI] Ошибка JSON: {response.text[:300]}")
        return None


# =============================================
# Получение МОИХ грузов (исправленная логика)
# =============================================

async def get_my_loads(manager_key: str) -> list:
    url = f"{ATI_BASE_URL}/v1.0/loads"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, headers=get_headers(manager_key))
    except httpx.RequestError as e:
        print(f"[ATI] Ошибка сети get_my_loads: {e}")
        return []

    if response.status_code != 200:
        print(f"[ATI] Ошибка получения грузов: {response.status_code}")
        return []

    data = await safe_json(response)
    if not data:
        return []

    # 👉 Получаем список всех грузов
    loads = data if isinstance(data, list) else data.get("loads", [])

    print(f"[{manager_key}] всего грузов: {len(loads)}")

    # =============================================
    # 🔥 ФИЛЬТР ПО contact_id (ключевой фикс)
    # =============================================

    manager_contact_id = MANAGERS[manager_key].get("contact_id")

    if manager_contact_id is not None:
        filtered_loads = [
            load for load in loads
            if str(load.get("ContactId1")) == str(manager_contact_id)
        ]

        print(f"[{manager_key}] после фильтра: {len(filtered_loads)}")

        return filtered_loads

    return loads


# =============================================
# Получение откликов
# =============================================

async def get_load_responses(manager_key: str, load_id: str) -> list:
    url = f"{ATI_BASE_URL}/v1.0/loads/{load_id}/responses"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(url, headers=get_headers(manager_key))
    except httpx.RequestError as e:
        print(f"[ATI] Ошибка сети get_load_responses: {e}")
        return []

    if response.status_code != 200:
        print(f"[ATI] get_load_responses error: {response.status_code}")
        return []

    data = await safe_json(response)
    if not data:
        return []

    return data if isinstance(data, list) else (
        data.get("responses") or data.get("items") or []
    )


# =============================================
# Обновление груза
# =============================================

async def renew_load(manager_key: str, load_id: str) -> dict:
    url = f"{ATI_BASE_URL}/v1.0/loads/{load_id}/renew"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.put(url, headers=get_headers(manager_key))
    except httpx.RequestError as e:
        return {"success": False, "load_id": load_id, "reason": str(e)}

    if response.status_code in (200, 204):
        return {"success": True, "load_id": load_id}

    if response.status_code == 429:
        return {"success": False, "load_id": load_id, "reason": "Слишком много запросов"}

    data = await safe_json(response)
    reason = None

    if data:
        reason = data.get("Reason") or data.get("error")

    return {
        "success": False,
        "load_id": load_id,
        "reason": reason or response.text,
    }


# =============================================
# Новые отклики
# =============================================

async def get_new_responses(manager_key: str, date_from: str) -> list:
    url = f"{ATI_BASE_URL}/v1.0/loads/new/responses"

    params = {
        "dateFrom": date_from
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                url,
                headers=get_headers(manager_key),
                params=params
            )
    except httpx.RequestError as e:
        print(f"[ATI] ошибка new_responses: {e}")
        return []

    if response.status_code != 200:
        print(f"[ATI] new_responses status: {response.status_code}")
        return []

    data = await safe_json(response)
    if not data:
        return []

    if isinstance(data, list):
        return data

    return data.get("responses") or []


async def get_new_responses(manager_key: str, date_from: str) -> list:
    url = f"{ATI_BASE_URL}/v1.0/loads/new/responses"

    params = {
        "dateFrom": date_from
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                url,
                headers=get_headers(manager_key),
                params=params
            )
    except httpx.RequestError as e:
        print(f"[ATI] ошибка new_responses: {e}")
        return []

    if response.status_code != 200:
        print(f"[ATI] new_responses status: {response.status_code}")
        return []

    data = await safe_json(response)
    if not data:
        return []

    if isinstance(data, list):
        return data

    return data.get("responses") or []