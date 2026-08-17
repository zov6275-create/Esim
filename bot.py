import asyncio
import os
import json
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
_admin_id = os.getenv("ADMIN_ID")
if not _admin_id:
    raise RuntimeError("ADMIN_ID environment variable is not set!")
ADMIN_ID = int(_admin_id)

# ─── БАЗА ДАННЫХ ─────────────────────────────────────────

DATA_FILE = "data.json"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

DEFAULT_DATA = {
    "operators": {
        "7Телеком":   {"bh": 13, "hold": 16},
        "Билайн":     {"bh": 18, "hold": 21},
        "ВТБ":        {"bh": 20, "hold": 25},
        "Газпром":    {"bh": 20, "hold": 25},
        "Добросвязь": {"bh": 12, "hold": 15},
        "МТС":        {"bh": 15, "hold": 19},
        "МТС WORLD":  {"bh": 28, "hold": 31},
        "Миранда":    {"bh": 18, "hold": 21},
        "Сбер":       {"bh": 16, "hold": 19},
        "Т2":         {"bh": 16, "hold": 19},
        "ТБанк":      {"bh": 18, "hold": 21},
    },
    "users": {}
}

def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "username": "",
            "full_name": "",
            "esims_month": 0,
            "esims_total": 0,
            "numbers": [],
            "bonus": 0
        }
    return data["users"][uid]


# ─── FSM СОСТОЯНИЯ ───────────────────────────────────────

class SubmitESIM(StatesGroup):
    choose_mode = State()
    choose_operator = State()
    waiting_photo = State()
    waiting_qr_number = State()

class AdminEditPrice(StatesGroup):
    choose_operator = State()
    choose_type = State()
    enter_price = State()

class AdminBonus(StatesGroup):
    enter_user_id = State()
    enter_amount = State()

class AdminNumbers(StatesGroup):
    enter_user_id = State()


# ─── КЛАВИАТУРА ГЛАВНОГО МЕНЮ ────────────────────────────

def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Сдать ESIM")],
            [KeyboardButton(text="👤 Профиль")]
        ],
        resize_keyboard=True
    )


# ─── СТАРТ ───────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # Сохраняем юзера
    data = load_data()
    user = get_user(data, message.from_user.id)
    user["username"] = message.from_user.username or ""
    user["full_name"] = message.from_user.full_name or ""
    save_data(data)

    operators = data["operators"]
    lines = []
    for name, prices in operators.items():
        lines.append(f"• {name} — БХ: {prices['bh']}$ / ХОЛД: {prices['hold']}$")

    text = (
        "👋 Добро пожаловать в сервис приёмки eSIM!\n\n"
        "📋 <b>Актуальные цены:</b>\n"
        + "\n".join(lines) +
        "\n\n"
        "⚡ <b>БХ</b> — без холда, оплата сразу\n"
        "⏳ <b>ХОЛД</b> — холд 30 минут, цена выше"
    )

    await message.answer(text, reply_markup=main_kb(), parse_mode="HTML")


# ─── ПРОФИЛЬ ─────────────────────────────────────────────

@dp.message(F.text == "👤 Профиль")
async def show_profile(message: Message, state: FSMContext):
    await state.clear()
    data = load_data()
    user = get_user(data, message.from_user.id)
    user["username"] = message.from_user.username or ""
    user["full_name"] = message.from_user.full_name or ""
    save_data(data)

    username = f"@{user['username']}" if user['username'] else user['full_name']
    bonus_line = f"💰 Бонус: +{user['bonus']}$\n" if user['bonus'] > 0 else ""

    text = (
        f"👤 <b>Профиль</b> {username}\n"
        f"🆔 <code>{message.from_user.id}</code>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"✅ Сдано за месяц: <b>{user['esims_month']}</b>\n"
        f"📦 Всего сдано: <b>{user['esims_total']}</b>\n"
        f"{bonus_line}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Мои номера", callback_data="my_numbers")]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "my_numbers")
