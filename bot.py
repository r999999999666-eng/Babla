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
SUPPORT = "@Kevin001KG"
BOT_NAME = "Tezpay"

# Премиум эмодзи (HTML)
EMOJI = {
    "star": '<tg-emoji emoji-id="5368324170671202286">⭐</tg-emoji>',
    "vip": '<tg-emoji emoji-id="5368324170671202287">👑</tg-emoji>',
    "gem": '<tg-emoji emoji-id="5368324170671202288">💎</tg-emoji>',
    "sparkles": '<tg-emoji emoji-id="5368324170671202289">✨</tg-emoji>',
    "wallet": '<tg-emoji emoji-id="5368324170671202290">👛</tg-emoji>',
    "deposit": '<tg-emoji emoji-id="5368324170671202291">📥</tg-emoji>',
    "withdraw": '<tg-emoji emoji-id="5368324170671202292">📤</tg-emoji>',
    "support": '<tg-emoji emoji-id="5368324170671202293">👨‍💻</tg-emoji>',
    "admin": '<tg-emoji emoji-id="5368324170671202294">⚙️</tg-emoji>',
    "money": '<tg-emoji emoji-id="5368324170671202295">💸</tg-emoji>',
    "fire": '<tg-emoji emoji-id="5368324170671202296">🔥</tg-emoji>',
    "target": '<tg-emoji emoji-id="5368324170671202297">🎯</tg-emoji>',
    "check": '<tg-emoji emoji-id="5368324170671202298">✅</tg-emoji>',
    "cross": '<tg-emoji emoji-id="5368324170671202299">❌</tg-emoji>',
    "clock": '<tg-emoji emoji-id="5368324170671202300">⏳</tg-emoji>',
    "rocket": '<tg-emoji emoji-id="5368324170671202301">🚀</tg-emoji>',
    "lightning": '<tg-emoji emoji-id="5368324170671202302">⚡️</tg-emoji>',
    "stats": '<tg-emoji emoji-id="5368324170671202303">📈</tg-emoji>',
    "broadcast": '<tg-emoji emoji-id="5368324170671202304">📢</tg-emoji>',
    "qr": '<tg-emoji emoji-id="5368324170671202305">🖼</tg-emoji>',
    "off": '<tg-emoji emoji-id="5368324170671202306">🔴</tg-emoji>',
    "on": '<tg-emoji emoji-id="5368324170671202307">🟢</tg-emoji>',
    "info": '<tg-emoji emoji-id="5368324170671202308">ℹ️</tg-emoji>',
    "key": '<tg-emoji emoji-id="5368324170671202309">🔑</tg-emoji>'
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
                        chat_id INTEGER PRIMARY KEY, join_date TEXT, balance REAL DEFAULT 0.0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS deposits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
                        account_id TEXT, photo_id TEXT, status TEXT, date TEXT, timestamp INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS qr_codes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, elqr_photo TEXT,
                        id_photo TEXT, sms_code TEXT, status TEXT, date TEXT)''')
        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (MAIN_ADMIN,))
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("bot_active", "True")')
        conn.commit()
    logger.info("База данных готова")

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

def add_user(chat_id):
    with get_db() as conn:
        if not conn.execute('SELECT 1 FROM users WHERE chat_id = ?', (chat_id,)).fetchone():
            conn.execute('INSERT INTO users (chat_id, join_date) VALUES (?, ?)',
                         (chat_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
            conn.commit()
            return True
        return False

def get_all_users():
    with get_db() as conn:
        return [r[0] for r in conn.execute('SELECT chat_id FROM users').fetchall()]

def add_admin(chat_id):
    with get_db() as conn:
        conn.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (chat_id,))
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
    logger.info(f"QR очищен и сохранён: {file_id}")

def get_last_qr():
    with get_db() as conn:
        row = conn.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1').fetchone()
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
                    conn.execute('UPDATE deposits SET photo_id = NULL WHERE photo_id = ?', (file_id,))
                    conn.commit()
            except:
                pass
            if caption:
                return send_msg(chat_id, caption, reply_markup)
            return None

def cancel_payment(user_id):
    temp_data.pop(user_id, None)
    payment_timers.pop(user_id, None)
    try:
        send_msg(user_id, f"{EMOJI['clock']} <b>ВРЕМЯ ОПЛАТЫ ИСТЕКЛО!</b>\n\nЗаявка автоматически отменена.")
    except:
        pass

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📥 Пополнить", "📤 Вывести")
    markup.add("👨‍💻 Поддержка")
    if user_id in get_admins() or user_id == MAIN_ADMIN:
        markup.add("⚙️ Admin")
    return markup

def admin_menu():
    active = is_bot_active()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Заявки", "📈 Статистика")
    markup.add("🖼 Изменить QR", "➕ Админ")
    markup.add("📢 Рассылка")
    markup.add("🔴 ВЫКЛ" if active else "🟢 ВКЛ")
    markup.add("🔙 Главное меню")
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Назад")
    return markup

@bot.message_handler(commands=['start'])
def start(msg):
    chat_id = msg.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    if chat_id in payment_timers:
        try:
            payment_timers[chat_id].cancel()
        except:
            pass
        payment_timers.pop(chat_id, None)
    temp_data[chat_id] = {}

    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(chat_id, f"{EMOJI['off']} <b>Бот временно отключен на техническое обслуживание.</b>")
        return

    add_user(chat_id)
    welcome = f"""{EMOJI['sparkles']} Приветствуем в <b>{BOT_NAME}</b>! {EMOJI['vip']}

{EMOJI['money']} <b>Быстрое пополнение и моментальные выводы!</b>

{EMOJI['gem']} <b>Защищенные транзакции</b>
{EMOJI['rocket']} <b>Пополнение:</b> 5-15 сек 
{EMOJI['lightning']} <b>Быстрые выводы</b>

{EMOJI['star']} Работаем <b>24/7</b> без перерывов!

{EMOJI['support']} <b>Оператор поддержки:</b> {SUPPORT}"""
    send_msg(chat_id, welcome, reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text in ["👨‍💻 Поддержка", "Поддержка"])
def support_handler(msg):
    send_msg(msg.chat.id,
             f"{EMOJI['support']} <b>Служба поддержки:</b> {SUPPORT}\n{EMOJI['sparkles']} Пишите по любым вопросам!",
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
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("1xBet 🏆", callback_data="dep_bk_1xbet"),
        types.InlineKeyboardButton("Melbet 🎯", callback_data="dep_bk_melbet")
    )
    send_msg(msg.chat.id, f"{EMOJI['target']} <b>Выберите букмекера для пополнения:</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["dep_bk_1xbet", "dep_bk_melbet"])
def deposit_select_bk(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bk_name = "1xBet" if call.data == "dep_bk_1xbet" else "Melbet"
    temp_data.setdefault(chat_id, {})["platform"] = bk_name
    send_msg(chat_id, f"{EMOJI['info']} <b>Введите ваш ID аккаунта {bk_name}:</b>", reply_markup=back_menu())
    bot.register_next_step_handler_by_chat_id(chat_id, get_account_id)

def get_account_id(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    bk = temp_data.get(msg.chat.id, {}).get("platform", "1xBet")
    temp_data.setdefault(msg.chat.id, {})["account_id"] = f"{bk} | {msg.text.strip()}"
    send_msg(msg.chat.id, f"{EMOJI['money']} <b>Введите сумму для пополнения (от 100 до 500 000 сом):</b>",
             reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_amount)

def get_amount(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    try:
        base = float(msg.text.replace(',', '.'))
    except:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Введите корректное число!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
    if not (100 <= base <= 500000):
        send_msg(msg.chat.id, f"{EMOJI['cross']} Сумма должна быть от 100 до 500 000 сом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return

    final = round(base + round(random.randint(10, 99) / 100.0, 2), 2)
    user_id = msg.chat.id
    account_id = temp_data.get(user_id, {}).get("account_id", "Не указан")
    temp_data[user_id]["amount"] = final

    qr = get_last_qr()
    caption_qr = f"{EMOJI['wallet']} <b>ОПЛАТИТЕ РОВНО {final:.2f} сом</b>\n{EMOJI['clock']} 5 минут на оплату"
    if qr:
        send_media_bulletproof(user_id, qr, caption=caption_qr)
    else:
        send_msg(user_id, f"{EMOJI['qr']} QR-код пока не загружен администратором.")

    text = f"""{EMOJI['sparkles']} <b>Прикрепите скриншот чека</b>

━━━━━━━━━━━━━━━━━━━━━

🆔 <b>Счет:</b> <code>{safe_html(account_id)}</code>
{EMOJI['money']} <b>К оплате:</b> <code>{final:.2f}</code> сом {EMOJI['check']}

⚠️ <b>ВАЖНО:</b> Переводите <u>ровную сумму с копейками</u> ({final:.2f} сом)!

━━━━━━━━━━━━━━━━━━━━━

{EMOJI['clock']} <b>Оплатите и отправьте скриншот чека в течение 5 минут!</b>"""
    send_msg(user_id, text, reply_markup=back_menu())

    if user_id in payment_timers:
        try:
            payment_timers[user_id].cancel()
        except:
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
            except:
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
        except:
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
    caption = (f"{EMOJI['lightning']} <b>ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id}</b>\n\n"
               f"👤 Юзер: {user_id}\n"
               f"{EMOJI['money']} Сумма: {amount:.2f} сом\n"
               f"🆔 {safe_html(account_id)}")
    for admin in get_admins():
        send_media_bulletproof(admin, photo_id, caption=caption, reply_markup=markup)

    send_msg(user_id,
             f"{EMOJI['check']} <b>ЗАЯВКА ПРИНЯТА!</b>\n\n"
             f"🆔 {safe_html(account_id)}\n"
             f"{EMOJI['money']} СУММА: {amount:.2f} сом\n\n"
             f"{EMOJI['clock']} ОЖИДАЙТЕ ОБРАБОТКИ ОПЕРАТОРОМ...",
             reply_markup=main_menu(user_id))
    temp_data.pop(user_id, None)

# ==================== ВЫВОД ====================
@bot.message_handler(func=lambda m: m.text in ["📤 Вывести", "Вывести"])
def withdraw_start(msg):
    if not is_bot_active() and msg.from_user.id not in get_admins() and msg.from_user.id != MAIN_ADMIN:
        send_msg(msg.chat.id, f"{EMOJI['off']} Бот на тех. обслуживании.")
        return
    temp_data[msg.chat.id] = {}
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("1xBet 🏆", callback_data="wd_bk_1xbet"),
        types.InlineKeyboardButton("Melbet 🎯", callback_data="wd_bk_melbet")
    )
    send_msg(msg.chat.id, f"{EMOJI['target']} <b>Выберите букмекера для вывода:</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["wd_bk_1xbet", "wd_bk_melbet"])
def withdraw_select_bk(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    bk_name = "1xBet" if call.data == "wd_bk_1xbet" else "Melbet"
    temp_data.setdefault(chat_id, {})["platform"] = bk_name
    send_msg(chat_id, f"{EMOJI['qr']} <b>Отправьте QR код вашего кошелька:</b>", reply_markup=back_menu())
    bot.register_next_step_handler_by_chat_id(chat_id, withdraw_get_elqr)

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
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте изображение QR-кода!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_elqr)
        return
    temp_data.setdefault(msg.chat.id, {})["elqr"] = elqr
    bk = temp_data.get(msg.chat.id, {}).get("platform", "1xBet")
    send_msg(msg.chat.id, f"{EMOJI['info']} <b>Отправьте ваш ID {bk}:</b>", reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_id_text)

def withdraw_get_id_text(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text.strip():
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте корректный ID!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_id_text)
        return
    bk = temp_data.get(msg.chat.id, {}).get("platform", "1xBet")
    temp_data.setdefault(msg.chat.id, {})["id_photo"] = f"{bk} | {msg.text.strip()}"
    instruction = f"""📍Заходим👇
📍1. Настройки!
📍2. Вывести со счета!
📍3. Наличные
📍4. Сумму для Вывода!
<b>Город: Бишкек</b>
<b>Улица: {BOT_NAME}</b>
📍5. Подтвердить
📍6. Получить Код!
📍7. Отправить его в бота"""
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
        send_msg(user_id, f"{EMOJI['cross']} Данные утеряны. Попробуйте снова.")
        start(msg)
        return
    w_id = add_withdrawal(user_id, elqr, id_photo, code)
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Готово", callback_data=f"w_done_{w_id}"),
        types.InlineKeyboardButton("❌ Отказать", callback_data=f"w_cancel_{w_id}")
    )
    caption = (f"{EMOJI['withdraw']} <b>ЗАЯВКА НА ВЫВОД #{w_id}</b>\n\n"
               f"👤 Юзер: {user_id}\n"
               f"🆔 Счет: <code>{safe_html(id_photo)}</code>\n"
               f"{EMOJI['key']} Код: <code>{safe_html(code)}</code>\n\n"
               f"💳 QR-код прикреплен выше.")
    for admin in get_admins():
        send_media_bulletproof(admin, elqr, caption=caption, reply_markup=markup)
    send_msg(user_id, f"{EMOJI['check']} Ваша заявка на вывод принята оператором! Ожидайте выплаты.",
             reply_markup=main_menu(user_id))
    temp_data.pop(user_id, None)

# ==================== АДМИН ====================
@bot.message_handler(func=lambda m: m.text in ["⚙️ Admin", "Admin"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def admin_panel(msg):
    send_msg(msg.chat.id, f"{EMOJI['admin']} <b>Панель администратора</b>", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text in ["➕ Админ", "Админ"] and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def add_admin_btn(msg):
    send_msg(msg.chat.id, f"{EMOJI['info']} Введите ID нового администратора:", reply_markup=back_menu())
    bot.register_next_step_handler(msg, process_add_admin)

def process_add_admin(msg):
    if not msg.text or msg.text.startswith('/start') or msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    try:
        add_admin(int(msg.text.strip()))
        send_msg(msg.chat.id, f"{EMOJI['check']} Администратор добавлен!", reply_markup=admin_menu())
    except:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Введите корректный числовой ID!", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: ("ВЫКЛ" in (m.text or "") or "ВКЛ" in (m.text or "")) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def toggle_bot(msg):
    active = "ВКЛ" in msg.text
    set_bot_active(active)
    send_msg(msg.chat.id, f"{EMOJI['on'] if active else EMOJI['off']} Бот {'ВКЛЮЧЕН' if active else 'ВЫКЛЮЧЕН'}",
             reply_markup=admin_menu())

@bot.message_handler(func=lambda m: "Изменить QR" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def change_qr(msg):
    send_msg(msg.chat.id, f"{EMOJI['qr']} Отправьте новый QR-код:", reply_markup=back_menu())
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
        send_msg(msg.chat.id, f"{EMOJI['check']} Новый QR-код сохранен!", reply_markup=admin_menu())
    else:
        send_msg(msg.chat.id, f"{EMOJI['cross']} Отправьте изображение!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, save_new_qr)

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
             f"{EMOJI['stats']} <b>СТАТИСТИКА</b>\n\n"
             f"👥 Пользователей: {s['users']}\n"
             f"{EMOJI['clock']} В очереди: {s['pending']}\n"
             f"{EMOJI['money']} Общий объем: {s['total']:.2f} сом")

@bot.message_handler(func=lambda m: "Рассылка" in (m.text or "") and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def broadcast_start(msg):
    send_msg(msg.chat.id, f"{EMOJI['broadcast']} <b>Отправьте сообщение для рассылки (текст или фото):</b>",
             reply_markup=back_menu())
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
        except:
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
                    f"{EMOJI['check']} <b>Ваш баланс успешно пополнен!</b>\n\n"
                    f"{EMOJI['money']} <b>Сумма:</b> {amount:.2f} сом\n"
                    f"<b>Счет:</b> {safe_html(account_id)}\n"
                    f"⏱️ <b>Обработано за:</b> {elapsed}s")
            except:
                pass
            try:
                bot.edit_message_caption(
                    f"{EMOJI['check']} ЗАЯВКА #{dep_id} ОДОБРЕНА",
                    call.message.chat.id, call.message.message_id)
            except:
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
                    f"{EMOJI['cross']} ЗАЯВКА НА {amount:.2f} сом ОТКЛОНЕНА!\n"
                    f"{EMOJI['support']} Помощь: {SUPPORT}")
            except:
                pass
            try:
                bot.edit_message_caption(
                    f"{EMOJI['cross']} ЗАЯВКА #{dep_id} ОТКЛОНЕНА",
                    call.message.chat.id, call.message.message_id)
            except:
                pass

    elif data.startswith('w_done_'):
        w_id = int(data.split('_')[2])
        with get_db() as conn:
            conn.execute('UPDATE withdrawals SET status = "completed" WHERE id = ?', (w_id,))
            row = conn.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,)).fetchone()
            conn.commit()
        if row:
            bot.answer_callback_query(call.id, "✅ Выполнено")
            try:
                bot.send_message(row[0], f"{EMOJI['check']} Заявка на вывод #{w_id} успешно обработана!")
            except:
                pass
        try:
            bot.edit_message_caption(
                f"{EMOJI['check']} ЗАЯВКА НА ВЫВОД #{w_id} ВЫПОЛНЕНА",
                call.message.chat.id, call.message.message_id)
        except:
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
                bot.send_message(row[0],
                    f"{EMOJI['cross']} Заявка на вывод #{w_id} отклонена. Поддержка: {SUPPORT}")
            except:
                pass
        try:
            bot.edit_message_caption(
                f"{EMOJI['cross']} ЗАЯВКА НА ВЫВОД #{w_id} ОТКЛОНЕНА",
                call.message.chat.id, call.message.message_id)
        except:
            pass

@app.route('/')
def home():
    return {"status": "ok", "bot": BOT_NAME}, 200

if __name__ == "__main__":
    try:
        bot.remove_webhook()
        time.sleep(1)
        logger.info("Webhook удалён")
    except Exception as e:
        logger.warning(f"remove_webhook: {e}")

    def run_flask():
        port = int(os.environ.get("PORT", 10000))
        app.run(host="0.0.0.0", port=port)

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask запущен")

    logger.info("🚀 Запускаю Tezpay...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=40)
        except Exception as e:
            logger.error(f"Ошибка polling: {e}")
            time.sleep(5)
