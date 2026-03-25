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
from ati_client import delete_load

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# =========================================================
# КЛАВИАТУРА
# =========================================================

def main_keyboard(manager_key: str):
    auto = is_auto_update_enabled(manager_key)

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои грузы")],
            [KeyboardButton(text="Автообновление: ВКЛ" if auto else "Автообновление: ВЫКЛ")],
            # [KeyboardButton(text="🔄 Обновить грузы вручную"), 
            [KeyboardButton(text="👤 Сменить менеджера")],
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
    await callback.answer("Загружаю...")
    key = callback.data.replace("m_", "")
    set_active_manager(callback.message.chat.id, key)

    await callback.message.answer(
        f"Менеджер: {MANAGERS[key]['name']}",
        reply_markup=main_keyboard(key)
    )

# =========================================================
# архив
# =========================================================
@dp.callback_query(F.data.startswith("archive_"))
async def archive_load_handler(callback: CallbackQuery):
    await callback.answer("Убираем в архив...")
    
    load_id = callback.data.replace("archive_", "")
    manager = get_active_manager(callback.message.chat.id)

    result = await delete_load(manager, load_id)

    if result["success"]:
        await callback.message.answer("🗄 Груз убран (архив)")
    else:
        await callback.message.answer(f"❌ Ошибка: {result.get('reason')}")
        
# =========================================================
# МОИ ГРУЗЫ (ПОДРОБНО)
# =========================================================

@dp.message(F.text == "📋 Мои грузы")
async def loads_handler(message: Message):

    manager = get_active_manager(message.chat.id)
    if not manager:
        await message.answer("Сначала выбери менеджера")
        return

    loads = await get_my_loads(manager)

    if not loads:
        await message.answer("Нет грузов")
        return

    for l in loads:
        load = parse_load(l)

        weight = f"{load['weight']}т" if load["weight"] != "—" else "—"

        # 🔥 получаем отклики и фильтруем только актуальные
        responses = await get_load_responses(manager, load["id"])

        actual_count = 0
        if responses:
            actual_count = len([
                r for r in responses
                if not r.get("IsOutdated")
            ])

        text = (
            f"{load['from_city']} → {load['to_city']}\n"
            f"Вес: {weight}\n"
            f"💬 Откликов: {actual_count}\n"
        )

        # ⏳ если нельзя обновить — показываем причину
        if not load["can_renew"]:
            text += f"\n⏳ {load['renew_restriction']}"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Обновить",
                        callback_data=f"renew_{load['id']}"
                    ),
                    InlineKeyboardButton(
                        text="💬 Отклики",
                        callback_data=f"responses_{load['id']}"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🗄 В архив",
                        callback_data=f"archive_{load['id']}"
                    )
                ]
            ]
        )

        await message.answer(text, reply_markup=keyboard)


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
    await callback.answer("Обновляем...")

    load_id = callback.data.replace("renew_", "")
    manager = get_active_manager(callback.message.chat.id)

    loads = await get_my_loads(manager)

    load = None
    for l in loads:
        parsed = parse_load(l)
        if parsed["id"] == load_id:
            load = parsed
            break

    if not load:
        await callback.message.answer("Груз не найден")
        return

    # 🔥 ключевая проверка
    if not load["can_renew"]:
        await callback.message.answer(
            f"❌ Нельзя обновить\n{load['renew_restriction']}"
        )
        return

    result = await renew_load(manager, load_id)

    if result["success"]:
        await callback.message.answer("✅ Груз обновлен")
    else:
        await callback.message.answer(f"❌ Ошибка: {result.get('reason')}")


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
        f"{load['from_city']} → {load['to_city']}"
    ]

    for i, r in enumerate(new_responses, start=1):

        if r.get("IsOutdated"):
            continue

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        rating = firm.get("TotalScore")

        name = contact.get("Name") or "—"
        phone = contact.get("Mobile") or contact.get("Telephone") or "—"

        phone_link = phone.replace(" ", "").replace("(", "").replace(")", "").replace("-", "")

        # 💰 СТАВКА (ВАЖНО)
        price_value = r.get("Price")
        if price_value:
            is_nds = bool(r.get("PayAttributes", 0) & 2)
            nds_text = "с НДС" if is_nds else "без НДС"
            price = f"{int(price_value):,} ₽ ({nds_text})"
        else:
            price = "—"

        note = r.get("Note") or "—"
        rating_text = f"⭐ {rating}" if rating else ""

        lines.append(
            f"<b>{i}.</b> {company} {rating_text}\n"
            f"   👤 {name}\n"
            f"   📞 <a href='tel:{phone_link}'>{phone}</a>\n"
            f"   💰 {price}\n"
            f"   💬 {note}"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📋 Показать все отклики",
                callback_data=f"all_{load['id']}"
            )]
        ]
    )

    await bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# =========================================================
