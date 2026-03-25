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
    get_active_manager, set_active_manager,
)
from ati_client import get_my_loads, get_load_responses, renew_load, parse_load


bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =========================================================
# КЛАВИАТУРА
# =========================================================

def main_keyboard(manager_key: str):
    auto = is_auto_update_enabled(manager_key)

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои грузы"), KeyboardButton(text="⏱ До обновления")],
            [KeyboardButton(text="Автообновление: ВКЛ" if auto else "Автообновление: ВЫКЛ")],
            [KeyboardButton(text="🔄 Обновить грузы вручную"), KeyboardButton(text="👤 Сменить менеджера")],
        ],
        resize_keyboard=True
    )


def managers_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=v["name"], callback_data=f"m_{k}")]
            for k, v in MANAGERS.items()
        ]
    )


# =========================================================
# СТАРТ
# =========================================================

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Выбери менеджера", reply_markup=managers_keyboard())


@dp.callback_query(F.data.startswith("m_"))
async def select_manager(callback: CallbackQuery):
    key = callback.data.replace("m_", "")
    set_active_manager(callback.message.chat.id, key)

    await callback.message.answer(
        f"Менеджер: {MANAGERS[key]['name']}",
        reply_markup=main_keyboard(key)
    )


# =========================================================
# МОИ ГРУЗЫ (ПОДРОБНО)
# =========================================================

@dp.message(F.text == "📋 Мои грузы")
async def loads_handler(message: Message):

    manager = get_active_manager(message.chat.id)
    if not manager:
        return

    loads = await get_my_loads(manager)

    if not loads:
        await message.answer("Нет грузов")
        return

    lines = [f"📋 Активные грузы {MANAGERS[manager]['name']}:\n"]

    for i, l in enumerate(loads, 1):
        load = parse_load(l)

        renew_icon = "🟡" if load["can_renew"] else "⏳"
        weight = f"{load['weight']}т" if load["weight"] != "—" else "—"

        lines.append(f"{i}) {renew_icon} {load['from_city']} → {load['to_city']}, {weight}")

        if not load["can_renew"]:
            lines.append(f"   {load['renew_restriction']}")

        resp_count = load.get("response_count", 0)
        lines.append(f"   💬 Откликов: {resp_count}\n")

    await message.answer("\n".join(lines))


# =========================================================
# АВТООБНОВЛЕНИЕ
# =========================================================

@dp.message(F.text.startswith("Автообновление"))
async def toggle_auto(message: Message):

    manager = get_active_manager(message.chat.id)
    if not manager:
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

    manager = get_active_manager(message.chat.id)
    if not manager:
        return

    last = get_last_update_time(manager)

    if not last:
        await message.answer("Ещё не было обновлений")
        return

    next_time = last + timedelta(hours=1)
    remaining = next_time - datetime.now()

    mins = int(remaining.total_seconds() // 60)

    await message.answer(f"До обновления: {mins} мин")


# =========================================================
# РУЧНОЕ ОБНОВЛЕНИЕ
# =========================================================

@dp.message(F.text == "🔄 Обновить грузы вручную")
async def manual_update(message: Message):

    manager = get_active_manager(message.chat.id)
    if not manager:
        return

    loads = await get_my_loads(manager)

    if not loads:
        await message.answer("Нет грузов")
        return

    keyboard = []
    text = ["Выбери груз:\n"]

    for l in loads:
        load = parse_load(l)

        text.append(f"{load['from_city']} → {load['to_city']}")

        keyboard.append([
            InlineKeyboardButton(
                text=f"Обновить {load['from_city']}",
                callback_data=f"renew_{load['id']}"
            )
        ])

    await message.answer(
        "\n".join(text),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@dp.callback_query(F.data.startswith("renew_"))
async def renew_one(callback: CallbackQuery):

    load_id = callback.data.replace("renew_", "")
    manager = get_active_manager(callback.message.chat.id)

    result = await renew_load(manager, load_id)

    if result["success"]:
        await callback.message.answer("Обновлено")
    else:
        await callback.message.answer("Ошибка обновления")


# =========================================================
# СМЕНА МЕНЕДЖЕРА
# =========================================================

@dp.message(F.text == "👤 Сменить менеджера")
async def change_manager(message: Message):
    await message.answer("Выбери менеджера", reply_markup=managers_keyboard())


# =========================================================
# 🔥 НОВЫЕ ОТКЛИКИ
# =========================================================

async def notify_new_response(manager_key: str, load: dict, new_responses: list):

    chat_id = TELEGRAM_CHAT_IDS.get(manager_key)
    if not chat_id:
        return

    lines = [
        "🔔 Новый отклик",
        f"{load['from_city']} → {load['to_city']}\n"
    ]

    for r in new_responses:

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        name = contact.get("Name") or "—"
        phone = contact.get("Mobile") or contact.get("Telephone") or "—"

        if r.get("NdsPrice"):
            price = f"{int(r['NdsPrice'])} ₽ с НДС"
        elif r.get("NotNdsPrice"):
            price = f"{int(r['NotNdsPrice'])} ₽ без НДС"
        else:
            price = "—"

        lines.append(f"{company}\n{name}\n{phone}\n{price}\n")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📋 Показать все отклики",
                callback_data=f"all_{load['id']}"
            )]
        ]
    )

    await bot.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)


# =========================================================
# ВСЕ ОТКЛИКИ
# =========================================================

@dp.callback_query(F.data.startswith("all_"))
async def all_responses(callback: CallbackQuery):

    load_id = callback.data.replace("all_", "")
    manager = get_active_manager(callback.message.chat.id)

    responses = await get_load_responses(manager, load_id)

    if not responses:
        await callback.message.answer("Нет откликов")
        return

    lines = ["Все отклики:\n"]

    for r in responses:

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        name = contact.get("Name") or "—"

        if r.get("NdsPrice"):
            price = f"{int(r['NdsPrice'])} ₽ с НДС"
        elif r.get("NotNdsPrice"):
            price = f"{int(r['NotNdsPrice'])} ₽ без НДС"
        else:
            price = "—"

        lines.append(f"{company} | {name} | {price}")

    await callback.message.answer("\n".join(lines))