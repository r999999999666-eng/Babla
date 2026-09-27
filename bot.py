import asyncio
import logging
import os
import random
import string
import sqlite3
import time
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

def _token() -> str:
    for k in ("TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN"):
        v = (os.environ.get(k) or "").strip().strip('"').strip("'")
        if len(v) >= 40 and ":" in v:
            return v
    return ""

BOT_TOKEN = _token()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8992968778"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@DiamondPAY_News").strip()
CHANNEL_URL = os.environ.get("CHANNEL_LINK", "https://t.me/DiamondPAY_News").strip()
SUPPORT_USER = os.environ.get("SUPPORT_USER", "@DiamondPAY_HELP")
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111258120233520910129965023532261202111302123408%D0%9D%D0%A3%D0%A0%D0%AD%D0%9B%20%D0%9A.520473995303417540105906O%21Bank63044CEE",
)
BOT_NAME = "DiamondPAY"
MIN_DEPOSIT = 100
MAX_DEPOSIT = 500_000
REF_PERCENT = 2.5
MIN_REF = 500
TZ = ZoneInfo("Asia/Bishkek")

def now_kg() -> datetime:
    return datetime.now(TZ)

def code_gen(n: int = 5) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def pe(eid: str, fb: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'

E = {
    "rocket": pe("5188481279963715781", "🚀"),
    "check": pe("6273749318717412886", "✅"),
    "money": pe("5224257782013769471", "💰"),
    "lock": "🔒",
    "wave": "👋",
}

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
""")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_active', '1')")
conn.commit()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise SystemExit("TOKEN missing. Set Env TOKEN=123456:AAH... on Render.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

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

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID

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

def greet(name: str) -> str:
    h = now_kg().hour
    if 5 <= h < 12: g = "Доброе утро"
    elif 12 <= h < 17: g = "Добрый день"
    elif 17 <= h < 23: g = "Добрый вечер"
    else: g = "Доброй ночи"
    return f"{g}, {name}! {E['wave']}"

async def subscribed(uid: int) -> bool:
    if is_admin(uid) or not CHANNEL_USERNAME:
        return True
    try:
        m = await bot.get_chat_member(CHANNEL_USERNAME, uid)
        return m.status in ("creator", "administrator", "member", "restricted")
    except Exception as e:
        log.warning(f"sub: {e}")
        return True

def kb_sub():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить", callback_data="check_sub")],
    ])

def kb_main():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Пополнить"), KeyboardButton(text="💰 Вывести")],
        [KeyboardButton(text="👤 Поддержка"), KeyboardButton(text="📖 Инструкция")],
        [KeyboardButton(text="🤝 Пригласить друга")],
    ], resize_keyboard=True)

def kb_admin():
    on = bot_on()
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📋 Заявки"), KeyboardButton(text="📩 Обращения")],
        [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="🟢 ВКЛ" if not on else "🔴 ВЫКЛ")],
        [KeyboardButton(text="🔙 Главное меню")],
    ], resize_keyboard=True)

def kb_platform(prefix: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ 1xBet", callback_data=f"{prefix}_1x"),
         InlineKeyboardButton(text="2️⃣ Melbet", callback_data=f"{prefix}_mel")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

def kb_amounts():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="200", callback_data="amt_200"),
         InlineKeyboardButton(text="500", callback_data="amt_500")],
        [InlineKeyboardButton(text="1000", callback_data="amt_1000"),
         InlineKeyboardButton(text="2000", callback_data="amt_2000")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

def kb_banks():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="MBank", url=PAY_LINK),
         InlineKeyboardButton(text="O! Bank", url=PAY_LINK)],
        [InlineKeyboardButton(text="BakAI", url=PAY_LINK),
         InlineKeyboardButton(text="MegaPay", url=PAY_LINK)],
        [InlineKeyboardButton(text="DemirBank", url=PAY_LINK)],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])

def kb_ref():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить 1xBet с реф. баланса", callback_data="ref_1x")],
        [InlineKeyboardButton(text="Пополнить Melbet с реф. баланса", callback_data="ref_mel")],
        [InlineKeyboardButton(text="Вывести реф. баланс", callback_data="ref_out")],
        [InlineKeyboardButton(text="Главное меню", callback_data="main_menu")],
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

def kb_refmod(rid: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Зачислено", callback_data=f"refok_{rid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"refno_{rid}"),
    ]])

def kb_ticket(tid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 В работу", callback_data=f"tkt_work_{tid}"),
         InlineKeyboardButton(text="💬 Ответить", callback_data=f"tkt_reply_{tid}")],
        [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"tkt_close_{tid}")],
    ])

def kb_back():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Главное меню")]], resize_keyboard=True)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    uname = message.from_user.username or ""
    name = message.from_user.full_name or message.from_user.first_name or ""
    ref = None
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try: ref = int(parts[1].replace("ref_", "", 1))
        except ValueError: pass
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    is_new = cur.fetchone() is None
    ensure_user(uid, uname, name, ref)
    if is_new and ref and ref != uid:
        await message.answer("✅ Приглашение принято.\n\nПосле ваших пополнений пригласивший получит бонус по программе «Пригласи друга».")
    if not bot_on() and not is_admin(uid):
        await message.answer("❌ Бот временно отключён.")
        return
    if not await subscribed(uid):
        await message.answer(
            f"👋 Добро пожаловать в <b>{BOT_NAME}</b>!\n\n"
            f"Чтобы продолжить, подпишитесь на наш официальный канал <b>{CHANNEL_USERNAME}</b>. "
            f"Там публикуются новости и обновления сервиса.\n\nПосле подписки нажмите «Проверить».",
            reply_markup=kb_sub(), parse_mode="HTML")
        return
    await show_main(message)

@dp.callback_query(F.data == "check_sub")
async def cb_sub(call: types.CallbackQuery):
    if await subscribed(call.from_user.id):
        try: await call.message.delete()
        except Exception: pass
        await call.message.answer("✅ Подписка подтверждена!")
        await show_main(call.message)
    else:
        await call.answer("Вы ещё не подписались на канал!", show_alert=True)

@dp.callback_query(F.data.in_({"main_menu", "cancel"}))
async def cb_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show_main(call.message)

async def show_main(message: types.Message):
    name = getattr(message.from_user, "first_name", None) or "друг"
    text = (
        f"{greet(name)}\n\n"
        f"{E['rocket']} Пополнение и выводы работают стабильно\n"
        f"{E['check']} Актуально на: {now_kg().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"{E['money']} Комиссия: <b>0%</b>\n"
        f"{E['lock']} Все ваши транзакции защищены\n"
        f"🕐 Работаем <b>24/7</b>\n\n"
        f"Выберите нужное действие ниже."
    )
    await message.answer(text, reply_markup=kb_main(), parse_mode="HTML")

@dp.message(F.text == "🔙 Главное меню")
async def back_main(message: types.Message, state: FSMContext):
    await state.clear()
    await show_main(message)

@dp.message(F.text.in_({"💎 Пополнить", "📥 Пополнить", "Пополнить"}))
async def dep_start(message: types.Message, state: FSMContext):
    if not await subscribed(message.from_user.id):
        await message.answer("Сначала подпишитесь на канал.", reply_markup=kb_sub())
        return
    if not bot_on() and not is_admin(message.from_user.id):
        await message.answer("Бот на обслуживании.")
        return
    await state.set_state(Dep.platform)
    await message.answer("<b>Пополнение счёта</b>\n\nВыберите букмекера:", reply_markup=kb_platform("dep"), parse_mode="HTML")

@dp.callback_query(F.data.in_({"dep_1x", "dep_mel"}))
async def dep_plat(call: types.CallbackQuery, state: FSMContext):
    platform = "1xBet" if call.data == "dep_1x" else "Melbet"
    await state.update_data(platform=platform)
    await state.set_state(Dep.account)
    await call.answer()
    sample = random.randint(100000000, 999999999)
    await call.message.answer(
        f"<b>ПОПОЛНЕНИЕ СЧЁТА</b> <code>{sample}</code>\n"
        f"<i>Типы систем · Методы по GEO-локации</i>\n\n"
        f"💳 Введите номер счёта, на который вы вносите средства.\n\n"
        f"Это ваш <b>DEPOSIT ID</b> ({platform}). Он состоит только из цифр.",
        parse_mode="HTML", reply_markup=kb_back())

@dp.message(Dep.account)
async def dep_acc(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    acc = (message.text or "").strip()
    if not acc.isdigit():
        await message.answer("⚠️ DEPOSIT ID только из цифр. Попробуйте снова:")
        return
    await state.update_data(account_id=acc)
    await state.set_state(Dep.amount)
    await message.answer(
        f"✅ ID принят: <code>{acc}</code>\n\n"
        f"Проверьте цифры: предварительная проверка аккаунта временно отключена.\n\n"
        f"Теперь введите сумму пополнения только цифрами или выберите кнопку ({MIN_DEPOSIT}–{MAX_DEPOSIT}):",
        reply_markup=kb_amounts(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("amt_"))
async def dep_amt_btn(call: types.CallbackQuery, state: FSMContext):
    amount = float(call.data.replace("amt_", ""))
    final = round(amount + random.randint(10, 99) / 100.0, 2)
    await call.answer()
    await send_pay(call.message, state, final)

@dp.message(Dep.amount)
async def dep_amt_txt(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear(); await show_main(message); return
    try: base = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("⚠️ Введите число!"); return
    if not (MIN_DEPOSIT <= base <= MAX_DEPOSIT):
        await message.answer(f"⚠️ От {MIN_DEPOSIT} до {MAX_DEPOSIT}"); return
    final = round(base + random.randint(10, 99) / 100.0, 2)
    await send_pay(message, state, final)

async def send_pay(message: types.Message, state: FSMContext, amount: float):
    await state.update_data(amount=amount)
    await state.set_state(Dep.receipt)
    await message.answer(
        f"💳 <b>К оплате: {amount:.2f} KGS</b>\n\n"
        f"⚠️ Реквизиты актуальны в течение <b>5 минут</b>.\n"
        f"Выберите банк ниже и оплатите по ссылке.\n\n"
        f"🧾 После оплаты отправьте, пожалуйста, <b>скриншот чека</b>.\n\n"
        f"⏳ До окончания оплаты: 05:00",
        reply_markup=kb_banks(), parse_mode="HTML")

@dp.message(Dep.receipt, F.photo | F.document)
async def dep_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    platform = data.get("platform", "1xBet")
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
        f"✅ Ваша заявка <b>{c}</b> принята на проверку!\n\n"
        f"🆔 ID {platform}: <code>{acc}</code>\n"
        f"💵 Сумма: <b>{amount:.2f} KGS</b>\n"
        f"💰 Комиссия: <b>0%</b>\n\n"
        f"⚠️ Пополнение занимает от 5 секунд до 15 минут\n\n"
        f"Пожалуйста подождите!\n\n"
        f"✅ Вы получите уведомление о зачислении средств!\n\n"
        f"Если возникли проблемы 👇\n👨‍💻 Оператор: {SUPPORT_USER}",
        parse_mode="HTML", reply_markup=kb_back())
    progress = await message.answer("⏳ 10%")
    for p in (20, 30, 40, 50):
        await asyncio.sleep(0.5)
        try: await progress.edit_text(f"⏳ {p}%")
        except Exception: break
    cap = f"🔥 <b>ЗАЯВКА #{dep_id}</b> · <code>{c}</code>\n\n👤 {label(uid)}\n💵 <b>{amount:.2f} KGS</b>\n🆔 {platform} | <code>{acc}</code>"
    try:
        await bot.send_photo(ADMIN_ID, photo, caption=cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
    except Exception:
        await bot.send_message(ADMIN_ID, cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
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
                f"✅ <b>Баланс успешно пополнен!</b>\n\n💵 <b>{amount:.2f} KGS</b>\n"
                f"🆔 {platform} | <code>{acc}</code>\n⏱ {elapsed} сек\n\nСпасибо, что выбрали <b>{BOT_NAME}</b>!",
                parse_mode="HTML")
        except Exception: pass
        cur.execute("SELECT referrer_id FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if r and r[0]:
            bonus = round(float(amount) * REF_PERCENT / 100.0, 2)
            if bonus > 0:
                cur.execute("UPDATE users SET ref_balance=COALESCE(ref_balance,0)+? WHERE user_id=?", (bonus, r[0]))
                conn.commit()
                try:
                    await bot.send_message(r[0],
                        f"🎁 Вам начислен реферальный бонус: <b>{bonus:.2f} KGS</b>\n\nДруг пополнил: <b>{amount:.2f} KGS</b>",
                        parse_mode="HTML")
                except Exception: pass
        try: await call.message.edit_caption(caption=f"✅ #{dep_id} {code} ОДОБРЕНА")
        except Exception: pass
    else:
        try: await bot.send_message(uid, f"❌ Заявка {code} на {amount:.2f} KGS отклонена.\nОператор: {SUPPORT_USER}")
        except Exception: pass
        try: await call.message.edit_caption(caption=f"❌ #{dep_id} {code} ОТКЛОНЕНА")
        except Exception: pass

@dp.message(F.text.in_({"💰 Вывести", "📤 Вывести", "Вывести"}))
async def wd_start(message: types.Message, state: FSMContext):
    if not await subscribed(message.from_user.id):
        await message.answer("Сначала подпишитесь на канал.", reply_markup=kb_sub()); return
    if not bot_on() and not is_admin(message.from_user.id):
        await message.answer("Бот на обслуживании."); return
    await state.set_state(Wd.platform)
    await message.answer("📤 <b>Вывод средств</b>\n\nВыберите букмекера:", reply_markup=kb_platform("wd"), parse_mode="HTML")

@dp.callback_query(F.data.in_({"wd_1x", "wd_mel"}))
async def wd_plat(call: types.CallbackQuery, state: FSMContext):
    platform = "1xBet" if call.data == "wd_1x" else "Melbet"
    await state.update_data(platform=platform)
    await state.set_state(Wd.qr)
    await call.answer()
    await call.message.answer("📤 Отправьте <b>фото QR</b> кошелька (ELQR / банк):", parse_mode="HTML")

@dp.message(Wd.qr, F.photo | F.document)
async def wd_qr(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else message.document.file_id
    data = await state.get_data()
    await state.update_data(qr_file_id=fid)
    await state.set_state(Wd.account)
    await message.answer(f"Введите ID <b>{data.get('platform','1xBet')}</b>:", parse_mode="HTML")

@dp.message(Wd.qr)
async def wd_qr_bad(message: types.Message):
    await message.answer("Нужно фото QR!")

@dp.message(Wd.account)
async def wd_acc(message: types.Message, state: FSMContext):
    acc = (message.text or "").strip()
    if not acc:
        await message.answer("Введите ID!"); return
    data = await state.get_data()
    platform = data.get("platform", "1xBet")
    await state.update_data(account_id=acc)
    await state.set_state(Wd.code)
    await message.answer(
        f"📍 <b>Инструкция по выводу · {platform}</b>\n\n"
        f"1. Настройки → Вывести со счёта\n2. Способ: <b>MOBCASH / LMWPAY</b>\n"
        f"3. Укажите сумму\n4. Город: <b>Бишкек</b>\n5. Улица: <b>DiamondPAY KG</b>\n"
        f"6. Подтвердите → получите код\n7. Отправьте код в этот бот",
        parse_mode="HTML")

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
    try:
        await bot.send_photo(ADMIN_ID, data.get("qr_file_id"), caption=cap, reply_markup=kb_wd(w_id), parse_mode="HTML")
    except Exception:
        await bot.send_message(ADMIN_ID, cap, reply_markup=kb_wd(w_id), parse_mode="HTML")
    await state.clear()
    await message.answer(f"✅ Заявка <b>{c}</b> на вывод принята!\n\nОжидайте выплаты.", parse_mode="HTML", reply_markup=kb_main())

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

@dp.message(F.text.in_({"🤝 Пригласить друга", "Пригласить друга"}))
async def show_ref(message: types.Message):
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    bal = ref_bal(uid)
    cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (uid,))
    friends = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*), COALESCE(SUM(d.amount),0) FROM deposits d
           JOIN users u ON u.user_id=d.user_id WHERE u.referrer_id=? AND d.status='approved'""", (uid,))
    cnt, ssum = cur.fetchone()
    text = (
        f"🤝 <b>Пригласи друга</b>\n\nВаша персональная ссылка:\n<code>{link}</code>\n\n"
        f"За каждое принятое пополнение приглашённого друга начисляется <b>{REF_PERCENT}%</b>.\n\n"
        f"👥 Приглашено друзей: <b>{friends}</b>\n✅ Пополнений друзей: <b>{cnt}</b>\n"
        f"💵 Сумма пополнений друзей: <b>{ssum:.2f} KGS</b>\n🎁 Доступный баланс: <b>{bal:.2f} KGS</b>\n\n"
        f"Минимальная сумма пополнения или вывода: <b>{MIN_REF} KGS</b>."
    )
    await message.answer(text, reply_markup=kb_ref(), parse_mode="HTML")

