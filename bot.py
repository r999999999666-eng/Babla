
import asyncio
import logging
import sqlite3
import time
import io
import qrcode
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
)

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE" # Токен от @BotFather
ADMIN_ID = 8992968778 # Ваш Telegram ID
CHANNEL_USERNAME = "@DiamondPAY_News" # Канал для обязательной подписки
CHANNEL_URL = "https://t.me/DiamondPAY_News"

# ================= БАЗА ДАННЫХ =================
conn = sqlite3.connect("diamondpay.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    referrer_id INTEGER,
    ref_balance REAL DEFAULT 0.0,
    ref_count INTEGER DEFAULT 0,
    total_ref_deposits REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    account_id TEXT,
    amount REAL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# ================= ИНИЦИАЛИЗАЦИЯ AIOGRAM =================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= FSM СОСТОЯНИЯ =================
class DepositState(StatesGroup):
    waiting_for_account = State()
    waiting_for_amount = State()
    waiting_for_receipt = State()

class WithdrawState(StatesGroup):
    waiting_for_qr = State()
    waiting_for_amount = State()

# ================= КЛАВИАТУРЫ =================
def get_subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↗️ Подписаться", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить", callback_data="check_subscription")]
    ])

def get_main_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📥 Пополнить"), KeyboardButton(text="📤 Вывести")],
        [KeyboardButton(text="🤝 Пригласить друга")]
    ], resize_keyboard=True)

def get_amounts_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="200", callback_data="amt_200"), InlineKeyboardButton(text="500", callback_data="amt_500")],
        [InlineKeyboardButton(text="1000", callback_data="amt_1000"), InlineKeyboardButton(text="2000", callback_data="amt_2000")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_deposit")]
    ])

def get_banks_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 MBank", url="https://mbank.kg"), InlineKeyboardButton(text="📱 O! Bank", url="https://o.kg")],
        [InlineKeyboardButton(text="💳 Optima Bank", url="https://optimabank.kg"), InlineKeyboardButton(text="🤝 Компаньон", url="https://kompanion.kg")],
        [InlineKeyboardButton(text="🏛 BakAi", url="https://bakai.kg"), InlineKeyboardButton(text="📲 MegaPay", url="https://megapay.kg")],
        [InlineKeyboardButton(text="🏦 DemirBank", url="https://demirbank.kg")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def get_ref_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Пополнить 1xBet с реф. баланса")],
        [KeyboardButton(text="Вывести реф. баланс")],
        [KeyboardButton(text="Главное меню")]
    ], resize_keyboard=True)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        logging.error(f"Error checking sub: {e}")
        return True # В случае ошибки пропускаем

def generate_qr_bytes(data_str: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio.getvalue()

# ================= ХЕНДЛЕРЫ =================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    # Реферальная система из аргументов /start ref_12345
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id == user_id:
                referrer_id = None
        except ValueError:
            pass

    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)",
                       (user_id, username, referrer_id))
        conn.commit()

    if not await is_subscribed(user_id):
        text = (
            "👋 Добро пожаловать в DiamondPAY!\n\n"
            f"Чтобы продолжить, пожалуйста, подпишитесь на наш официальный канал {CHANNEL_USERNAME}. "
            "Там мы публикуем важные новости и обновления сервиса.\n\n"
            "После подписки нажмите «Проверить»."
        )
        await message.answer(text, reply_markup=get_subscribe_kb())
        return

    await show_main_menu(message)

@dp.callback_query(F.data == "check_subscription")
async def cb_check_sub(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("✅ Подписка подтверждена!")
        await show_main_menu(callback.message)
    else:
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)

async def show_main_menu(message: types.Message):
    today = datetime.now().strftime("%d.%m.%Y %H:%M")
    name = message.from_user.first_name or "Пользователь"
    text = (
        f"Добрый вечер, {name}! 👋\n\n"
        "🚀 Пополнение и выводы работают стабильно\n"
        f"🗓 Актуально на: {today}\n\n"
        "💸 Комиссия: 0%\n"
        "🛡 Все ваши транзакции защищены\n"
        "⚡️ Работаем 24/7\n\n"
        "Выберите нужное действие ниже."
    )
    await message.answer(text, reply_markup=get_main_menu_kb())

# --- ПОПОЛНЕНИЕ ---
@dp.message(F.text == "📥 Пополнить")
async def start_deposit(message: types.Message, state: FSMContext):
    await state.set_state(DepositState.waiting_for_account)
    text = (
        "ПОПОЛНЕНИЕ СЧЁТА\n"
        "[ Типы систем ] [ Методы по GEO-локации ]\n\n"
        "💳 Введите номер счёта, на который вы вносите средства.\n\n"
        "Это ваш DEPOSIT ID. Он состоит только из цифр."
    )
    await message.answer(text)

@dp.message(DepositState.waiting_for_account)
async def process_account_id(message: types.Message, state: FSMContext):
    account_id = message.text.strip()
    if not account_id.isdigit():
        await message.answer("⚠️ DEPOSIT ID должен состоять только из цифр. Попробуйте снова:")
        return

    await state.update_data(account_id=account_id)
    await state.set_state(DepositState.waiting_for_amount)
    text = (
        "Отлично ✅\nАккаунт найден\n\n"
        "Выберите сумму кнопкой или введите нужную сумму пополнения цифрами."
    )
    await message.answer(text, reply_markup=get_amounts_kb())

