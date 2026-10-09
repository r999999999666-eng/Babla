import asyncio
import logging
import os
import random
import sqlite3
import string
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Configuration & Helpers
def _token() -> str:
    for k in ("TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN"):
        v = (os.environ.get(k) or "").strip().strip('"').strip("'")
        if len(v) >= 40 and ":" in v:
            return v
    return ""

BOT_TOKEN = _token()

def _parse_admins() -> list[int]:
    raw = (os.environ.get("ADMIN_IDS") or os.environ.get("ADMIN_ID") or "8992968778").strip()
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            n = int(part)
            if n not in ids:
                ids.append(n)
    for extra in (8992968778, 7541027590):
        if extra not in ids:
            ids.append(extra)
    return ids

ADMIN_IDS = _parse_admins()
ADMIN_ID = ADMIN_IDS[0]
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "").strip()
CHANNEL_URL = os.environ.get("CHANNEL_LINK", "").strip()
SUPPORT_USER = os.environ.get("SUPPORT_USER", "@DiamondPAY_HELP")
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111214680148545710129962221176241202111302123409%D0%A0%D1%83%D1%81%D0%BB%D0%B0%D0%BD%20%D0%A8.520473995303417540105906O%21Bank6304E60B",
)
BOT_NAME = "SomPayKG"
MIN_DEPOSIT = 50
MAX_DEPOSIT = 20_000
REF_PERCENT = 2.5
MIN_REF = 500
PLATFORM = "1xBet"
TZ = ZoneInfo("Asia/Bishkek")

def now_kg() -> datetime:
    return datetime.now(TZ)

