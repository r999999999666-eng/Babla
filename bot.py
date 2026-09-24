import os
import sqlite3
import time
import threading
import html
import random
import logging
from datetime import datetime
from flask import Flask
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN_REF") or os.environ.get("TOKEN")
if not TOKEN or len(TOKEN) < 40:
    logger.error("ТОКЕН НЕ НАЙДЕН!")
    raise SystemExit("No token")

MAIN_ADMIN = 8957913298
SUPPORT = "@DiamondPAY_HELP_bot"
BOT_NAME = "DiamondPAY"
MIN_DEPOSIT = 100
MAX_DEPOSIT = 500000
REF_PERCENT = 2.5  # % с пополнения друга
BOT_USERNAME = "DiamondPAY_KG_bot"

# Ссылка оплаты (dengi.o.kg) — одна на все банки, как в вашем примере
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111258120233520910129965023532261202111302123408%D0%9D%D0%A3%D0%A0%D0%AD%D0%9B%20%D0%9A.520473995303417540105906O%21Bank63044CEE",
)


def pe(eid, fb):
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


EMOJI = {
    "star": pe("5379607913046242841", "❄️"),
    "vip": pe("5400373628950840597", "❄️"),
    "gem": pe("5399942684817258282", "❄️"),
    "sparkles": pe("5379943126653761268", "❄️"),
    "wallet": pe("5215420556089776398", "👛"),
    "deposit": pe("5224257782013769471", "💰"),
    "withdraw": pe("5201691993775818138", "🛫"),
    "support": pe("5472239203590888751", "📩"),
    "admin": pe("5193177581888755275", "💻"),
    "money": pe("5224257782013769471", "💰"),
    "fire": pe("5201945242227472933", "⚡️"),
    "target": pe("5201732344993576400", "🌐"),
    "check": pe("6273749318717412886", "✅"),
    "cross": "❌",
    "clock": pe("5226830214020999125", "⚡️"),
    "rocket": pe("5188481279963715781", "🚀"),
    "lightning": pe("5201945242227472933", "⚡️"),
    "stats": pe("5224588661999282075", "💲"),
    "broadcast": pe("5472239203590888751", "📩"),
    "qr": pe("5193177581888755275", "💻"),
    "off": "🔴",
    "on": "🟢",
    "info": pe("5201732344993576400", "🌐"),
    "key": pe("5197269100878907942", "✍️"),
    "dollar": pe("5197434882321567830", "💵"),
    "exchange": pe("5377336227533969892", "💱"),
    "snow": pe("5397807437531086888", "❄️"),
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
                        referred_by INTEGER, ref_earned REAL DEFAULT 0.0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS deposits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
                        account_id TEXT, photo_id TEXT, status TEXT, date TEXT, timestamp INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS qr_codes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdraw_images (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, elqr_photo TEXT,
                        id_photo TEXT, sms_code TEXT, status TEXT, date TEXT)''')
        try:
            c.execute('ALTER TABLE users ADD COLUMN referred_by INTEGER')
        except Exception:
            pass
        try:
            c.execute('ALTER TABLE users ADD COLUMN ref_earned REAL DEFAULT 0.0')
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


def set_bot_active(status: bool):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES ("bot_active", ?)', (str(status),))
        conn.commit()


def get_admins():
    with get_db() as conn:
        admins = [r[0] for r in conn.execute('SELECT chat_id FROM admins').fetchall()]
        if MAIN_ADMIN not in admins:
            admins.append(MAIN_ADMIN)
        return admins


def add_user(chat_id, referred_by=None):
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM users WHERE chat_id = ?', (chat_id,)).fetchone():
            ref = None
            if referred_by and int(referred_by) != int(chat_id):
                if conn.execute('SELECT 1 FROM users WHERE chat_id = ?', (int(referred_by),)).fetchone():
                    ref = int(referred_by)
            conn.execute(
                'INSERT INTO users (chat_id, join_date, referred_by) VALUES (?, ?, ?)',
                (chat_id, datetime.now().strftime("%d.%m.%Y %H:%M"), ref),
            )
            conn.commit()
            return True
        return False


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
                   datetime.now().strftime("%d.%m.%Y %H:%M:%S"), int(time.time())))
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
                  (user_id, elqr, id_photo, code, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
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
                     (file_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit()


def get_last_qr():
    with get_db() as conn:
        row = conn.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else None


def save_withdraw_image(file_id):
    with get_db() as conn:
        conn.execute('DELETE FROM withdraw_images')
        conn.execute('INSERT INTO withdraw_images (file_id, date) VALUES (?, ?)',
                     (file_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
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
            try:
                with get_db() as conn:
                    conn.execute('DELETE FROM qr_codes WHERE file_id = ?', (file_id,))
                    conn.execute('DELETE FROM withdraw_images WHERE file_id = ?', (file_id,))
                    conn.execute('UPDATE deposits SET photo_id = NULL WHERE photo_id = ?', (file_id,))
                    conn.commit()
            except Exception:
                pass
            if caption:
                return send_msg(chat_id, caption, reply_markup)
            return None


def cancel_payment(user_id):
    temp_data.pop(user_id, None)
    payment_timers.pop(user_id, None)
    try:
        send_msg(user_id, f"{EMOJI['clock']} <b>ВРЕМЯ ОПЛАТЫ ИСТЕКЛО!</b>\n\nЗаявка автоматически отменена.")
    except Exception:
        pass


def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📥 Пополнить", "📤 Вывести")
    markup.add("🎁 Рефералы", "👨‍💻 Поддержка")
    if user_id in get_admins() or user_id == MAIN_ADMIN:
        markup.add("⚙️ Admin")
    return markup


def admin_menu():
    active = is_bot_active()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Заявки", "📈 Статистика")
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

    is_new = add_user(chat_id, referred_by=referred_by)
    name = msg.from_user.first_name or "друг"
    welcome = f"""{EMOJI['sparkles']} <b>Добро пожаловать в {BOT_NAME}</b> {EMOJI['vip']}

Привет, <b>{name}</b>!

━━━━━━━━━━━━━━━━━━━━
{EMOJI['target']} <b>1xBet</b> и <b>Melbet</b>
{EMOJI['gem']} Безопасные транзакции
{EMOJI['rocket']} Пополнение: 5–15 сек
{EMOJI['lightning']} Моментальные выводы
{EMOJI['money']} Мин. сумма: <b>{MIN_DEPOSIT}</b> сом
🎁 Реферал: <b>{REF_PERCENT}%</b> с пополнения друга
━━━━━━━━━━━━━━━━━━━━

{EMOJI['star']} Работаем <b>24/7</b>
{EMOJI['support']} Поддержка: {SUPPORT}"""
    send_msg(chat_id, welcome, reply_markup=main_menu(msg.from_user.id))


@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)



@bot.message_handler(func=lambda m: m.text in ["🎁 Рефералы", "Рефералы"])
def referral_info(msg):
    add_user(msg.chat.id)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{msg.chat.id}"
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(ref_earned, 0) FROM users WHERE chat_id = ?",
            (msg.chat.id,),
        ).fetchone()
        cnt = conn.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by = ?",
            (msg.chat.id,),
        ).fetchone()
    earned = float(row[0]) if row else 0.0
    count = int(cnt[0]) if cnt else 0
    send_msg(
        msg.chat.id,
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей — получайте <b>{REF_PERCENT}%</b> с их пополнений.\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"💰 Заработано: <b>{earned:.2f} KGS</b>",
        reply_markup=main_menu(msg.chat.id),
    )


@bot.message_handler(func=lambda m: m.text in ["👨‍💻 Поддержка", "Поддержка"])
def support_handler(msg):
    send_msg(msg.chat.id,
             f"{EMOJI['support']} <b>Служба поддержки</b>\n\n{SUPPORT}\n\nПишите по любым вопросам!",
             reply_markup=back_menu())


@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back_handler(msg):
    start(msg)


# ==================== ПОПОЛНЕНИЕ ====================
@bot.message_handler(func=lambda m: m.text in ["📥 Пополнить", "Пополнить"])
def deposit_start(msg):
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
                 f"{EMOJI['cross']} Сумма от {MIN_DEPOSIT} до {MAX_DEPOSIT} сом!",
                 reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return

    final = round(base + round(random.randint(10, 99) / 100.0, 2), 2)
    user_id = msg.chat.id
    account_id = temp_data.get(user_id, {}).get("account_id", "Не указан")
    temp_data[user_id]["amount"] = final

    # QR (если админ загрузил) — дополнительно
    qr = get_last_qr()
    if qr:
        send_media_bulletproof(
            user_id, qr,
            caption=f"{EMOJI['wallet']} <b>ОПЛАТИТЕ РОВНО {final:.2f} сом</b>\n{EMOJI['clock']} 5 минут",
        )

    # Кнопки банков (как на скрине)
    banks = types.InlineKeyboardMarkup(row_width=2)
    banks.add(
        types.InlineKeyboardButton("Mbank", url=PAY_LINK),
        types.InlineKeyboardButton("O! Bank", url=PAY_LINK),
    )
    banks.add(
        types.InlineKeyboardButton("BakAI", url=PAY_LINK),
        types.InlineKeyboardButton("MegaPay", url=PAY_LINK),
    )
    banks.add(types.InlineKeyboardButton("DemirBank", url=PAY_LINK))

    text = f"""💳 <b>К оплате: {final:.2f} KGS</b>

⚠️ Реквизиты актуальны в течение <b>5 минут</b>.
Выберите банк ниже и оплатите по ссылке.

━━━━━━━━━━━━━━━━━━━━
🆔 Счёт: <code>{safe_html(account_id)}</code>
⚠️ Переведите <u>точную сумму</u> с копейками
━━━━━━━━━━━━━━━━━━━━

После оплаты пришлите <b>скриншот чека</b>."""
    send_msg(user_id, text, reply_markup=banks)
    send_msg(user_id, f"{EMOJI['clock']} Ждём чек…", reply_markup=back_menu())

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

    photo_id = None
    if msg.photo:
        photo_id = msg.photo[-1].file_id
    elif msg.document:
        photo_id = msg.document.file_id
    else:
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

    dep_id = add_deposit(user_id, amount, account_id, photo_id)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
    )
    caption = (f"{EMOJI['lightning']} <b>ЗАЯВКА #{dep_id}</b>\n\n"
               f"👤 Юзер: {user_id}\n"
               f"{EMOJI['money']} Сумма: {amount:.2f} сом\n"
               f"🆔 {safe_html(account_id)}")
    for admin in get_admins():
        send_media_bulletproof(admin, photo_id, caption=caption, reply_markup=markup)

    send_msg(user_id,
             f"""{EMOJI['check']} <b>Заявка принята!</b>

━━━━━━━━━━━━━━━━━━━━
🆔 {safe_html(account_id)}
{EMOJI['money']} Сумма: <b>{amount:.2f} сом</b>
━━━━━━━━━━━━━━━━━━━━

{EMOJI['clock']} Ожидайте оператора""",
             reply_markup=main_menu(user_id))
    temp_data.pop(user_id, None)


# ==================== ВЫВОД ====================
@bot.message_handler(func=lambda m: m.text in ["📤 Вывести", "Вывести"])
def withdraw_start(msg):
    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.")
        return
    temp_data[msg.chat.id] = {}
    send_msg(msg.chat.id,
             f"{EMOJI['info']} <b>Выберите букмекера для вывода:</b>",
             reply_markup=platform_kb())
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
    elqr = None
    if msg.photo:
        elqr = msg.photo[-1].file_id
    elif msg.document:
        elqr = msg.document.file_id
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
    if not msg.text.strip():
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте ID!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_id_text)
        return
    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    temp_data.setdefault(msg.chat.id, {})["id_photo"] = f"{platform} | {msg.text.strip()}"

    img = get_withdraw_image()
    if img:
        send_media_bulletproof(msg.chat.id, img)

    instruction = f"""{EMOJI['info']} <b>Инструкция по выводу ({platform})</b>

1. Настройки
2. Вывести со счёта
3. <b>MOBCASH / DiamondPAY</b>
4. Укажите сумму
5. Город: <b>Бишкек</b>
6. Улица: <b>DiamondPAY KG</b>
7. Подтвердить
8. Получить код
9. Отправить код в бота

━━━━━━━━━━━━━━━━━━━━
🏙 Город: <b>Бишкек</b>
📍 Улица: <b>DiamondPAY KG</b>
💳 {BOT_NAME}
🕐 24/7
{EMOJI['support']} Помощь: {SUPPORT}"""
    send_msg(msg.chat.id, instruction, reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_code)


def withdraw_get_code(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text.strip():
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте код!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_code)
        return
    user_id = msg.chat.id
    elqr = temp_data.get(user_id, {}).get("elqr")
    id_photo = temp_data.get(user_id, {}).get("id_photo")
    code = msg.text.strip()
    if not elqr or not id_photo:
        send_msg(user_id, f"{EMOJI['cross']} Данные утеряны. Начните снова.")
        start(msg)
        return
    w_id = add_withdrawal(user_id, elqr, id_photo, code)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Готово", callback_data=f"w_done_{w_id}"),
        types.InlineKeyboardButton("❌ Отказать", callback_data=f"w_cancel_{w_id}")
    )
    caption = (f"{EMOJI['withdraw']} <b>ВЫВОД #{w_id}</b>\n\n"
               f"👤 Юзер: {user_id}\n"
               f"🆔 <code>{safe_html(id_photo)}</code>\n"
               f"{EMOJI['key']} Код: <code>{safe_html(code)}</code>")
    for admin in get_admins():
        send_media_bulletproof(admin, elqr, caption=caption, reply_markup=markup)
    send_msg(user_id, f"{EMOJI['check']} <b>Заявка на вывод принята!</b>\n\nОжидайте выплаты.",
             reply_markup=main_menu(user_id))
    temp_data.pop(user_id, None)


# ==================== АДМИН ====================
@bot.message_handler(func=lambda m: m.text in ["⚙️ Admin", "Admin"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def admin_panel(msg):
    send_msg(msg.chat.id, f"{EMOJI['admin']} <b>Панель администратора</b>", reply_markup=admin_menu())


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
    send_msg(msg.chat.id, f"{EMOJI['on'] if active else EMOJI['off']} Бот {'ВКЛЮЧЕН' if active else 'ВЫКЛЮЧЕН'}",
             reply_markup=admin_menu())


@bot.message_handler(func=lambda m: "Изменить QR" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_qr(msg):
    send_msg(msg.chat.id, f"{EMOJI['qr']} Отправьте новый QR:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, save_new_qr)


def save_new_qr(msg):
    if msg.text and (msg.text.startswith('/start') or msg.text == "🔙 Назад"):
        admin_panel(msg)
        return
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id
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
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id
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
            types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
        )
        caption = (f"{EMOJI['lightning']} <b>ЗАЯВКА #{dep_id}</b>\n\n"
                   f"👤 {user_id}\n"
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
        time.sleep(0.05)
    send_msg(msg.chat.id, f"{EMOJI['check']} Рассылка: {success}/{len(users)}", reply_markup=admin_menu())


@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_', 'w_done_', 'w_cancel_')))
def handle_admin_callbacks(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "❌ Нет прав!")
        return
    data = call.data

    if data.startswith('approve_'):
        dep_id = int(data.split('_')[1])
        with get_db() as conn:
            row = conn.execute(
                'SELECT user_id, amount, account_id, timestamp FROM deposits WHERE id = ?', (dep_id,)
            ).fetchone()
        if row:
            user_id, amount, account_id, ts = row
            update_deposit_status(dep_id, "approved")
            bot.answer_callback_query(call.id, "✅ Одобрено!")
            elapsed = int(time.time()) - ts
            try:
                bot.send_message(user_id,
                    f"""{EMOJI['check']} <b>Баланс пополнен!</b>

{EMOJI['money']} Сумма: <b>{amount:.2f} сом</b>
🆔 <code>{safe_html(account_id)}</code>
⏱️ {elapsed} сек

Спасибо за <b>{BOT_NAME}</b>!""")
            except Exception:
                pass
            # Реферальный бонус 2.5%
            ref_id = get_referrer(user_id)
            if ref_id:
                bonus = round(float(amount) * REF_PERCENT / 100.0, 2)
                if bonus > 0:
                    add_ref_bonus(ref_id, bonus, float(amount))
            try:
                bot.edit_message_caption(f"{EMOJI['check']} #{dep_id} ОДОБРЕНА",
                                         call.message.chat.id, call.message.message_id)
            except Exception:
                pass

    elif data.startswith('reject_'):
        dep_id = int(data.split('_')[1])
        with get_db() as conn:
            row = conn.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,)).fetchone()
        if row:
            user_id, amount = row
            update_deposit_status(dep_id, "rejected")
            bot.answer_callback_query(call.id, "❌ Отклонено!")
            try:
                bot.send_message(user_id,
                    f"{EMOJI['cross']} Заявка на {amount:.2f} сом отклонена!\n\n{EMOJI['support']} {SUPPORT}")
            except Exception:
                pass
            try:
                bot.edit_message_caption(f"{EMOJI['cross']} #{dep_id} ОТКЛОНЕНА",
                                         call.message.chat.id, call.message.message_id)
            except Exception:
                pass

    elif data.startswith('w_done_'):
        w_id = int(data.split('_')[2])
        with get_db() as conn:
            conn.execute('UPDATE withdrawals SET status = "completed" WHERE id = ?', (w_id,))
            row = conn.execute('SELECT user_id, id_photo FROM withdrawals WHERE id = ?', (w_id,)).fetchone()
            conn.commit()
        if row:
            bot.answer_callback_query(call.id, "✅ Выполнено")
            try:
                bot.send_message(row[0],
                    f"""{EMOJI['check']} <b>Вывод выполнен</b>

🆔 <code>{safe_html(row[1])}</code>
{EMOJI['money']} Статус: <b>Готово</b>""")
            except Exception:
                pass
        try:
            bot.edit_message_caption(f"{EMOJI['check']} ВЫВОД #{w_id} ГОТОВ",
                                     call.message.chat.id, call.message.message_id)
        except Exception:
            pass

    elif data.startswith('w_cancel_'):
        w_id = int(data.split('_')[2])
        with get_db() as conn:
            conn.execute('UPDATE withdrawals SET status = "rejected" WHERE id = ?', (w_id,))
            row = conn.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,)).fetchone()
            conn.commit()
        if row:
            bot.answer_callback_query(call.id, "❌ Отклонено")
            try:
                bot.send_message(row[0], f"{EMOJI['cross']} Вывод #{w_id} отклонён.\n\n{SUPPORT}")
            except Exception:
                pass
        try:
            bot.edit_message_caption(f"{EMOJI['cross']} ВЫВОД #{w_id} ОТКЛОНЁН",
                                     call.message.chat.id, call.message.message_id)
        except Exception:
            pass


@app.route('/')
def home():
    return {"status": "ok", "bot": BOT_NAME}, 200


if __name__ == "__main__":
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        logger.warning(f"remove_webhook: {e}")

    def run_flask():
        port = int(os.environ.get("PORT", 10000))
        app.run(host="0.0.0.0", port=port)

    threading.Thread(target=run_flask, daemon=True).start()

    logger.info(f"{BOT_NAME} started")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=40)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)