async def show_my_numbers(callback: CallbackQuery):
    data = load_data()
    user = get_user(data, callback.from_user.id)
    numbers = user.get("numbers", [])

    if not numbers:
        await callback.answer("У вас пока нет сданных номеров.", show_alert=True)
        return

    lines = [f"{i+1}. {n}" for i, n in enumerate(numbers)]
    text = "📱 <b>Мои номера:</b>\n\n" + "\n".join(lines)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ─── СДАЧА ESIM ──────────────────────────────────────────

@dp.message(F.text == "📱 Сдать ESIM")
async def start_submit(message: Message, state: FSMContext):
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚡ БХ (без холда)", callback_data="mode:BH"),
            InlineKeyboardButton(text="⏳ ХОЛД (30 мин)", callback_data="mode:HOLD"),
        ]
    ])
    await message.answer("Выберите режим сдачи:", reply_markup=kb)
    await state.set_state(SubmitESIM.choose_mode)


@dp.callback_query(SubmitESIM.choose_mode, F.data.startswith("mode:"))
async def choose_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]
    await state.update_data(mode=mode)

    data = load_data()
    price_key = "bh" if mode == "BH" else "hold"
    mode_label = "⚡ БХ (без холда)" if mode == "BH" else "⏳ ХОЛД (30 минут)"

    buttons = []
    row = []
    for i, (name, prices) in enumerate(data["operators"].items()):
        price = prices[price_key]
        row.append(InlineKeyboardButton(
            text=f"{name} · {price}$",
            callback_data=f"op:{name}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        f"Режим: <b>{mode_label}</b>\n\nВыберите оператора:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(SubmitESIM.choose_operator)


@dp.callback_query(SubmitESIM.choose_operator, F.data.startswith("op:"))
async def choose_operator(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":", 1)[1]
    await state.update_data(operator=operator)

    await callback.message.edit_text(
        f"✅ Оператор: <b>{operator}</b>\n\n"
        f"📸 Отправьте скриншот или фото eSIM:",
        parse_mode="HTML"
    )
    await state.set_state(SubmitESIM.waiting_photo)


@dp.message(SubmitESIM.waiting_photo, F.photo)
async def got_photo(message: Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer(
        "✅ Фото получено.\n\n"
        "📲 Теперь отправьте <b>QR-код и номер телефона</b> одним сообщением.\n\n"
        "Пример:\n<code>QR: LPA:1$...</code>\n<code>Номер: +79991234567</code>",
        parse_mode="HTML"
    )
    await state.set_state(SubmitESIM.waiting_qr_number)


@dp.message(SubmitESIM.waiting_photo)
async def wrong_photo(message: Message):
    await message.answer("📸 Пожалуйста, отправьте именно фото или скриншот.")


@dp.message(SubmitESIM.waiting_qr_number, F.text)
async def got_qr_number(message: Message, state: FSMContext):
    state_data = await state.get_data()
    operator = state_data.get("operator")
    mode = state_data.get("mode")
    photo_id = state_data.get("photo_id")
    qr_number_text = message.text

    data = load_data()
    price_key = "bh" if mode == "BH" else "hold"
    price = data["operators"][operator][price_key]
    mode_label = "⚡ БХ (без холда)" if mode == "BH" else "⏳ ХОЛД (30 мин)"

    user = message.from_user

    caption = (
        f"📥 <b>Новая заявка на приёмку eSIM</b>\n\n"
        f"👤 Клиент: <a href='tg://user?id={user.id}'>{user.full_name}</a>\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📡 Оператор: <b>{operator}</b>\n"
        f"🔄 Режим: <b>{mode_label}</b>\n"
        f"💵 Сумма: <b>{price}$</b>\n\n"
        f"📲 <b>QR / Номер:</b>\n{qr_number_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Принять",
                callback_data=f"accept:{user.id}:{price}:{operator}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject:{user.id}"
            )
        ]
    ])

    await bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_id,
        caption=caption,
        reply_markup=kb,
        parse_mode="HTML"
    )

    await message.answer(
        "✅ Заявка отправлена на проверку.\n"
        "⏳ Ожидайте — мы уведомим вас о решении.",
        reply_markup=main_kb()
    )
    await state.clear()


