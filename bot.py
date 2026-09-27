import asyncio
import logging
import os
import sqlite3
import time
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = os.environ.get("TOKEN") or os.environ.get("BOT_TOKEN") or ""
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8992968778"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@DiamondPAY_News").strip()
CHANNEL_URL = os.environ.get("CHANNEL_LINK", "https://t.me/DiamondPAY_News").strip()
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111258120233520910129965023532261202111302123408%D0%9D%D0%A3%D0%A0%D0%AD%D0%9B%20%D0%9A.520473995303417540105906O%21Bank63044CEE",
)
BOT_NAME = "DiamondPAY"
MIN_DEPOSIT = 100
MAX_DEPOSIT = 500_000
REF_PERCENT = 2.5
MIN_REF_OUT = 100
TZ = ZoneInfo("Asia/Bishkek")


def now_kg() -> datetime:
    return datetime.now(TZ)


# ================= PREMIUM ЭМОДЗИ =================
def pe(eid: str, fb: str) -> str:
    """Telegram Premium custom emoji (HTML)."""
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


E = {
    "star": pe("5379607913046242841", "❄️"),
    "vip": pe("5400373628950840597", "❄️"),
    "gem": pe("5399942684817258282", "❄️"),
    "sparkles": pe("5379943126653761268", "❄️"),
    "check": pe("6273749318717412886", "✅"),
    "cross": "❌",
    "clock": pe("5226830214020999125", "⚡️"),
    "fire": pe("5201945242227472933", "⚡️"),
    "rocket": pe("5188481279963715781", "🚀"),
    "money": pe("5224257782013769471", "💰"),
    "dollar": pe("5197434882321567830", "💵"),
    "wallet": pe("5215420556089776398", "👛"),
    "stats": pe("5224588661999282075", "💲"),
    "withdraw": pe("5201691993775818138", "🛫"),
    "target": pe("5201732344993576400", "🌐"),
    "support": pe("5472239203590888751", "📩"),
    "admin": pe("5193177581888755275", "💻"),
    "key": pe("5197269100878907942", "✍️"),
    "wave": "👋",
    "gift": pe("5379943126653761268", "🎁"),
    "lock": "🔒",
}


# ================= БАЗА =================
conn = sqlite3.connect("diamondpay.db", check_same_thread=False)
cursor = conn.cursor()
cursor.executescript(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    referrer_id INTEGER,
    ref_balance REAL DEFAULT 0.0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    platform TEXT,
    account_id TEXT,
    amount REAL,
    photo_id TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    ts INTEGER
);
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    platform TEXT,
    account_id TEXT,
    qr_file_id TEXT,
    code TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS ref_outs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    platform TEXT,
    target TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    message TEXT,
    photo_id TEXT,
    status TEXT DEFAULT 'new',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""
)
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_active', '1')")
conn.commit()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ================= FSM =================
class DepositState(StatesGroup):
    platform = State()
    account = State()
    amount = State()
    receipt = State()


class WithdrawState(StatesGroup):
    platform = State()
    qr = State()
    account = State()
    code = State()


class RefOutState(StatesGroup):
    platform = State()
    target = State()
    qr = State()


class SupportState(StatesGroup):
    message = State()


class AdminReplyState(StatesGroup):
    text = State()


class BroadcastState(StatesGroup):
    content = State()


# ================= HELPERS =================
def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def bot_active() -> bool:
    cursor.execute("SELECT value FROM settings WHERE key='bot_active'")
    row = cursor.fetchone()
    return (row[0] if row else "1") == "1"


def set_bot_active(on: bool):
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('bot_active', ?)",
        ("1" if on else "0"),
    )
    conn.commit()


def ensure_user(user_id: int, username: str = "", full_name: str = "", referrer_id: int | None = None):
    cursor.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if cursor.fetchone():
        cursor.execute(
            "UPDATE users SET username=COALESCE(?,username), full_name=COALESCE(?,full_name) WHERE user_id=?",
            (username or None, full_name or None, user_id),
        )
        conn.commit()
        return False
    ref = None
    if referrer_id and referrer_id != user_id:
        cursor.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,))
        if cursor.fetchone():
            ref = referrer_id
    cursor.execute(
        "INSERT INTO users (user_id, username, full_name, referrer_id, created_at) VALUES (?,?,?,?,?)",
        (user_id, username, full_name, ref, now_kg().strftime("%d.%m.%Y %H:%M")),
    )
    conn.commit()
    return True


def user_label(uid: int) -> str:
    cursor.execute("SELECT username, full_name FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()
    parts = [f"<code>{uid}</code>"]
    if row:
        if row[0]:
            parts.append(f"@{row[0]}")
        if row[1]:
            parts.append(row[1])
    return " · ".join(parts)


def get_ref_balance(uid: int) -> float:
    cursor.execute("SELECT COALESCE(ref_balance,0) FROM users WHERE user_id=?", (uid,))
    row = cursor.fetchone()
    return float(row[0]) if row else 0.0


def greeting(name: str) -> str:
    h = now_kg().hour
    if 5 <= h < 12:
        g = "Доброе утро"
    elif 12 <= h < 17:
        g = "Добрый день"
    elif 17 <= h < 23:
        g = "Добрый вечер"
    else:
        g = "Доброй ночи"
    return f"{g}, {name}! {E['wave']}"


async def is_subscribed(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    if not CHANNEL_USERNAME:
        return True
    try:
        m = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return m.status in ("creator", "administrator", "member", "restricted")
    except Exception as e:
        logger.warning(f"sub: {e}")
        return True


# ================= KEYBOARDS =================
def kb_subscribe():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
        ]
    )


