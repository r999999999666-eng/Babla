import os
import sqlite3
import time
import threading
import html
import random
import logging
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

TZ_KG = ZoneInfo("Asia/Bishkek")  # Кыргызстан UTC+6

def now_kg():
    """Текущее время по Кыргызстану (Бишкек)."""
    return datetime.now(TZ_KG)

from flask import Flask, jsonify
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN_REF") or os.environ.get("TOKEN") or "YOUR_TELEGRAM_BOT_TOKEN_HERE"

MAIN_ADMIN = int(os.environ.get("MAIN_ADMIN", "8992968778"))
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1905")
OPERATOR_ID = int(os.environ.get("OPERATOR_ID", "8992968778"))
SUPPORT = os.environ.get("SUPPORT", "")  # например @username оператора

def support_url():
    """Ссылка на чат с оператором-человеком."""
    if SUPPORT and str(SUPPORT).strip():
        u = str(SUPPORT).lstrip("@").strip()
        return f"https://t.me/{u}"
    return f"tg://user?id={OPERATOR_ID}"

BOT_NAME = "DiamondPAY"
MIN_DEPOSIT = 100
MAX_DEPOSIT = 500000
REF_PERCENT = 2.5  # % с пополнения друга
BOT_USERNAME = os.environ.get("BOT_USERNAME", "DiamondPAY_KG_bot").lstrip("@")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "").strip()
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "").strip()
MIN_REF_WITHDRAW = 100  # мин. вывод реф. баланса


def day_greeting(name: str) -> str:
    h = now_kg().hour
    if 5 <= h < 12:
        g = "Доброе утро"
    elif 12 <= h < 17:
        g = "Добрый день"
    elif 17 <= h < 23:
        g = "Добрый вечер"
    else:
        g = "Доброй ночи"
    return f"{g}, {name}! {EMOJI['wave']}"


def tpl_status_line() -> str:
    return f"{EMOJI['check']} Актуально на: {now_kg().strftime('%d.%m.%Y %H:%M')}"


WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111258120233520910129965023532261202111302123408%D0%9D%D0%A3%D0%A0%D0%AD%D0%9B%20%D0%9A.520473995303417540105906O%21Bank63044CEE",
)


def pe(eid, fb):
    """Telegram Premium custom emoji (HTML parse_mode)."""
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


EMOJI = {
    "star":     pe("5379607913046242841", "❄️"),
    "vip":      pe("5400373628950840597", "❄️"),
    "gem":      pe("5399942684817258282", "❄️"),
    "sparkles": pe("5379943126653761268", "❄️"),
    "snow":     pe("5397807437531086888", "❄️"),
    "check":    pe("6273749318717412886", "✅"),
    "cross":    "❌",
    "clock":    pe("5226830214020999125", "⚡️"),
    "fire":     pe("5201945242227472933", "⚡️"),
    "lightning":pe("5201945242227472933", "⚡️"),
    "rocket":   pe("5188481279963715781", "🚀"),
    "zap":      pe("5226830214020999125", "⚡️"),
    "money":    pe("5224257782013769471", "💰"),
    "dollar":   pe("5197434882321567830", "💵"),
    "wallet":   pe("5215420556089776398", "👛"),
    "stats":    pe("5224588661999282075", "💲"),
    "exchange": pe("5377336227533969892", "💱"),
    "deposit":  pe("5224257782013769471", "💰"),
    "withdraw": pe("5201691993775818138", "🛫"),
    "target":   pe("5201732344993576400", "🌐"),
    "info":     pe("5201732344993576400", "🌐"),
    "support":  pe("5472239203590888751", "📩"),
    "broadcast":pe("5472239203590888751", "📩"),
    "admin":    pe("5193177581888755275", "💻"),
    "qr":       pe("5193177581888755275", "💻"),
    "key":      pe("5197269100878907942", "✍️"),
    "write":    pe("5197269100878907942", "✍️"),
    "off": "🔴",
    "on": "🟢",
    "lock": "🔒",
    "wave": "👋",
    "gift": pe("5379943126653761268", "❄️"),
}


bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
app = Flask(__name__)

temp_data = {}
payment_timers = {}
DB_NAME = 'bot.db'


def safe_html(text):
    return html.escape(str(text)) if text else ""


def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=15, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn


def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        chat_id INTEGER PRIMARY KEY, join_date TEXT, balance REAL DEFAULT 0.0,
                        referred_by INTEGER, ref_earned REAL DEFAULT 0.0,
                        username TEXT, full_name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS deposits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
                        account_id TEXT, photo_id TEXT, status TEXT, date TEXT, timestamp INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS qr_codes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdraw_images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS ref_withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER, amount REAL, platform TEXT, account_id TEXT,
                        status TEXT DEFAULT 'pending', date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        username TEXT,
                        message TEXT,
                        photo_id TEXT,
                        status TEXT DEFAULT 'new',
                        created TEXT,
                        updated TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS support_replies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER,
                        from_admin INTEGER,
                        message TEXT,
                        created TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, elqr_photo TEXT,
                        id_photo TEXT, sms_code TEXT, status TEXT, date TEXT)''')
        for col, typ in [
            ("username", "TEXT"),
            ("full_name", "TEXT"),
            ("referred_by", "INTEGER"),
            ("ref_earned", "REAL DEFAULT 0.0"),
        ]:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
            except Exception:
                pass
        try:
            c.execute('ALTER TABLE support_tickets ADD COLUMN photo_id TEXT')
        except Exception:
            pass
        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (MAIN_ADMIN,))
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("bot_active", "True")')
        conn.commit()
    logger.info("База готова")


def is_bot_active():
    with get_db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = "bot_active"').fetchone()
        return True if row is None else row[0] == 'True'


def channel_url():
    if CHANNEL_LINK:
        return CHANNEL_LINK
    if CHANNEL_USERNAME:
        u = CHANNEL_USERNAME.lstrip("@")
        if u.startswith("-100") or u.lstrip("-").isdigit():
            return None
        return f"https://t.me/{u}"
    return None


def is_subscribed(user_id):
    if not CHANNEL_USERNAME:
        return True
    if user_id in get_admins() or user_id == MAIN_ADMIN or user_id == OPERATOR_ID:
        return True
    chat = CHANNEL_USERNAME
    if not str(chat).startswith("@") and not str(chat).startswith("-"):
        chat = "@" + str(chat).lstrip("@")
    try:
        m = bot.get_chat_member(chat, user_id)
        return m.status in ("member", "administrator", "creator", "restricted")
    except Exception as e:
        logger.warning(f"subscribe check {user_id}: {e}")
        return True


def require_subscribe(msg_or_chat):
    if hasattr(msg_or_chat, "chat"):
        chat_id = msg_or_chat.chat.id
        user_id = msg_or_chat.from_user.id
    else:
        chat_id = user_id = msg_or_chat
    if is_subscribed(user_id):
        return True
    kb = types.InlineKeyboardMarkup()
    url = channel_url()
    if url:
        kb.add(types.InlineKeyboardButton("📢 Подписаться на канал", url=url))
    kb.add(ibtn("✅ Я подписался", "check_sub", style="success"))
    send_msg(
        chat_id,
        f"📢 <b>Подписка на канал</b>\n\n"
        f"Чтобы пользоваться {BOT_NAME}, подпишитесь на наш канал.\n"
        f"После подписки нажмите «Я подписался».",
        reply_markup=kb,
    )
    return False


def set_bot_active(status: bool):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("bot_active", ?)', (str(status),))
        conn.commit()


def get_admins():
    with get_db() as conn:
        admins = [r[0] for r in conn.execute('SELECT chat_id FROM admins').fetchall()]
        if MAIN_ADMIN not in admins:
            admins.append(MAIN_ADMIN)
        return list(set(admins))


def add_user(chat_id, referred_by=None, username=None, full_name=None):
    with get_db() as conn:
        exists = conn.execute('SELECT 1 FROM users WHERE chat_id = ?', (chat_id,)).fetchone()
        if not exists:
            ref = None
            if referred_by and int(referred_by) != int(chat_id):
                if conn.execute('SELECT 1 FROM users WHERE chat_id = ?', (int(referred_by),)).fetchone():
                    ref = int(referred_by)
            conn.execute(
                'INSERT INTO users (chat_id, join_date, referred_by, username, full_name) VALUES (?, ?, ?, ?, ?)',
                (chat_id, now_kg().strftime("%d.%m.%Y %H:%M"), ref, username or "", full_name or ""),
            )
            conn.commit()
            return True
        if username is not None or full_name is not None:
            conn.execute(
                'UPDATE users SET username = COALESCE(?, username), full_name = COALESCE(?, full_name) WHERE chat_id = ?',
                (username, full_name, chat_id),
            )
            conn.commit()
        return False


def user_label(user_id):
    with get_db() as conn:
        row = conn.execute(
            'SELECT username, full_name FROM users WHERE chat_id = ?', (user_id,)
        ).fetchone()
    if not row:
        return f"<code>{user_id}</code>"
    uname, fname = row[0] or "", row[1] or ""
    parts = [f"<code>{user_id}</code>"]
    if uname:
        parts.append(f"@{safe_html(uname)}")
    if fname:
        parts.append(safe_html(fname))
    return " · ".join(parts)


def touch_user(msg):
    u = msg.from_user
    add_user(
        u.id,
        username=u.username or "",
        full_name=(u.full_name or u.first_name or ""),
    )


def get_referrer(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT referred_by FROM users WHERE chat_id = ?', (user_id,)).fetchone()
        return row[0] if row and row[0] else None


def add_ref_bonus(referrer_id, bonus, deposit_amount):
    with get_db() as conn:
        conn.execute(
            'UPDATE users SET ref_earned = COALESCE(ref_earned, 0) + ? WHERE chat_id = ?',
            (bonus, referrer_id),
        )
        conn.commit()
    try:
        bot.send_message(
            referrer_id,
            f"🎁 <b>Вам начислен реферальный бонус: {bonus:.2f} KGS</b>\n\n"
            f"Друг пополнил: <b>{deposit_amount:.2f} KGS</b>",
        )
    except Exception as e:
        logger.warning(f"ref notify {referrer_id}: {e}")


def get_ref_balance(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(ref_earned, 0) FROM users WHERE chat_id = ?", (user_id,)
        ).fetchone()
        return float(row[0]) if row else 0.0


def deduct_ref_balance(user_id, amount):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET ref_earned = COALESCE(ref_earned, 0) - ? WHERE chat_id = ?",
            (amount, user_id),
        )
        conn.commit()


def add_ref_withdrawal(user_id, amount, platform, account_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO ref_withdrawals (user_id, amount, platform, account_id, status, date)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (user_id, amount, platform, account_id, now_kg().strftime("%d.%m.%Y %H:%M")),
        )
        wid = c.lastrowid
        conn.commit()
        return wid


def create_ticket(user_id, username, message, photo_id=None):
    now = now_kg().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO support_tickets (user_id, username, message, photo_id, status, created, updated)
               VALUES (?, ?, ?, ?, 'new', ?, ?)""",
            (user_id, username or "", message or "", photo_id, now, now),
        )
        tid = c.lastrowid
        conn.commit()
        return tid


def get_ticket(tid):
    with get_db() as conn:
        return conn.execute("SELECT * FROM support_tickets WHERE id = ?", (tid,)).fetchone()


def set_ticket_status(tid, status):
    now = now_kg().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        conn.execute(
            "UPDATE support_tickets SET status = ?, updated = ? WHERE id = ?",
            (status, now, tid),
        )
        conn.commit()


def add_ticket_reply(tid, from_admin, message):
    now = now_kg().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO support_replies (ticket_id, from_admin, message, created)
               VALUES (?, ?, ?, ?)""",
            (tid, 1 if from_admin else 0, message, now),
        )
        conn.commit()


def list_tickets(status=None, limit=20):
    with get_db() as conn:
        if status:
            return conn.execute(
                "SELECT id, user_id, username, message, status, created FROM support_tickets WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return conn.execute(
            "SELECT id, user_id, username, message, status, created FROM support_tickets ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def notify_operators_ticket(tid, user_id, username, message, photo_id=None):
    uname = f"@{username}" if username else user_label(user_id)
    text = (
        f"🆘 <b>Обращение #{tid}</b>\n"
        f"Статус: <b>Новое</b>\n\n"
        f"👤 {uname}\n"
        f"💬 {safe_html(message) if message else '📎 Фото'}"
    )
    kb = types.InlineKeyboardMarkup()
    kb.row(
        ibtn("В работу", f"tkt_work_{tid}", style="primary"),
        ibtn("Ответить", f"tkt_reply_{tid}", style="success"),
    )
    kb.row(ibtn("Закрыть", f"tkt_close_{tid}", style="danger"))
    targets = set(get_admins())
    targets.add(MAIN_ADMIN)
    targets.add(OPERATOR_ID)
    for oid in targets:
        try:
            if photo_id:
                send_media_bulletproof(oid, photo_id, caption=text, reply_markup=kb)
            else:
                bot.send_message(oid, text, reply_markup=kb)
        except Exception as e:
            logger.warning(f"ticket notify {oid}: {e}")


def get_all_users():
    with get_db() as conn:
        return [r[0] for r in conn.execute('SELECT chat_id FROM users').fetchall()]


def add_admin(chat_id):
    with get_db() as conn:
        conn.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (chat_id,))
        conn.commit()


def remove_admin(chat_id):
    with get_db() as conn:
        conn.execute('DELETE FROM admins WHERE chat_id = ?', (chat_id,))
        conn.commit()


def add_deposit(user_id, amount, account_id, photo_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO deposits (user_id, amount, account_id, photo_id, status, date, timestamp)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, amount, account_id, photo_id, 'pending',
                   now_kg().strftime("%d.%m.%Y %H:%M:%S"), int(time.time())))
        dep_id = c.lastrowid
        conn.commit()
        return dep_id


def update_deposit_status(dep_id, status):
    with get_db() as conn:
        conn.execute('UPDATE deposits SET status = ? WHERE id = ?', (status, dep_id))
        conn.commit()


def add_withdrawal(user_id, elqr, id_photo, code):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO withdrawals (user_id, elqr_photo, id_photo, sms_code, status, date)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (user_id, elqr, id_photo, code, 'pending', now_kg().strftime("%d.%m.%Y %H:%M")))
        w_id = c.lastrowid
        conn.commit()
        return w_id


def get_pending_deposits():
    with get_db() as conn:
        return conn.execute(
            'SELECT id, user_id, amount, account_id, photo_id, date, timestamp FROM deposits WHERE status="pending"'
        ).fetchall()


def save_qr(file_id):
    with get_db() as conn:
        conn.execute('DELETE FROM qr_codes')
        conn.execute('UPDATE deposits SET photo_id = NULL WHERE status = "pending"')
        conn.execute('INSERT INTO qr_codes (file_id, date) VALUES (?, ?)',
                     (file_id, now_kg().strftime("%d.%m.%Y %H:%M")))
        conn.commit()


def get_last_qr():
    with get_db() as conn:
        row = conn.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else None


def save_withdraw_image(file_id):
    with get_db() as conn:
        conn.execute('DELETE FROM withdraw_images')
        conn.execute('INSERT INTO withdraw_images (file_id, date) VALUES (?, ?)',
                     (file_id, now_kg().strftime("%d.%m.%Y %H:%M")))
        conn.commit()


def get_withdraw_image():
    with get_db() as conn:
        row = conn.execute('SELECT file_id FROM withdraw_images ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else None


def get_stats():
    with get_db() as conn:
        c = conn.cursor()
        users = c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        pending = c.execute('SELECT COUNT(*) FROM deposits WHERE status="pending"').fetchone()[0]
        total = c.execute('SELECT SUM(amount) FROM deposits WHERE status="approved"').fetchone()[0] or 0
        return {'users': users, 'pending': pending, 'total': total}


init_db()


def send_msg(chat_id, text, reply_markup=None):
    try:
        return bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"send_msg [{chat_id}]: {e}")
        return None


def send_media_bulletproof(chat_id, file_id, caption=None, reply_markup=None):
    if not file_id:
        return send_msg(chat_id, caption, reply_markup) if caption else None
    try:
        return bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"send_photo failed: {e}")
        try:
            return bot.send_document(chat_id, file_id, caption=caption, reply_markup=reply_markup, parse_mode='HTML')
        except Exception as e2:
            logger.warning(f"send_document failed: {e2}")
            if caption:
                return send_msg(chat_id, caption, reply_markup)
            return None


def cancel_payment(user_id):
    temp_data.pop(user_id, None)
    payment_timers.pop(user_id, None)
    try:
        send_msg(user_id, f"⏳ <b>Время оплаты истекло</b>\n\nЗаявка отменена. Нажмите «💎 Пополнить», чтобы начать снова.")
    except Exception:
        pass


def ibtn(text, callback_data=None, url=None, style=None, icon_id=None):
    kwargs = {"text": text}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if style:
        kwargs["style"] = style
    if icon_id:
        kwargs["icon_custom_emoji_id"] = str(icon_id)
    try:
        return types.InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        kwargs.pop("icon_custom_emoji_id", None)
        return types.InlineKeyboardButton(**kwargs)


def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("💎 Пополнить", "💰 Вывести")
    markup.add("👤 Поддержка", "📖 Инструкция")
    markup.add("🤝 Пригласить друга")
    if user_id in get_admins() or user_id == MAIN_ADMIN:
        markup.add("⚙️ Admin")
    return markup

def reply_main_menu(user_id):
    return main_menu(user_id)


def admin_menu():
    active = is_bot_active()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Заявки", "📩 Обращения")
    markup.add("📈 Статистика")
    markup.add("🖼 Изменить QR", "🖼 Инструкция вывода")
    markup.add("➕ Админ", "➖ Удалить админа")
    markup.add("📢 Рассылка")
    markup.add("🔴 ВЫКЛ" if active else "🟢 ВКЛ")
    markup.add("🔙 Главное меню")
    return markup


def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Назад")
    return markup


def platform_kb():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("1️⃣ 1xBet", "2️⃣ Melbet")
    markup.add("🔙 Назад")
    return markup


@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def check_sub_callback(call):
    bot.answer_callback_query(call.id)
    if is_subscribed(call.from_user.id):
        try:
            bot.edit_message_text(
                f"{EMOJI['check']} Подписка подтверждена! Нажмите /start",
                call.message.chat.id,
                call.message.message_id,
            )
        except Exception:
            pass
        class M:
            pass
        m = M()
        m.chat = call.message.chat
        m.from_user = call.from_user
        m.text = "/start"
        start(m)
    else:
        bot.answer_callback_query(call.id, "Вы ещё не подписаны", show_alert=True)


@bot.message_handler(commands=['start'])
def start(msg):
    chat_id = msg.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    if chat_id in payment_timers:
        try:
            payment_timers[chat_id].cancel()
        except Exception:
            pass
        payment_timers.pop(chat_id, None)
    temp_data[chat_id] = {}

    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(chat_id, f"{EMOJI['off']} <b>Бот временно отключен.</b>")
        return

    if not require_subscribe(msg):
        return

    referred_by = None
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referred_by = int(parts[1].replace("ref_", "", 1))
        except Exception:
            referred_by = None

    add_user(chat_id, referred_by=referred_by,
             username=msg.from_user.username or "",
             full_name=msg.from_user.full_name or msg.from_user.first_name or "")
    name = msg.from_user.first_name or "друг"
    welcome = f"""{day_greeting(name)}

{EMOJI['rocket']} Пополнение и выводы работают стабильно
{tpl_status_line()}

{EMOJI['money']} Комиссия: <b>0%</b>
{EMOJI['key']} Все ваши транзакции защищены
{EMOJI['clock']} Работаем <b>24/7</b>

{EMOJI['target']} Букмекеры: <b>1xBet</b> · <b>Melbet</b>
{EMOJI['dollar']} Мин. пополнение: <b>{MIN_DEPOSIT}</b> KGS
{EMOJI['sparkles']} Реферал: <b>{REF_PERCENT}%</b>

{EMOJI['support']} Поддержка — оператор в боте

Выберите действие ниже 👇"""
    send_msg(chat_id, welcome, reply_markup=main_menu(msg.from_user.id))


@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)


@bot.message_handler(func=lambda m: m.text in ["🤝 Пригласить друга", "🎁 Рефералы", "Рефералы"])
def referral_info(msg):
    add_user(msg.chat.id)
    uid = msg.chat.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    with get_db() as conn:
        bal_row = conn.execute(
            "SELECT COALESCE(ref_earned, 0) FROM users WHERE chat_id = ?", (uid,)
        ).fetchone()
        friends = conn.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by = ?", (uid,)
        ).fetchone()[0]
        dep_stats = conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(d.amount), 0)
               FROM deposits d
               JOIN users u ON u.chat_id = d.user_id
               WHERE u.referred_by = ? AND d.status = 'approved'""",
            (uid,),
        ).fetchone()
    bal = float(bal_row[0]) if bal_row else 0.0
    dep_count = int(dep_stats[0] or 0)
    dep_sum = float(dep_stats[1] or 0)

    text = (
        f"{EMOJI['sparkles']} <b>Пригласи друга</b>\n\n"
        f"Ваша персональная ссылка:\n"
        f"<code>{link}</code>\n\n"
        f"За каждое принятое пополнение приглашённого друга начисляется <b>{REF_PERCENT}%</b>.\n\n"
        f"{EMOJI['vip']} Приглашено друзей: <b>{friends}</b>\n"
        f"{EMOJI['check']} Пополнений друзей: <b>{dep_count}</b>\n"
        f"{EMOJI['dollar']} Сумма пополнений друзей: <b>{dep_sum:.2f} KGS</b>\n"
        f"{EMOJI['money']} Доступный баланс: <b>{bal:.2f} KGS</b>\n\n"
        f"Минимальная сумма вывода рефки: <b>{MIN_REF_WITHDRAW}</b> KGS."
    )

    kb = types.InlineKeyboardMarkup()
    if bal >= MIN_REF_WITHDRAW:
        kb.add(ibtn("Пополнить 1xBet с рефки", "ref_to_1x",
                    style="primary", icon_id="5224257782013769471"))
        kb.add(ibtn("Пополнить Melbet с рефки", "ref_to_melbet",
                    style="primary", icon_id="5224257782013769471"))
        kb.add(ibtn("Вывести на QR", "ref_out_qr",
                    style="success", icon_id="5215420556089776398"))
        kb.add(ibtn("Вывести на 1xBet / Melbet", "ref_out",
                    style="success", icon_id="5201691993775818138"))
    kb.add(ibtn("Главное меню", "ref_home", style="danger"))

    text += (
        f"\n\n{EMOJI['rocket']} <b>{BOT_NAME}</b>\n"
        f"Бот работает в автоматическом режиме\n"
        f"Admin: оператор"
    )
    send_msg(msg.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "ref_home")
def ref_home(call):
    bot.answer_callback_query(call.id)
    class M:
        pass
    m = M()
    m.chat = call.message.chat
    m.from_user = call.from_user
    m.text = "/start"
    start(m)


@bot.callback_query_handler(func=lambda c: c.data in ("ref_to_1x", "ref_to_melbet", "ref_out", "ref_out_qr"))
def ref_action(call):
    bal = get_ref_balance(call.from_user.id)
    if bal < MIN_REF_WITHDRAW:
        bot.answer_callback_query(call.id, f"Мин. {MIN_REF_WITHDRAW} KGS", show_alert=True)
        return
    bot.answer_callback_query(call.id)

    if call.data == "ref_out_qr":
        temp_data[call.from_user.id] = {
            "ref_out": True, "ref_amount": bal, "ref_mode": "qr", "ref_platform": "QR",
        }
        send_msg(
            call.from_user.id,
            f"📱 <b>Вывод рефки на QR</b>\n\n"
            f"Сумма: <b>{bal:.2f} KGS</b>\n\n"
            f"Отправьте <b>фото QR-кода</b> кошелька (ELQR / банк):",
            reply_markup=back_menu(),
        )
        bot.register_next_step_handler_by_chat_id(call.from_user.id, ref_out_qr_photo)
        return

    if call.data == "ref_to_1x":
        platform, mode = "1xBet", "topup"
    elif call.data == "ref_to_melbet":
        platform, mode = "Melbet", "topup"
    else:
        temp_data[call.from_user.id] = {"ref_out": True, "ref_amount": bal, "ref_mode": "out"}
        send_msg(
            call.from_user.id,
            f"💸 <b>Вывод реферального баланса</b>\n\n"
            f"Сумма: <b>{bal:.2f} KGS</b>\n\n"
            f"Куда зачислить?",
            reply_markup=platform_kb(),
        )
        bot.register_next_step_handler_by_chat_id(call.from_user.id, ref_out_platform)
        return

    temp_data[call.from_user.id] = {
        "ref_out": True,
        "ref_amount": bal,
        "ref_platform": platform,
        "ref_mode": mode,
    }
    send_msg(
        call.from_user.id,
        f"🎁 <b>Пополнение {platform} с реф. баланса</b>\n\n"
        f"Сумма: <b>{bal:.2f} KGS</b>\n\n"
        f"Введите ID {platform}:",
        reply_markup=back_menu(),
    )
    bot.register_next_step_handler_by_chat_id(call.from_user.id, ref_out_id)


def ref_out_qr_photo(msg):
    if msg.text and (msg.text.startswith("/start") or msg.text == "🔙 Назад"):
        start(msg)
        return
    photo_id = None
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document:
        photo_id = msg.document.file_id
    if not photo_id:
        send_msg(msg.chat.id, "❌ Отправьте фото QR!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_out_qr_photo)
        return
    uid = msg.chat.id
    bal = get_ref_balance(uid)
    if bal < MIN_REF_WITHDRAW:
        send_msg(uid, f"❌ Мин. {MIN_REF_WITHDRAW} KGS", reply_markup=reply_main_menu(uid))
        return
    touch_user(msg)
    deduct_ref_balance(uid, bal)
    wid = add_ref_withdrawal(uid, bal, "QR", photo_id)
    send_msg(
        uid,
        f"✅ <b>Заявка на вывод рефки на QR #{wid}</b>\n\n"
        f"💰 {bal:.2f} KGS\n\n"
        f"⏳ Ожидайте выплаты.",
        reply_markup=reply_main_menu(uid),
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        ibtn("Зачислено", f"refw_ok_{wid}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"refw_no_{wid}", style="danger"),
    )
    for admin in get_admins():
        try:
            send_media_bulletproof(
                admin, photo_id,
                caption=(
                    f"🎁 <b>РЕФКА QR #{wid}</b>\n\n"
                    f"👤 Игрок: {user_label(uid)}\n"
                    f"💰 {bal:.2f} KGS\n"
                    f"📱 Вывод на QR"
                ),
                reply_markup=markup,
            )
        except Exception:
            pass
    temp_data.pop(uid, None)


def ref_out_platform(msg):
    if not msg.text or msg.text.startswith("/start") or msg.text == "🔙 Назад":
        start(msg)
        return
    text = msg.text.strip()
    if "1xBet" in text or text.startswith("1️⃣"):
        platform = "1xBet"
    elif "Melbet" in text or text.startswith("2️⃣"):
        platform = "Melbet"
    else:
        send_msg(msg.chat.id, "❌ Выберите 1xBet или Melbet", reply_markup=platform_kb())
        bot.register_next_step_handler(msg, ref_out_platform)
        return
    temp_data.setdefault(msg.chat.id, {})["ref_platform"] = platform
    temp_data[msg.chat.id]["ref_mode"] = "out"
    send_msg(
        msg.chat.id,
        f"🆔 Введите ID <b>{platform}</b> для зачисления рефки:",
        reply_markup=back_menu(),
    )
    bot.register_next_step_handler(msg, ref_out_id)


def ref_out_id(msg):
    if not msg.text or msg.text.startswith("/start") or msg.text == "🔙 Назад":
        start(msg)
        return
    account = msg.text.strip()
    if not account:
        send_msg(msg.chat.id, "❌ Введите ID!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_out_id)
        return
    uid = msg.chat.id
    bal = get_ref_balance(uid)
    if bal < MIN_REF_WITHDRAW:
        send_msg(uid, f"❌ Недостаточно средств (мин. {MIN_REF_WITHDRAW} KGS)", reply_markup=reply_main_menu(uid))
        return
    platform = temp_data.get(uid, {}).get("ref_platform", "Melbet")
    mode = temp_data.get(uid, {}).get("ref_mode", "out")
    deduct_ref_balance(uid, bal)
    wid = add_ref_withdrawal(uid, bal, platform, account)
    kind = "пополнение с рефки" if mode == "topup" else "вывод рефки"
    send_msg(
        uid,
        f"✅ <b>Заявка на {kind} #{wid}</b>\n\n"
        f"💰 {bal:.2f} KGS\n"
        f"🆔 {platform} | <code>{safe_html(account)}</code>\n\n"
        f"⏳ Ожидайте зачисления.",
        reply_markup=main_menu(uid),
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        ibtn("Зачислено", f"refw_ok_{wid}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"refw_no_{wid}", style="danger"),
    )
    for admin in get_admins():
        try:
            bot.send_message(
                admin,
                f"🎁 <b>РЕФКА #{wid}</b> ({kind})\n\n"
                f"👤 Игрок: {user_label(uid)}\n"
                f"💰 {bal:.2f} KGS\n"
                f"🆔 {platform} | <code>{safe_html(account)}</code>",
                reply_markup=markup,
            )
        except Exception:
            pass
    temp_data.pop(uid, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("refw_ok_") or c.data.startswith("refw_no_"))
def ref_withdraw_mod(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "Нет прав")
        return
    ok = call.data.startswith("refw_ok_")
    wid = int(call.data.split("_")[-1])
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id, amount, platform, account_id, status FROM ref_withdrawals WHERE id = ?",
            (wid,),
        ).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "Не найдено")
            return
        user_id, amount, platform, account, status = row
        if status != "pending":
            bot.answer_callback_query(call.id, "Уже обработано")
            return
        conn.execute(
            "UPDATE ref_withdrawals SET status = ? WHERE id = ?",
            ("done" if ok else "rejected", wid),
        )
        if not ok:
            conn.execute(
                "UPDATE users SET ref_earned = COALESCE(ref_earned, 0) + ? WHERE chat_id = ?",
                (amount, user_id),
            )
        conn.commit()
    bot.answer_callback_query(call.id, "OK")
    try:
        bot.edit_message_text(
            (call.message.text or "") + ("\n\n✅ Зачислено" if ok else "\n\n❌ Отклонено"),
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception:
        pass
    try:
        if ok:
            bot.send_message(
                user_id,
                f"{EMOJI['check']} <b>Рефка зачислена!</b>\n\n"
                f"💰 {amount:.2f} KGS\n"
                f"🆔 {platform} | <code>{safe_html(account)}</code>",
            )
        else:
            bot.send_message(
                user_id,
                f"❌ Вывод рефки #{wid} отклонён.\n"
                f"Сумма возвращена на реферальный баланс.",
            )
    except Exception:
        pass


@bot.message_handler(func=lambda m: m.text in ["📖 Инструкция", "Инструкция"])
def instruction_handler(msg):
    send_msg(
        msg.chat.id,
        (
            f"📖 <b>Инструкция {BOT_NAME}</b>\n\n"
            f"<b>Пополнение</b>\n"
            f"1. Нажмите «💎 Пополнить»\n"
            f"2. Выберите 1xBet или Melbet\n"
            f"3. Введите ID и сумму\n"
            f"4. Оплатите по ссылке банка\n"
            f"5. Пришлите чек\n\n"
            f"<b>Вывод</b>\n"
            f"1. Нажмите «💰 Вывести»\n"
            f"2. Выберите букмекера\n"
            f"3. Отправьте QR или код счета\n"
            f"Город: <b>Бишкек</b>, ул. <b>DiamondPAY KG</b>\n\n"
            f"<b>Рефералы</b>\n"
            f"«🤝 Пригласить друга» — {REF_PERCENT}% с пополнений\n"
            f"Вывод рефки от {MIN_REF_WITHDRAW} KGS на QR · 1xBet · Melbet\n\n"
            f"{EMOJI['support']} Поддержка: оператор"
        ),
        reply_markup=main_menu(msg.chat.id),
    )


@bot.message_handler(func=lambda m: m.text in ["👤 Поддержка", "👨‍💻 Поддержка", "Поддержка"])
def support_handler(msg):
    send_msg(
        msg.chat.id,
        f"👤 <b>Поддержка {BOT_NAME}</b>\n\n"
        f"Напишите вопрос текстом или отправьте <b>фото</b> (можно с подписью).\n"
        f"Оператор ответит здесь, в боте.",
        reply_markup=back_menu(),
    )
    bot.register_next_step_handler(msg, support_receive_message)


def support_receive_message(msg):
    if msg.text and (msg.text.startswith("/start") or msg.text == "🔙 Назад"):
        start(msg)
        return

    photo_id = None
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document and (getattr(msg.document, "mime_type", None) or "").startswith("image/"):
        photo_id = msg.document.file_id

    text = ""
    if msg.caption:
        text = msg.caption.strip()
    elif msg.text:
        text = msg.text.strip()

    if not photo_id and len(text) < 2:
        send_msg(msg.chat.id, "❌ Напишите текст или отправьте фото:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, support_receive_message)
        return

    if not text and photo_id:
        text = "📎 Фото"

    touch_user(msg)
    uid = msg.from_user.id
    uname = msg.from_user.username or ""
    tid = create_ticket(uid, uname, text, photo_id=photo_id)
    notify_operators_ticket(tid, uid, uname, text, photo_id=photo_id)
    send_msg(
        msg.chat.id,
        f"✅ <b>Обращение #{tid} принято</b>\n\n"
        f"Статус: <b>Новое</b>\n"
        f"Оператор ответит в этот чат.",
        reply_markup=reply_main_menu(uid),
    )


@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_handler(msg):
    start(msg)


# ==================== ПОПОЛНЕНИЕ ====================

@bot.message_handler(func=lambda m: m.text in ["💎 Пополнить", "📥 Пополнить", "Пополнить"])
def deposit_start(msg):
    if not require_subscribe(msg):
        return
    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.")
        return
    temp_data[msg.chat.id] = {}
    send_msg(msg.chat.id,
             f"{EMOJI['info']} <b>Выберите букмекера:</b>",
             reply_markup=platform_kb())
    bot.register_next_step_handler(msg, deposit_choose_platform)


def deposit_choose_platform(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    text = msg.text.strip()
    if "1xBet" in text or text.startswith("1️⃣"):
        platform = "1xBet"
    elif "Melbet" in text or text.startswith("2️⃣"):
        platform = "Melbet"
    else:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Выберите 1xBet или Melbet", reply_markup=platform_kb())
        bot.register_next_step_handler(msg, deposit_choose_platform)
        return
    temp_data[msg.chat.id] = {"platform": platform}
    send_msg(msg.chat.id,
             f"{EMOJI['info']} <b>Введите ваш ID {platform}:</b>",
             reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_account_id)


def get_account_id(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    temp_data.setdefault(msg.chat.id, {})["account_id"] = f"{platform} | {msg.text.strip()}"
    send_msg(msg.chat.id,
             f"{EMOJI['money']} <b>Введите сумму</b>\n\nОт <b>{MIN_DEPOSIT}</b> до <b>{MAX_DEPOSIT}</b> сом",
             reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_amount)


def get_amount(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    try:
        base = float(msg.text.replace(',', '.'))
    except Exception:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Введите корректное число!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return

    if not (MIN_DEPOSIT <= base <= MAX_DEPOSIT):
        send_msg(msg.chat.id,
                 f"{EMOJI['cross']} Сумма от {MIN_DEPOSIT} до {MAX_DEPOSIT} KGS. Попробуйте снова:",
                 reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return

    chat_id = msg.chat.id
    temp_data.setdefault(chat_id, {})["amount"] = base

    # Таймер на 15 минут
    if chat_id in payment_timers:
        payment_timers[chat_id].cancel()
    t = threading.Timer(900, cancel_payment, args=[chat_id])
    payment_timers[chat_id] = t
    t.start()

    qr_file = get_last_qr()
    kb = types.InlineKeyboardMarkup()
    kb.add(ibtn("💳 Оплатить через O!Bank / MBank", url=PAY_LINK, style="primary"))
    
    caption = (
        f"⏳ <b>К оплате: {base:.2f} KGS</b>\n\n"
        f"⚠️ Реквизиты актуальны в течение <b>15 минут</b>.\n"
        f"Отсканируйте QR или перейдите по ссылке оплаты выше.\n\n"
        f"🧾 <b>После оплаты отправьте скриншот чека прямо в этот чат.</b>"
    )

    if qr_file:
        send_media_bulletproof(chat_id, qr_file, caption=caption, reply_markup=kb)
    else:
        send_msg(chat_id, caption, reply_markup=kb)

    bot.register_next_step_handler(msg, get_receipt)


def get_receipt(msg):
    chat_id = msg.chat.id
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        start(msg)
        return

    photo_id = None
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document and (getattr(msg.document, "mime_type", None) or "").startswith("image/"):
        photo_id = msg.document.file_id

    if not photo_id:
        send_msg(chat_id, "❌ Пожалуйста, отправьте скриншот чека фото:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_receipt)
        return

    data = temp_data.get(chat_id, {})
    amount = data.get("amount", 0.0)
    account_id = data.get("account_id", "Не указан")

    if chat_id in payment_timers:
        payment_timers[chat_id].cancel()
        payment_timers.pop(chat_id, None)

    dep_id = add_deposit(chat_id, amount, account_id, photo_id)
    touch_user(msg)

    send_msg(
        chat_id,
        f"✅ <b>Чек отправлен на проверку!</b>\n\n"
        f"Заявка <b>#{dep_id}</b> создана.\n"
        f"Сумма: <b>{amount:.2f} KGS</b>\n"
        f"Ожидайте зачисления в течение 2-5 минут.",
        reply_markup=main_menu(chat_id),
    )

    # Уведомление админам
    kb = types.InlineKeyboardMarkup()
    kb.add(
        ibtn("Подтвердить", f"dep_ok_{dep_id}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"dep_no_{dep_id}", style="danger"),
    )
    for admin in get_admins():
        try:
            send_media_bulletproof(
                admin,
                photo_id,
                caption=(
                    f"📥 <b>НОВАЯ ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id}</b>\n\n"
                    f"👤 Пользователь: {user_label(chat_id)}\n"
                    f"💰 Сумма: <b>{amount:.2f} KGS</b>\n"
                    f"🆔 Счет: <code>{safe_html(account_id)}</code>"
                ),
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin}: {e}")

    temp_data.pop(chat_id, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("dep_ok_") or c.data.startswith("dep_no_"))
def deposit_moderation(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    ok = call.data.startswith("dep_ok_")
    dep_id = int(call.data.split("_")[-1])

    with get_db() as conn:
        row = conn.execute("SELECT user_id, amount, account_id, status FROM deposits WHERE id = ?", (dep_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "Заявка не найдена")
            return
        user_id, amount, account_id, status = row
        if status != "pending":
            bot.answer_callback_query(call.id, "Заявка уже обработана")
            return

        new_status = "approved" if ok else "rejected"
        update_deposit_status(dep_id, new_status)

        # Обработка реферального бонуса
        if ok:
            referrer = get_referrer(user_id)
            if referrer:
                bonus = round(amount * (REF_PERCENT / 100.0), 2)
                add_ref_bonus(referrer, bonus, amount)

    bot.answer_callback_query(call.id, "Обработано")
    try:
        status_str = "✅ Подтверждено" if ok else "❌ Отклонено"
        bot.edit_message_caption(
            (call.message.caption or "") + f"\n\n<b>Статус:</b> {status_str}",
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception:
        pass

    try:
        if ok:
            bot.send_message(
                user_id,
                f"🎉 <b>Ваш счёт пополнен!</b>\n\n"
                f"Сумма: <b>{amount:.2f} KGS</b>\n"
                f"Счёт: <code>{safe_html(account_id)}</code>\n"
                f"Спасибо за использование {BOT_NAME}!",
            )
        else:
            bot.send_message(
                user_id,
                f"❌ <b>Заявка #{dep_id} отклонена.</b>\nЕсли возникли вопросы, обратитесь в поддержку.",
            )
    except Exception:
        pass


# ==================== ВЫВОД ====================

@bot.message_handler(func=lambda m: m.text in ["💰 Вывести", "📤 Вывести", "Вывести"])
def withdraw_start(msg):
    if not require_subscribe(msg):
        return
    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.")
        return
    send_msg(msg.chat.id, f"{EMOJI['withdraw']} <b>Выберите букмекерскую контору для вывода:</b>", reply_markup=platform_kb())
    bot.register_next_step_handler(msg, withdraw_choose_platform)


def withdraw_choose_platform(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    text = msg.text.strip()
    if "1xBet" in text or text.startswith("1️⃣"):
        platform = "1xBet"
    elif "Melbet" in text or text.startswith("2️⃣"):
        platform = "Melbet"
    else:
        send_msg(msg.chat.id, "❌ Выберите 1xBet или Melbet", reply_markup=platform_kb())
        bot.register_next_step_handler(msg, withdraw_choose_platform)
        return

    temp_data[msg.chat.id] = {"w_platform": platform}
    
    img = get_withdraw_image()
    instruction = (
        f"📤 <b>Вывод средств ({platform})</b>\n\n"
        f"Для снятия денег в приложении {platform}:\n"
        f"1. Выберите город: <b>Бишкек</b>\n"
        f"2. Улица/Касса: <b>DiamondPAY KG</b>\n"
        f"3. Отправьте сюда <b>QR-код или код вывода (SMS)</b> с указанием вашего ID."
    )
    if img:
        send_media_bulletproof(msg.chat.id, img, caption=instruction, reply_markup=back_menu())
    else:
        send_msg(msg.chat.id, instruction, reply_markup=back_menu())

    bot.register_next_step_handler(msg, withdraw_get_details)


def withdraw_get_details(msg):
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        start(msg)
        return

    photo_id = None
    text_data = msg.text or msg.caption or ""

    if msg.photo:
        photo_id = msg.photo[-1].file_id

    if not photo_id and len(text_data) < 3:
        send_msg(msg.chat.id, "❌ Пожалуйста, отправьте QR-код скриншотом или укажите код вывода текстом:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_details)
        return

    uid = msg.chat.id
    platform = temp_data.get(uid, {}).get("w_platform", "1xBet")
    w_id = add_withdrawal(uid, photo_id, None, text_data)
    touch_user(msg)

    send_msg(
        uid,
        f"✅ <b>Заявка на вывод #{w_id} принята!</b>\n\n"
        f"Платформа: <b>{platform}</b>\n"
        f"Оператор проверит код и отправит средства. Ожидайте!",
        reply_markup=main_menu(uid),
    )

    kb = types.InlineKeyboardMarkup()
    kb.add(
        ibtn("Выплачено", f"w_ok_{w_id}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"w_no_{w_id}", style="danger"),
    )

    caption = (
        f"📤 <b>ЗАЯВКА НА ВЫВОД #{w_id}</b>\n\n"
        f"👤 Игрок: {user_label(uid)}\n"
        f"🎮 Платформа: <b>{platform}</b>\n"
        f"📝 Данные: {safe_html(text_data) if text_data else '📎 Фото QR'}"
    )

    for admin in get_admins():
        try:
            if photo_id:
                send_media_bulletproof(admin, photo_id, caption=caption, reply_markup=kb)
            else:
                bot.send_message(admin, caption, reply_markup=kb)
        except Exception:
            pass

    temp_data.pop(uid, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("w_ok_") or c.data.startswith("w_no_"))
def withdrawal_moderation(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    ok = call.data.startswith("w_ok_")
    w_id = int(call.data.split("_")[-1])

    with get_db() as conn:
        row = conn.execute("SELECT user_id, status FROM withdrawals WHERE id = ?", (w_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "Заявка не найдена")
            return
        user_id, status = row
        if status != "pending":
            bot.answer_callback_query(call.id, "Уже обработано")
            return

        conn.execute("UPDATE withdrawals SET status = ? WHERE id = ?", ("done" if ok else "rejected", w_id))
        conn.commit()

    bot.answer_callback_query(call.id, "OK")
    try:
        bot.edit_message_caption(
            (call.message.caption or call.message.text or "") + ("\n\n✅ Выплачено" if ok else "\n\n❌ Отклонено"),
            call.message.chat.id,
            call.message.message_id,
        )
    except Exception:
        pass

    try:
        if ok:
            bot.send_message(user_id, f"✅ <b>Заявка на вывод #{w_id} успешно обработана!</b> Средства отправлены.")
        else:
            bot.send_message(user_id, f"❌ <b>Заявка на вывод #{w_id} отклонена.</b> Свяжитесь с поддержкой.")
    except Exception:
        pass


# ==================== ОБРАБОТКА ОБРАЩЕНИЙ В ПОДДЕРЖКУ ====================

@bot.callback_query_handler(func=lambda c: c.data.startswith("tkt_"))
def ticket_callback(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "Нет доступа")
        return

    parts = call.data.split("_")
    action = parts[1]
    tid = int(parts[2])
    tkt = get_ticket(tid)

    if not tkt:
        bot.answer_callback_query(call.id, "Тикет не найден")
        return

    user_id = tkt[1]

    if action == "work":
        set_ticket_status(tid, "in_progress")
        bot.answer_callback_query(call.id, "Взято в работу")
        try:
            bot.send_message(user_id, f"👨‍💻 Оператор взялся за ваше обращение <b>#{tid}</b>.")
        except Exception:
            pass

    elif action == "close":
        set_ticket_status(tid, "closed")
        bot.answer_callback_query(call.id, "Закрыто")
        try:
            bot.send_message(user_id, f"✅ Ваше обращение <b>#{tid}</b> закрыто.")
        except Exception:
            pass

    elif action == "reply":
        bot.answer_callback_query(call.id)
        send_msg(call.from_user.id, f"✍️ Введите ответ для пользователя по тикету <b>#{tid}</b>:")
        bot.register_next_step_handler_by_chat_id(call.from_user.id, admin_reply_ticket_step, tid, user_id)


def admin_reply_ticket_step(msg, tid, user_id):
    reply_text = msg.text or msg.caption or ""
    if not reply_text:
        send_msg(msg.chat.id, "❌ Текст ответа не может быть пустым.")
        return

    add_ticket_reply(tid, from_admin=True, message=reply_text)
    set_ticket_status(tid, "answered")

    try:
        bot.send_message(
            user_id,
            f"📩 <b>Ответ оператора (Обращение #{tid}):</b>\n\n{safe_html(reply_text)}"
        )
        send_msg(msg.chat.id, f"✅ Ответ отправлен пользователю по тикету #{tid}.")
    except Exception as e:
        send_msg(msg.chat.id, f"❌ Ошибка отправки сообщения пользователю: {e}")


# ==================== АДМИН ПАНЕЛЬ ====================

@bot.message_handler(func=lambda m: m.text in ["⚙️ Admin", "Admin", "/admin"])
def admin_panel(msg):
    if msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, "❌ Нет прав доступа.")
        return
    send_msg(msg.chat.id, f"{EMOJI['admin']} <b>Панель администратора:</b>", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN)
def admin_actions(msg):
    text = msg.text or ""

    if text == "📋 Заявки":
        pending = get_pending_deposits()
        if not pending:
            send_msg(msg.chat.id, "✅ Активных заявок на пополнение нет.")
            return
        for item in pending:
            dep_id, uid, amt, acc, photo, date_str, _ = item
            kb = types.InlineKeyboardMarkup()
            kb.add(
                ibtn("Подтвердить", f"dep_ok_{dep_id}", style="success"),
                ibtn("Отклонить", f"dep_no_{dep_id}", style="danger"),
            )
            caption = f"📥 <b>Заявка #{dep_id}</b>\nИгрок: {user_label(uid)}\nСумма: {amt:.2f} KGS\nСчёт: {acc}\nДата: {date_str}"
            send_media_bulletproof(msg.chat.id, photo, caption=caption, reply_markup=kb)

    elif text == "📩 Обращения":
        tickets = list_tickets(status="new", limit=10)
        if not tickets:
            send_msg(msg.chat.id, "✅ Новых обращений в поддержку нет.")
            return
        for tkt in tickets:
            tid, uid, uname, message, status, created = tkt
            notify_operators_ticket(tid, uid, uname, message)

    elif text == "📈 Статистика":
        st = get_stats()
        send_msg(
            msg.chat.id,
            f"📊 <b>Статистика бота:</b>\n\n"
            f"👥 Всего пользователей: <b>{st['users']}</b>\n"
            f"⏳ Ожидают проверки: <b>{st['pending']}</b>\n"
            f"💰 Успешных пополнений: <b>{st['total']:.2f} KGS</b>"
        )

    elif text == "🖼 Изменить QR":
        send_msg(msg.chat.id, "Отправьте новое фото QR-кода для оплаты:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, admin_save_qr_step)

    elif text == "🖼 Инструкция вывода":
        send_msg(msg.chat.id, "Отправьте новое фото для инструкции вывода:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, admin_save_withdraw_img_step)

    elif text in ["🔴 ВЫКЛ", "🟢 ВКЛ"]:
        current = is_bot_active()
        set_bot_active(not current)
        status_str = "выключен 🔴" if current else "включен 🟢"
        send_msg(msg.chat.id, f"Бот теперь <b>{status_str}</b>", reply_markup=admin_menu())

    elif text == "📢 Рассылка":
        send_msg(msg.chat.id, "Введите текст сообщения или отправьте фото с подписью для рассылки всем юзерам:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, admin_broadcast_step)

    elif text == "➕ Админ":
        send_msg(msg.chat.id, "Введите Telegram ID нового администратора:")
        bot.register_next_step_handler(msg, admin_add_step)

    elif text == "➖ Удалить админа":
        send_msg(msg.chat.id, "Введите Telegram ID администратора для удаления:")
        bot.register_next_step_handler(msg, admin_remove_step)


def admin_save_qr_step(msg):
    if msg.photo:
        save_qr(msg.photo[-1].file_id)
        send_msg(msg.chat.id, "✅ Новый QR-код оплаты успешно сохранен!", reply_markup=admin_menu())
    else:
        send_msg(msg.chat.id, "❌ Отправьте именно фотографию.", reply_markup=admin_menu())


def admin_save_withdraw_img_step(msg):
    if msg.photo:
        save_withdraw_image(msg.photo[-1].file_id)
        send_msg(msg.chat.id, "✅ Картинка инструкции вывода сохранена!", reply_markup=admin_menu())
    else:
        send_msg(msg.chat.id, "❌ Отправьте именно фотографию.", reply_markup=admin_menu())


def admin_add_step(msg):
    try:
        new_id = int(msg.text.strip())
        add_admin(new_id)
        send_msg(msg.chat.id, f"✅ Пользователь <code>{new_id}</code> добавлен в админы.", reply_markup=admin_menu())
    except Exception:
        send_msg(msg.chat.id, "❌ Введите корректный числовой ID.", reply_markup=admin_menu())


def admin_remove_step(msg):
    try:
        rem_id = int(msg.text.strip())
        if rem_id == MAIN_ADMIN:
            send_msg(msg.chat.id, "❌ Нельзя удалить главного администратора!", reply_markup=admin_menu())
            return
        remove_admin(rem_id)
        send_msg(msg.chat.id, f"✅ Администратор <code>{rem_id}</code> удален.", reply_markup=admin_menu())
    except Exception:
        send_msg(msg.chat.id, "❌ Введите корректный числовой ID.", reply_markup=admin_menu())


def admin_broadcast_step(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    users = get_all_users()
    send_msg(msg.chat.id, f"🚀 Начинаем рассылку для {len(users)} пользователей...")
    success = 0
    photo_id = msg.photo[-1].file_id if msg.photo else None
    text = msg.caption or msg.text or ""

    for uid in users:
        try:
            if photo_id:
                bot.send_photo(uid, photo_id, caption=text)
            else:
                bot.send_message(uid, text)
            success += 1
            time.sleep(0.05)
        except Exception:
            pass

    send_msg(msg.chat.id, f"✅ Рассылка завершена!\nДоставлено: {success}/{len(users)}", reply_markup=admin_menu())


# ==================== FLASK SERVER FOR HOSTING ====================

@app.route('/')
def home():
    return jsonify({"status": "active", "service": "DiamondPAY Bot", "timestamp": now_kg().isoformat()})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    # Запуск веб-сервера в фоновом потоке для Render/Heroku/Koyeb
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Бот DiamondPAY запущен...")
    
    # Запуск polling телеграм бота
    bot.infinity_polling(skip_pending=True)