# ─── АДМИН: ПРИНЯТЬ / ОТКЛОНИТЬ ──────────────────────────

@dp.callback_query(F.data.startswith("accept:"))
async def admin_accept(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    parts = callback.data.split(":")
    client_id = int(parts[1])
    price = parts[2]
    operator = parts[3]

    # Обновляем статистику клиента
    data = load_data()
    user = get_user(data, client_id)
    user["esims_month"] = user.get("esims_month", 0) + 1
    user["esims_total"] = user.get("esims_total", 0) + 1

    # Достаём номер из caption
    caption = callback.message.caption or ""
    qr_line = ""
    if "QR / Номер:" in caption:
        qr_part = caption.split("QR / Номер:")[1].strip()
        # Ищем номер телефона
        for line in qr_part.split("\n"):
            if "Номер:" in line or "+7" in line or "8" in line:
                number = line.replace("Номер:", "").strip()
                if number:
                    user["numbers"].append(number)
                    qr_line = number
                    break

    save_data(data)

    await bot.send_message(
        chat_id=client_id,
        text=(
            f"✅ <b>Ваша заявка принята!</b>\n\n"
            f"📡 Оператор: <b>{operator}</b>\n"
            f"💵 Сумма к выплате: <b>{price}$</b>\n\n"
            f"Ожидайте перевод."
        ),
        parse_mode="HTML"
    )

    await callback.message.edit_caption(
        caption=caption + "\n\n<b>✅ ПРИНЯТО</b>",
        reply_markup=None,
        parse_mode="HTML"
    )
    await callback.answer("✅ Принято. Клиент уведомлён.")


@dp.callback_query(F.data.startswith("reject:"))
async def admin_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет доступа.", show_alert=True)
        return

    client_id = int(callback.data.split(":")[1])

    await bot.send_message(
        chat_id=client_id,
        text=(
            "❌ <b>Ваша заявка отклонена.</b>\n\n"
            "Если есть вопросы — свяжитесь с поддержкой."
        ),
        parse_mode="HTML"
    )

    caption = callback.message.caption or ""
    await callback.message.edit_caption(
        caption=caption + "\n\n<b>❌ ОТКЛОНЕНО</b>",
        reply_markup=None,
        parse_mode="HTML"
    )
    await callback.answer("❌ Отклонено. Клиент уведомлён.")


# ─── АДМИН: ПАНЕЛЬ ───────────────────────────────────────

@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить цены", callback_data="admin:prices")],
        [InlineKeyboardButton(text="🎁 Добавить бонус клиенту", callback_data="admin:bonus")],
        [InlineKeyboardButton(text="📱 Номера клиента", callback_data="admin:numbers")],
    ])
    await message.answer("⚙️ <b>Панель администратора</b>", reply_markup=kb, parse_mode="HTML")


# ─── АДМИН: ЦЕНЫ ─────────────────────────────────────────