def code_gen(n: int = 5) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def pe(eid: str, fb: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'

E = {
    "star": pe("5379607913046242841", "❄️"),
    "vip": pe("5400373628950840597", "❄️"),
    "gem": pe("5399942684817258282", "❄️"),
    "spark": pe("5379943126653761268", "❄️"),
    "spark2": pe("5397807437531086888", "❄️"),
    "rocket": pe("5188481279963715781", "🚀"),
    "check": pe("6273749318717412886", "✅"),
    "money": pe("5224257782013769471", "💰"),
    "cash": pe("5197434882321567830", "💵"),
    "withdraw": pe("5201691993775818138", "🛫"),
    "wallet": pe("5215420556089776398", "👛"),
    "support": pe("5472239203590888751", "📩"),
    "admin": pe("5193177581888755275", "💻"),
    "fire": pe("5201945242227472933", "⚡️"),
    "zap": pe("5226830214020999125", "⚡️"),
    "web": pe("5201732344993576400", "🌐"),
    "stats": pe("5224588661999282075", "💲"),
    "write": pe("5197269100878907942", "✍️"),
    "exchange": pe("5377336227533969892", "💱"),
    "lock": "🔒",
    "wave": "👋",
    "cross": "❌",
}

# Database Initialization
conn = sqlite3.connect("diamondpay.db", check_same_thread=False)
cur = conn.cursor()
cur.executescript("""
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
    code TEXT,
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
    code TEXT,
    user_id INTEGER,
    platform TEXT,
    account_id TEXT,
    qr_file_id TEXT,
    code_txt TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS ref_outs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT,
    user_id INTEGER,
    amount REAL,
    platform TEXT,
    target TEXT,
    qr_file_id TEXT,
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
CREATE TABLE IF NOT EXISTS admins (
    chat_id INTEGER PRIMARY KEY
);
""")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_active', '1')")
for _aid in ADMIN_IDS:
    cur.execute("INSERT OR IGNORE INTO admins (chat_id) VALUES (?)", (_aid,))
try:
    cur.execute("ALTER TABLE users ADD COLUMN melbet_id TEXT")
    conn.commit()
except Exception:
    pass
conn.commit()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise SystemExit("TOKEN missing. Set Env TOKEN=123456:AAH... on Render.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# States
class Dep(StatesGroup):
    platform = State()
    account = State()
    amount = State()
    receipt = State()

class Wd(StatesGroup):
    platform = State()
    qr = State()
    account = State()
    code = State()

class RefOut(StatesGroup):
    qr = State()
    amount = State()
    target = State()

class Support(StatesGroup):
    msg = State()

class AdminReply(StatesGroup):
    text = State()

class Broadcast(StatesGroup):
    content = State()

class AdminAdd(StatesGroup):
    uid = State()

class AdminDel(StatesGroup):
    uid = State()

# Functions
def get_admins() -> list[int]:
    cur.execute("SELECT chat_id FROM admins")
    ids = [r[0] for r in cur.fetchall()]
    for a in ADMIN_IDS:
        if a not in ids:
            ids.append(a)
    return ids

def is_admin(uid: int) -> bool:
    return uid in get_admins()

async def notify_admins(text: str = None, photo: str = None, reply_markup=None, parse_mode: str = "HTML"):
    for aid in get_admins():
        try:
            if photo:
                await bot.send_photo(aid, photo, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            elif text:
                await bot.send_message(aid, text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            log.warning(f"notify_admin {aid}: {e}")

def add_admin(uid: int):
    cur.execute("INSERT OR IGNORE INTO admins (chat_id) VALUES (?)", (uid,))
    conn.commit()

def remove_admin(uid: int):
    if uid == ADMIN_ID:
        return False
    cur.execute("DELETE FROM admins WHERE chat_id=?", (uid,))
    conn.commit()
    return True

def bot_on() -> bool:
    cur.execute("SELECT value FROM settings WHERE key='bot_active'")
    r = cur.fetchone()
    return (r[0] if r else "1") == "1"

def set_bot(on: bool):
    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('bot_active',?)", ("1" if on else "0"))
    conn.commit()

def ensure_user(uid: int, uname: str = "", name: str = "", ref: int | None = None):
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if cur.fetchone():
        cur.execute("UPDATE users SET username=COALESCE(?,username), full_name=COALESCE(?,full_name) WHERE user_id=?",
                    (uname or None, name or None, uid))
        conn.commit()
        return
    rid = None
    if ref and ref != uid:
        cur.execute("SELECT 1 FROM users WHERE user_id=?", (ref,))
        if cur.fetchone():
            rid = ref
    cur.execute("INSERT INTO users (user_id,username,full_name,referrer_id,created_at) VALUES (?,?,?,?,?)",
                (uid, uname, name, rid, now_kg().strftime("%d.%m.%Y %H:%M")))
    conn.commit()

def label(uid: int) -> str:
    cur.execute("SELECT username, full_name FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    p = [f"<code>{uid}</code>"]
    if r:
        if r[0]: p.append(f"@{r[0]}")
        if r[1]: p.append(r[1])
    return " · ".join(p)

def ref_bal(uid: int) -> float:
    cur.execute("SELECT COALESCE(ref_balance,0) FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return float(r[0]) if r else 0.0

def save_player_id(uid: int, account_id: str):
    acc = (account_id or "").strip()
    if not acc:
        return
    cur.execute("UPDATE users SET melbet_id=? WHERE user_id=?", (acc, uid))
    conn.commit()

def get_player_id(uid: int) -> str:
    cur.execute("SELECT melbet_id FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return (r[0] or "").strip() if r and r[0] else ""

# Keyboards
def kb_main(uid: int | None = None):
    rows = [
        [KeyboardButton(text="💎 Пополнить"), KeyboardButton(text="💰 Вывести")],
        [KeyboardButton(text="👤 Поддержка"), KeyboardButton(text="📖 Инструкция")],
    ]
    if uid is not None and is_admin(uid):
        rows.append([KeyboardButton(text="⚙️ Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

def kb_support():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Сообщение в бота", callback_data="support_bot")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])

def kb_admin():
    on = bot_on()
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Заявки"), KeyboardButton(text="📈 Статистика")],
        [KeyboardButton(text="📩 Обращения"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="➕ Админ"), KeyboardButton(text="➖ Удалить админа")],
        [KeyboardButton(text="🔴 ВЫКЛ" if on else "🟢 ВКЛ")],
        [KeyboardButton(text="🔙 Главное меню")],
    ], resize_keyboard=True, is_persistent=True)

def kb_amounts():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="50"), KeyboardButton(text="100"), KeyboardButton(text="200")],
        [KeyboardButton(text="500"), KeyboardButton(text="1000"), KeyboardButton(text="2000")],
        [KeyboardButton(text="5000"), KeyboardButton(text="10000"), KeyboardButton(text="20000")],
        [KeyboardButton(text="🔙 Главное меню")],
    ], resize_keyboard=True)

def kb_banks():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 O! Bank — оплатить", url=PAY_LINK)],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])

def kb_dep(dep_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"dep_ok_{dep_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dep_no_{dep_id}"),
    ]])

def kb_wd(w_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Готово", callback_data=f"wd_ok_{w_id}"),
        InlineKeyboardButton(text="❌ Отказать", callback_data=f"wd_no_{w_id}"),
    ]])

