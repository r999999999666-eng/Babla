import os
import sqlite3
import time
import threading
import html
import random
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
import telebot
from telebot import types

# Часовой пояс Кыргызстана (Бишкек, UTC+6)
KG_TZ = ZoneInfo("Asia/Bishkek")

def get_kg_now():
    return datetime.now(KG_TZ)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN_REF") or os.environ.get("TOKEN")
if not TOKEN or len(TOKEN) < 40:
    logger.error("ТОКЕН НЕ НАЙДЕН!")
    raise SystemExit("No token")

MAIN_ADMIN = int(os.environ.get("MAIN_ADMIN", "8992968778"))
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1905")
OPERATOR_ID = int(os.environ.get("OPERATOR_ID", "8992968778"))
SUPPORT = os.environ.get("SUPPORT", "")

BOT_NAME = "DiamondPAY"
MIN_DEPOSIT = 100
MAX_DEPOSIT = 500000
REF_PERCENT = 2.5
BOT_USERNAME = os.environ.get("BOT_USERNAME", "DiamondPAY_KG_bot")
MIN_REF_WITHDRAW = 100

WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111258120233520910129965023532261202111302123408%D0%9D%D0%A3%D0%A0%D0%AD%D0%9B%20%D0%9A.5204739953034175401059060%21Bank63044CEE",
)

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
app = Flask(__name__)

temp_data = {}
payment_timers = {}
DB_NAME = 'bot.db'


def pe(eid, fb):
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
    "key":      pe("5197269100878907942", "✍"),
    "write":    pe("5197269100878907942", "✍️"),
    "off": "🔴",
    "on": "🟢",
    "lock": "🔒",
    "wave": "👋",
    "gift": pe("5379943126653761268", "❄️"),
}


def day_greeting(name: str) -> str:
    h = get_kg_now().hour
    if 5 <= h < 12:
        g = "Доброе утро"
    elif 12 <= h < 17:
        g = "Добрый день"
    elif 17 <= h < 23:
        g = "Добрый вечер"
    else:
        g = "Доброй ночи"
    return f"{g}, {html.escape(name)}! {EMOJI['wave']}"