@dp.callback_query(F.data == "admin:prices")
async def admin_prices(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    data = load_data()
    buttons = []
    row = []
    for name in data["operators"].keys():
        row.append(InlineKeyboardButton(text=name, callback_data=f"edit:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "Выберите оператора для изменения цены:",
        reply_markup=kb
    )
    await state.set_state(AdminEditPrice.choose_operator)


@dp.callback_query(AdminEditPrice.choose_operator, F.data.startswith("edit:"))
async def admin_choose_operator(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":", 1)[1]
    await state.update_data(operator=operator)

    data = load_data()
    prices = data["operators"][operator]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"⚡ БХ ({prices['bh']}$)", callback_data="edittype:bh"),
            InlineKeyboardButton(text=f"⏳ ХОЛД ({prices['hold']}$)", callback_data="edittype:hold"),
        ]
    ])
    await callback.message.edit_text(
        f"Оператор: <b>{operator}</b>\n\nКакую цену меняем?",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(AdminEditPrice.choose_type)


@dp.callback_query(AdminEditPrice.choose_type, F.data.startswith("edittype:"))
async def admin_choose_type(callback: CallbackQuery, state: FSMContext):
    price_type = callback.data.split(":")[1]
    await state.update_data(price_type=price_type)
    type_label = "БХ" if price_type == "bh" else "ХОЛД"
    state_data = await state.get_data()

    await callback.message.edit_text(
        f"Оператор: <b>{state_data['operator']}</b> — <b>{type_label}</b>\n\n"
        f"Введите новую цену (только число):",
        parse_mode="HTML"
    )
    await state.set_state(AdminEditPrice.enter_price)


@dp.message(AdminEditPrice.enter_price)
async def admin_enter_price(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.strip().isdigit():
        await message.answer("⚠️ Только число, например: 18")
        return

    new_price = int(message.text.strip())
    state_data = await state.get_data()
    operator = state_data["operator"]
    price_type = state_data["price_type"]

    data = load_data()
    data["operators"][operator][price_type] = new_price
    save_data(data)

    type_label = "БХ" if price_type == "bh" else "ХОЛД"
    await message.answer(
        f"✅ {operator} — {type_label}: <b>{new_price}$</b>",
        parse_mode="HTML"
    )
    await state.clear()


# ─── АДМИН: БОНУС ────────────────────────────────────────

@dp.callback_query(F.data == "admin:bonus")
async def admin_bonus_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Введите Telegram ID клиента:")
    await state.set_state(AdminBonus.enter_user_id)


@dp.message(AdminBonus.enter_user_id)
async def admin_bonus_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.strip().lstrip("-").isdigit():
        await message.answer("⚠️ Введите числовой ID, например: 123456789")
        return

    await state.update_data(target_id=message.text.strip())
    await message.answer("Введите сумму бонуса в долларах (например: 5):")
    await state.set_state(AdminBonus.enter_amount)


@dp.message(AdminBonus.enter_amount)
async def admin_bonus_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.strip().lstrip("-").isdigit():
        await message.answer("⚠️ Только число, например: 5")
        return

    amount = int(message.text.strip())
    state_data = await state.get_data()
    target_id = int(state_data["target_id"])

    data = load_data()
    user = get_user(data, target_id)
    user["bonus"] = user.get("bonus", 0) + amount
    save_data(data)

    # Уведомляем клиента
    try:
        await bot.send_message(
            chat_id=target_id,
            text=f"🎁 Вам начислен бонус: <b>+{amount}$</b>",
            parse_mode="HTML"
        )
        notify = "Клиент уведомлён."
    except Exception:
        notify = "⚠️ Не удалось уведомить клиента."

    await message.answer(
        f"✅ Бонус +{amount}$ добавлен клиенту <code>{target_id}</code>.\n{notify}",
        parse_mode="HTML"
    )
    await state.clear()


# ─── АДМИН: НОМЕРА КЛИЕНТА ───────────────────────────────

@dp.callback_query(F.data == "admin:numbers")
async def admin_numbers_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Введите Telegram ID клиента:")
    await state.set_state(AdminNumbers.enter_user_id)


@dp.message(AdminNumbers.enter_user_id)
async def admin_numbers_show(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.text.strip().lstrip("-").isdigit():
        await message.answer("⚠️ Введите числовой ID")
        return

    target_id = int(message.text.strip())
    data = load_data()
    user = get_user(data, target_id)
    numbers = user.get("numbers", [])

    if not numbers:
        await message.answer(f"У клиента {target_id} нет сданных номеров.")
    else:
        lines = [f"{i+1}. {n}" for i, n in enumerate(numbers)]
        await message.answer(
            f"📱 <b>Номера клиента {target_id}:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML"
        )
    await state.clear()


# ─── ЗАПУСК ───────────────────────────────────────────────

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