def kb_main():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 Пополнить"), KeyboardButton(text="📤 Вывести")],
            [KeyboardButton(text="👤 Поддержка"), KeyboardButton(text="📖 Инструкция")],
            [KeyboardButton(text="🤝 Пригласить друга")],
        ],
        resize_keyboard=True,
    )


def kb_admin():
    active = bot_active()
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Заявки"), KeyboardButton(text="📩 Обращения")],
            [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="🟢 ВКЛ" if not active else "🔴 ВЫКЛ")],
            [KeyboardButton(text="🔙 Главное меню")],
        ],
        resize_keyboard=True,
    )


def kb_platform(prefix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣ 1xBet", callback_data=f"{prefix}_1x"),
                InlineKeyboardButton(text="2️⃣ Melbet", callback_data=f"{prefix}_mel"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def kb_amounts():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="200", callback_data="amt_200"),
                InlineKeyboardButton(text="500", callback_data="amt_500"),
            ],
            [
                InlineKeyboardButton(text="1000", callback_data="amt_1000"),
                InlineKeyboardButton(text="2000", callback_data="amt_2000"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def kb_banks():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="MBank", url=PAY_LINK),
                InlineKeyboardButton(text="O! Bank", url=PAY_LINK),
            ],
            [
                InlineKeyboardButton(text="BakAI", url=PAY_LINK),
                InlineKeyboardButton(text="MegaPay", url=PAY_LINK),
            ],
            [InlineKeyboardButton(text="DemirBank", url=PAY_LINK)],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")],
        ]
    )


def kb_ref(bal: float):
    rows = []
    if bal >= MIN_REF_OUT:
        rows += [
            [InlineKeyboardButton(text="Пополнить 1xBet с рефки", callback_data="ref_1x")],
            [InlineKeyboardButton(text="Пополнить Melbet с рефки", callback_data="ref_mel")],
            [InlineKeyboardButton(text="Вывести на QR", callback_data="ref_qr")],
            [InlineKeyboardButton(text="Вывести на 1xBet/Melbet", callback_data="ref_out")],
        ]
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_dep(dep_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"dep_ok_{dep_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dep_no_{dep_id}"),
            ]
        ]
    )


def kb_wd(w_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Готово", callback_data=f"wd_ok_{w_id}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"wd_no_{w_id}"),
            ]
        ]
    )


def kb_ticket(tid: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 В работу", callback_data=f"tkt_work_{tid}"),
                InlineKeyboardButton(text="💬 Ответить", callback_data=f"tkt_reply_{tid}"),
            ],
            [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"tkt_close_{tid}")],
        ]
    )


# ================= START + ПОДПИСКА =================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    uname = message.from_user.username or ""
    fname = message.from_user.full_name or message.from_user.first_name or ""

    referrer_id = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1].replace("ref_", "", 1))
        except ValueError:
            pass

    ensure_user(uid, uname, fname, referrer_id)

    if not bot_active() and not is_admin(uid):
        await message.answer(f"{E['cross']} Бот временно отключён.", parse_mode="HTML")
        return

    if not await is_subscribed(uid):
        await message.answer(
            f"{E['wave']} Добро пожаловать в <b>{BOT_NAME}</b>!\n\n"
            f"{E['target']} Подпишитесь на канал {CHANNEL_USERNAME}\n"
            f"После подписки нажмите «Я подписался».",
            reply_markup=kb_subscribe(),
            parse_mode="HTML",
        )
        return

    await show_main(message)


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(f"{E['check']} Подписка подтверждена!", parse_mode="HTML")
        await show_main(callback.message)
    else:
        await callback.answer("Вы ещё не подписаны на канал!", show_alert=True)


@dp.callback_query(F.data.in_({"main_menu", "cancel"}))
async def cb_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await show_main(callback.message)


async def show_main(message: types.Message):
    name = getattr(message.from_user, "first_name", None) or "друг"
    text = (
        f"{greeting(name)}\n\n"
        f"{E['rocket']} Пополнение и выводы работают стабильно\n"
        f"{E['check']} Актуально на: {now_kg().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"{E['money']} Комиссия: <b>0%</b>\n"
        f"{E['lock']} Все ваши транзакции защищены\n"
        f"{E['clock']} Работаем <b>24/7</b>\n\n"
        f"{E['target']} Букмекеры: <b>1xBet</b> · <b>Melbet</b>\n"
        f"{E['dollar']} Мин. пополнение: <b>{MIN_DEPOSIT}</b> KGS\n"
        f"{E['gift']} Реферал: <b>{REF_PERCENT}%</b>\n\n"
        f"Выберите действие ниже 👇"
    )
    await message.answer(text, reply_markup=kb_main(), parse_mode="HTML")