@dp.callback_query(F.data.startswith("amt_"))
async def cb_select_amount(callback: types.CallbackQuery, state: FSMContext):
    amount = float(callback.data.replace("amt_", ""))
    await process_deposit_invoice(callback.message, state, amount, callback.from_user.id)

async def process_deposit_invoice(message: types.Message, state: FSMContext, amount: float, user_id: int):
    data = await state.get_data()
    account_id = data.get("account_id")
    
    qr_data = f"https://diamondpay.kg/pay?id={account_id}&amount={amount}"
    qr_bytes = generate_qr_bytes(qr_data)
    photo_file = BufferedInputFile(qr_bytes, filename="qr.png")

    caption = (
        f"⏳ К оплате: {amount:.2f} KGS\n\n"
        "⚠️ Реквизиты актуальны в течение 5 минут.\n"
        "Отсканируйте QR или загрузите его из галереи в приложение банка.\n"
        "Также можно выбрать банк ниже и оплатить по ссылке.\n\n"
        "🧾 После оплаты отправьте, пожалуйста, скриншот чека.\n\n"
        "⏳ До окончания оплаты: 05:00"
    )
    
    sent_msg = await message.answer_photo(photo=photo_file, caption=caption, reply_markup=get_banks_kb())
    await state.set_state(DepositState.waiting_for_receipt)
    await state.update_data(deposit_amount=amount, deposit_msg_id=sent_msg.message_id)

@dp.message(DepositState.waiting_for_receipt, F.photo)
async def process_receipt(message: types.Message, state: FSMContext):
    await message.answer("✅ Чек получен и отправлен оператору! Пополнение произойдёт в течение 2-5 минут.")
    await state.clear()
    await show_main_menu(message)

# --- РЕФЕРАЛЬНАЯ СИСТЕМА ---
@dp.message(F.text == "🤝 Пригласить друга")
async def show_referral(message: types.Message):
    user_id = message.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    cursor.execute("SELECT ref_balance, ref_count, total_ref_deposits FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone() or (0.0, 0, 0.0)
    ref_bal, ref_cnt, total_dep = row

    text = (
        "🤝 Пригласи друга\n\n"
        f"Ваша персональная ссылка:\n{ref_link}\n\n"
        "За каждое принятое пополнение приглашенного друга начисляется 3%.\n\n"
        f"👥 Приглашено друзей: {ref_cnt}\n"
        f"🛍 Пополнений друзей: 0\n"
        f"💵 Сумма пополнений друзей: {total_dep:.2f} KGS\n"
        f"💰 Доступный баланс: {ref_bal:.2f} KGS\n\n"
        "Минимальная сумма пополнения или вывода: 500 KGS."
    )
    await message.answer(text, reply_markup=get_ref_kb())

@dp.message(F.text == "Вывести реф. баланс")
async def withdraw_ref_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    cursor.execute("SELECT ref_balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    bal = row[0] if row else 0.0

    if bal < 500:
        await message.answer(f"⚠️ Недостаточно средств на реферальном балансе.\nДоступно: {bal:.2f} KGS\nМинимальная сумма: 500 KGS.")
        return

    await state.set_state(WithdrawState.waiting_for_qr)
    await message.answer("📤 Вывод реферального баланса\n\nОтправьте QR-код вашего банка скриншотом.")

@dp.message(WithdrawState.waiting_for_qr, F.photo)
async def process_withdraw_qr(message: types.Message, state: FSMContext):
    await state.set_state(WithdrawState.waiting_for_amount)
    user_id = message.from_user.id
    cursor.execute("SELECT ref_balance FROM users WHERE user_id = ?", (user_id,))
    bal = cursor.fetchone()[0]

    await message.answer(
        "Введите сумму с реферального баланса только цифрами.\n\n"
        f"Доступно: {bal:.2f} KGS\n"
        "Минимальная сумма: 500 KGS."
    )

@dp.message(WithdrawState.waiting_for_amount)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        amt = float(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Введите корректное число!")
        return

    cursor.execute("SELECT ref_balance FROM users WHERE user_id = ?", (user_id,))
    bal = cursor.fetchone()[0]

    if amt < 500 or amt > bal:
        await message.answer("⚠️ Недопустимая сумма вывода!")
        return

    new_bal = bal - amt
    cursor.execute("UPDATE users SET ref_balance = ? WHERE user_id = ?", (new_bal, user_id))
    conn.commit()

    await state.clear()
    await message.answer(
        f"✅ Заявка на вывод создана.\n"
        f"💳 Списано с реферального баланса: {amt:.2f} KGS\n"
        f"💰 Остаток: {new_bal:.2f} KGS\n\n"
        "После проверки оператор подтвердит заявку.\n"
        "⌛ 5 минут истекли. Если вывод еще не поступил, напишите в поддержку."
    )

@dp.message(F.text == "Главное меню")
async def back_to_main(message: types.Message):
    await show_main_menu(message)

# ================= ЗАПУСК =================
async def main():
    print("Бот @DiamondPAY_KG_bot успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