def kb_ticket(tid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 В работу", callback_data=f"tkt_work_{tid}"),
         InlineKeyboardButton(text="💬 Ответить", callback_data=f"tkt_reply_{tid}")],
        [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"tkt_close_{tid}")],
    ])

def kb_back():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Главное меню")]], resize_keyboard=True)

# Handlers
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    uname = message.from_user.username or ""
    name = message.from_user.full_name or message.from_user.first_name or ""
    ensure_user(uid, uname, name, None)
    if not bot_on() and not is_admin(uid):
        await message.answer("❌ Бот временно отключён.")
        return
    await show_main(message, user=message.from_user)

@dp.callback_query(F.data.in_({"main_menu", "cancel"}))
async def cb_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show_main(call.message, user=call.from_user)

async def show_main(message: types.Message, user: types.User = None):
    target_user = user or message.from_user
    name = target_user.first_name if target_user else "друг"
    uid = target_user.id if target_user else None
    
    text = (
        f"{E['wave']} Привет, <b>{name}</b>!\n\n"
        f"{E['gem']} Добро пожаловать в <b>{BOT_NAME}</b>\n\n"
        f"{E['money']} Авто пополнение — до 1 секунды\n"
        f"{E['withdraw']} Вывод — до 3 часов\n\n"
        f"{E['support']} Поддержка: нажмите кнопку ниже 👇"
    )
    await message.answer(text, reply_markup=kb_main(uid), parse_mode="HTML")

@dp.message(F.text == "🔙 Главное меню")
async def back_main(message: types.Message, state: FSMContext):
    await state.clear()
    await show_main(message)

@dp.message(F.text.in_({"💎 Пополнить", "📥 Пополнить", "Пополнить"}))
async def dep_start(message: types.Message, state: FSMContext):
    if not bot_on() and not is_admin(message.from_user.id):
        await message.answer("Бот на обслуживании.")
        return
    await state.update_data(platform=PLATFORM)
    await state.set_state(Dep.account)
    sample = random.randint(100000000, 999999999)
    await message.answer(
        f"{E['money']} <b>ПОПОЛНЕНИЕ СЧЁТА</b> <code>{sample}</code>\n"
        f"<i>Только {PLATFORM}</i>\n\n"
        f"{E['wallet']} Введите номер счёта, на который вы вносите средства.\n\n"
        f"Это ваш <b>DEPOSIT ID</b> ({PLATFORM}). Он состоит только из цифр.",
        parse_mode="HTML", reply_markup=kb_back())