@dp.message(F.text == "🔙 Главное меню")
async def back_main(message: types.Message, state: FSMContext):
    await state.clear()
    await show_main(message)


# ================= ПОПОЛНЕНИЕ =================
@dp.message(F.text.in_({"📥 Пополнить", "💎 Пополнить", "Пополнить"}))
async def dep_start(message: types.Message, state: FSMContext):
    if not await is_subscribed(message.from_user.id):
        await message.answer(
            f"{E['target']} Сначала подпишитесь на канал.",
            reply_markup=kb_subscribe(),
            parse_mode="HTML",
        )
        return
    if not bot_active() and not is_admin(message.from_user.id):
        await message.answer(f"{E['cross']} Бот на обслуживании.", parse_mode="HTML")
        return
    await state.set_state(DepositState.platform)
    await message.answer(
        f"{E['money']} <b>Выберите букмекера:</b>",
        reply_markup=kb_platform("dep"),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.in_({"dep_1x", "dep_mel"}))
async def dep_plat(callback: types.CallbackQuery, state: FSMContext):
    platform = "1xBet" if callback.data == "dep_1x" else "Melbet"
    await state.update_data(platform=platform)
    await state.set_state(DepositState.account)
    await callback.answer()
    await callback.message.answer(
        f"{E['key']} Введите ID <b>{platform}</b> (только цифры):",
        parse_mode="HTML",
    )


