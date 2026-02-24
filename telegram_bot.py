# telegram_bot.py

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.fsm.storage.memory import MemoryStorage
from datetime import datetime, timedelta

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, MANAGERS
from state import (
    is_auto_update_enabled, set_auto_update, toggle_auto_update,
    get_last_update_time, get_known_responses,
    get_active_manager, set_active_manager,
)
from ati_client import get_my_loads, get_load_responses, renew_load, get_new_responses, parse_load


def normalize_phone(phone: str) -> str:
    """Приводит телефон к формату +7XXXXXXXXXX для кликабельности в Telegram"""
    if not phone or phone == "—":
        return phone

    # Удаляем всё кроме цифр
    import re
    digits = re.sub(r"[^\d]", "", phone)
    if not digits:
        return phone

    # Если начинается с 8 — заменяем на 7
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]

    # Если 10 цифр — добавляем 7 в начало
    if len(digits) == 10:
        digits = "7" + digits

    if digits.startswith("7") and len(digits) == 11:
        return f"+{digits}"
    return phone  # если не распознали — оставляем как есть


def calc_vat(price: float, has_vat: bool) -> tuple[float, float]:
    """Возвращает (с_ндс, без_ндс). НДС = 22%"""
    VAT = 1.22
    if has_vat:
        return price, round(price / VAT)
    else:
        return round(price * VAT), price


def format_price(price_with_vat: float, price_without_vat: float) -> str:
    """Форматирует ставку: обе суммы"""

    def fmt(p):
        return f"{int(p):,}".replace(",", " ")

    return f"{fmt(price_with_vat)} ₽ с НДС / {fmt(price_without_vat)} ₽ без НДС"


def parse_response_price(resp: dict) -> tuple[float, float, float]:
    """
    Возвращает (price_with_vat, price_without_vat, sort_price).
    PayAttributes: 1 = с НДС, 2 = без НДС
    sort_price — ставка с НДС для сравнения.
    """
    price = resp.get("Price") or 0
    pay_attr = resp.get("PayAttributes", 2)
    has_vat = pay_attr == 1
    with_vat, without_vat = calc_vat(price, has_vat)
    return with_vat, without_vat, with_vat  # sort by price_with_vat


bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# один раз покажем легенду по эмодзи
bot_started = False


def get_manager_key_by_chat(chat_id: int) -> str | None:
    for key, cid in TELEGRAM_CHAT_IDS.items():
        if cid == chat_id:
            return key
    return None


# =============================================
# Клавиатуры
# =============================================