def tpl_status_line() -> str:
    return f"{EMOJI['check']} Актуально на: {get_kg_now().strftime('%d.%m.%Y %H:%M')} (KG)"


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
                        user_id INTEGER, username TEXT, message TEXT,
                        status TEXT DEFAULT 'new', created TEXT, updated TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS support_replies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER, from_admin INTEGER, message TEXT, created TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, elqr_photo TEXT,
                        id_photo TEXT, sms_code TEXT, status TEXT, date TEXT)''')
        
        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (MAIN_ADMIN,))
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("bot_active", "True")')
        conn.commit()
    logger.info("База данных успешно инициализирована")


def is_bot_active():
    with get_db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = "bot_active"').fetchone()
        return True if row is None else row[0] == 'True'


def set_bot_active(status: bool):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("bot_active", ?)', (str(status),))
        conn.commit()


def get_admins():
    with get_db() as conn:
        admins = [int(r[0]) for r in conn.execute('SELECT chat_id FROM admins').fetchall()]
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
                (chat_id, get_kg_now().strftime("%d.%m.%Y %H:%M"), ref, username or "", full_name or ""),
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
        row = conn.execute('SELECT username, full_name FROM users WHERE chat_id = ?', (user_id,)).fetchone()
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
        row = conn.execute("SELECT COALESCE(ref_earned, 0) FROM users WHERE chat_id = ?", (user_id,)).fetchone()
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
            (user_id, amount, platform, account_id, get_kg_now().strftime("%d.%m.%Y %H:%M")),
        )
        wid = c.lastrowid
        conn.commit()
        return wid


def create_ticket(user_id, username, message):
    now = get_kg_now().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO support_tickets (user_id, username, message, status, created, updated)
               VALUES (?, ?, ?, 'new', ?, ?)""",
            (user_id, username or "", message, now, now),
        )
        tid = c.lastrowid
        conn.commit()
        return tid


def get_ticket(tid):
    with get_db() as conn:
        return conn.execute("SELECT * FROM support_tickets WHERE id = ?", (tid,)).fetchone()


def set_ticket_status(tid, status):
    now = get_kg_now().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        conn.execute("UPDATE support_tickets SET status = ?, updated = ? WHERE id = ?", (status, now, tid))
        conn.commit()


def add_ticket_reply(tid, from_admin, message):
    now = get_kg_now().strftime("%d.%m.%Y %H:%M")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO support_replies (ticket_id, from_admin, message, created) VALUES (?, ?, ?, ?)",
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


def notify_operators_ticket(tid, user_id, username, message):
    uname = f"@{username}" if username else user_label(user_id)
    text = (
        f"🆘 <b>Обращение #{tid}</b>\n"
        f"Статус: <b>Новое</b>\n\n"
        f"👤 {uname}\n"
        f"💬 {safe_html(message)}"
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
                   get_kg_now().strftime("%d.%m.%Y %H:%M:%S"), int(time.time())))
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
                  (user_id, elqr, id_photo, code, 'pending', get_kg_now().strftime("%d.%m.%Y %H:%M")))
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
                     (file_id, get_kg_now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()


def get_last_qr():
    with get_db() as conn:
        row = conn.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else None


def save_withdraw_image(file_id):
    with get_db() as conn:
        conn.execute('DELETE FROM withdraw_images')
        conn.execute('INSERT INTO withdraw_images (file_id, date) VALUES (?, ?)',
                     (file_id, get_kg_now().strftime("%d.%m.%Y %H:%M")))
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
    send_msg(user_id, f"⏳ <b>Время оплаты истекло</b>\n\nЗаявка отменена. Нажмите «💎 Пополнить», чтобы начать снова.")


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

    # Инлайн-кнопки пополнения и вывода с цветным стилем (Primary / Success)
    inline_actions = types.InlineKeyboardMarkup(row_width=2)
    inline_actions.add(
        ibtn("💎 Пополнить", callback_data="act_deposit", style="primary"),
        ibtn("💰 Вывести", callback_data="act_withdraw", style="success")
    )

    send_msg(chat_id, welcome, reply_markup=main_menu(msg.from_user.id))
    send_msg(chat_id, "Быстрый выбор:", reply_markup=inline_actions)


@bot.callback_query_handler(func=lambda c: c.data in ["act_deposit", "act_withdraw"])
def inline_action_handler(call):
    bot.answer_callback_query(call.id)
    class M: pass
    m = M()
    m.chat = call.message.chat
    m.from_user = call.from_user
    if call.data == "act_deposit":
        m.text = "💎 Пополнить"
        deposit_start(m)
    else:
        m.text = "💰 Вывести"
        withdraw_start(m)


@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)


@bot.message_handler(func=lambda m: m.text in ["🤝 Пригласить друга", "🎁 Рефералы", "Рефералы"])
def referral_info(msg):
    add_user(msg.chat.id)
    uid = msg.chat.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    with get_db() as conn:
        bal_row = conn.execute("SELECT COALESCE(ref_earned, 0) FROM users WHERE chat_id = ?", (uid,)).fetchone()
        friends = conn.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (uid,)).fetchone()[0]
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
        kb.add(ibtn("Пополнить 1xBet с рефки", "ref_to_1x", style="primary", icon_id="5224257782013769471"))
        kb.add(ibtn("Пополнить Melbet с рефки", "ref_to_melbet", style="primary", icon_id="5224257782013769471"))
        kb.add(ibtn("Вывести на QR", "ref_out_qr", style="success", icon_id="5215420556089776398"))
        kb.add(ibtn("Вывести на 1xBet / Melbet", "ref_out", style="success", icon_id="5201691993775818138"))
    kb.add(ibtn("Главное меню", "ref_home", style="danger"))

    text += (
        f"\n\n{EMOJI['rocket']} <b>{BOT_NAME}</b>\n"
        f"Бот работает в автоматическом режиме\n"
        f"Admin: оператор\n"
        f"<i>«Если у вас уже есть аккаунт, не нужно регистрировать новый»</i>"
    )
    send_msg(msg.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "ref_home")
def ref_home(call):
    bot.answer_callback_query(call.id)
    class M: pass
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
        temp_data[call.from_user.id] = {"ref_mode": "qr", "ref_platform": "QR"}
    elif call.data == "ref_to_1x":
        temp_data[call.from_user.id] = {"ref_mode": "topup", "ref_platform": "1xBet"}
    elif call.data == "ref_to_melbet":
        temp_data[call.from_user.id] = {"ref_mode": "topup", "ref_platform": "Melbet"}
    else: # ref_out
        temp_data[call.from_user.id] = {"ref_mode": "out"}
        send_msg(
            call.from_user.id,
            f"💸 <b>Вывод реферального баланса</b>\n\nДоступно: <b>{bal:.2f} KGS</b>\n\nКуда зачислить?",
            reply_markup=platform_kb(),
        )
        bot.register_next_step_handler_by_chat_id(call.from_user.id, ref_out_platform)
        return

    send_msg(
        call.from_user.id,
        f"💵 <b>Доступно для вывода: {bal:.2f} KGS</b>\n\n"
        f"Введите сумму вывода (мин. <b>{MIN_REF_WITHDRAW} KGS</b>):",
        reply_markup=back_menu(),
    )
    bot.register_next_step_handler_by_chat_id(call.from_user.id, ref_get_amount)


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
    bal = get_ref_balance(msg.chat.id)
    
    send_msg(
        msg.chat.id,
        f"💵 <b>Доступно для вывода: {bal:.2f} KGS</b>\n\n"
        f"Введите сумму вывода (мин. <b>{MIN_REF_WITHDRAW} KGS</b>):",
        reply_markup=back_menu()
    )
    bot.register_next_step_handler(msg, ref_get_amount)


def ref_get_amount(msg):
    if not msg.text or msg.text.startswith("/start") or msg.text == "🔙 Назад":
        start(msg)
        return
    try:
        amount = float(msg.text.replace(',', '.'))
    except ValueError:
        send_msg(msg.chat.id, "❌ Введите корректную сумму числом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_get_amount)
        return

    uid = msg.chat.id
    bal = get_ref_balance(uid)

    if amount < MIN_REF_WITHDRAW:
        send_msg(msg.chat.id, f"❌ Минимальная сумма вывода: <b>{MIN_REF_WITHDRAW} KGS</b>", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_get_amount)
        return

    if amount > bal:
        send_msg(msg.chat.id, f"❌ У вас недостаточно средств! Доступно: <b>{bal:.2f} KGS</b>", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_get_amount)
        return

    temp_data.setdefault(uid, {})["ref_amount"] = amount
    mode = temp_data[uid].get("ref_mode")

    if mode == "qr":
        send_msg(
            uid,
            f"📱 <b>Вывод рефки на QR</b>\n\nСумма: <b>{amount:.2f} KGS</b>\n\nОтправьте <b>фото QR-кода</b> кошелька (ELQR / банк):",
            reply_markup=back_menu(),
        )
        bot.register_next_step_handler(msg, ref_out_qr_photo)
    else:
        platform = temp_data[uid].get("ref_platform", "1xBet")
        send_msg(
            uid,
            f"🆔 <b>Вывод рефки на {platform}</b>\n\nСумма: <b>{amount:.2f} KGS</b>\n\nВведите ваш ID {platform}:",
            reply_markup=back_menu(),
        )
        bot.register_next_step_handler(msg, ref_out_id)


def ref_out_qr_photo(msg):
    if msg.text and (msg.text.startswith("/start") or msg.text == "🔙 Назад"):
        start(msg)
        return
    photo_id = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    if not photo_id:
        send_msg(msg.chat.id, "❌ Отправьте фото QR!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_out_qr_photo)
        return
    uid = msg.chat.id
    amount = temp_data.get(uid, {}).get("ref_amount", 0)
    bal = get_ref_balance(uid)
    
    if amount < MIN_REF_WITHDRAW or amount > bal:
        send_msg(uid, "❌ Ошибка баланса или суммы. Попробуйте снова.", reply_markup=reply_main_menu(uid))
        return
    
    touch_user(msg)
    deduct_ref_balance(uid, amount)
    wid = add_ref_withdrawal(uid, amount, "QR", photo_id)
    send_msg(
        uid,
        f"✅ <b>Заявка на вывод рефки на QR #{wid}</b>\n\n💰 {amount:.2f} KGS\n\n⏳ Ожидайте выплаты.",
        reply_markup=reply_main_menu(uid),
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        ibtn("Зачислено", f"refw_ok_{wid}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"refw_no_{wid}", style="danger"),
    )
    for admin in get_admins():
        send_media_bulletproof(
            admin, photo_id,
            caption=f"🎁 <b>РЕФКА QR #{wid}</b>\n\n👤 Игрок: {user_label(uid)}\n💰 {amount:.2f} KGS\n📱 Вывод на QR",
            reply_markup=markup,
        )
    temp_data.pop(uid, None)


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
    amount = temp_data.get(uid, {}).get("ref_amount", 0)
    bal = get_ref_balance(uid)
    
    if amount < MIN_REF_WITHDRAW or amount > bal:
        send_msg(uid, "❌ Недостаточно средств или неверная сумма.", reply_markup=reply_main_menu(uid))
        return
        
    platform = temp_data.get(uid, {}).get("ref_platform", "Melbet")
    mode = temp_data.get(uid, {}).get("ref_mode", "out")
    deduct_ref_balance(uid, amount)
    wid = add_ref_withdrawal(uid, amount, platform, account)
    kind = "пополнение с рефки" if mode == "topup" else "вывод рефки"
    send_msg(
        uid,
        f"✅ <b>Заявка на {kind} #{wid}</b>\n\n💰 {amount:.2f} KGS\n🆔 {platform} | <code>{safe_html(account)}</code>\n\n⏳ Ожидайте зачисления.",
        reply_markup=main_menu(uid),
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(
        ibtn("Зачислено", f"refw_ok_{wid}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"refw_no_{wid}", style="danger"),
    )
    for admin in get_admins():
        send_msg(
            admin,
            f"🎁 <b>РЕФКА #{wid}</b> ({kind})\n\n👤 Игрок: {user_label(uid)}\n💰 {amount:.2f} KGS\n🆔 {platform} | <code>{safe_html(account)}</code>",
            reply_markup=markup,
        )
    temp_data.pop(uid, None)


@bot.callback_query_handler(func=lambda c: c.data.startswith("refw_ok_") or c.data.startswith("refw_no_"))
def ref_withdraw_mod(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "Нет прав")
        return
    ok = call.data.startswith("refw_ok_")
    wid = int(call.data.split("_")[-1])
    with get_db() as conn:
        row = conn.execute("SELECT user_id, amount, platform, account_id, status FROM ref_withdrawals WHERE id = ?", (wid,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "Не найдено")
            return
        user_id, amount, platform, account, status = row
        if status != "pending":
            bot.answer_callback_query(call.id, "Уже обработано")
            return
        conn.execute("UPDATE ref_withdrawals SET status = ? WHERE id = ?", ("done" if ok else "rejected", wid))
        if not ok:
            conn.execute("UPDATE users SET ref_earned = COALESCE(ref_earned, 0) + ? WHERE chat_id = ?", (amount, user_id))
        conn.commit()

    bot.answer_callback_query(call.id, "OK")
    try:
        bot.edit_message_text((call.message.text or "") + ("\n\n✅ Зачислено" if ok else "\n\n❌ Отклонено"), call.message.chat.id, call.message.message_id)
    except Exception:
        pass

    try:
        if ok:
            bot.send_message(user_id, f"{EMOJI['check']} <b>Рефка зачислена!</b>\n\n💰 {amount:.2f} KGS\n🆔 {platform} | <code>{safe_html(account)}</code>")
        else:
            bot.send_message(user_id, f"❌ Вывод рефки #{wid} отклонён.\nСумма возвращена на реферальный баланс.")
    except Exception:
        pass


@bot.message_handler(func=lambda m: m.text in ["📖 Инструкция", "Инструкция"])
def instruction_handler(msg):
    send_msg(
        msg.chat.id,
        (
            f"📖 <b>Инструкция {BOT_NAME}</b>\n\n"
            f"<b>Пополнение</b>\n1. Нажмите «💎 Пополнить»\n2. Выберите 1xBet или Melbet\n3. Введите ID и сумму\n4. Оплатите по ссылке банка\n5. Пришлите чек\n\n"
            f"<b>Вывод</b>\n1. Нажмите «💰 Вывести»\n2. Выберите букмекера\n3. QR → ID → код\nГород: <b>Бишкек</b>, ул. <b>DiamondPAY KG</b>\n\n"
            f"<b>Рефералы</b>\n«🤝 Пригласить друга» — {REF_PERCENT}% с пополнений\nВывод рефки от {MIN_REF_WITHDRAW} KGS на QR · 1xBet · Melbet\n\n"
            f"{EMOJI['support']} Поддержка: оператор"
        ),
        reply_markup=main_menu(msg.chat.id),
    )


@bot.message_handler(func=lambda m: m.text in ["👤 Поддержка", "👨‍💻 Поддержка", "Поддержка"])
def support_handler(msg):
    send_msg(
        msg.chat.id,
        f"👤 <b>Поддержка {BOT_NAME}</b>\n\nНапишите ваш вопрос одним сообщением.\nОператор ответит здесь, в боте.",
        reply_markup=back_menu(),
    )
    bot.register_next_step_handler(msg, support_receive_message)


def support_receive_message(msg):
    if not msg.text or msg.text.startswith("/start") or msg.text == "🔙 Назад":
        start(msg)
        return
    text = msg.text.strip()
    if len(text) < 2:
        send_msg(msg.chat.id, "❌ Слишком коротко. Напишите вопрос:", reply_markup=back_menu())
        bot.register_next_step_handler(msg, support_receive_message)
        return
    touch_user(msg)
    uid = msg.from_user.id
    uname = msg.from_user.username or ""
    tid = create_ticket(uid, uname, text)
    notify_operators_ticket(tid, uid, uname, text)
    send_msg(
        msg.chat.id,
        f"✅ <b>Обращение #{tid} принято</b>\n\nСтатус: <b>Новое</b>\nОператор ответит в этот чат.",
        reply_markup=reply_main_menu(uid),
    )


@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_handler(msg):
    start(msg)


@bot.message_handler(func=lambda m: m.text in ["💎 Пополнить", "📥 Пополнить", "Пополнить"])
def deposit_start(msg):
    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.")
        return
    temp_data[msg.chat.id] = {}
    send_msg(msg.chat.id, f"{EMOJI['info']} <b>Выберите букмекера:</b>", reply_markup=platform_kb())
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
    send_msg(msg.chat.id, f"{EMOJI['info']} <b>Введите ваш ID {platform}:</b>", reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_account_id)


def get_account_id(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    temp_data.setdefault(msg.chat.id, {})["account_id"] = f"{platform} | {msg.text.strip()}"
    send_msg(msg.chat.id, f"{EMOJI['money']} <b>Введите сумму</b>\n\nОт <b>{MIN_DEPOSIT}</b> до <b>{MAX_DEPOSIT}</b> сом", reply_markup=back_menu())
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
        send_msg(msg.chat.id, f"{EMOJI['cross']} Сумма от {MIN_DEPOSIT} до {MAX_DEPOSIT} сом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return

    final = round(base + round(random.randint(10, 99) / 100.0, 2), 2)
    user_id = msg.chat.id
    account_id = temp_data.get(user_id, {}).get("account_id", "Не указан")
    temp_data[user_id]["amount"] = final

    qr = get_last_qr()
    if qr:
        send_media_bulletproof(user_id, qr, caption=f"{EMOJI['wallet']} <b>ОПЛАТИТЕ РОВНО {final:.2f} сом</b>\n{EMOJI['clock']} 5 минут")

    banks = types.InlineKeyboardMarkup(row_width=1)
    banks.add(
        ibtn(
            "O! Bank", 
            url=PAY_LINK, 
            style="primary", 
            icon_id="5224257782013769471"
        )
    )

    text = f"""{EMOJI['wallet']} <b>К оплате: {final:.2f} KGS</b>

{EMOJI['clock']} Реквизиты актуальны <b>5 минут</b>
{EMOJI['money']} Переведите <u>точную сумму</u> с копейками

🆔 Счёт: <code>{safe_html(account_id)}</code>

Оплатите по кнопке ниже через <b>O! Bank</b>.
После оплаты пришлите <b>скриншот чека</b>."""
    send_msg(user_id, text, reply_markup=banks)
    send_msg(user_id, "⏳ Ожидаем чек…\nНажмите «🔙 Назад» для отмены.", reply_markup=back_menu())

    if user_id in payment_timers:
        try:
            payment_timers[user_id].cancel()
        except Exception:
            pass
    timer = threading.Timer(300, cancel_payment, args=[user_id])
    payment_timers[user_id] = timer
    timer.start()
    bot.register_next_step_handler(msg, get_check_photo)


def get_check_photo(msg):
    user_id = msg.chat.id
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        if user_id in payment_timers:
            try:
                payment_timers[user_id].cancel()
            except Exception:
                pass
            payment_timers.pop(user_id, None)
        start(msg)
        return

    photo_id = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    if not photo_id:
        send_msg(user_id, f"{EMOJI['cross']} Отправьте фото или файл чека!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_check_photo)
        return

    if user_id in payment_timers:
        try:
            payment_timers[user_id].cancel()
        except Exception:
            pass
        payment_timers.pop(user_id, None)

    account_id = temp_data.get(user_id, {}).get("account_id")
    amount = temp_data.get(user_id, {}).get("amount")
    if not account_id or not amount:
        send_msg(user_id, f"{EMOJI['cross']} Ошибка данных. Начните заново.")
        start(msg)
        return

    touch_user(msg)
    dep_id = add_deposit(user_id, amount, account_id, photo_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        ibtn("Одобрить", f"approve_{dep_id}", style="success", icon_id="6273749318717412886"),
        ibtn("Отклонить", f"reject_{dep_id}", style="danger")
    )
    caption = (f"{EMOJI['lightning']} <b>ЗАЯВКА #{dep_id}</b>\n\n"
               f"👤 Игрок: {user_label(user_id)}\n"
               f"{EMOJI['money']} Сумма: {amount:.2f} сом\n"
               f"🆔 {safe_html(account_id)}")
    for admin in get_admins():
        send_media_bulletproof(admin, photo_id, caption=caption, reply_markup=markup)

    send_msg(user_id,
             f"""{EMOJI['check']} <b>Заявка принята!</b>

🆔 Счёт: <code>{safe_html(account_id)}</code>
💰 Сумма: <b>{amount:.2f} KGS</b>

⏳ Оператор проверяет платёж.
Обычно это занимает несколько минут.""",
             reply_markup=reply_main_menu(user_id))
    temp_data.pop(user_id, None)


@bot.message_handler(func=lambda m: m.text in ["💰 Вывести", "📤 Вывести", "Вывести"])
def withdraw_start(msg):
    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.")
        return
    temp_data[msg.chat.id] = {}
    send_msg(msg.chat.id, f"{EMOJI['info']} <b>Выберите букмекера для вывода:</b>", reply_markup=platform_kb())
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
        send_msg(msg.chat.id, f"{EMOJI['cross']} Выберите 1xBet или Melbet", reply_markup=platform_kb())
        bot.register_next_step_handler(msg, withdraw_choose_platform)
        return
    temp_data[msg.chat.id] = {"platform": platform}
    send_msg(msg.chat.id, f"{EMOJI['qr']} <b>Отправьте QR код кошелька:</b>", reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_elqr)


def withdraw_get_elqr(msg):
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        start(msg)
        return
    elqr = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    if not elqr:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте изображение QR!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_elqr)
        return
    temp_data.setdefault(msg.chat.id, {})["elqr"] = elqr
    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    send_msg(msg.chat.id, f"{EMOJI['info']} <b>Отправьте ваш ID {platform}:</b>", reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_id_text)


def withdraw_get_id_text(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    temp_data.setdefault(msg.chat.id, {})["id_photo"] = f"{platform} | {msg.text.strip()}"

    img = get_withdraw_image()
    if img:
        send_media_bulletproof(msg.chat.id, img)

    instruction = f"""📖 <b>Вывод · {platform}</b>

1. Настройки → Вывести со счёта
2. Способ: <b>MOBCASH / LMWPAY</b>
3. Укажите сумму
4. Город: <b>Бишкек</b>
5. Улица: <b>DiamondPAY KG</b>
6. Подтвердите и получите код
7. Отправьте код в этот бот

🏙 Бишкек · 📍 DiamondPAY KG
🕒 24/7 · 📩 оператор"""
    send_msg(msg.chat.id, instruction, reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_code)


def withdraw_get_code(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    user_id = msg.chat.id
    elqr = temp_data.get(user_id, {}).get("elqr")
    id_photo = temp_data.get(user_id, {}).get("id_photo")
    code = msg.text.strip()
    if not elqr or not id_photo:
        send_msg(user_id, f"{EMOJI['cross']} Данные утеряны. Начните снова.")
        start(msg)
        return
    touch_user(msg)
    w_id = add_withdrawal(user_id, elqr, id_photo, code)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        ibtn("Готово", f"w_done_{w_id}", style="success", icon_id="6273749318717412886"),
        ibtn("Отказать", f"w_cancel_{w_id}", style="danger")
    )
    caption = (f"{EMOJI['withdraw']} <b>ВЫВОД #{w_id}</b>\n\n"
               f"👤 Игрок: {user_label(user_id)}\n"
               f"🆔 <code>{safe_html(id_photo)}</code>\n"
               f"{EMOJI['key']} Код: <code>{safe_html(code)}</code>")
    for admin in get_admins():
        send_media_bulletproof(admin, elqr, caption=caption, reply_markup=markup)
    send_msg(user_id,
             f"{EMOJI['check']} <b>Заявка на вывод принята!</b>\n\n⏳ Ожидайте выплаты. Обычно это быстро.",
             reply_markup=reply_main_menu(user_id))
    temp_data.pop(user_id, None)


@bot.message_handler(commands=["admin"])
@bot.message_handler(func=lambda m: m.text in ["⚙️ Admin", "Admin"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def admin_panel(msg):
    uid = msg.from_user.id
    send_msg(msg.chat.id, f"{EMOJI['admin']} <b>Панель администратора</b>\n\nКоманда: /admin\nID: <code>{uid}</code>", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: m.text in ["➕ Админ", "Админ"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def add_admin_btn(msg):
    send_msg(msg.chat.id, f"{EMOJI['info']} ID нового администратора:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, process_add_admin)


def process_add_admin(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    try:
        add_admin(int(msg.text.strip()))
        send_msg(msg.chat.id, f"{EMOJI['check']} Админ добавлен!", reply_markup=admin_menu())
    except Exception:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Некорректный ID!", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: m.text in ["➖ Удалить админа", "Удалить админа"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def remove_admin_btn(msg):
    if msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Только главный админ.")
        return
    send_msg(msg.chat.id, f"{EMOJI['info']} ID для удаления:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, process_remove_admin)


def process_remove_admin(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    try:
        admin_id = int(msg.text.strip())
        if admin_id == MAIN_ADMIN:
            send_msg(msg.chat.id, f"{EMOJI['cross']} Нельзя удалить главного!", reply_markup=admin_menu())
            return
        remove_admin(admin_id)
        send_msg(msg.chat.id, f"{EMOJI['check']} Админ <code>{admin_id}</code> удалён!", reply_markup=admin_menu())
    except Exception:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Некорректный ID!", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: ("ВЫКЛ" in (m.text or "") or "ВКЛ" in (m.text or "")) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def toggle_bot(msg):
    active = "ВКЛ" in msg.text
    set_bot_active(active)
    send_msg(msg.chat.id, f"{EMOJI['on'] if active else EMOJI['off']} Бот {'ВКЛЮЧЕН' if active else 'ВЫКЛЮЧЕН'}", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: "Изменить QR" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_qr(msg):
    send_msg(msg.chat.id, f"{EMOJI['qr']} Отправьте новый QR:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, save_new_qr)


def save_new_qr(msg):
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        admin_panel(msg)
        return
    file_id = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    if file_id:
        save_qr(file_id)
        send_msg(msg.chat.id, f"{EMOJI['check']} QR сохранён!", reply_markup=admin_menu())
    else:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте изображение!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, save_new_qr)


@bot.message_handler(func=lambda m: "Инструкция вывода" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_withdraw_image(msg):
    send_msg(msg.chat.id, f"{EMOJI['qr']} Картинка инструкции:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, save_new_withdraw_image)


def save_new_withdraw_image(msg):
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        admin_panel(msg)
        return
    file_id = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    if file_id:
        save_withdraw_image(file_id)
        send_msg(msg.chat.id, f"{EMOJI['check']} Инструкция сохранена!", reply_markup=admin_menu())
    else:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте изображение!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, save_new_withdraw_image)


@bot.message_handler(func=lambda m: m.text in ["📋 Заявки", "Заявки"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def view_requests(msg):
    deposits = get_pending_deposits()
    if not deposits:
        send_msg(msg.chat.id, f"{EMOJI['check']} Нет активных заявок.")
        return
    for dep in deposits:
        dep_id, user_id, amount, account_id, photo_id, date, ts = dep
        markup = types.InlineKeyboardMarkup()
        markup.add(
            ibtn("Одобрить", f"approve_{dep_id}", style="success", icon_id="6273749318717412886"),
            ibtn("Отклонить", f"reject_{dep_id}", style="danger")
        )
        caption = (f"{EMOJI['lightning']} <b>ЗАЯВКА #{dep_id}</b>\n\n"
                   f"👤 Игрок: {user_label(user_id)}\n"
                   f"{EMOJI['money']} {amount:.2f} сом\n"
                   f"🆔 {safe_html(account_id)}")
        send_media_bulletproof(msg.chat.id, photo_id, caption=caption, reply_markup=markup)


@bot.message_handler(func=lambda m: "Статистика" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def stats(msg):
    s = get_stats()
    send_msg(msg.chat.id,
             f"""{EMOJI['stats']} <b>СТАТИСТИКА</b>

👥 Пользователей: <b>{s['users']}</b>
{EMOJI['clock']} В очереди: <b>{s['pending']}</b>
{EMOJI['money']} Объём: <b>{s['total']:.2f} сом</b>""")


@bot.message_handler(func=lambda m: "Рассылка" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def broadcast_start(msg):
    send_msg(msg.chat.id, f"{EMOJI['broadcast']} Сообщение для рассылки:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, broadcast_send)


def broadcast_send(msg):
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        admin_panel(msg)
        return
    users = get_all_users()
    success = 0
    photo_id = msg.photo[-1].file_id if msg.photo else None
    text = msg.caption or msg.text or ""
    for uid in users:
        try:
            if photo_id:
                bot.send_photo(uid, photo_id, caption=text)
            elif text:
                bot.send_message(uid, text)
            success += 1
        except Exception:
            pass
        time.sleep(0.03)
    send_msg(msg.chat.id, f"{EMOJI['check']} Рассылка: {success}/{len(users)}", reply_markup=admin_menu())


@bot.message_handler(func=lambda m: m.text in ["📩 Обращения", "Обращения"] and (m.from_user.id in get_admins() or m.from_user.id in (MAIN_ADMIN, OPERATOR_ID)))
def operator_tickets(msg):
    rows = list_tickets(limit=15)
    if not rows:
        send_msg(msg.chat.id, "✅ Нет обращений.")
        return
    status_map = {"new": "🆕 Новое", "work": "🔄 В работе", "closed": "✅ Закрыто"}
    for tid, user_id, username, message, status, created in rows:
        st = status_map.get(status, status)
        uname = f"@{username}" if username else str(user_id)
        kb = types.InlineKeyboardMarkup()
        if status != "closed":
            kb.row(
                ibtn("В работу", f"tkt_work_{tid}", style="primary"),
                ibtn("Ответить", f"tkt_reply_{tid}", style="success"),
            )
            kb.row(ibtn("Закрыть", f"tkt_close_{tid}", style="danger"))
        send_msg(
            msg.chat.id,
            f"🆘 <b>#{tid}</b> · {st}\n"
            f"👤 {uname} · <code>{user_id}</code>\n"
            f"📅 {created}\n\n"
            f"💬 {safe_html(message[:500])}",
            reply_markup=kb if status != "closed" else None,
        )


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("tkt_"))
def ticket_callbacks(call):
    if call.from_user.id not in get_admins() and call.from_user.id not in (MAIN_ADMIN, OPERATOR_ID):
        bot.answer_callback_query(call.id, "Нет прав")
        return
    parts = call.data.split("_")
    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Ошибка")
        return
    action = parts[1]
    tid = int(parts[2])
    row = get_ticket(tid)
    if not row:
        bot.answer_callback_query(call.id, "Не найдено")
        return
    user_id = row[1]

    if action == "work":
        set_ticket_status(tid, "work")
        bot.answer_callback_query(call.id, "В работе")
        send_msg(user_id, f"🔄 Обращение #{tid} взято в работу.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    if action == "close":
        set_ticket_status(tid, "closed")
        bot.answer_callback_query(call.id, "Закрыто")
        send_msg(user_id, f"✅ Обращение #{tid} закрыто.")
        try:
            bot.edit_message_text((call.message.text or "") + "\n\n✅ <b>Закрыто</b>", call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return

    if action == "reply":
        bot.answer_callback_query(call.id)
        send_msg(call.from_user.id, f"✍️ Ответ для обращения #{tid}:\nНапишите текст ответа.")
        temp_data[call.from_user.id] = {"reply_ticket": tid}
        bot.register_next_step_handler_by_chat_id(call.from_user.id, operator_send_reply)
        return


def operator_send_reply(msg):
    if not msg.text or msg.text.startswith("/start"):
        start(msg)
        return
    tid = temp_data.get(msg.chat.id, {}).get("reply_ticket")
    if not tid:
        send_msg(msg.chat.id, "❌ Сессия ответа сброшена.")
        return
    row = get_ticket(tid)
    if not row:
        send_msg(msg.chat.id, "❌ Обращение не найдено.")
        return
    user_id = row[1]
    answer = msg.text.strip()
    add_ticket_reply(tid, True, answer)
    set_ticket_status(tid, "work")
    
    res = send_msg(user_id, f"💬 <b>Ответ оператора</b> (обращение #{tid})\n\n{safe_html(answer)}")
    if not res:
        send_msg(msg.chat.id, f"❌ Не удалось доставить сообщение пользователю {user_id}.")
        return
    send_msg(msg.chat.id, f"✅ Ответ отправлен пользователю (#{tid}).", reply_markup=admin_menu())
    temp_data.pop(msg.chat.id, None)


@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_', 'w_done_', 'w_cancel_')))
def handle_admin_callbacks(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "❌ Нет прав!")
        return
    data = call.data

    if data.startswith('approve_'):
        dep_id = int(data.split('_')[1])
        with get_db() as conn:
            row = conn.execute('SELECT user_id, amount, account_id, timestamp, status FROM deposits WHERE id = ?', (dep_id,)).fetchone()
            if not row or row[4] != 'pending':
                bot.answer_callback_query(call.id, "Заявка уже обработана!")
                return
            user_id, amount, account_id, ts, _ = row
            conn.execute('UPDATE deposits SET status = "approved" WHERE id = ?', (dep_id,))
            conn.commit()

        bot.answer_callback_query(call.id, "✅ Одобрено!")
        elapsed = int(time.time()) - ts
        send_msg(user_id,
                 f"""{EMOJI['check']} <b>Баланс успешно пополнен!</b>

💰 Сумма: <b>{amount:.2f} KGS</b>
🆔 Счёт: <code>{safe_html(account_id)}</code>
⏱ Время: <b>{elapsed} сек</b>

🚀 Спасибо, что выбрали <b>{BOT_NAME}</b>!""")

        ref_id = get_referrer(user_id)
        if ref_id:
            bonus = round(float(amount) * REF_PERCENT / 100.0, 2)
            if bonus > 0:
                add_ref_bonus(ref_id, bonus, float(amount))

        try:
            bot.edit_message_caption(f"{EMOJI['check']} #{dep_id} ОДОБРЕНА", call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif data.startswith('reject_'):
        dep_id = int(data.split('_')[1])
        with get_db() as conn:
            row = conn.execute('SELECT user_id, amount, status FROM deposits WHERE id = ?', (dep_id,)).fetchone()
            if not row or row[2] != 'pending':
                bot.answer_callback_query(call.id, "Заявка уже обработана!")
                return
            user_id, amount, _ = row
            conn.execute('UPDATE deposits SET status = "rejected" WHERE id = ?', (dep_id,))
            conn.commit()

        bot.answer_callback_query(call.id, "❌ Отклонено!")
        send_msg(user_id, f"{EMOJI['cross']} Заявка на {amount:.2f} сом отклонена!\n\n{EMOJI['support']} Поддержка: оператор")
        try:
            bot.edit_message_caption(f"{EMOJI['cross']} #{dep_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif data.startswith('w_done_'):
        w_id = int(data.split('_')[2])
        with get_db() as conn:
            row = conn.execute('SELECT user_id, id_photo, status FROM withdrawals WHERE id = ?', (w_id,)).fetchone()
            if not row or row[2] != 'pending':
                bot.answer_callback_query(call.id, "Уже обработано!")
                return
            conn.execute('UPDATE withdrawals SET status = "completed" WHERE id = ?', (w_id,))
            conn.commit()

        bot.answer_callback_query(call.id, "✅ Выполнено")
        send_msg(row[0], f"""{EMOJI['check']} <b>Вывод выполнен</b>\n\n🆔 <code>{safe_html(row[1])}</code>\n{EMOJI['money']} Статус: <b>Готово</b>""")
        try:
            bot.edit_message_caption(f"{EMOJI['check']} ВЫВОД #{w_id} ГОТОВ", call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif data.startswith('w_cancel_'):
        w_id = int(data.split('_')[2])
        with get_db() as conn:
            row = conn.execute('SELECT user_id, status FROM withdrawals WHERE id = ?', (w_id,)).fetchone()
            if not row or row[1] != 'pending':
                bot.answer_callback_query(call.id, "Уже обработано!")
                return
            conn.execute('UPDATE withdrawals SET status = "rejected" WHERE id = ?', (w_id,))
            conn.commit()

        bot.answer_callback_query(call.id, "❌ Отклонено")
        send_msg(row[0], f"{EMOJI['cross']} Заявка на вывод #{w_id} была отклонена.")
        try:
            bot.edit_message_caption(f"{EMOJI['cross']} ВЫВОД #{w_id} ОТКЛОНЕН", call.message.chat.id, call.message.message_id)
        except Exception:
            pass


@app.route("/", methods=["GET", "POST"])
def health_check():
    return jsonify({"status": "ok", "bot": BOT_NAME}), 200


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Бот запущен...")
    bot.infinity_polling(skip_pending=True)