@dp.callback_query(F.data.in_({"ref_1x", "ref_mel", "ref_out"}))
async def ref_act(call: types.CallbackQuery, state: FSMContext):
    bal = ref_bal(call.from_user.id)
    if bal < MIN_REF:
        await call.answer()
        await call.message.answer(
            f"Недостаточно средств на реферальном балансе.\n\nДоступно: <b>{bal:.2f} KGS</b>\n"
            f"Минимальная сумма операции: <b>{MIN_REF} KGS</b>.", parse_mode="HTML")
        return
    await call.answer()
    if call.data == "ref_out":
        await state.set_state(RefOut.qr)
        await call.message.answer("📤 Вывод реферального баланса\n\nОтправьте QR-код вашего банка скриншотом.")
        return
    platform = "1xBet" if call.data == "ref_1x" else "Melbet"
    await state.update_data(ref_platform=platform)
    await state.set_state(RefOut.target)
    await call.message.answer(f"Введите ID <b>{platform}</b>:", parse_mode="HTML")

@dp.message(RefOut.qr, F.photo | F.document)
async def ref_qr(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else message.document.file_id
    await state.update_data(qr_file_id=fid)
    await state.set_state(RefOut.amount)
    bal = ref_bal(message.from_user.id)
    await message.answer(
        f"Введите сумму с реферального баланса только цифрами.\n\nДоступно: <b>{bal:.2f} KGS</b>\n"
        f"Минимальная сумма: <b>{MIN_REF} KGS</b>.", parse_mode="HTML")

@dp.message(RefOut.amount)
async def ref_amount(message: types.Message, state: FSMContext):
    try: amt = float((message.text or "").replace(",", "."))
    except ValueError:
        await message.answer("Введите число!"); return
    uid = message.from_user.id
    bal = ref_bal(uid)
    if amt < MIN_REF or amt > bal:
        await message.answer(f"Недопустимая сумма.\nДоступно: {bal:.2f}\nМин: {MIN_REF}"); return
    data = await state.get_data()
    c = code_gen()
    cur.execute("UPDATE users SET ref_balance=COALESCE(ref_balance,0)-? WHERE user_id=?", (amt, uid))
    cur.execute("""INSERT INTO ref_outs (code,user_id,amount,platform,target,qr_file_id,status,created_at)
           VALUES (?,?,?,'QR','QR',?,'pending',?)""",
                (c, uid, amt, data.get("qr_file_id"), now_kg().strftime("%d.%m.%Y %H:%M")))
    rid = cur.lastrowid
    conn.commit()
    await state.clear()
    await message.answer(
        f"✅ Заявка <b>{c}</b> на вывод создана.\n\n💵 Списано: <b>{amt:.2f} KGS</b>\n"
        f"🎁 Остаток: <b>{ref_bal(uid):.2f} KGS</b>\n\nПосле перевода оператор подтвердит заявку.",
        parse_mode="HTML", reply_markup=kb_main())
    try:
        await bot.send_photo(ADMIN_ID, data.get("qr_file_id"),
            caption=f"🎁 РЕФКА QR #{rid} · {c}\n👤 {label(uid)}\n💵 {amt:.2f} KGS",
            reply_markup=kb_refmod(rid), parse_mode="HTML")
    except Exception: pass

@dp.message(RefOut.target)
async def ref_target(message: types.Message, state: FSMContext):
    target = (message.text or "").strip()
    if not target:
        await message.answer("Введите ID!"); return
    data = await state.get_data()
    platform = data.get("ref_platform", "1xBet")
    uid = message.from_user.id
    bal = ref_bal(uid)
    if bal < MIN_REF:
        await message.answer("Недостаточно средств."); await state.clear(); return
    amt = bal
    c = code_gen()
    cur.execute("UPDATE users SET ref_balance=0 WHERE user_id=?", (uid,))
    cur.execute("""INSERT INTO ref_outs (code,user_id,amount,platform,target,status,created_at)
           VALUES (?,?,?,?,?,'pending',?)""",
                (c, uid, amt, platform, target, now_kg().strftime("%d.%m.%Y %H:%M")))
    rid = cur.lastrowid
    conn.commit()
    await state.clear()
    await bot.send_message(ADMIN_ID,
        f"🎁 РЕФКА #{rid} · {c}\n👤 {label(uid)}\n💵 {amt:.2f}\n🆔 {platform} | <code>{target}</code>",
        reply_markup=kb_refmod(rid), parse_mode="HTML")
    await message.answer(f"✅ Заявка <b>{c}</b> создана.\n💵 {amt:.2f} KGS → {platform} <code>{target}</code>",
                         parse_mode="HTML", reply_markup=kb_main())

@dp.callback_query(F.data.startswith("refok_") | F.data.startswith("refno_"))
async def ref_mod(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет прав", show_alert=True); return
    ok = call.data.startswith("refok_")
    rid = int(call.data.split("_")[-1])
    cur.execute("SELECT user_id, amount, status, code FROM ref_outs WHERE id=?", (rid,))
    row = cur.fetchone()
    if not row or row[2] != "pending":
        await call.answer("Уже обработано"); return
    cur.execute("UPDATE ref_outs SET status=? WHERE id=?", ("done" if ok else "rejected", rid))
    if not ok:
        cur.execute("UPDATE users SET ref_balance=COALESCE(ref_balance,0)+? WHERE user_id=?", (row[1], row[0]))
    conn.commit()
    await call.answer("OK")
    try:
        if ok:
            await bot.send_message(row[0], f"✅ Вывод успешно принят!\nСредства отправлены на ваш банк.\nСпасибо, что пользуетесь {BOT_NAME}.")
        else:
            await bot.send_message(row[0], f"❌ Рефка {row[3]} отклонена, сумма возвращена.")
    except Exception: pass

@dp.message(F.text.in_({"👤 Поддержка", "Поддержка"}))
async def support_start(message: types.Message, state: FSMContext):
    await state.set_state(Support.msg)
    await message.answer(
        f"👤 <b>Поддержка {BOT_NAME}</b>\n\nНапишите вопрос текстом или отправьте фото.\nОператор: {SUPPORT_USER}",
        parse_mode="HTML", reply_markup=kb_back())

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
    try:
        if photo:
            await bot.send_photo(ADMIN_ID, photo, caption=cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
        else:
            await bot.send_message(ADMIN_ID, cap, reply_markup=kb_ticket(tid), parse_mode="HTML")
    except Exception: pass
    await message.answer(f"✅ Обращение <b>#{tid}</b> принято.", parse_mode="HTML", reply_markup=kb_main())

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
        f"📖 <b>Инструкция {BOT_NAME}</b>\n\n"
        f"<b>Пополнение</b>\n1. 💎 Пополнить → 1xBet / Melbet\n2. DEPOSIT ID → сумма → банк → чек\n\n"
        f"<b>Вывод</b>\n1. 💰 Вывести → букмекер → QR → ID → код\nГород: <b>Бишкек</b> · Улица: <b>DiamondPAY KG</b>\n\n"
        f"<b>Рефералы</b> — {REF_PERCENT}%, от {MIN_REF} KGS\n<b>Поддержка</b> — в боте или {SUPPORT_USER}",
        parse_mode="HTML", reply_markup=kb_main())

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа"); return
    await state.clear()
    await message.answer(
        f"💻 <b>Панель администратора</b>\n\nID: <code>{message.from_user.id}</code>\n"
        f"Канал: {CHANNEL_USERNAME}\nБот: {'🟢 Вкл' if bot_on() else '🔴 Выкл'}",
        reply_markup=kb_admin(), parse_mode="HTML")

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
        f"📈 <b>СТАТИСТИКА</b>\n\n👥 Пользователей: <b>{users}</b>\n⏳ В очереди: <b>{pending}</b>\n"
        f"🆘 Новых обращений: <b>{tickets}</b>\n💵 Объём: <b>{total:.2f} KGS</b>", parse_mode="HTML")

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

async def main():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("webhook deleted")
    except Exception as e:
        log.warning(f"delete_webhook: {e}")
    log.info(f"{BOT_NAME} start | admin={ADMIN_ID} | channel={CHANNEL_USERNAME}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