@dp.message(DepositState.account)
async def dep_acc(message: types.Message, state: FSMContext):
    acc = (message.text or "").strip()
    if not acc.isdigit():
        await message.answer(f"{E['cross']} Только цифры. Попробуйте снова:", parse_mode="HTML")
        return
    await state.update_data(account_id=acc)
    await state.set_state(DepositState.amount)
    await message.answer(
        f"{E['check']} Аккаунт принят\n\n"
        f"Выберите сумму или введите число ({MIN_DEPOSIT}–{MAX_DEPOSIT}):",
        reply_markup=kb_amounts(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("amt_"))
async def dep_amt_btn(callback: types.CallbackQuery, state: FSMContext):
    amount = float(callback.data.replace("amt_", ""))
    await callback.answer()
    await send_invoice(callback.message, state, amount)


@dp.message(DepositState.amount)
async def dep_amt_txt(message: types.Message, state: FSMContext):
    try:
        base = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer(f"{E['cross']} Введите число!", parse_mode="HTML")
        return
    if not (MIN_DEPOSIT <= base <= MAX_DEPOSIT):
        await message.answer(f"{E['cross']} От {MIN_DEPOSIT} до {MAX_DEPOSIT}", parse_mode="HTML")
        return
    final = round(base + random.randint(10, 99) / 100.0, 2)
    await send_invoice(message, state, final)


async def send_invoice(message: types.Message, state: FSMContext, amount: float):
    data = await state.get_data()
    platform = data.get("platform", "Melbet")
    account_id = data.get("account_id", "")
    await state.update_data(amount=amount)
    await state.set_state(DepositState.receipt)
    text = (
        f"{E['wallet']} <b>К оплате: {amount:.2f} KGS</b>\n\n"
        f"{E['clock']} Реквизиты актуальны <b>5 минут</b>\n"
        f"🆔 Счёт: <code>{platform} | {account_id}</code>\n"
        f"📌 Переведите <u>точную сумму</u> с копейками\n\n"
        f"Выберите банк и оплатите.\n"
        f"После оплаты пришлите <b>скриншот чека</b>."
    )
    await message.answer(text, reply_markup=kb_banks(), parse_mode="HTML")


@dp.message(DepositState.receipt, F.photo | F.document)
async def dep_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    platform = data.get("platform", "Melbet")
    account_id = data.get("account_id", "")
    amount = float(data.get("amount") or 0)
    if not account_id or amount < MIN_DEPOSIT:
        await message.answer(f"{E['cross']} Данные утеряны. Начните: 📥 Пополнить", parse_mode="HTML")
        await state.clear()
        return
    photo_id = message.photo[-1].file_id if message.photo else message.document.file_id
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    cursor.execute(
        """INSERT INTO deposits (user_id, platform, account_id, amount, photo_id, status, created_at, ts)
           VALUES (?,?,?,?,?,'pending',?,?)""",
        (
            uid,
            platform,
            f"{platform} | {account_id}",
            amount,
            photo_id,
            now_kg().strftime("%d.%m.%Y %H:%M"),
            int(time.time()),
        ),
    )
    dep_id = cursor.lastrowid
    conn.commit()
    caption = (
        f"{E['fire']} <b>ЗАЯВКА #{dep_id}</b>\n\n"
        f"👤 {user_label(uid)}\n"
        f"{E['money']} <b>{amount:.2f} KGS</b>\n"
        f"🆔 <code>{platform} | {account_id}</code>"
    )
    try:
        await bot.send_photo(ADMIN_ID, photo_id, caption=caption, reply_markup=kb_dep(dep_id), parse_mode="HTML")
    except Exception:
        await bot.send_message(ADMIN_ID, caption, reply_markup=kb_dep(dep_id), parse_mode="HTML")
    await state.clear()
    await message.answer(
        f"{E['check']} <b>Заявка #{dep_id} принята!</b>\n\n"
        f"{E['money']} {amount:.2f} KGS\n"
        f"{E['clock']} Оператор проверяет платёж.",
        parse_mode="HTML",
        reply_markup=kb_main(),
    )


@dp.callback_query(F.data.startswith("dep_ok_") | F.data.startswith("dep_no_"))
async def dep_mod(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    ok = callback.data.startswith("dep_ok_")
    dep_id = int(callback.data.split("_")[-1])
    cursor.execute(
        "SELECT user_id, amount, account_id, status, ts FROM deposits WHERE id=?",
        (dep_id,),
    )
    row = cursor.fetchone()
    if not row or row[3] != "pending":
        await callback.answer("Уже обработано")
        return
    user_id, amount, account_id, _, ts = row
    cursor.execute(
        "UPDATE deposits SET status=? WHERE id=?",
        ("approved" if ok else "rejected", dep_id),
    )
    conn.commit()
    await callback.answer("OK")
    if ok:
        elapsed = int(time.time()) - (ts or int(time.time()))
        try:
            await bot.send_message(
                user_id,
                f"{E['check']} <b>Баланс успешно пополнен!</b>\n\n"
                f"{E['money']} <b>{amount:.2f} KGS</b>\n"
                f"🆔 <code>{account_id}</code>\n"
                f"{E['clock']} {elapsed} сек\n\n"
                f"{E['rocket']} Спасибо, что выбрали <b>{BOT_NAME}</b>!",
                parse_mode="HTML",
            )
        except Exception:
            pass
        cursor.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,))
        r = cursor.fetchone()
        if r and r[0]:
            bonus = round(float(amount) * REF_PERCENT / 100.0, 2)
            if bonus > 0:
                cursor.execute(
                    "UPDATE users SET ref_balance=COALESCE(ref_balance,0)+? WHERE user_id=?",
                    (bonus, r[0]),
                )
                conn.commit()
                try:
                    await bot.send_message(
                        r[0],
                        f"{E['gift']} <b>Реферальный бонус: {bonus:.2f} KGS</b>\n\n"
                        f"Друг пополнил: <b>{amount:.2f} KGS</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        try:
            await callback.message.edit_caption(caption=f"{E['check']} #{dep_id} ОДОБРЕНА", parse_mode="HTML")
        except Exception:
            pass
    else:
        try:
            await bot.send_message(user_id, f"{E['cross']} Заявка на {amount:.2f} KGS отклонена.", parse_mode="HTML")
        except Exception:
            pass
        try:
            await callback.message.edit_caption(caption=f"{E['cross']} #{dep_id} ОТКЛОНЕНА", parse_mode="HTML")
        except Exception:
            pass


# ================= ВЫВОД =================
@dp.message(F.text.in_({"📤 Вывести", "💰 Вывести", "Вывести"}))
async def wd_start(message: types.Message, state: FSMContext):
    if not await is_subscribed(message.from_user.id):
        await message.answer(
            f"{E['target']} Сначала подпишитесь на канал.",
            reply_markup=kb_subscribe(),
            parse_mode="HTML",
        )
        return
    if not bot_active() and not is_admin(message.from_user.id):
        await message.answer(f"{E['cross']} Бот на обслуживании.", parse_mode="HTML")
        return
    await state.set_state(WithdrawState.platform)
    await message.answer(
        f"{E['withdraw']} <b>Выберите букмекера для вывода:</b>",
        reply_markup=kb_platform("wd"),
        parse_mode="HTML",
    )


@dp.callback_query(F.data.in_({"wd_1x", "wd_mel"}))
async def wd_plat(callback: types.CallbackQuery, state: FSMContext):
    platform = "1xBet" if callback.data == "wd_1x" else "Melbet"
    await state.update_data(platform=platform)
    await state.set_state(WithdrawState.qr)
    await callback.answer()
    await callback.message.answer(
        f"{E['wallet']} Отправьте <b>фото QR</b> кошелька (ELQR / банк):",
        parse_mode="HTML",
    )


@dp.message(WithdrawState.qr, F.photo | F.document)
async def wd_qr(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else message.document.file_id
    data = await state.get_data()
    platform = data.get("platform", "Melbet")
    await state.update_data(qr_file_id=fid)
    await state.set_state(WithdrawState.account)
    await message.answer(f"{E['key']} Введите ID <b>{platform}</b>:", parse_mode="HTML")


@dp.message(WithdrawState.qr)
async def wd_qr_bad(message: types.Message):
    await message.answer(f"{E['cross']} Нужно фото QR!", parse_mode="HTML")


@dp.message(WithdrawState.account)
async def wd_acc(message: types.Message, state: FSMContext):
    acc = (message.text or "").strip()
    if not acc:
        await message.answer(f"{E['cross']} Введите ID!", parse_mode="HTML")
        return
    data = await state.get_data()
    platform = data.get("platform", "Melbet")
    await state.update_data(account_id=f"{platform} | {acc}")
    await state.set_state(WithdrawState.code)
    await message.answer(
        f"{E['withdraw']} <b>Инструкция вывода · {platform}</b>\n\n"
        f"1. Настройки → Вывести со счёта\n"
        f"2. Способ: <b>MOBCASH / LMWPAY</b>\n"
        f"3. Укажите сумму\n"
        f"4. Город: <b>Бишкек</b>\n"
        f"5. Улица: <b>DiamondPAY KG</b>\n"
        f"6. Подтвердите → получите код\n"
        f"7. Отправьте код в этот бот",
        parse_mode="HTML",
    )


@dp.message(WithdrawState.code)
async def wd_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip()
    if not code:
        await message.answer(f"{E['cross']} Отправьте код!", parse_mode="HTML")
        return
    data = await state.get_data()
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    cursor.execute(
        """INSERT INTO withdrawals (user_id, platform, account_id, qr_file_id, code, status, created_at)
           VALUES (?,?,?,?,?,'pending',?)""",
        (
            uid,
            data.get("platform"),
            data.get("account_id"),
            data.get("qr_file_id"),
            code,
            now_kg().strftime("%d.%m.%Y %H:%M"),
        ),
    )
    w_id = cursor.lastrowid
    conn.commit()
    caption = (
        f"{E['withdraw']} <b>ВЫВОД #{w_id}</b>\n\n"
        f"👤 {user_label(uid)}\n"
        f"🆔 <code>{data.get('account_id')}</code>\n"
        f"{E['key']} Код: <code>{code}</code>"
    )
    try:
        await bot.send_photo(
            ADMIN_ID,
            data.get("qr_file_id"),
            caption=caption,
            reply_markup=kb_wd(w_id),
            parse_mode="HTML",
        )
    except Exception:
        await bot.send_message(ADMIN_ID, caption, reply_markup=kb_wd(w_id), parse_mode="HTML")
    await state.clear()
    await message.answer(
        f"{E['check']} <b>Заявка на вывод #{w_id} принята!</b>\n\n"
        f"{E['clock']} Ожидайте выплаты.",
        parse_mode="HTML",
        reply_markup=kb_main(),
    )


@dp.callback_query(F.data.startswith("wd_ok_") | F.data.startswith("wd_no_"))
async def wd_mod(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    ok = callback.data.startswith("wd_ok_")
    w_id = int(callback.data.split("_")[-1])
    cursor.execute("SELECT user_id, account_id, status FROM withdrawals WHERE id=?", (w_id,))
    row = cursor.fetchone()
    if not row or row[2] != "pending":
        await callback.answer("Уже обработано")
        return
    cursor.execute(
        "UPDATE withdrawals SET status=? WHERE id=?",
        ("completed" if ok else "rejected", w_id),
    )
    conn.commit()
    await callback.answer("OK")
    try:
        if ok:
            await bot.send_message(
                row[0],
                f"{E['check']} <b>Вывод выполнен</b>\n🆔 <code>{row[1]}</code>",
                parse_mode="HTML",
            )
            await callback.message.edit_caption(
                caption=f"{E['check']} ВЫВОД #{w_id} ГОТОВ", parse_mode="HTML"
            )
        else:
            await bot.send_message(row[0], f"{E['cross']} Вывод #{w_id} отклонён.", parse_mode="HTML")
            await callback.message.edit_caption(
                caption=f"{E['cross']} ВЫВОД #{w_id} ОТКЛОНЁН", parse_mode="HTML"
            )
    except Exception:
        pass


# ================= РЕФЕРАЛЫ =================
@dp.message(F.text.in_({"🤝 Пригласить друга", "Рефералы"}))
async def show_ref(message: types.Message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    bal = get_ref_balance(uid)
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (uid,))
    friends = cursor.fetchone()[0]
    cursor.execute(
        """SELECT COUNT(*), COALESCE(SUM(d.amount),0) FROM deposits d
           JOIN users u ON u.user_id=d.user_id
           WHERE u.referrer_id=? AND d.status='approved'""",
        (uid,),
    )
    cnt, ssum = cursor.fetchone()
    text = (
        f"{E['gift']} <b>Пригласи друга</b>\n\n"
        f"Ссылка:\n<code>{link}</code>\n\n"
        f"Бонус с пополнений друзей: <b>{REF_PERCENT}%</b>\n\n"
        f"👥 Друзей: <b>{friends}</b>\n"
        f"{E['check']} Пополнений: <b>{cnt}</b>\n"
        f"{E['dollar']} Сумма: <b>{ssum:.2f} KGS</b>\n"
        f"{E['money']} Баланс: <b>{bal:.2f} KGS</b>\n\n"
        f"Мин. вывод рефки: <b>{MIN_REF_OUT}</b> KGS\n"
        f"Вывод: QR · 1xBet · Melbet"
    )
    await message.answer(text, reply_markup=kb_ref(bal), parse_mode="HTML")


@dp.callback_query(F.data.in_({"ref_1x", "ref_mel", "ref_out", "ref_qr"}))
async def ref_act(callback: types.CallbackQuery, state: FSMContext):
    bal = get_ref_balance(callback.from_user.id)
    if bal < MIN_REF_OUT:
        await callback.answer(f"Мин. {MIN_REF_OUT} KGS", show_alert=True)
        return
    await callback.answer()
    if callback.data == "ref_qr":
        await state.update_data(ref_amount=bal, ref_mode="qr")
        await state.set_state(RefOutState.qr)
        await callback.message.answer(
            f"{E['wallet']} Вывод рефки на QR\nСумма: <b>{bal:.2f} KGS</b>\n\nОтправьте фото QR:",
            parse_mode="HTML",
        )
        return
    if callback.data == "ref_1x":
        await state.update_data(ref_amount=bal, ref_platform="1xBet", ref_mode="topup")
        await state.set_state(RefOutState.target)
        await callback.message.answer(f"{E['key']} ID <b>1xBet</b>:", parse_mode="HTML")
        return
    if callback.data == "ref_mel":
        await state.update_data(ref_amount=bal, ref_platform="Melbet", ref_mode="topup")
        await state.set_state(RefOutState.target)
        await callback.message.answer(f"{E['key']} ID <b>Melbet</b>:", parse_mode="HTML")
        return
    await state.update_data(ref_amount=bal, ref_mode="out")
    await state.set_state(RefOutState.platform)
    await callback.message.answer("Куда зачислить?", reply_markup=kb_platform("refp"))


@dp.callback_query(F.data.in_({"refp_1x", "refp_mel"}))
async def ref_plat(callback: types.CallbackQuery, state: FSMContext):
    platform = "1xBet" if callback.data == "refp_1x" else "Melbet"
    await state.update_data(ref_platform=platform)
    await state.set_state(RefOutState.target)
    await callback.answer()
    await callback.message.answer(f"{E['key']} ID <b>{platform}</b>:", parse_mode="HTML")


@dp.message(RefOutState.qr, F.photo | F.document)
async def ref_qr(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else message.document.file_id
    data = await state.get_data()
    bal = float(data.get("ref_amount") or 0)
    uid = message.from_user.id
    if get_ref_balance(uid) < MIN_REF_OUT:
        await message.answer(f"{E['cross']} Недостаточно", parse_mode="HTML")
        await state.clear()
        return
    cursor.execute(
        "UPDATE users SET ref_balance=COALESCE(ref_balance,0)-? WHERE user_id=?",
        (bal, uid),
    )
    cursor.execute(
        """INSERT INTO ref_outs (user_id, amount, platform, target, status, created_at)
           VALUES (?,?,?,'QR','pending',?)""",
        (uid, bal, "QR", now_kg().strftime("%d.%m.%Y %H:%M")),
    )
    rid = cursor.lastrowid
    conn.commit()
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Зачислено", callback_data=f"refok_{rid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"refno_{rid}"),
            ]
        ]
    )
    try:
        await bot.send_photo(
            ADMIN_ID,
            fid,
            caption=f"{E['gift']} РЕФКА QR #{rid}\n👤 {user_label(uid)}\n{E['money']} {bal:.2f} KGS",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        pass
    await message.answer(f"{E['check']} Заявка #{rid} принята.", reply_markup=kb_main(), parse_mode="HTML")


@dp.message(RefOutState.target)
async def ref_target(message: types.Message, state: FSMContext):
    target = (message.text or "").strip()
    if not target:
        await message.answer(f"{E['cross']} Введите ID!", parse_mode="HTML")
        return
    data = await state.get_data()
    bal = float(data.get("ref_amount") or 0)
    platform = data.get("ref_platform", "Melbet")
    uid = message.from_user.id
    if get_ref_balance(uid) < MIN_REF_OUT:
        await message.answer(f"{E['cross']} Недостаточно", parse_mode="HTML")
        await state.clear()
        return
    cursor.execute(
        "UPDATE users SET ref_balance=COALESCE(ref_balance,0)-? WHERE user_id=?",
        (bal, uid),
    )
    cursor.execute(
        """INSERT INTO ref_outs (user_id, amount, platform, target, status, created_at)
           VALUES (?,?,?,?,'pending',?)""",
        (uid, bal, platform, target, now_kg().strftime("%d.%m.%Y %H:%M")),
    )
    rid = cursor.lastrowid
    conn.commit()
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Зачислено", callback_data=f"refok_{rid}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"refno_{rid}"),
            ]
        ]
    )
    await bot.send_message(
        ADMIN_ID,
        f"{E['gift']} РЕФКА #{rid}\n👤 {user_label(uid)}\n{E['money']} {bal:.2f}\n"
        f"🆔 {platform} | <code>{target}</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await message.answer(f"{E['check']} Заявка #{rid} принята.", reply_markup=kb_main(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("refok_") | F.data.startswith("refno_"))
async def ref_mod(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    ok = callback.data.startswith("refok_")
    rid = int(callback.data.split("_")[-1])
    cursor.execute("SELECT user_id, amount, status FROM ref_outs WHERE id=?", (rid,))
    row = cursor.fetchone()
    if not row or row[2] != "pending":
        await callback.answer("Уже обработано")
        return
    cursor.execute(
        "UPDATE ref_outs SET status=? WHERE id=?",
        ("done" if ok else "rejected", rid),
    )
    if not ok:
        cursor.execute(
            "UPDATE users SET ref_balance=COALESCE(ref_balance,0)+? WHERE user_id=?",
            (row[1], row[0]),
        )
    conn.commit()
    await callback.answer("OK")
    try:
        if ok:
            await bot.send_message(
                row[0],
                f"{E['check']} Рефка #{rid} зачислена: {row[1]:.2f} KGS",
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                row[0],
                f"{E['cross']} Рефка #{rid} отклонена, сумма возвращена.",
                parse_mode="HTML",
            )
    except Exception:
        pass


# ================= ПОДДЕРЖКА =================
@dp.message(F.text.in_({"👤 Поддержка", "Поддержка"}))
async def support_start(message: types.Message, state: FSMContext):
    await state.set_state(SupportState.message)
    await message.answer(
        f"{E['support']} <b>Поддержка {BOT_NAME}</b>\n\n"
        f"Напишите вопрос текстом или отправьте <b>фото</b> (можно с подписью).\n"
        f"Статусы: Новое → В работе → Закрыто",
        parse_mode="HTML",
    )


@dp.message(SupportState.message)
async def support_msg(message: types.Message, state: FSMContext):
    if message.text in ("🔙 Назад", "/start", "🔙 Главное меню"):
        await state.clear()
        await show_main(message)
        return
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        photo_id = message.document.file_id
    text = (message.caption or message.text or "").strip()
    if not photo_id and len(text) < 2:
        await message.answer(f"{E['cross']} Текст или фото:", parse_mode="HTML")
        return
    if not text:
        text = "📎 Фото"
    uid = message.from_user.id
    uname = message.from_user.username or ""
    ensure_user(uid, uname, message.from_user.full_name or "")
    cursor.execute(
        """INSERT INTO tickets (user_id, username, message, photo_id, status, created_at)
           VALUES (?,?,?,?,'new',?)""",
        (uid, uname, text, photo_id, now_kg().strftime("%d.%m.%Y %H:%M")),
    )
    tid = cursor.lastrowid
    conn.commit()
    await state.clear()
    cap = (
        f"🆘 <b>Обращение #{tid}</b> · Новое\n\n"
        f"👤 {user_label(uid)}\n"
        f"💬 {text}"
    )
    try:
        if photo_id:
            await bot.send_photo(ADMIN_ID, photo_id, caption=cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
        else:
            await bot.send_message(ADMIN_ID, cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
    except Exception as e:
        logger.warning(e)
    await message.answer(
        f"{E['check']} Обращение <b>#{tid}</b> принято.\nСтатус: <b>Новое</b>",
        parse_mode="HTML",
        reply_markup=kb_main(),
    )


@dp.callback_query(F.data.startswith("tkt_"))
async def tkt_cb(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    parts = callback.data.split("_")
    action, tid = parts[1], int(parts[2])
    cursor.execute("SELECT user_id FROM tickets WHERE id=?", (tid,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Не найдено")
        return
    uid = row[0]
    if action == "work":
        cursor.execute("UPDATE tickets SET status='work' WHERE id=?", (tid,))
        conn.commit()
        await callback.answer("В работе")
        try:
            await bot.send_message(uid, f"{E['clock']} Обращение #{tid} в работе.", parse_mode="HTML")
        except Exception:
            pass
    elif action == "close":
        cursor.execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,))
        conn.commit()
        await callback.answer("Закрыто")
        try:
            await bot.send_message(uid, f"{E['check']} Обращение #{tid} закрыто.", parse_mode="HTML")
        except Exception:
            pass
    elif action == "reply":
        await state.set_state(AdminReplyState.text)
        await state.update_data(reply_tid=tid)
        await callback.answer()
        await callback.message.answer(f"{E['key']} Ответ для #{tid}:", parse_mode="HTML")


@dp.message(AdminReplyState.text)
async def admin_reply(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    tid = data.get("reply_tid")
    cursor.execute("SELECT user_id FROM tickets WHERE id=?", (tid,))
    row = cursor.fetchone()
    await state.clear()
    if not row:
        await message.answer("Не найдено")
        return
    cursor.execute("UPDATE tickets SET status='work' WHERE id=?", (tid,))
    conn.commit()
    try:
        await bot.send_message(
            row[0],
            f"{E['support']} <b>Ответ оператора</b> (#{tid})\n\n{message.text}",
            parse_mode="HTML",
        )
        await message.answer(f"{E['check']} Отправлено", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ================= ИНСТРУКЦИЯ =================
@dp.message(F.text.in_({"📖 Инструкция", "Инструкция"}))
async def instruction(message: types.Message):
    await message.answer(
        f"{E['admin']} <b>Инструкция {BOT_NAME}</b>\n\n"
        f"<b>Пополнение</b>\n"
        f"1. 📥 Пополнить → 1xBet / Melbet\n"
        f"2. ID → сумма → банк → чек\n\n"
        f"<b>Вывод</b>\n"
        f"1. 📤 Вывести → букмекер\n"
        f"2. QR кошелька → ID → код MOBCASH\n"
        f"Город: <b>Бишкек</b> · Улица: <b>DiamondPAY KG</b>\n\n"
        f"<b>Рефералы</b> — {REF_PERCENT}%, от {MIN_REF_OUT} KGS\n"
        f"<b>Поддержка</b> — текст или фото в боте",
        parse_mode="HTML",
        reply_markup=kb_main(),
    )


# ================= АДМИН ПАНЕЛЬ =================
@dp.message(Command("admin"))
async def admin_cmd(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer(f"{E['cross']} Нет доступа", parse_mode="HTML")
        return
    await state.clear()
    await message.answer(
        f"{E['admin']} <b>Панель администратора</b>\n\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Канал: {CHANNEL_USERNAME}\n"
        f"Бот: {'🟢 Вкл' if bot_active() else '🔴 Выкл'}",
        reply_markup=kb_admin(),
        parse_mode="HTML",
    )


@dp.message(F.text == "📋 Заявки")
async def admin_deps(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute(
        "SELECT id, user_id, amount, account_id, photo_id FROM deposits WHERE status='pending' ORDER BY id DESC LIMIT 20"
    )
    rows = cursor.fetchall()
    if not rows:
        await message.answer(f"{E['check']} Нет активных заявок на пополнение.", parse_mode="HTML")
        return
    for dep_id, uid, amount, acc, photo_id in rows:
        cap = (
            f"{E['fire']} <b>ЗАЯВКА #{dep_id}</b>\n\n"
            f"👤 {user_label(uid)}\n"
            f"{E['money']} {amount:.2f} KGS\n"
            f"🆔 <code>{acc}</code>"
        )
        try:
            if photo_id:
                await bot.send_photo(
                    message.chat.id, photo_id, caption=cap, reply_markup=kb_dep(dep_id), parse_mode="HTML"
                )
            else:
                await message.answer(cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
        except Exception:
            await message.answer(cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")


@dp.message(F.text == "📩 Обращения")
async def admin_tickets(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute(
        "SELECT id, user_id, username, message, photo_id, status, created_at FROM tickets "
        "WHERE status!='closed' ORDER BY id DESC LIMIT 15"
    )
    rows = cursor.fetchall()
    if not rows:
        await message.answer(f"{E['check']} Нет открытых обращений.", parse_mode="HTML")
        return
    st_map = {"new": "🆕 Новое", "work": "🔄 В работе", "closed": "✅ Закрыто"}
    for tid, uid, uname, msg, photo_id, status, created in rows:
        cap = (
            f"🆘 <b>#{tid}</b> · {st_map.get(status, status)}\n"
            f"👤 {user_label(uid)}\n"
            f"📅 {created}\n\n💬 {msg[:400]}"
        )
        try:
            if photo_id:
                await bot.send_photo(
                    message.chat.id, photo_id, caption=cap, reply_markup=kb_ticket(tid), parse_mode="HTML"
                )
            else:
                await message.answer(cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
        except Exception:
            await message.answer(cap, reply_markup=kb_ticket(tid), parse_mode="HTML")


@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'")
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status='approved'")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status='new'")
    tickets = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    wds = cursor.fetchone()[0]
    await message.answer(
        f"{E['stats']} <b>СТАТИСТИКА</b>\n\n"
        f"👥 Пользователей: <b>{users}</b>\n"
        f"{E['clock']} Пополнений в очереди: <b>{pending}</b>\n"
        f"{E['withdraw']} Выводов в очереди: <b>{wds}</b>\n"
        f"🆘 Новых обращений: <b>{tickets}</b>\n"
        f"{E['money']} Объём: <b>{total:.2f} KGS</b>",
        parse_mode="HTML",
    )


@dp.message(F.text == "📢 Рассылка")
async def admin_bc_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastState.content)
    await message.answer(f"{E['support']} Отправьте текст или фото с подписью для рассылки:", parse_mode="HTML")


@dp.message(BroadcastState.content)
async def admin_bc_send(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    cursor.execute("SELECT user_id FROM users")
    users = [r[0] for r in cursor.fetchall()]
    ok = 0
    photo = message.photo[-1].file_id if message.photo else None
    text = message.caption or message.text or ""
    for uid in users:
        try:
            if photo:
                await bot.send_photo(uid, photo, caption=text, parse_mode="HTML")
            elif text:
                await bot.send_message(uid, text, parse_mode="HTML")
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await message.answer(
        f"{E['check']} Рассылка: {ok}/{len(users)}",
        reply_markup=kb_admin(),
        parse_mode="HTML",
    )


@dp.message(F.text.in_({"🔴 ВЫКЛ", "🟢 ВКЛ"}))
async def admin_toggle(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    on = "ВКЛ" in (message.text or "")
    set_bot_active(on)
    await message.answer(
        f"{'🟢' if on else '🔴'} Бот {'ВКЛЮЧЕН' if on else 'ВЫКЛЮЧЕН'}",
        reply_markup=kb_admin(),
    )


# ================= ЗАПУСК =================
async def main():
    if not BOT_TOKEN or len(BOT_TOKEN) < 40:
        raise SystemExit("Укажите TOKEN в env")
    # Сброс webhook — иначе Conflict с другим getUpdates
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("webhook deleted, pending updates dropped")
    except Exception as e:
        logger.warning(f"delete_webhook: {e}")
    logger.info(
        f"{BOT_NAME} start | admin={ADMIN_ID} | channel={CHANNEL_USERNAME} | pay=ok"
    )
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
