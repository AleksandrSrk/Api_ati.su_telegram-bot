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
# КЛАВИАТУРЫ
# =========================================================

def main_keyboard(manager_key: str):
    auto = is_auto_update_enabled(manager_key)
    auto_label = "🟢 Авто: ВКЛ" if auto else "🔴 Авто: ВЫКЛ"

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои грузы")],
            [KeyboardButton(text=auto_label)],
            [KeyboardButton(text="🔄 Обновить"), KeyboardButton(text="👤 Сменить")],
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
# ГРУЗЫ
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

    lines = ["📋 Грузы:\n"]

    for i, l in enumerate(loads, 1):
        load = parse_load(l)
        lines.append(f"{i}) {load['from_city']} → {load['to_city']}")

    await message.answer("\n".join(lines))


# =========================================================
# 🔥 НОВЫЙ ОТКЛИК
# =========================================================

async def notify_new_response(manager_key: str, load: dict, new_responses: list):

    chat_id = TELEGRAM_CHAT_IDS.get(manager_key)
    if not chat_id:
        return

    lines = [
        "🔔 Новый отклик",
        f"{load['from_city']} → {load['to_city']}\n"
    ]

    for i, r in enumerate(new_responses, 1):

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        stars = firm.get("TotalScore") or "—"

        name = contact.get("Name") or "—"
        phone = contact.get("Mobile") or contact.get("Telephone") or "—"

        if r.get("NdsPrice"):
            price = f"{int(r['NdsPrice'])} ₽ с НДС"
        elif r.get("NotNdsPrice"):
            price = f"{int(r['NotNdsPrice'])} ₽ без НДС"
        else:
            price = "—"

        comment = r.get("Note") or "—"

        lines.append(
            f"{i}) {company} ⭐{stars}\n"
            f"   👤 {name}\n"
            f"   📞 {phone}\n"
            f"   💰 {price}\n"
            f"   💬 {comment}\n"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📋 Показать все",
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

    lines = ["📋 Все отклики:\n"]

    for i, r in enumerate(responses, 1):

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        stars = firm.get("TotalScore") or "—"

        name = contact.get("Name") or "—"
        phone = contact.get("Mobile") or contact.get("Telephone") or "—"

        if r.get("NdsPrice"):
            price = f"{int(r['NdsPrice'])} ₽ с НДС"
        elif r.get("NotNdsPrice"):
            price = f"{int(r['NotNdsPrice'])} ₽ без НДС"
        else:
            price = "—"

        comment = r.get("Note") or "—"

        lines.append(
            f"{i}) {company} ⭐{stars}\n"
            f"   👤 {name}\n"
            f"   📞 {phone}\n"
            f"   💰 {price}\n"
            f"   💬 {comment}\n"
        )

    await callback.message.answer("\n".join(lines))