# 
# =========================================================
@dp.callback_query(F.data.startswith("responses_"))
async def show_responses(callback: CallbackQuery):
    await callback.answer("Загружаю...")

    load_id = callback.data.replace("responses_", "")
    manager = get_active_manager(callback.message.chat.id)

    responses = await get_load_responses(manager, load_id)

    if not responses:
        await callback.message.answer("Откликов нет")
        return

    lines = ["📋 Отклики:"]

    for i, r in enumerate(responses, start=1):

        if r.get("IsOutdated"):
            continue

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        rating = firm.get("TotalScore")

        name = contact.get("Name") or "—"
        phone = contact.get("Mobile") or contact.get("Telephone") or "—"

        phone_link = phone.replace(" ", "").replace("(", "").replace(")", "").replace("-", "")

        # 💰 СТАВКА
        price_value = r.get("Price")
        if price_value:
            is_nds = bool(r.get("PayAttributes", 0) & 2)
            nds_text = "с НДС" if is_nds else "без НДС"
            price = f"{int(price_value):,} ₽ ({nds_text})"
        else:
            price = "—"

        note = r.get("Note") or "—"
        rating_text = f"⭐ {rating}" if rating else ""

        lines.append(
            f"<b>{i}.</b> {company} {rating_text}\n"
            f"   👤 {name}\n"
            f"   📞 <a href='tel:{phone_link}'>{phone}</a>\n"
            f"   💰 {price}\n"
            f"   💬 {note}"
        )

    if len(lines) == 1:
        await callback.message.answer("Нет актуальных откликов")
        return

    await callback.message.answer(
        "\n".join(lines),
        parse_mode="HTML"
    )

# =========================================================
# ВСЕ ОТКЛИКИ
# =========================================================

@dp.callback_query(F.data.startswith("all_"))
async def all_responses(callback: CallbackQuery):
    await callback.answer("Загружаю...")

    load_id = callback.data.replace("all_", "")
    manager = get_active_manager(callback.message.chat.id)

    responses = await get_load_responses(manager, load_id)

    if not responses:
        await callback.message.answer("Нет откликов")
        return

    lines = ["📋 Все отклики:\n"]

    for i, r in enumerate(responses, start=1):

        if r.get("IsOutdated"):
            continue

        firm = r.get("FirmInfo", {})
        contact = firm.get("Contact", {})

        company = firm.get("FullFirmName") or r.get("FirmName") or "—"
        rating = firm.get("TotalScore")

        name = contact.get("Name") or "—"
        phone = contact.get("Mobile") or contact.get("Telephone") or "—"

        phone_link = phone.replace(" ", "").replace("(", "").replace(")", "").replace("-", "")

        # 💰 СТАВКА
        price_value = r.get("Price")
        if price_value:
            is_nds = bool(r.get("PayAttributes", 0) & 2)
            nds_text = "с НДС" if is_nds else "без НДС"
            price = f"{int(price_value):,} ₽ ({nds_text})"
        else:
            price = "—"

        note = r.get("Note") or "—"
        rating_text = f"⭐ {rating}" if rating else ""

        lines.append(
            f"<b>{i}.</b> {company} {rating_text}\n"
            f"   👤 {name}\n"
            f"   📞 <a href='tel:{phone_link}'>{phone}</a>\n"
            f"   💰 {price}\n"
            f"   💬 {note}"
        )

    if len(lines) == 1:
        await callback.message.answer("Нет актуальных откликов")
        return

    await callback.message.answer(
        "\n".join(lines),
        parse_mode="HTML"
    )