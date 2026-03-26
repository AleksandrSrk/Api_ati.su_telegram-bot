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
    is_auto_update_enabled, set_auto_update,
    get_last_update_time,
)
from config import USERS
from ati_client import get_my_loads, get_load_responses, renew_load, parse_load
from ati_client import delete_load

def get_manager_by_user(user_id: int):
    return USERS.get(user_id)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# =========================================================
# 🔧 УТИЛИТЫ ФОРМАТИРОВАНИЯ
# =========================================================

def format_phone(contact: dict) -> str:
    """
    Приводит телефон к формату +7XXXXXXXXXX
    """
    phone_raw = contact.get("Mobile") or contact.get("Telephone") or ""

    phone_clean = (
        phone_raw.replace(" ", "")
        .replace("(", "")
        .replace(")", "")
        .replace("-", "")
        .replace("+", "")
    )

    if phone_clean.startswith("8"):
        phone_clean = "7" + phone_clean[1:]

    return f"+{phone_clean}" if phone_clean else "—"


def format_rating(firm: dict) -> str:
    """
    Форматирует рейтинг:
    ⭐ положительный
    🔴 отрицательный
    """
    rating = firm.get("TotalScore")

    if rating is None:
        return ""

    return f"⭐ {rating:.1f}" if rating >= 0 else f"🔴 {-rating:.1f}"


def format_price(r: dict) -> str:
    nds_price = r.get("NdsPrice") or 0
    not_nds_price = r.get("NotNdsPrice") or 0
    price_value = r.get("Price") or 0
    pay_attr = r.get("PayAttributes", 0)

    try:
        nds_price = float(nds_price)
        not_nds_price = float(not_nds_price)
        price_value = float(price_value)
    except:
        return "—"

    # приоритет — явные поля
    if nds_price > 0:
        return f"{int(nds_price):,} ₽ (с НДС)"
    elif not_nds_price > 0:
        return f"{int(not_nds_price):,} ₽ (без НДС)"

    # fallback через PayAttributes
    elif price_value > 0:
        if pay_attr & 8:
            return f"{int(price_value):,} ₽ (с НДС)"
        else:
            return f"{int(price_value):,} ₽ (без НДС)"

    return "—"


def format_response_line(r: dict, i: int) -> str:
    """
    Формирует одну строку отклика
    """
    firm = r.get("FirmInfo", {})
    contact = firm.get("Contact", {})

    company = firm.get("FullFirmName") or r.get("FirmName") or "—"
    rating = format_rating(firm)
    name = contact.get("Name") or "—"
    phone = format_phone(contact)
    price = format_price(r)
    note = r.get("Note") or "—"

    return (
        f"<b>{i}.</b> {company} {rating}\n"
        f"   👤 {name}\n"
        f"   📞 {phone}\n"
        f"   💰 {price}\n"
        f"   💬 {note}"
    )


def build_responses_lines(responses: list, title: str = None) -> list:
    """
    Собирает список строк откликов:
    - фильтрует устаревшие
    - форматирует
    """
    lines = []

    if title:
        lines.append(title)

    for i, r in enumerate(responses, start=1):
        if r.get("IsOutdated"):
            continue

        lines.append(format_response_line(r, i))

    return lines


# =========================================================
# КЛАВИАТУРА
# =========================================================

def main_keyboard(manager_key: str):
    auto = is_auto_update_enabled(manager_key)

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои грузы")],
            [KeyboardButton(text="Автообновление: ВКЛ" if auto else "Автообновление: ВЫКЛ")],
        ],
        resize_keyboard=True
    )


# =========================================================
# СТАРТ
# =========================================================

@dp.message(Command("start"))
async def start(message: Message):
    manager = get_manager_by_user(message.from_user.id)

    if not manager:
        await message.answer("❌ Нет доступа")
        return

    manager_data = MANAGERS.get(manager)

    if not manager_data:
        await message.answer("❌ Ошибка конфигурации")
        return

    await message.answer(
        f"✅ Вы авторизованы как: {manager_data['name']}",
        reply_markup=main_keyboard(manager)
    )


# =========================================================
# АРХИВ
# =========================================================

@dp.callback_query(F.data.startswith("archive_"))
async def archive_load_handler(callback: CallbackQuery):
    await callback.answer("Убираем в архив...")

    load_id = callback.data.replace("archive_", "")
    manager = get_manager_by_user(callback.from_user.id)
    if not manager:
        await callback.message.answer("❌ Нет доступа")
        return

    result = await delete_load(manager, load_id)

    if result["success"]:
        await callback.message.answer("🗄 Груз убран (архив)")
    else:
        await callback.message.answer(f"❌ Ошибка: {result.get('reason')}")


# =========================================================
# МОИ ГРУЗЫ
# =========================================================

@dp.message(F.text == "📋 Мои грузы")
async def loads_handler(message: Message):

    manager = get_manager_by_user(message.from_user.id)
    if not manager:
        await message.answer("❌ Нет доступа")
        return

    loads = await get_my_loads(manager)

    if not loads:
        await message.answer("Нет грузов")
        return

    for l in loads:
        load = parse_load(l)

        weight = f"{load['weight']}т" if load["weight"] != "—" else "—"

        responses = await get_load_responses(manager, load["id"])
        actual_count = len([r for r in responses if not r.get("IsOutdated")]) if responses else 0

        text = (
            f"{load['from_city']} → {load['to_city']}\n"
            f"Вес: {weight}\n"
            f"💬 Откликов: {actual_count}\n"
        )

        if not load["can_renew"]:
            text += f"\n⏳ {load['renew_restriction']}"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"renew_{load['id']}"),
                    InlineKeyboardButton(text="💬 Отклики", callback_data=f"responses_{load['id']}"),
                  
                ],
                [
                    InlineKeyboardButton(text="🗄 В архив", callback_data=f"archive_{load['id']}")
                ]
            ]
        )

        await message.answer(text, reply_markup=keyboard)


