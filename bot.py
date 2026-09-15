import os
import logging
import sqlite3
from datetime import datetime

import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("melbet")

TOKEN = os.environ.get("TOKEN") or os.environ.get("BOT_TOKEN") or ""
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "8957913298").split(",") if x.strip()]
SUPPORT_USERNAME = "@Bet1xbw"
MIN_DEPOSIT = int(os.environ.get("MIN_DEPOSIT", "15"))
BOT_NAME = "Melbet LMWPAY"

if not TOKEN or len(TOKEN) < 30:
    raise SystemExit("Укажите TOKEN")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
DB = "melbet.db"

support_mode = set()
reply_map = {}

# ─── PREMIUM EMOJI ────────────────────────────────────────
def pe(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

E = {
    "snow1": pe("5379607913046242841", "❄️"),
    "snow2": pe("5400373628950840597", "❄️"),
    "snow3": pe("5399942684817258282", "❄️"),
    "zap": pe("5201945242227472933", "⚡️"),
    "web": pe("5201732344993576400", "🌐"),
    "ok": pe("6273749318717412886", "✅"),
    "dollar": pe("5197434882321567830", "💵"),
    "plane": pe("5201691993775818138", "🛫"),
    "pc": pe("5193177581888755275", "💻"),
    "money": pe("5224257782013769471", "💰"),
    "exchange": pe("5377336227533969892", "💱"),
    "wallet": pe("5215420556089776398", "👛"),
    "mail": pe("5472239203590888751", "📩"),
    "rocket": pe("5188481279963715781", "🚀"),
    "write": pe("5197269100878907942", "✍️"),
}


def db():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            admin_msg_id INTEGER,
            created_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            melbet_id TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT
        )""")
        conn.commit()


def ensure_user(u):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, created_at) VALUES (?,?,?,?)",
            (u.id, u.username or "", u.full_name or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()


def main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("💎 Пополнение", "🚀 Вывод")
    kb.add("💬 Поддержка", "✨ Инфо")
    return kb


def cancel_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("❌ Отмена")
    return kb


def is_admin(uid):
    return uid in ADMIN_IDS


@bot.message_handler(commands=["start", "menu"])
def start(msg):
    ensure_user(msg.from_user)
    support_mode.discard(msg.from_user.id)
    name = msg.from_user.first_name or "друг"
    bot.send_message(
        msg.chat.id,
        f"{E['rocket']} <b>{BOT_NAME}</b>\n\n"
        f"Привет, <b>{name}</b>!\n\n"
        f"{E['web']} Букмекер: <b>Melbet</b>\n"
        f"{E['exchange']} Оплата: <b>LMWPAY</b>\n"
        f"{E['money']} Мин. сумма: <b>{MIN_DEPOSIT}</b>\n"
        f"{E['mail']} Поддержка: {SUPPORT_USERNAME}\n\n"
        f"Выберите действие 👇",
        reply_markup=main_kb(),
    )


@bot.message_handler(func=lambda m: m.text == "❌ Отмена")
def cancel(msg):
    support_mode.discard(msg.from_user.id)
    bot.send_message(msg.chat.id, f"{E['zap']} Отменено.", reply_markup=main_kb())


@bot.message_handler(func=lambda m: m.text in ["✨ Инфо", "ℹ️ Инфо"])
def info(msg):
    bot.send_message(
        msg.chat.id,
        f"{E['pc']} <b>Информация</b>\n\n"
        f"{E['web']} Букмекер: <b>Melbet</b>\n"
        f"{E['exchange']} Оплата: <b>LMWPAY</b>\n"
        f"{E['money']} Минимум: <b>{MIN_DEPOSIT}</b>\n"
        f"{E['mail']} Поддержка: {SUPPORT_USERNAME}\n\n"
        f"Пишите в бота — оператор ответит здесь.",
        reply_markup=main_kb(),
    )


@bot.message_handler(func=lambda m: m.text in ["💎 Пополнение", "💳 Пополнение"])
def deposit_start(msg):
    ensure_user(msg.from_user)
    support_mode.discard(msg.from_user.id)
    bot.send_message(
        msg.chat.id,
        f"{E['wallet']} <b>Пополнение Melbet</b>\n\n"
        f"Введите сумму (мин. <b>{MIN_DEPOSIT}</b>):",
        reply_markup=cancel_kb(),
    )
    bot.register_next_step_handler(msg, deposit_amount)


def deposit_amount(msg):
    if not msg.text or msg.text == "❌ Отмена":
        cancel(msg)
        return
    try:
        amount = int(msg.text.strip().replace(" ", ""))
    except ValueError:
        bot.send_message(msg.chat.id, f"{E['zap']} Введите число", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, deposit_amount)
        return
    if amount < MIN_DEPOSIT:
        bot.send_message(msg.chat.id, f"{E['zap']} Минимум {MIN_DEPOSIT}", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, deposit_amount)
        return

    bot.send_message(
        msg.chat.id,
        f"{E['write']} Отправьте ваш <b>ID Melbet</b>:",
        reply_markup=cancel_kb(),
    )
    bot.register_next_step_handler(msg, deposit_id, amount)


def deposit_id(msg, amount):
    if not msg.text or msg.text == "❌ Отмена":
        cancel(msg)
        return
    melbet_id = msg.text.strip()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO deposits (user_id, amount, melbet_id, status, created_at) VALUES (?,?,?,'new',?)",
            (msg.from_user.id, amount, melbet_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        dep_id = cur.lastrowid
        conn.commit()

    bot.send_message(
        msg.chat.id,
        f"{E['ok']} <b>Заявка #{dep_id} принята</b>\n\n"
        f"{E['money']} Сумма: <b>{amount}</b>\n"
        f"{E['pc']} Melbet ID: <code>{melbet_id}</code>\n"
        f"{E['exchange']} Способ: <b>LMWPAY</b>\n\n"
        f"Ожидайте подтверждение\n"
        f"{E['mail']} {SUPPORT_USERNAME}",
        reply_markup=main_kb(),
    )

    for admin in ADMIN_IDS:
        try:
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅ Готово", callback_data=f"dep_ok:{dep_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"dep_no:{dep_id}"),
            )
            bot.send_message(
                admin,
                f"{E['wallet']} <b>Пополнение #{dep_id}</b>\n\n"
                f"👤 {msg.from_user.full_name} (@{msg.from_user.username or '—'})\n"
                f"ID: <code>{msg.from_user.id}</code>\n"
                f"{E['money']} {amount}\n"
                f"{E['pc']} Melbet: <code>{melbet_id}</code>\n"
                f"{E['exchange']} LMWPAY",
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"admin notify: {e}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("dep_ok:") or c.data.startswith("dep_no:"))
def deposit_mod(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет прав")
        return
    action, dep_id = call.data.split(":")
    dep_id = int(dep_id)
    with db() as conn:
        row = conn.execute("SELECT * FROM deposits WHERE id=?", (dep_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "Не найдено")
            return
        status = "done" if action == "dep_ok" else "rejected"
        conn.execute("UPDATE deposits SET status=? WHERE id=?", (status, dep_id))
        conn.commit()

    if action == "dep_ok":
        text_admin = call.message.text + f"\n\n{E['ok']} Выполнено"
        text_user = (
            f"{E['ok']} <b>Заявка #{dep_id} выполнена!</b>\n\n"
            f"{E['money']} {row['amount']}\n"
            f"{E['pc']} {row['melbet_id']}\n"
            f"{E['rocket']} Удачной игры!"
        )
    else:
        text_admin = call.message.text + "\n\n❌ Отклонено"
        text_user = f"❌ Заявка #{dep_id} отклонена.\n{E['mail']} Напишите в поддержку."

    try:
        bot.edit_message_text(text_admin, call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    try:
        bot.send_message(row["user_id"], text_user)
    except Exception:
        pass
    bot.answer_callback_query(call.id, "OK")


@bot.message_handler(func=lambda m: m.text in ["🚀 Вывод", "📤 Вывод"])
def withdraw_start(msg):
    ensure_user(msg.from_user)
    support_mode.discard(msg.from_user.id)
    bot.send_message(
        msg.chat.id,
        f"{E['plane']} <b>Вывод Melbet</b>\n\n"
        f"{E['write']} <b>Инструкция</b>\n"
        f"1. Настройки → Вывести со счёта\n"
        f"2. LMWPAY / MOBCASH\n"
        f"3. Укажите сумму → получите код\n"
        f"4. Отправьте в бота:\n\n"
        f"<code>сумма код</code>\n"
        f"Пример: <code>500 AB12CD</code>",
        reply_markup=cancel_kb(),
    )
    bot.register_next_step_handler(msg, withdraw_process)


def withdraw_process(msg):
    if not msg.text or msg.text == "❌ Отмена":
        cancel(msg)
        return
    parts = msg.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(msg.chat.id, f"{E['zap']} Формат: <code>сумма код</code>", reply_markup=cancel_kb())
        bot.register_next_step_handler(msg, withdraw_process)
        return
    amount, code = parts[0], parts[1]
    bot.send_message(
        msg.chat.id,
        f"{E['ok']} <b>Заявка на вывод принята</b>\n\n"
        f"{E['money']} {amount}\n"
        f"{E['dollar']} <code>{code}</code>",
        reply_markup=main_kb(),
    )
    for admin in ADMIN_IDS:
        try:
            bot.send_message(
                admin,
                f"{E['plane']} <b>Вывод</b>\n\n"
                f"👤 {msg.from_user.full_name} (@{msg.from_user.username or '—'})\n"
                f"ID: <code>{msg.from_user.id}</code>\n"
                f"{E['money']} {amount}\n"
                f"{E['dollar']} <code>{code}</code>",
            )
        except Exception:
            pass


@bot.message_handler(func=lambda m: m.text == "💬 Поддержка")
def support_start(msg):
    ensure_user(msg.from_user)
    support_mode.add(msg.from_user.id)
    bot.send_message(
        msg.chat.id,
        f"{E['mail']} <b>Поддержка</b>\n\n"
        f"Напишите вопрос — оператор ответит <b>в этом боте</b>.\n"
        f"{SUPPORT_USERNAME}\n\n"
        f"Выход: «❌ Отмена» или /start",
        reply_markup=cancel_kb(),
    )


@bot.message_handler(func=lambda m: m.from_user.id in support_mode and m.text and m.text != "❌ Отмена" and not m.text.startswith("/"))
def support_user_message(msg):
    text = (
        f"{E['mail']} <b>Сообщение в поддержку</b>\n\n"
        f"👤 {msg.from_user.full_name}\n"
        f"@{msg.from_user.username or '—'}\n"
        f"ID: <code>{msg.from_user.id}</code>\n\n"
        f"{E['write']} {msg.text}\n\n"
        f"<i>↩ Ответьте реплаем на это сообщение</i>"
    )
    for admin in ADMIN_IDS:
        try:
            sent = bot.send_message(admin, text)
            reply_map[sent.message_id] = msg.from_user.id
            with db() as conn:
                conn.execute(
                    "INSERT INTO tickets (user_id, message, admin_msg_id, created_at) VALUES (?,?,?,?)",
                    (msg.from_user.id, msg.text, sent.message_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"support forward: {e}")

    bot.send_message(msg.chat.id, f"{E['ok']} Отправлено. Ожидайте ответ.")


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.reply_to_message is not None)
def admin_reply(msg):
    replied_id = msg.reply_to_message.message_id
    user_id = reply_map.get(replied_id)
    if not user_id:
        with db() as conn:
            row = conn.execute("SELECT user_id FROM tickets WHERE admin_msg_id=?", (replied_id,)).fetchone()
            if row:
                user_id = row["user_id"]
    if not user_id:
        return
    try:
        bot.send_message(user_id, f"{E['mail']} <b>Ответ поддержки</b>\n\n{msg.text or ''}")
        bot.reply_to(msg, f"{E['ok']} Отправлено")
    except Exception as e:
        bot.reply_to(msg, f"❌ {e}")


if __name__ == "__main__":
    init_db()
    logger.info(f"{BOT_NAME} started")
    bot.infinity_polling(timeout=40, long_polling_timeout=40)
