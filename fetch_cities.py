# fetch_cities.py
# Запусти один раз: python fetch_cities.py
# Скачивает все города из АТИ.СУ API и сохраняет в cities.json

import httpx
import json
import sys

ATI_BASE_URL = "https://api.ati.su"

try:
    from config import MANAGERS
    first_manager = next(
        (v for v in MANAGERS.values() if v.get("access_token") and "ВАШ_ACCESS_TOKEN" not in v.get("access_token", "")),
        None
    )
    if not first_manager:
        print("Ошибка: нет валидного access_token в config.py")
        sys.exit(1)
    TOKEN = first_manager["access_token"]
except Exception as e:
    print(f"Ошибка импорта config.py: {e}")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

if __name__ == "__main__":
    print("Загружаю города из АТИ.СУ API...")

    url = f"{ATI_BASE_URL}/v1.0/dictionaries/cities"
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url, headers=HEADERS)

    if response.status_code != 200:
        print(f"Ошибка: {response.status_code} {response.text[:300]}")
        sys.exit(1)

    items = response.json()
    if isinstance(items, dict):
        items = items.get("cities") or items.get("Cities") or []

    # Поля из реального ответа: CityId, CityName
    cities = {}
    for item in items:
        city_id = item.get("CityId")
        name = item.get("CityName") or item.get("ShortName")
        if city_id is not None and name:
            cities[str(city_id)] = name

    with open("cities.json", "w", encoding="utf-8") as f:
        json.dump(cities, f, ensure_ascii=False, indent=2)

    print(f"✅ Сохранено {len(cities)} городов в cities.json")
    print("Примеры:")
    for k, v in list(cities.items())[:5]:
        print(f"  {k}: {v}")

    # Проверим наши города из лога
    test_ids = ["2548", "270", "3611", "60", "7437"]
    print("\nПроверка нужных городов:")
    for cid in test_ids:
        print(f"  {cid}: {cities.get(cid, 'НЕТ В СЛОВАРЕ')}")