def main_reply_keyboard(manager_key: str) -> ReplyKeyboardMarkup:
    auto = is_auto_update_enabled(manager_key)
    auto_label = (
        "🟢 Автообновление всех грузов: ВКЛ"
        if auto
        else "🔴 Автообновление всех грузов: ВЫКЛ"
    )
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои грузы"), KeyboardButton(text="⏱ До обновления")],
            [KeyboardButton(text=auto_label)],
            [KeyboardButton(text="🔄 Обновить вручную"), KeyboardButton(text="👤 Сменить менеджера")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def managers_inline_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, data in MANAGERS.items():
        buttons.append(
            [InlineKeyboardButton(text=f"👤 {data['name']}", callback_data=f"select_{key}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def loads_renew_keyboard(loads: list) -> InlineKeyboardMarkup:
    """Клавиатура для ручного обновления — кнопка под каждым грузом"""
    buttons = []
    for load in loads:
        label = f"{load['from_city']} → {load['to_city']}"
        if load["can_renew"]:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🔄 Обновить: {label}",
                        callback_data=f"renew_{load['id']}",
                    )
                ]
            )
        else:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"⏳ Недоступно: {label}",
                        callback_data=f"renew_blocked_{load['id']}",
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =============================================
# Хендлеры команд
# =============================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    global bot_started
    if not bot_started:
        bot_started = True
        await message.answer(
            "Обозначения:\n"
            "🟡 — груз можно обновить\n"
            "♻️ — обновление груза выполнено\n"
            "🔥 — лучшее встречное предложение по цене\n"
            "⏳ — пока нельзя обновить / нет предложений\n"
            "🔄 — запустить обновление вручную\n"
            "📋 — список грузов\n"
            "⏱ — время до автообновления\n"
        )

    await message.answer(
        "👋 Привет! Выбери менеджера для работы:",
        reply_markup=managers_inline_keyboard(),
    )


@dp.callback_query(F.data.startswith("select_"))
async def select_manager(callback: CallbackQuery):
    manager_key = callback.data.replace("select_", "")
    name = MANAGERS[manager_key]["name"]
    chat_id = callback.message.chat.id
    set_active_manager(chat_id, manager_key)
    await callback.message.edit_text(
        f"✅ Выбран менеджер: *{name}*",
        parse_mode="Markdown",
    )
    await callback.message.answer(
        "Что делаем?",
        reply_markup=main_reply_keyboard(manager_key),
    )


# =============================================
# Хендлеры кнопок снизу (ReplyKeyboard)
# =============================================

@dp.message(F.text == "👤 Сменить менеджера")
async def change_manager_handler(message: Message):
    await message.answer(
        "👤 Выбери менеджера:",
        reply_markup=managers_inline_keyboard(),
    )


@dp.message(F.text == "📋 Мои грузы")
async def my_loads_handler(message: Message):
    chat_id = message.chat.id
    manager_key = get_active_manager(chat_id) or get_manager_key_by_chat(chat_id)
    if not manager_key:
        await message.answer("Сначала выбери менеджера через /start")
        return

    await message.answer("⏳ Загружаю грузы...")
    loads_raw = await get_my_loads(manager_key)
    if not loads_raw:
        await message.answer("📭 Активных грузов не найдено")
        return

    def e(t) -> str:
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = [f"📋 Активные грузы {e(MANAGERS[manager_key]['name'])}:\n"]

    for i, load_raw in enumerate(loads_raw, 1):
        load = parse_load(load_raw)
        renew_icon = "🟡" if load["can_renew"] else "⏳"
        weight_str = f"{load['weight']}т" if load["weight"] != "—" else "—"
        resp_count = load.get("response_count", 0)

        lines.append(
            f"{i}️⃣ {renew_icon} {e(load['from_city'])} → {e(load['to_city'])}, {e(weight_str)}"
        )

        if not load["can_renew"] and load["renew_restriction"]:
            lines.append(f"  {e(load['renew_restriction'])}")

        # Встречные предложения
        if resp_count == 0:
            lines.append("  💬 Встречных предложений нет")
        else:
            lines.append(f"  💬 Встречных предложений: {resp_count}")
            responses = await get_load_responses(manager_key, load["id"])
            if responses:
                priced = []
                for resp in responses:
                    with_vat, without_vat, sort_p = parse_response_price(resp)
                    if sort_p > 0:
                        priced.append((sort_p, with_vat, without_vat, resp))
                priced.sort(key=lambda x: x[0])
                best_resp_id = priced[0][3].get("ResponseId") if priced else None

                for sort_p, with_vat, without_vat, resp in priced:
                    firm_info = resp.get("FirmInfo") or {}
                    contact_info = firm_info.get("Contact") or {}
                    company = (
                        firm_info.get("FullFirmName")
                        or resp.get("FirmName")
                        or "—"
                    )
                    stars = firm_info.get("TotalScore")
                    stars_str = (
                        f"{stars:.2f}".rstrip("0").rstrip(".")
                        if isinstance(stars, float)
                        else (str(stars) if stars else "—")
                    )
                    price_str = (
                        format_price(with_vat, without_vat)
                        if with_vat > 0
                        else "ставка не указана"
                    )
                    contact_name = contact_info.get("Name") or "—"
                    phone = normalize_phone(
                        contact_info.get("Telephone")
                        or contact_info.get("Mobile")
                        or "—"
                    )
                    comment = resp.get("Note") or "—"
                    best = "🔥 " if resp.get("ResponseId") == best_resp_id else ""
                    lines.append(
                        "  ┌─────────────────\n"
                        f"  {best}🏢 {e(company)} ⭐{e(stars_str)}\n"
                        f"  👤 {e(contact_name)} 📞 {e(phone)}\n"
                        f"  💰 {e(price_str)}\n"
                        f"  💬 {e(comment)}\n"
                        "  └─────────────────"
                    )

        lines.append("")  # пустая строка между грузами

    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text == "⏱ До обновления")