@dp.message(Dep.account)
async def dep_acc(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    acc = (message.text or "").strip()
    if not acc.isdigit():
        await message.answer("⚠️ DEPOSIT ID только из цифр. Попробуйте снова:")
        return
    try:
        await message.delete()
    except Exception:
        pass
    save_player_id(message.from_user.id, acc)
    await state.update_data(account_id=acc)
    await state.set_state(Dep.amount)
    await message.answer(
        f"{E['check']} ID сохранён: <code>{acc}</code>\n\n"
        f"{E['cash']} Введите сумму пополнения только цифрами или выберите кнопку ({MIN_DEPOSIT}–{MAX_DEPOSIT}):",
        reply_markup=kb_amounts(), parse_mode="HTML")

@dp.message(Dep.amount)
async def dep_amt_txt(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    try: 
        base = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("⚠️ Введите число!"); return
    if not (MIN_DEPOSIT <= base <= MAX_DEPOSIT):
        await message.answer(f"⚠️ От {MIN_DEPOSIT} до {MAX_DEPOSIT}"); return
    final = round(base + random.randint(10, 99) / 100.0, 2)
    try:
        await message.delete()
    except Exception:
        pass
    await send_pay(message, state, final)

async def send_pay(message: types.Message, state: FSMContext, amount: float):
    await state.update_data(amount=amount)
    await state.set_state(Dep.receipt)
    await message.answer(
        f"{E['money']} <b>К оплате: {amount:.2f} KGS</b>\n\n"
        f"{E['zap']} Реквизиты актуальны в течение <b>5 минут</b>.\n"
        f"Нажмите кнопку <b>O! Bank — оплатить</b> ниже.\n\n"
        f"{E['write']} После оплаты отправьте <b>скриншот чека</b> в этот чат.\n\n"
        f"⏳ До окончания оплаты: 05:00",
        reply_markup=kb_banks(), parse_mode="HTML")
    await message.answer("После оплаты — отправьте фото чека 👇", reply_markup=kb_back())

@dp.message(Dep.receipt, F.photo | F.document)
async def dep_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    platform = data.get("platform", PLATFORM)
    acc = data.get("account_id", "")
    amount = float(data.get("amount") or 0)
    if not acc or amount < MIN_DEPOSIT:
        await message.answer("Данные утеряны. Начните: 💎 Пополнить")
        await state.clear(); return
    photo = message.photo[-1].file_id if message.photo else message.document.file_id
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    c = code_gen()
    cur.execute(
        """INSERT INTO deposits (code,user_id,platform,account_id,amount,photo_id,status,created_at,ts)
           VALUES (?,?,?,?,?,?,'pending',?,?)""",
        (c, uid, platform, acc, amount, photo, now_kg().strftime("%d.%m.%Y %H:%M"), int(time.time())))
    dep_id = cur.lastrowid
    conn.commit()
    await message.answer(
        f"{E['check']} Ваша заявка <b>{c}</b> принята на проверку!\n\n"
        f"🆔 ID {platform}: <code>{acc}</code>\n"
        f"{E['cash']} Сумма: <b>{amount:.2f} KGS</b>\n"
        f"{E['money']} Комиссия: <b>0%</b>\n\n"
        f"{E['zap']} Пополнение занимает от 5 секунд до 15 минут\n\n"
        f"Пожалуйста подождите!\n\n"
        f"{E['check']} Вы получите уведомление о зачислении средств!\n\n"
        f"Если возникли проблемы 👇\n{E['support']} Кнопка «👤 Поддержка» в меню",
        parse_mode="HTML", reply_markup=kb_back())
    
    cap = f"🔥 <b>ЗАЯВКА #{dep_id}</b> · <code>{c}</code>\n\n👤 {label(uid)}\n💵 <b>{amount:.2f} KGS</b>\n🆔 {platform} | <code>{acc}</code>"
    await notify_admins(text=cap, photo=photo, reply_markup=kb_dep(dep_id))
    await state.clear()

@dp.callback_query(F.data.startswith("dep_ok_") | F.data.startswith("dep_no_"))
async def dep_mod(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет прав", show_alert=True); return
    ok = call.data.startswith("dep_ok_")
    dep_id = int(call.data.split("_")[-1])
    cur.execute("SELECT user_id, amount, account_id, platform, status, ts, code FROM deposits WHERE id=?", (dep_id,))
    row = cur.fetchone()
    if not row or row[4] != "pending":
        await call.answer("Уже обработано"); return
    uid, amount, acc, platform, _, ts, code = row
    cur.execute("UPDATE deposits SET status=? WHERE id=?", ("approved" if ok else "rejected", dep_id))
    conn.commit()
    await call.answer("OK")
    if ok:
        elapsed = int(time.time()) - (ts or int(time.time()))
        try:
            await bot.send_message(uid,
                f"{E['check']} <b>Баланс успешно пополнен!</b>\n\n{E['cash']} <b>{amount:.2f} KGS</b>\n"
                f"🆔 {platform} | <code>{acc}</code>\n⏱ {elapsed} сек\n\n{E['rocket']} Спасибо, что выбрали <b>{BOT_NAME}</b>!",
                parse_mode="HTML")
        except Exception: pass
        try: await call.message.edit_caption(caption=f"✅ #{dep_id} {code} ОДОБРЕНА")
        except Exception: pass
    else:
        try: await bot.send_message(uid, f"❌ Заявка {code} на {amount:.2f} KGS отклонена.\nНапишите в поддержку через меню.")
        except Exception: pass
        try: await call.message.edit_caption(caption=f"❌ #{dep_id} {code} ОТКЛОНЕНА")
        except Exception: pass

@dp.message(F.text.in_({"💰 Вывести", "📤 Вывести", "Вывести"}))
async def wd_start(message: types.Message, state: FSMContext):
    if not bot_on() and not is_admin(message.from_user.id):
        await message.answer("Бот на обслуживании."); return
    await state.update_data(platform=PLATFORM)
    await state.set_state(Wd.qr)
    await message.answer(
        f"{E['withdraw']} <b>Вывод средств · {PLATFORM}</b>\n\n"
        f"📍 <b>Заходим👇</b>\n"
        f"📍1. Настройки!\n"
        f"📍2. Вывести со счета!\n"
        f"📍3. Mobcash\n"
        f"📍4. Сумму для Вывода!\n"
        f"Город: <b>Бишкек</b>\n"
        f"Улица: <b>SomPayKG 24/7</b>\n"
        f"📍5. Подтвердить\n"
        f"📍6. Получить Код!\n"
        f"📍7. Отправить его в бота\n\n"
        f"{E['wallet']} Сначала отправьте <b>фото QR</b> кошелька (ELQR / банк):",
        parse_mode="HTML", reply_markup=kb_back())

@dp.message(Wd.qr, F.photo | F.document)
async def wd_qr(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else message.document.file_id
    await state.update_data(qr_file_id=fid)
    await state.set_state(Wd.account)
    saved = get_player_id(message.from_user.id)
    if saved:
        await message.answer(
            f"{E['check']} <b>Шаг 2/3 · ID</b>\n\n"
            f"Сохранённый ID: <code>{saved}</code>\n\n"
            f"Отправьте <b>этот же ID</b> или введите другой:",
            parse_mode="HTML", reply_markup=kb_back())
    else:
        await message.answer(
            f"{E['write']} <b>Шаг 2/3 · ID</b>\n\n"
            f"Введите ID <b>{PLATFORM}</b> (только цифры):",
            parse_mode="HTML", reply_markup=kb_back())

@dp.message(Wd.account)
async def wd_acc(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    acc = (message.text or "").strip()
    if not acc:
        await message.answer("Введите ID!"); return
    save_player_id(message.from_user.id, acc)
    await state.update_data(account_id=acc)
    await state.set_state(Wd.code)
    await message.answer(
        f"{E['check']} ID: <code>{acc}</code>\n\n"
        f"{E['write']} <b>Шаг 3/3 · Код</b>\n\n"
        f"Отправьте <b>код вывода</b>:",
        parse_mode="HTML", reply_markup=kb_back())

@dp.message(Wd.code)
async def wd_code(message: types.Message, state: FSMContext):
    code_txt = (message.text or "").strip()
    if not code_txt:
        await message.answer("Отправьте код!"); return
    data = await state.get_data()
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    c = code_gen()
    cur.execute(
        """INSERT INTO withdrawals (code,user_id,platform,account_id,qr_file_id,code_txt,status,created_at)
           VALUES (?,?,?,?,?,?,'pending',?)""",
        (c, uid, data.get("platform"), data.get("account_id"), data.get("qr_file_id"), code_txt,
         now_kg().strftime("%d.%m.%Y %H:%M")))
    w_id = cur.lastrowid
    conn.commit()
    cap = (f"🛫 <b>ВЫВОД #{w_id}</b> · <code>{c}</code>\n\n👤 {label(uid)}\n"
           f"🆔 {data.get('platform')} | <code>{data.get('account_id')}</code>\n🔑 Код: <code>{code_txt}</code>")
    await notify_admins(text=cap, photo=data.get("qr_file_id"), reply_markup=kb_wd(w_id))
    await state.clear()
    await message.answer(
        f"{E['check']} Заявка <b>{c}</b> на вывод принята!\n\n{E['zap']} Ожидайте выплаты.",
        parse_mode="HTML", reply_markup=kb_main(message.from_user.id))

@dp.callback_query(F.data.startswith("wd_ok_") | F.data.startswith("wd_no_"))
async def wd_mod(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет прав", show_alert=True); return
    ok = call.data.startswith("wd_ok_")
    w_id = int(call.data.split("_")[-1])
    cur.execute("SELECT user_id, account_id, status, code FROM withdrawals WHERE id=?", (w_id,))
    row = cur.fetchone()
    if not row or row[2] != "pending":
        await call.answer("Уже обработано"); return
    cur.execute("UPDATE withdrawals SET status=? WHERE id=?", ("completed" if ok else "rejected", w_id))
    conn.commit()
    await call.answer("OK")
    try:
        if ok:
            await bot.send_message(row[0], f"✅ Вывод <b>{row[3]}</b> выполнен!\nСредства отправлены.\nСпасибо, что пользуетесь {BOT_NAME}.", parse_mode="HTML")
            await call.message.edit_caption(caption=f"✅ ВЫВОД #{w_id} ГОТОВ")
        else:
            await bot.send_message(row[0], f"❌ Вывод {row[3]} отклонён.")
            await call.message.edit_caption(caption=f"❌ ВЫВОД #{w_id} ОТКЛОНЁН")
    except Exception: pass

@dp.message(F.text.in_({"👤 Поддержка", "Поддержка"}))
async def support_start(message: types.Message, state: FSMContext):
    await message.answer(
        f"{E['support']} <b>Поддержка {BOT_NAME}</b>\n\n"
        f"{E['write']} Напишите ваше сообщение или вопрос прямо в бота (текст / фото).",
        parse_mode="HTML", reply_markup=kb_support())

@dp.callback_query(F.data == "support_bot")
async def support_bot_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(Support.msg)
    await call.message.answer(
        f"👤 Напишите вопрос текстом или отправьте фото.",
        reply_markup=kb_back())

@dp.message(Support.msg)
async def support_msg(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    photo = message.photo[-1].file_id if message.photo else None
    text = (message.caption or message.text or "").strip() or "📎 Фото"
    uid = message.from_user.id
    uname = message.from_user.username or ""
    ensure_user(uid, uname, message.from_user.full_name or "")
    cur.execute("""INSERT INTO tickets (user_id,username,message,photo_id,status,created_at)
           VALUES (?,?,?,?,'new',?)""", (uid, uname, text, photo, now_kg().strftime("%d.%m.%Y %H:%M")))
    tid = cur.lastrowid
    conn.commit()
    await state.clear()
    cap = f"🆘 <b>Обращение #{tid}</b>\n👤 {label(uid)}\n💬 {text}"
    await notify_admins(text=cap, photo=photo, reply_markup=kb_ticket(tid))
    await message.answer(f"✅ Обращение <b>#{tid}</b> принято.", parse_mode="HTML", reply_markup=kb_main(message.from_user.id))

@dp.callback_query(F.data.startswith("tkt_"))
async def tkt_cb(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет прав", show_alert=True); return
    parts = call.data.split("_")
    action, tid = parts[1], int(parts[2])
    cur.execute("SELECT user_id FROM tickets WHERE id=?", (tid,))
    row = cur.fetchone()
    if not row:
        await call.answer("Не найдено"); return
    uid = row[0]
    if action == "work":
        cur.execute("UPDATE tickets SET status='work' WHERE id=?", (tid,)); conn.commit()
        await call.answer("В работе")
        try: await bot.send_message(uid, f"⏳ Обращение #{tid} в работе.")
        except Exception: pass
    elif action == "close":
        cur.execute("UPDATE tickets SET status='closed' WHERE id=?", (tid,)); conn.commit()
        await call.answer("Закрыто")
        try: await bot.send_message(uid, f"✅ Обращение #{tid} закрыто.")
        except Exception: pass
    elif action == "reply":
        await state.set_state(AdminReply.text)
        await state.update_data(reply_tid=tid)
        await call.answer()
        await call.message.answer(f"Ответ для #{tid}:")

@dp.message(AdminReply.text)
async def admin_reply(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    tid = data.get("reply_tid")
    cur.execute("SELECT user_id FROM tickets WHERE id=?", (tid,))
    row = cur.fetchone()
    await state.clear()
    if not row:
        await message.answer("Не найдено"); return
    cur.execute("UPDATE tickets SET status='work' WHERE id=?", (tid,)); conn.commit()
    try:
        await bot.send_message(row[0], f"💬 <b>Ответ оператора</b> (#{tid})\n\n{message.text}", parse_mode="HTML")
        await message.answer("✅ Отправлено")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(F.text.in_({"📖 Инструкция", "Инструкция"}))
async def instruction(message: types.Message):
    await message.answer(
        f"{E['web']} <b>Инструкция {BOT_NAME}</b>\n\n"
        f"{E['money']} <b>Пополнение</b>\n1. Пополнить → DEPOSIT ID ({PLATFORM})\n"
        f"2. Сумма → O! Bank → скрин чека\n\n"
        f"{E['withdraw']} <b>Вывод</b>\n"
        f"📍Заходим👇\n"
        f"📍1. Настройки!\n"
        f"📍2. Вывести со счета!\n"
        f"📍3. Mobcash\n"
        f"📍4. Сумму для Вывода!\n"
        f"Город: <b>Бишкек</b>\n"
        f"Улица: <b>SomPayKG 24/7</b>\n"
        f"📍5. Подтвердить\n"
        f"📍6. Получить Код!\n"
        f"📍7. Отправить его в бота\n\n"
        f"{E['support']} <b>Поддержка</b> — кнопка «👤 Поддержка» в меню",
        parse_mode="HTML", reply_markup=kb_main(message.from_user.id))

@dp.message(Command("admin"))
@dp.message(F.text.in_({"⚙️ Admin", "Admin"}))
async def admin_cmd(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа"); return
    await state.clear()
    admins_list = ", ".join(f"<code>{a}</code>" for a in get_admins())
    await message.answer(
        f"{E['admin']} <b>Панель администратора</b>\n\n"
        f"Команда: /admin\n"
        f"ID: <code>{message.from_user.id}</code>\n"
        f"Админы: {admins_list}\n"
        f"Бот: {'🟢 Вкл' if bot_on() else '🔴 Выкл'}",
        reply_markup=kb_admin(), parse_mode="HTML")

@dp.message(F.text.in_({"➕ Админ", "Админ"}))
async def admin_add_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(AdminAdd.uid)
    await message.answer("ID нового администратора:", reply_markup=kb_back())

@dp.message(AdminAdd.uid)
async def admin_add_do(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    try:
        new_id = int((message.text or "").strip())
        add_admin(new_id)
        await state.clear()
        await message.answer(f"✅ Админ <code>{new_id}</code> добавлен!", reply_markup=kb_admin(), parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Некорректный ID!")

@dp.message(F.text.in_({"➖ Удалить админа", "Удалить админа"}))
async def admin_del_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Только главный админ."); return
    await state.set_state(AdminDel.uid)
    await message.answer("ID для удаления:", reply_markup=kb_back())

@dp.message(AdminDel.uid)
async def admin_del_do(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    try:
        del_id = int((message.text or "").strip())
        if del_id == ADMIN_ID:
            await message.answer("❌ Нельзя удалить главного!", reply_markup=kb_admin()); return
        remove_admin(del_id)
        await state.clear()
        await message.answer(f"✅ Админ <code>{del_id}</code> удалён!", reply_markup=kb_admin(), parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Некорректный ID!")

@dp.message(F.text == "📋 Заявки")
async def admin_deps(message: types.Message):
    if not is_admin(message.from_user.id): return
    cur.execute("SELECT id, code, user_id, amount, platform, account_id, photo_id FROM deposits WHERE status='pending' ORDER BY id DESC LIMIT 20")
    rows = cur.fetchall()
    if not rows:
        await message.answer("Нет активных заявок."); return
    for dep_id, code, uid, amount, platform, acc, photo in rows:
        cap = f"🔥 <b>#{dep_id}</b> · <code>{code}</code>\n👤 {label(uid)}\n💵 {amount:.2f}\n🆔 {platform} | <code>{acc}</code>"
        try:
            if photo:
                await bot.send_photo(message.chat.id, photo, caption=cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
            else:
                await message.answer(cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
        except Exception:
            await message.answer(cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")

@dp.message(F.text == "📩 Обращения")
async def admin_tickets(message: types.Message):
    if not is_admin(message.from_user.id): return
    cur.execute("SELECT id, user_id, message, photo_id, status, created_at FROM tickets WHERE status!='closed' ORDER BY id DESC LIMIT 15")
    rows = cur.fetchall()
    if not rows:
        await message.answer("Нет открытых обращений."); return
    for tid, uid, msg, photo, status, created in rows:
        cap = f"🆘 #{tid} · {status}\n👤 {label(uid)}\n📅 {created}\n💬 {msg[:400]}"
        try:
            if photo:
                await bot.send_photo(message.chat.id, photo, caption=cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
            else:
                await message.answer(cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
        except Exception:
            await message.answer(cap, reply_markup=kb_ticket(tid), parse_mode="HTML")

@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id): return
    cur.execute("SELECT COUNT(*) FROM users"); users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'"); pending = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status='approved'"); total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tickets WHERE status='new'"); tickets = cur.fetchone()[0]
    await message.answer(
        f"{E['stats']} <b>СТАТИСТИКА</b>\n\n👥 Пользователей: <b>{users}</b>\n⏳ В очереди: <b>{pending}</b>\n"
        f"🆘 Новых обращений: <b>{tickets}</b>\n{E['cash']} Объём: <b>{total:.2f} KGS</b>", parse_mode="HTML")

@dp.message(F.text == "📢 Рассылка")
async def bc_start(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.set_state(Broadcast.content)
    await message.answer("Отправьте текст или фото с подписью для рассылки:")

@dp.message(Broadcast.content)
async def bc_send(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await state.clear()
    cur.execute("SELECT user_id FROM users")
    users = [r[0] for r in cur.fetchall()]
    ok = 0
    photo = message.photo[-1].file_id if message.photo else None
    text = message.caption or message.text or ""
    for uid in users:
        try:
            if photo: await bot.send_photo(uid, photo, caption=text, parse_mode="HTML")
            elif text: await bot.send_message(uid, text, parse_mode="HTML")
            ok += 1
        except Exception: pass
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Рассылка: {ok}/{len(users)}", reply_markup=kb_admin())

@dp.message(F.text.in_({"🔴 ВЫКЛ", "🟢 ВКЛ"}))
async def admin_toggle(message: types.Message):
    if not is_admin(message.from_user.id): return
    on = "ВКЛ" in (message.text or "")
    set_bot(on)
    await message.answer(f"{'🟢' if on else '🔴'} Бот {'ВКЛЮЧЕН' if on else 'ВЫКЛЮЧЕН'}", reply_markup=kb_admin())

@dp.errors()
async def on_error(event: ErrorEvent):
    exc = event.exception
    update = event.update
    log.exception("Handler error: %s | update=%s", exc, getattr(update, "update_id", None))

    if isinstance(exc, TelegramRetryAfter):
        log.warning("Flood wait %s sec", exc.retry_after)
        await asyncio.sleep(exc.retry_after)
        return True

    if isinstance(exc, (TelegramForbiddenError, TelegramBadRequest)):
        return True

    if isinstance(exc, TelegramNetworkError):
        log.warning("Network error: %s", exc)
        return True

    chat_id = None
    try:
        if update.message:
            chat_id = update.message.chat.id
        elif update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id
    except Exception:
        pass

    if chat_id:
        try:
            await bot.send_message(
                chat_id,
                "❌ Произошла ошибка. Попробуйте /start или напишите в поддержку.",
                parse_mode="HTML",
            )
        except Exception:
            pass
    return True

async def main():
    while True:
        try:
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                log.info("webhook deleted")
            except Exception as e:
                log.warning(f"delete_webhook: {e}")
            log.info(f"{BOT_NAME} start | admins={ADMIN_IDS}")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except TelegramNetworkError as e:
            log.error("Polling network error: %s — retry in 5s", e)
            await asyncio.sleep(5)
        except Exception as e:
            log.exception("Polling crashed: %s — restart in 5s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped by user")
    except Exception as e:
        log.exception("Fatal: %s", e)
        raise
