# scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import MANAGERS, UPDATE_INTERVAL_MINUTES
from state import (
    is_auto_update_enabled, set_last_update_time,
    get_known_responses, add_known_response,
    is_responses_initialized, set_responses_initialized,
)
from ati_client import get_my_loads, renew_load, parse_load, get_load_responses

scheduler = AsyncIOScheduler()


async def update_loads_job(manager_key: str):
    """Автообновление грузов — раз в час"""
    if not is_auto_update_enabled(manager_key):
        return

    print(f"[{manager_key}] Автообновление грузов...")

    loads_raw = await get_my_loads(manager_key)
    if not loads_raw:
        return

    results = []

    for load_raw in loads_raw:
        load = parse_load(load_raw)
        if not load["can_renew"]:
            results.append({
                "success": False,
                "from_city": load["from_city"],
                "to_city": load["to_city"],
                "weight": load["weight"],
                "reason": load["renew_restriction"] or "Ещё не прошёл час",
                "load_id": load["id"],
            })
            continue

        result = await renew_load(manager_key, load["id"])
        result["from_city"] = load["from_city"]
        result["to_city"] = load["to_city"]
        result["weight"] = load["weight"]
        result["load_id"] = load["id"]
        results.append(result)

    set_last_update_time(manager_key)

    from telegram_bot import notify_update_result
    await notify_update_result(manager_key, results)


async def check_responses_job(manager_key: str):
    """
    Проверка новых откликов каждые 3 минуты.

    Первый запуск: просто запоминаем все текущие ResponseId и ничего не шлём.
    Следующие запуски: шлём уведомления только по новым откликам.
    """

    loads_raw = await get_my_loads(manager_key)
    if not loads_raw:
        return

    known = get_known_responses(manager_key)

    # Первый запуск для этого менеджера — инициализация known_responses
    if not is_responses_initialized(manager_key):
        for load_raw in loads_raw:
            load = parse_load(load_raw)
            load_id = load["id"]

            # пропускаем грузы без откликов
            if load.get("response_count", 0) == 0:
                continue

            responses = await get_load_responses(manager_key, load_id)
            if not responses:
                continue

            for r in responses:
                rid = r.get("ResponseId")
                if rid:
                    add_known_response(manager_key, load_id, rid)

        set_responses_initialized(manager_key)
        print(f"[{manager_key}] known_responses инициализированы, уведомления включены со следующего цикла.")
        return

    # Обычный режим — ищем новые отклики
    for load_raw in loads_raw:
        load = parse_load(load_raw)
        load_id = load["id"]

        # Пропускаем если нет откликов вообще
        if load.get("response_count", 0) == 0:
            continue

        responses = await get_load_responses(manager_key, load_id)
        if not responses:
            continue

        known_ids = set(known.get(load_id, []))
        new_responses = [r for r in responses if r.get("ResponseId") not in known_ids]

        if not new_responses:
            continue

        # Есть новые — обновляем known и шлём уведомление
        for r in new_responses:
            rid = r.get("ResponseId")
            if rid:
                add_known_response(manager_key, load_id, rid)

        from telegram_bot import notify_new_response
        await notify_new_response(manager_key, load, responses, new_responses)


def start_scheduler():
    from datetime import datetime, timedelta

    for manager_key in MANAGERS.keys():
        # Автообновление грузов
        scheduler.add_job(
            update_loads_job,
            trigger="interval",
            minutes=UPDATE_INTERVAL_MINUTES,
            args=[manager_key],
            id=f"update_{manager_key}",
            next_run_time=datetime.now() + timedelta(hours=1),
        )

        # Проверка новых откликов — каждые 3 минуты
        scheduler.add_job(
            check_responses_job,
            trigger="interval",
            minutes=3,
            args=[manager_key],
            id=f"responses_{manager_key}",
            next_run_time=datetime.now() + timedelta(seconds=30),
        )

    scheduler.start()
    print("[Scheduler] Запущен. Автообновление — выключено до нажатия кнопки.")
