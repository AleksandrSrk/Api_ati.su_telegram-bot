from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta

from config import MANAGERS, UPDATE_INTERVAL_MINUTES
from state import (
    is_auto_update_enabled,
    set_last_update_time,
    get_last_response_check,
    set_last_response_check,
)

from ati_client import (
    get_my_loads,
    renew_load,
    parse_load,
    get_new_responses,
)

scheduler = AsyncIOScheduler()


# =============================================
# 🔄 Автообновление грузов
# =============================================
async def update_loads_job(manager_key: str):

    if not is_auto_update_enabled(manager_key):
        return

    print(f"[{manager_key}] автообновление грузов")

    loads_raw = await get_my_loads(manager_key)
    if not loads_raw:
        return

    results = []

    for load_raw in loads_raw:
        load = parse_load(load_raw)

        # ❌ если нельзя обновить — возвращаем причину
        if not load["can_renew"]:
            results.append({
                "success": False,
                "from_city": load["from_city"],
                "to_city": load["to_city"],
                "weight": load["weight"],
                "reason": load["renew_restriction"] or "ещё не прошёл час",
                "load_id": load["id"],
            })
            continue

        # ✅ обновляем
        result = await renew_load(manager_key, load["id"])

        result.update({
            "from_city": load["from_city"],
            "to_city": load["to_city"],
            "weight": load["weight"],
            "load_id": load["id"],
        })

        results.append(result)

    set_last_update_time(manager_key)

    from telegram_bot import notify_update_result
    await notify_update_result(manager_key, results)


# =============================================
# ⚡ НОВЫЕ ОТКЛИКИ (реалтайм через API)
# =============================================
async def check_new_responses_job(manager_key: str):

    # когда последний раз проверяли
    last_check = get_last_response_check(manager_key)

    # если первый запуск — берем последние 30 сек
    if not last_check:
        last_check = datetime.utcnow() - timedelta(seconds=30)

    date_from = last_check.isoformat() + "Z"

    responses = await get_new_responses(manager_key, date_from)

    # если нет — просто обновляем время
    if not responses:
        set_last_response_check(manager_key, datetime.utcnow())
        return

    # получаем грузы чтобы сопоставить
    loads_raw = await get_my_loads(manager_key)
    loads_map = {}

    for l in loads_raw:
        parsed = parse_load(l)
        loads_map[str(parsed["id"])] = parsed

    from telegram_bot import notify_new_response

    for r in responses:

        # пропускаем устаревшие
        if r.get("IsOutdated"):
            continue

        load_id = str(r.get("LoadId"))
        load = loads_map.get(load_id)

        if not load:
            continue

        # отправляем сразу 1 отклик
        await notify_new_response(manager_key, load, [r])

    # обновляем время последней проверки
    set_last_response_check(manager_key, datetime.utcnow())


# =============================================
# 🚀 ЗАПУСК ПЛАНИРОВЩИКА
# =============================================
def start_scheduler():

    for manager_key in MANAGERS.keys():

        # автообновление грузов (раз в час)
        scheduler.add_job(
            update_loads_job,
            trigger="interval",
            minutes=UPDATE_INTERVAL_MINUTES,
            args=[manager_key],
            id=f"update_{manager_key}",
            next_run_time=datetime.now() + timedelta(hours=1),
        )

        # ⚡ проверка новых откликов (каждые 30 сек)
        scheduler.add_job(
            check_new_responses_job,
            trigger="interval",
            seconds=30,
            args=[manager_key],
            id=f"responses_{manager_key}",
            next_run_time=datetime.now() + timedelta(seconds=10),
        )

    scheduler.start()
    print("✅ scheduler запущен")