async def next_update_handler(message: Message):
    chat_id = message.chat.id
    manager_key = get_active_manager(chat_id) or get_manager_key_by_chat(chat_id)
    if not manager_key:
        await message.answer("Сначала выбери менеджера через /start")
        return

    last = get_last_update_time(manager_key)
    if not last:
        await message.answer("⏱ Автообновлений ещё не было")
        return

    next_time = last + timedelta(hours=1)
    remaining = next_time - datetime.now()
    minutes = max(0, int(remaining.total_seconds() // 60))
    seconds = max(0, int(remaining.total_seconds() % 60))
    await message.answer(
        f"⏱ До следующего автообновления: *{minutes} мин {seconds} сек*",
        parse_mode="Markdown",
    )


@dp.message(
    F.text.in_(
        {
            "🟢 Автообновление всех грузов: ВКЛ",
            "🔴 Автообновление всех грузов: ВЫКЛ",
        }
    )
)
async def toggle_auto_handler(message: Message):
    chat_id = message.chat.id
    manager_key = get_active_manager(chat_id) or get_manager_key_by_chat(chat_id)
    if not manager_key:
        await message.answer("Сначала выбери менеджера через /start")
        return

    currently_on = is_auto_update_enabled(manager_key)
    if currently_on:
        # Выключаем
        set_auto_update(manager_key, False)
        await message.answer(
            "🔴 Автообновление выключено",
            reply_markup=main_reply_keyboard(manager_key),
        )
    else:
        # Включаем — сразу обновляем все грузы
        set_auto_update(manager_key, True)
        await message.answer(
            "🟢 Автообновление включено\n⏳ Обновляю грузы прямо сейчас...",
            reply_markup=main_reply_keyboard(manager_key),
        )

        loads_raw = await get_my_loads(manager_key)
        if not loads_raw:
            await message.answer("📭 Грузов не найдено")
            return

        def e(t) -> str:
            return (
                str(t)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        lines = [f"🔄 Результат обновления {e(MANAGERS[manager_key]['name'])}:\n"]

        for load_raw in loads_raw:
            load = parse_load(load_raw)
            route = f"{load['from_city']} → {load['to_city']}"
            weight_str = (
                f"{load['weight']}т" if load["weight"] != "—" else "—"
            )

            if not load["can_renew"]:
                restriction = load["renew_restriction"] or "Ещё не прошёл час"
                lines.append(
                    f"⏳ {e(route)}, {e(weight_str)}\n  {e(restriction)}"
                )
            else:
                result = await renew_load(manager_key, load["id"])
                if result["success"]:
                    lines.append(
                        f"♻️ {e(route)}, {e(weight_str)} — обновлён"
                    )
                else:
                    reason = result.get("reason", "ошибка")
                    lines.append(
                        f"❌ {e(route)}, {e(weight_str)}\n  {e(reason)}"
                    )

            # Краткий список откликов
            responses = await get_load_responses(manager_key, load["id"])
            if responses:
                priced = []
                for resp in responses:
                    with_vat, without_vat, sort_p = parse_response_price(resp)
                    if sort_p > 0:
                        priced.append((sort_p, with_vat, without_vat, resp))
                priced.sort(key=lambda x: x[0])
                best_resp_id = priced[0][3].get("ResponseId") if priced else None

                lines.append(f"  💬 Встречных предложений: {len(responses)}")
                for sort_p, with_vat, without_vat, resp in priced:
                    firm_info = resp.get("FirmInfo") or {}
                    company = (
                        firm_info.get("FullFirmName")
                        or resp.get("FirmName")
                        or "—"
                    )
                    stars = firm_info.get("TotalScore")
                    stars_str = (
                        f"{stars:.1f}"
                        if isinstance(stars, float)
                        else str(stars or "—")
                    )
                    price_str = (
                        format_price(with_vat, without_vat)
                        if with_vat > 0
                        else "—"
                    )
                    best = "🔥 " if resp.get("ResponseId") == best_resp_id else ""
                    lines.append(
                        f"  {best}{e(company)} ⭐{stars_str} — {e(price_str)}"
                    )
            else:
                lines.append(f"  💬 Встречных предложений нет")

            lines.append("")

        from state import set_last_update_time

        set_last_update_time(manager_key)
        await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text == "🔄 Обновить вручную")
async def manual_renew_list_handler(message: Message):
    """Показывает список грузов с кнопкой Обновить под каждым"""
    chat_id = message.chat.id
    manager_key = get_active_manager(chat_id) or get_manager_key_by_chat(chat_id)
    if not manager_key:
        await message.answer("Сначала выбери менеджера через /start")
        return

    await message.answer("⏳ Загружаю грузы...")
    loads_raw = await get_my_loads(manager_key)
    if not loads_raw:
        await message.answer("📭 Активных грузов не найдено")
        return

    loads = [parse_load(l) for l in loads_raw]
    lines = [
        f"🔄 *Ручное обновление грузов {MANAGERS[manager_key]['name']}:*\n"
    ]
    for i, load in enumerate(loads, 1):
        renew_icon = "🟡" if load["can_renew"] else "⏳"
        weight_str = f"{load['weight']}т" if load["weight"] != "—" else "—"
        lines.append(
            f"{i}️⃣ {renew_icon} *{load['from_city']} → {load['to_city']}*, {weight_str}"
        )
        if not load["can_renew"] and load["renew_restriction"]:
            lines.append(f" _{load['renew_restriction']}_")
        lines.append("")

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=loads_renew_keyboard(loads),
    )


@dp.callback_query(F.data.startswith("renew_blocked_"))
async def renew_blocked_handler(callback: CallbackQuery):
    await callback.answer("⏳ Этот груз пока нельзя обновить", show_alert=True)


@dp.callback_query(F.data.startswith("renew_") & ~F.data.startswith("renew_blocked_"))
async def renew_single_handler(callback: CallbackQuery):
    """Обновление одного груза по кнопке"""
    load_id = callback.data.replace("renew_", "")
    chat_id = callback.message.chat.id
    manager_key = get_active_manager(chat_id) or get_manager_key_by_chat(chat_id)
    if not manager_key:
        await callback.answer("Сначала выбери менеджера", show_alert=True)
        return

    await callback.answer("⏳ Обновляю...")

    loads_raw = await get_my_loads(manager_key)
    load_info = None
    for l in loads_raw:
        if str(l.get("Id", "")) == load_id:
            load_info = parse_load(l)
            break

    result = await renew_load(manager_key, load_id)
    route = (
        f"{load_info['from_city']} → {load_info['to_city']}"
        if load_info
        else load_id
    )
    if result["success"]:
        await callback.message.reply(
            f"♻️ Груз обновлён: {route}", parse_mode="HTML"
        )
    else:
        reason = result.get("reason", "неизвестная ошибка")
        await callback.message.reply(
            f"❌ {route} — не обновлён: {reason}", parse_mode="HTML"
        )


# =============================================
# Функции для scheduler
# =============================================

async def do_renew_all(manager_key: str) -> list:
    """Обновляет все грузы менеджера, возвращает результаты"""
    loads_raw = await get_my_loads(manager_key)
    results = []
    for load_raw in loads_raw:
        load = parse_load(load_raw)
        if not load["can_renew"]:
            results.append(
                {
                    "success": False,
                    "from_city": load["from_city"],
                    "to_city": load["to_city"],
                    "weight": load["weight"],
                    "reason": load["renew_restriction"] or "Ещё не прошёл час",
                    "load_id": load["id"],
                }
            )
        else:
            result = await renew_load(manager_key, load["id"])
            result["from_city"] = load["from_city"]
            result["to_city"] = load["to_city"]
            result["weight"] = load["weight"]
            result["load_id"] = load["id"]
            results.append(result)
    return results


async def notify_update_result(manager_key: str, results: list):
    """Уведомление о результате обновления грузов — с краткими откликами"""
    chat_id = TELEGRAM_CHAT_IDS.get(manager_key)
    if not chat_id or chat_id == 987654321:
        print(f"[Bot] Нет chat_id для {manager_key}")
        return

    def e(t) -> str:
        return (
            str(t)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    lines = [f"🔄 Обновление грузов {e(MANAGERS[manager_key]['name'])}:\n"]

    for r in results:
        route = f"{r.get('from_city', '—')} → {r.get('to_city', '—')}"
        weight_str = f"{r.get('weight', '—')}т"
        if r.get("success"):
            lines.append(f"♻️ {e(route)}, {e(weight_str)} — обновлён")
        else:
            reason = r.get("reason", "неизвестно")
            lines.append(
                f"⏳ {e(route)}, {e(weight_str)}\n  {e(reason)}"
            )

        load_id = r.get("load_id")
        if load_id:
            responses = await get_load_responses(manager_key, load_id)
            if responses:
                priced = []
                for resp in responses:
                    with_vat, without_vat, sort_p = parse_response_price(resp)
                    if sort_p > 0:
                        priced.append((sort_p, with_vat, without_vat, resp))
                priced.sort(key=lambda x: x[0])
                best_resp_id = priced[0][3].get("ResponseId") if priced else None

                lines.append(f"  💬 Встречных предложений: {len(responses)}")
                for sort_p, with_vat, without_vat, resp in priced:
                    firm_info = resp.get("FirmInfo") or {}
                    company = (
                        firm_info.get("FullFirmName")
                        or resp.get("FirmName")
                        or "—"
                    )
                    stars = firm_info.get("TotalScore")
                    stars_str = (
                        f"{stars:.1f}"
                        if isinstance(stars, float)
                        else str(stars or "—")
                    )
                    price_str = (
                        format_price(with_vat, without_vat)
                        if with_vat > 0
                        else "—"
                    )
                    best = "🔥 " if resp.get("ResponseId") == best_resp_id else ""
                    lines.append(
                        f"  {best}{e(company)} ⭐{stars_str} — {e(price_str)}"
                    )
            else:
                lines.append(f"  💬 Встречных предложений нет")

        lines.append("")

    lines.append(f"🕐 {datetime.now().strftime('%d %b, %H:%M')}")
    await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


async def notify_new_response(
    manager_key: str, load: dict, all_responses: list, new_responses: list
):
    """Уведомление о новом отклике — с полным списком и выделением лучшей ставки"""
    chat_id = TELEGRAM_CHAT_IDS.get(manager_key)
    if not chat_id or chat_id == 987654321:
        print(
            f"[Bot] Нет chat_id для {manager_key}, уведомление не отправлено"
        )
        return

    def e(t) -> str:
        return (
            str(t)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    from_city = load.get("from_city") or "—"
    to_city = load.get("to_city") or "—"
    weight = load.get("weight", "—")
    weight_str = f"{weight}т" if weight != "—" else "—"

    priced = []
    for r in all_responses:
        with_vat, without_vat, sort_price = parse_response_price(r)
        if sort_price > 0:
            priced.append((sort_price, with_vat, without_vat, r))
    priced.sort(key=lambda x: x[0])
    best_response_id = priced[0][3].get("ResponseId") if priced else None

    lines = [
        "🔔 Новое встречное предложение!",
        f"📦 {e(from_city)} → {e(to_city)}, {e(weight_str)}",
        "",
    ]

    def render_response(r, is_new: bool, is_best: bool) -> str:
        firm_info = r.get("FirmInfo") or {}
        contact_info = firm_info.get("Contact") or {}
        company = (
            firm_info.get("FullFirmName") or r.get("FirmName") or "—"
        )
        stars = firm_info.get("TotalScore")
        stars_str = (
            f"{stars:.2f}".rstrip("0").rstrip(".")
            if isinstance(stars, float)
            else str(stars or "—")
        )
        with_vat, without_vat, _ = parse_response_price(r)
        price_str = (
            format_price(with_vat, without_vat)
            if with_vat > 0
            else "ставка не указана"
        )
        contact_name = contact_info.get("Name") or "—"
        phone = normalize_phone(
            contact_info.get("Telephone")
            or contact_info.get("Mobile")
            or "—"
        )
        comment = r.get("Note") or "—"
        badge = ""
        if is_best:
            badge += "🔥 "
        if is_new:
            badge += "🆕 "
        return (
            " ┌─────────────────\n"
            f" {badge}{e(company)} ⭐{e(stars_str)}\n"
            f" 👤 {e(contact_name)} 📞 {e(phone)}\n"
            f" 💰 {e(price_str)}\n"
            f" 💬 {e(comment)}\n"
            " └─────────────────"
        )

    new_ids = {r.get("ResponseId") for r in new_responses}
    for _, _, _, r in priced:
        is_new = r.get("ResponseId") in new_ids
        is_best = r.get("ResponseId") == best_response_id
        lines.append(render_response(r, is_new, is_best))

    lines.append(f"\n🕐 {datetime.now().strftime('%d %b, %H:%M')}")
    await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