# =========================================================
# АВТООБНОВЛЕНИЕ
# =========================================================

@dp.message(F.text.startswith("Автообновление"))
async def toggle_auto(message: Message):

    manager = get_manager_by_user(message.from_user.id)
    if not manager:
        await message.answer("❌ Нет доступа")
        return

    current = is_auto_update_enabled(manager)
    set_auto_update(manager, not current)

    await message.answer(
        f"Автообновление {'ВКЛЮЧЕНО' if not current else 'ВЫКЛЮЧЕНО'}",
        reply_markup=main_keyboard(manager)
    )


# =========================================================
# ДО ОБНОВЛЕНИЯ
# =========================================================

@dp.message(F.text == "⏱ До обновления")
async def next_update(message: Message):

    manager = get_manager_by_user(message.from_user.id)
    if not manager:
        await message.answer("❌ Нет доступа")
        return

    last = get_last_update_time(manager)

    if not last:
        await message.answer("Ещё не было обновлений")
        return

    mins = int(((last + timedelta(hours=1)) - datetime.now()).total_seconds() // 60)
    await message.answer(f"До обновления: {mins} мин")


# =========================================================
# НОВЫЕ ОТКЛИКИ
# =========================================================

async def notify_new_response(manager_key: str, load: dict, new_responses: list):

    chat_id = TELEGRAM_CHAT_IDS.get(manager_key)
    if not chat_id:
        return

    lines = [
        "🔔 Новый отклик",
        f"{load['from_city']} → {load['to_city']}"
    ]

    lines += build_responses_lines(new_responses)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📋 Показать все отклики",
                callback_data=f"all_{load['id']}"
            )]
        ]
    )

    await bot.send_message(chat_id, "\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


# =========================================================
# ОТКЛИКИ
# =========================================================

@dp.callback_query(F.data.startswith("responses_"))
async def show_responses(callback: CallbackQuery):
    await callback.answer("Загружаю...")

    load_id = callback.data.replace("responses_", "")
    manager = get_manager_by_user(callback.from_user.id)
    if not manager:
        await callback.message.answer("❌ Нет доступа")
        return

    responses = await get_load_responses(manager, load_id)

    if not responses:
        await callback.message.answer("Откликов нет")
        return

    lines = build_responses_lines(responses, "📋 Отклики:")

    if len(lines) == 1:
        await callback.message.answer("Нет актуальных откликов")
        return

    await callback.message.answer("\n".join(lines), parse_mode="HTML")


# =========================================================
# ВСЕ ОТКЛИКИ
# =========================================================

@dp.callback_query(F.data.startswith("all_"))
async def all_responses(callback: CallbackQuery):
    await callback.answer("Загружаю...")

    load_id = callback.data.replace("all_", "")
    manager = get_manager_by_user(callback.from_user.id)
    if not manager:
        await callback.message.answer("❌ Нет доступа")
        return

    responses = await get_load_responses(manager, load_id)

    if not responses:
        await callback.message.answer("Нет откликов")
        return

    lines = build_responses_lines(responses, "📋 Все отклики:")

    if len(lines) == 1:
        await callback.message.answer("Нет актуальных откликов")
        return

    await callback.message.answer("\n".join(lines), parse_mode="HTML")

# =========================================================
# ОБНОВИТЬ ВРУЧНУЮ
# =========================================================

@dp.callback_query(F.data.startswith("renew_"))
async def renew_one(callback: CallbackQuery):
    await callback.answer("Проверяю...")

    load_id = callback.data.replace("renew_", "")
    manager = get_manager_by_user(callback.from_user.id)
    if not manager:
        await callback.message.answer("❌ Нет доступа")
        return

    # 👉 получаем все грузы, чтобы найти нужный
    loads = await get_my_loads(manager)

    if not loads:
        await callback.message.answer("Грузы не найдены")
        return

    # 👉 ищем конкретный груз
    load_data = None
    for l in loads:
        if str(l.get("Id")) == load_id:
            load_data = parse_load(l)
            break

    if not load_data:
        await callback.message.answer("Груз не найден (возможно устарел)")
        return

    # 👉 если нельзя обновить
    if not load_data["can_renew"]:
        restriction = load_data.get("renew_restriction") or "позже"
        await callback.message.answer(f"⏳ Обновить нельзя\n{restriction}")
        return

    # 👉 если можно — обновляем
    result = await renew_load(manager, load_id)

    if result.get("success"):
        await callback.message.answer("✅ Груз обновлён")
    else:
        reason = result.get("reason", "Ошибка обновления")
        await callback.message.answer(f"❌ {reason}")

# =========================================================
# ПРИЧИНА НЕИСПРАВНОСТИ
# =========================================================
@dp.message()
async def debug_handler(message: Message):
    manager = get_manager_by_user(message.from_user.id)
    if not manager:
        return

    print("UNKNOWN MESSAGE:", message.text)


