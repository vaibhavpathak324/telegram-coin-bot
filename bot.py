import os
import logging
import random
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton,
    InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from supabase import create_client

# --- Config ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Telethon config (for userbot login)
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Telethon Userbot State ---
telethon_client = None
telethon_phone = None

# Conversation states for login flow
LOGIN_PHONE, LOGIN_OTP, LOGIN_2FA = range(3)

# --- Health check server (keeps Render happy + prevents sleep) ---
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health server running on port {port}")

# --- Keep-alive pinger ---
import httpx as _httpx

async def keep_alive(context):
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-coin-bot-hxxv.onrender.com")
    try:
        async with _httpx.AsyncClient() as client:
            await client.get(url, timeout=10)
    except:
        pass


# --- Health check server (keeps Render happy + prevents sleep) ---
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health server running on port {port}")

# --- Keep-alive pinger ---
import httpx as _httpx

async def keep_alive(context):
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-coin-bot-hxxv.onrender.com")
    try:
        async with _httpx.AsyncClient() as client:
            await client.get(url, timeout=10)
    except:
        pass


# --- Health check server (keeps Render happy + prevents sleep) ---
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health server running on port {port}")

# --- Keep-alive pinger ---
import httpx as _httpx

async def keep_alive(context):
    url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-coin-bot-hxxv.onrender.com")
    try:
        async with _httpx.AsyncClient() as client:
            await client.get(url, timeout=10)
    except:
        pass


# --- Helpers ---
def get_user(telegram_id):
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None

def create_user(telegram_id, username, first_name, phone=None):
    supabase.table("users").insert({
        "telegram_id": telegram_id,
        "username": username or "",
        "first_name": first_name or "",
        "phone": phone,
        "coins": 50,
        "streak": 0,
        "last_daily": None,
        "last_spin": None,
        "referral_code": f"REF{telegram_id}",
        "referred_by": None,
        "level": 1,
        "xp": 0,
        "total_earned": 50,
        "created_at": datetime.utcnow().isoformat()
    }).execute()

def update_user(telegram_id, **kwargs):
    supabase.table("users").update(kwargs).eq("telegram_id", telegram_id).execute()

def add_coins(telegram_id, amount, reason=""):
    user = get_user(telegram_id)
    if user:
        new_coins = user["coins"] + amount
        new_total = user["total_earned"] + (amount if amount > 0 else 0)
        new_xp = user["xp"] + abs(amount)
        new_level = 1 + new_xp // 500
        update_user(telegram_id, coins=new_coins, total_earned=new_total, xp=new_xp, level=new_level)
        supabase.table("transactions").insert({
            "telegram_id": telegram_id,
            "amount": amount,
            "reason": reason,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        return new_coins
    return 0

def get_leaderboard():
    res = supabase.table("users").select("first_name,username,coins,level").order("coins", desc=True).limit(10).execute()
    return res.data

# ============================================================
# TELETHON USERBOT LOGIN FLOW (Admin Only)
# ============================================================

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: Start Telethon login flow"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ This command is admin-only.")
        return ConversationHandler.END

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        await update.message.reply_text(
            "❌ *Telethon not configured!*\n\n"
            "Set these env vars on Render:\n"
            "`TELEGRAM_API_ID` — from my.telegram.org\n"
            "`TELEGRAM_API_HASH` — from my.telegram.org\n"
            "`ADMIN_ID` — your Telegram user ID",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔐 *Telethon Userbot Login*\n\n"
        "This will log into a Telegram account using Telethon.\n\n"
        "📱 *Send your phone number* (with country code, e.g. +91xxxxxxxxxx)\n\n"
        "Type /cancel to abort.",
        parse_mode="Markdown"
    )
    return LOGIN_PHONE

async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive phone number and send OTP"""
    global telethon_client, telethon_phone
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    phone = update.message.text.strip()
    if not phone.startswith("+"):
        await update.message.reply_text("❌ Include country code (e.g. +91xxxxxxxxxx). Try again:")
        return LOGIN_PHONE

    telethon_phone = phone
    try:
        telethon_client = TelegramClient(
            StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH
        )
        await telethon_client.connect()
        result = await telethon_client.send_code_request(phone)
        context.user_data["phone_code_hash"] = result.phone_code_hash

        await update.message.reply_text(
            "✅ *OTP sent to your Telegram app!*\n\n"
            "📩 Enter the OTP code you received:\n\n"
            "💡 _Tip: Send it as `1 2 3 4 5` with spaces to prevent Telegram from blocking it._",
            parse_mode="Markdown"
        )
        return LOGIN_OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Error sending code: `{e}`", parse_mode="Markdown")
        if telethon_client:
            await telethon_client.disconnect()
            telethon_client = None
        return ConversationHandler.END

async def login_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive OTP and try to sign in"""
    global telethon_client, telethon_phone
    from telethon.errors import SessionPasswordNeededError

    otp = update.message.text.strip().replace(" ", "").replace("-", "")
    phone_code_hash = context.user_data.get("phone_code_hash")

    try:
        await telethon_client.sign_in(
            telethon_phone, otp, phone_code_hash=phone_code_hash
        )
        # Success! Save session string
        from telethon.sessions import StringSession
        session_str = telethon_client.session.save()

        # Store in Supabase for persistence
        supabase.table("userbot_sessions").upsert({
            "id": 1,
            "session_string": session_str,
            "phone": telethon_phone,
            "logged_in_at": datetime.utcnow().isoformat()
        }).execute()

        me = await telethon_client.get_me()
        await update.message.reply_text(
            f"✅ *Login Successful!*\n\n"
            f"👤 Logged in as: *{me.first_name}* (@{me.username})\n"
            f"📱 Phone: `{telethon_phone}`\n"
            f"🔑 Session saved to database!\n\n"
            f"Use /userbot\\_status to check status\n"
            f"Use /userbot\\_logout to disconnect",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔒 *2FA Password Required!*\n\n"
            "Your account has Two-Factor Authentication enabled.\n"
            "Please enter your 2FA password:",
            parse_mode="Markdown"
        )
        return LOGIN_2FA
    except Exception as e:
        await update.message.reply_text(f"❌ Login failed: `{e}`", parse_mode="Markdown")
        if telethon_client:
            await telethon_client.disconnect()
            telethon_client = None
        return ConversationHandler.END

async def login_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA password"""
    global telethon_client, telethon_phone
    password = update.message.text.strip()

    try:
        await telethon_client.sign_in(password=password)

        from telethon.sessions import StringSession
        session_str = telethon_client.session.save()

        # Store in Supabase
        supabase.table("userbot_sessions").upsert({
            "id": 1,
            "session_string": session_str,
            "phone": telethon_phone,
            "logged_in_at": datetime.utcnow().isoformat()
        }).execute()

        me = await telethon_client.get_me()

        # Delete the 2FA message for security
        try:
            await update.message.delete()
        except:
            pass

        await update.message.reply_text(
            f"✅ *Login Successful (2FA verified)!*\n\n"
            f"👤 Logged in as: *{me.first_name}* (@{me.username})\n"
            f"📱 Phone: `{telethon_phone}`\n"
            f"🔑 Session saved to database!\n\n"
            f"Use /userbot\\_status to check status\n"
            f"Use /userbot\\_logout to disconnect",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ 2FA failed: `{e}`", parse_mode="Markdown")
        if telethon_client:
            await telethon_client.disconnect()
            telethon_client = None
        return ConversationHandler.END

async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel login flow"""
    global telethon_client
    if telethon_client:
        await telethon_client.disconnect()
        telethon_client = None
    await update.message.reply_text("❌ Login cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def userbot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check userbot session status"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    global telethon_client
    if telethon_client and telethon_client.is_connected():
        try:
            me = await telethon_client.get_me()
            await update.message.reply_text(
                f"✅ *Userbot Active*\n\n"
                f"👤 {me.first_name} (@{me.username})\n"
                f"📱 {telethon_phone}",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("⚠️ Client connected but session may be invalid. Try /login again.")
    else:
        try:
            res = supabase.table("userbot_sessions").select("*").eq("id", 1).execute()
            if res.data:
                await update.message.reply_text(
                    f"💾 *Session saved in DB* (not active in memory)\n"
                    f"📱 Phone: `{res.data[0].get('phone', 'N/A')}`\n"
                    f"🕐 Last login: {res.data[0].get('logged_in_at', 'N/A')}\n\n"
                    f"Use /userbot\\_restore to reconnect.",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ No userbot session. Use /login to set up.")
        except:
            await update.message.reply_text("❌ No userbot session. Use /login to set up.")

async def userbot_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restore userbot session from Supabase"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    global telethon_client, telethon_phone
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        res = supabase.table("userbot_sessions").select("*").eq("id", 1).execute()
        if not res.data:
            await update.message.reply_text("❌ No saved session. Use /login first.")
            return

        session_str = res.data[0]["session_string"]
        telethon_phone = res.data[0].get("phone", "")

        telethon_client = TelegramClient(
            StringSession(session_str), TELEGRAM_API_ID, TELEGRAM_API_HASH
        )
        await telethon_client.connect()
        me = await telethon_client.get_me()

        await update.message.reply_text(
            f"✅ *Session Restored!*\n\n"
            f"👤 {me.first_name} (@{me.username})",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Restore failed: `{e}`\nTry /login again.", parse_mode="Markdown")

async def userbot_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disconnect userbot"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    global telethon_client
    if telethon_client:
        await telethon_client.log_out()
        await telethon_client.disconnect()
        telethon_client = None

    try:
        supabase.table("userbot_sessions").delete().eq("id", 1).execute()
    except:
        pass

    await update.message.reply_text("✅ Userbot logged out and session deleted.")

# ============================================================
# ORIGINAL BOT HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if context.args and not user:
        referral_code = context.args[0]
        ref_res = supabase.table("users").select("telegram_id").eq("referral_code", referral_code).execute()
        if ref_res.data:
            referrer_id = ref_res.data[0]["telegram_id"]
            add_coins(referrer_id, 100, "Referral bonus")

    if user and user.get("phone"):
        await update.message.reply_text(
            f"🎉 Welcome back, {update.effective_user.first_name}!\n"
            f"💰 You have *{user['coins']}* coins\n"
            f"⭐ Level {user['level']}\n\n"
            f"Use /menu to see all options!",
            parse_mode="Markdown"
        )
        return

    contact_button = KeyboardButton("📱 Share Contact", request_contact=True)
    markup = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        f"👋 Hey {update.effective_user.first_name}!\n\n"
        "🤖 Welcome to *CoinBot* — earn coins, level up, and compete!\n\n"
        "🎁 Share your contact to get started and receive a *50 coin welcome bonus*!\n\n"
        "Your data is safe and used only for your account.",
        parse_mode="Markdown",
        reply_markup=markup
    )

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if not user:
        create_user(telegram_id, update.effective_user.username, update.effective_user.first_name, contact.phone_number)
        await update.message.reply_text(
            "✅ Account created! You earned *50 welcome coins*! 🎉\n\n"
            "Use /menu to explore all features!",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        update_user(telegram_id, phone=contact.phone_number)
        await update.message.reply_text(
            "📱 Contact updated! Use /menu to continue.",
            reply_markup=ReplyKeyboardRemove()
        )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("🎰 Spin Wheel", callback_data="spin")],
        [InlineKeyboardButton("📅 Daily Check-in", callback_data="daily"),
         InlineKeyboardButton("🎯 Tasks", callback_data="tasks")],
        [InlineKeyboardButton("🎮 Quiz Game", callback_data="quiz"),
         InlineKeyboardButton("🎲 Coin Flip", callback_data="coinflip")],
        [InlineKeyboardButton("🎁 Mystery Box", callback_data="mystery"),
         InlineKeyboardButton("👥 Referral", callback_data="referral")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
         InlineKeyboardButton("📊 Profile", callback_data="profile")],
    ]
    text = "🤖 *CoinBot Menu*\n\nChoose an option:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)
    back_btn = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]

    if not user:
        await query.edit_message_text("❌ Please /start first!", reply_markup=InlineKeyboardMarkup(back_btn))
        return

    now = datetime.utcnow()

    # --- BALANCE ---
    if data == "balance":
        await query.edit_message_text(
            f"💰 *Your Balance*\n\n🪙 Coins: *{user['coins']}*\n⭐ Level: *{user['level']}*\n✨ XP: *{user['xp']}*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
        )

    # --- DAILY CHECK-IN ---
    elif data == "daily":
        last_daily = user.get("last_daily")
        if last_daily:
            last_dt = datetime.fromisoformat(last_daily.replace("Z", "+00:00")).replace(tzinfo=None)
            if (now - last_dt).total_seconds() < 86400:
                remaining = 86400 - (now - last_dt).total_seconds()
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                await query.edit_message_text(
                    f"⏰ Already checked in today!\n\n⏳ Next check-in in *{hours}h {mins}m*",
                    parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
                )
                return
            if (now - last_dt).total_seconds() < 172800:
                new_streak = user["streak"] + 1
            else:
                new_streak = 1
        else:
            new_streak = 1

        bonus = 10 + (new_streak * 5)
        new_coins = add_coins(telegram_id, bonus, f"Daily check-in (streak {new_streak})")
        update_user(telegram_id, streak=new_streak, last_daily=now.isoformat())
        await query.edit_message_text(
            f"📅 *Daily Check-in!*\n\n🔥 Streak: *{new_streak}* days\n💰 Earned: *+{bonus}* coins\n🪙 Balance: *{new_coins}*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
        )

    # --- SPIN WHEEL ---
    elif data == "spin":
        last_spin = user.get("last_spin")
        if last_spin:
            last_sp = datetime.fromisoformat(last_spin.replace("Z", "+00:00")).replace(tzinfo=None)
            if (now - last_sp).total_seconds() < 3600:
                remaining = 3600 - (now - last_sp).total_seconds()
                mins = int(remaining // 60)
                await query.edit_message_text(
                    f"⏰ Spin cooldown!\n⏳ *{mins}* minutes remaining",
                    parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
                )
                return

        prizes = [
            (5, "🍋 5 coins"), (10, "🍊 10 coins"), (15, "🍇 15 coins"),
            (25, "⭐ 25 coins"), (50, "💎 50 coins"), (100, "🏆 100 coins JACKPOT!"),
            (0, "💨 Better luck next time!"), (3, "🍀 3 coins"),
        ]
        weights = [25, 25, 15, 10, 5, 2, 15, 3]
        prize = random.choices(prizes, weights=weights, k=1)[0]

        if prize[0] > 0:
            new_coins = add_coins(telegram_id, prize[0], "Spin wheel")
        else:
            new_coins = user["coins"]
        update_user(telegram_id, last_spin=now.isoformat())

        await query.edit_message_text(
            f"🎰 *Spin the Wheel!*\n\nResult: {prize[1]}\n🪙 Balance: *{new_coins}*\n\n⏰ Next spin in 1 hour!",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
        )

    # --- TASKS ---
    elif data == "tasks":
        keyboard = [
            [InlineKeyboardButton("✅ Watch Ad (+20 coins)", callback_data="task_watch")],
            [InlineKeyboardButton("📝 Complete Survey (+30 coins)", callback_data="task_survey")],
            [InlineKeyboardButton("📣 Share Bot (+15 coins)", callback_data="task_share")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")],
        ]
        await query.edit_message_text(
            "🎯 *Daily Tasks*\n\nComplete tasks to earn coins!",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("task_"):
        task_rewards = {"task_watch": 20, "task_survey": 30, "task_share": 15}
        task_names = {"task_watch": "Watch Ad", "task_survey": "Complete Survey", "task_share": "Share Bot"}
        reward = task_rewards.get(data, 10)
        name = task_names.get(data, "Task")
        new_coins = add_coins(telegram_id, reward, name)
        await query.edit_message_text(
            f"✅ *{name} Completed!*\n\n💰 Earned: *+{reward}* coins\n🪙 Balance: *{new_coins}*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
        )

    # --- QUIZ ---
    elif data == "quiz":
        quizzes = [
            {"q": "What is the capital of France?", "options": ["London", "Paris", "Berlin", "Rome"], "answer": 1},
            {"q": "What is 15 × 7?", "options": ["95", "105", "115", "85"], "answer": 1},
            {"q": "Which planet is closest to the Sun?", "options": ["Venus", "Mercury", "Mars", "Earth"], "answer": 1},
            {"q": "What year did the Titanic sink?", "options": ["1910", "1912", "1914", "1920"], "answer": 1},
            {"q": "What is the largest ocean?", "options": ["Atlantic", "Indian", "Pacific", "Arctic"], "answer": 2},
            {"q": "How many continents are there?", "options": ["5", "6", "7", "8"], "answer": 2},
            {"q": "Who painted the Mona Lisa?", "options": ["Picasso", "Van Gogh", "Da Vinci", "Monet"], "answer": 2},
            {"q": "What is H2O?", "options": ["Oxygen", "Hydrogen", "Water", "Helium"], "answer": 2},
        ]
        quiz = random.choice(quizzes)
        context.user_data["quiz_answer"] = quiz["answer"]
        keyboard = [[InlineKeyboardButton(opt, callback_data=f"quiz_{i}")] for i, opt in enumerate(quiz["options"])]
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")])
        await query.edit_message_text(
            f"🎮 *Quiz Time!*\n\n❓ {quiz['q']}",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("quiz_"):
        chosen = int(data.split("_")[1])
        correct = context.user_data.get("quiz_answer", -1)
        if chosen == correct:
            reward = random.randint(15, 40)
            new_coins = add_coins(telegram_id, reward, "Quiz correct")
            text = f"✅ *Correct!*\n\n💰 Earned: *+{reward}* coins\n🪙 Balance: *{new_coins}*"
        else:
            text = "❌ *Wrong answer!*\n\nBetter luck next time! Try another quiz."
        keyboard = [
            [InlineKeyboardButton("🎮 Play Again", callback_data="quiz")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # --- COIN FLIP ---
    elif data == "coinflip":
        keyboard = [
            [InlineKeyboardButton("🪙 Heads (Bet 10)", callback_data="flip_heads"),
             InlineKeyboardButton("🪙 Tails (Bet 10)", callback_data="flip_tails")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")],
        ]
        await query.edit_message_text(
            f"🎲 *Coin Flip!*\n\nBet 10 coins — win 20!\n🪙 Your balance: *{user['coins']}*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("flip_"):
        if user["coins"] < 10:
            await query.edit_message_text(
                "❌ Not enough coins! You need at least 10.",
                reply_markup=InlineKeyboardMarkup(back_btn)
            )
            return
        choice = data.split("_")[1]
        result = random.choice(["heads", "tails"])
        if choice == result:
            new_coins = add_coins(telegram_id, 10, "Coin flip win")
            text = f"🎉 *{result.upper()}!* You won!\n💰 +10 coins\n🪙 Balance: *{new_coins}*"
        else:
            new_coins = add_coins(telegram_id, -10, "Coin flip loss")
            text = f"😔 *{result.upper()}!* You lost!\n💸 -10 coins\n🪙 Balance: *{new_coins}*"
        keyboard = [
            [InlineKeyboardButton("🎲 Play Again", callback_data="coinflip")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # --- MYSTERY BOX ---
    elif data == "mystery":
        if user["coins"] < 25:
            await query.edit_message_text(
                "❌ Mystery box costs *25 coins*. You don't have enough!",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
            )
            return
        add_coins(telegram_id, -25, "Mystery box purchase")
        rewards = [(10, "🧸 Common: 10 coins"), (30, "🌟 Uncommon: 30 coins"),
                   (75, "💎 Rare: 75 coins"), (150, "👑 Legendary: 150 coins"), (0, "💀 Empty box!")]
        weights = [35, 30, 20, 5, 10]
        prize = random.choices(rewards, weights=weights, k=1)[0]
        if prize[0] > 0:
            new_coins = add_coins(telegram_id, prize[0], "Mystery box reward")
        else:
            new_coins = get_user(telegram_id)["coins"]
        net = prize[0] - 25
        emoji = "📈" if net > 0 else "📉" if net < 0 else "➡️"
        await query.edit_message_text(
            f"🎁 *Mystery Box Opened!*\n\n"
            f"Result: {prize[1]}\n"
            f"{emoji} Net: *{'+' if net > 0 else ''}{net}* coins\n"
            f"🪙 Balance: *{new_coins}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Open Another (25 coins)", callback_data="mystery")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
            ])
        )

    # --- LEADERBOARD ---
    elif data == "leaderboard":
        leaders = get_leaderboard()
        text = "🏆 *Top 10 Leaderboard*\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, l in enumerate(leaders):
            medal = medals[i] if i < 3 else f"{i+1}."
            name = l.get("first_name") or l.get("username") or "Unknown"
            text += f"{medal} {name} — *{l['coins']}* coins (Lv.{l['level']})\n"
        if not leaders:
            text += "No users yet!"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn))

    # --- REFERRAL ---
    elif data == "referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
        await query.edit_message_text(
            f"👥 *Referral Program*\n\n"
            f"Share your link and earn *100 coins* per referral!\n\n"
            f"🔗 Your link:\n`{ref_link}`\n\n"
            f"Tap to copy and share!",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
        )

    # --- PROFILE ---
    elif data == "profile":
        created = user.get("created_at", "Unknown")[:10]
        await query.edit_message_text(
            f"📊 *Your Profile*\n\n"
            f"👤 Name: *{user.get('first_name', 'N/A')}*\n"
            f"📱 Phone: *{user.get('phone', 'Not shared')}*\n"
            f"🪙 Coins: *{user['coins']}*\n"
            f"⭐ Level: *{user['level']}*\n"
            f"✨ XP: *{user['xp']}*\n"
            f"🔥 Streak: *{user['streak']}* days\n"
            f"📈 Total Earned: *{user['total_earned']}*\n"
            f"🔗 Referral Code: `{user['referral_code']}`\n"
            f"📅 Joined: *{created}*",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn)
        )

    # --- BACK TO MENU ---
    elif data == "menu":
        await menu(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *CoinBot Help*\n\n"
        "📌 *Commands:*\n"
        "/start - Start the bot\n"
        "/menu - Open main menu\n"
        "/balance - Check balance\n"
        "/daily - Daily check-in\n"
        "/spin - Spin the wheel\n"
        "/referral - Get referral link\n"
        "/help - Show this help\n\n"
        "💡 *Earning Methods:*\n"
        "• 📅 Daily check-in (streak bonuses!)\n"
        "• 🎰 Spin wheel (every hour)\n"
        "• 🎯 Complete tasks\n"
        "• 🎮 Quiz games\n"
        "• 🎲 Coin flip gambling\n"
        "• 🎁 Mystery boxes\n"
        "• 👥 Refer friends (+100 each!)\n\n"
        "🔐 *Admin Commands:*\n"
        "/login - Login to userbot (admin)\n"
        "/userbot\\_status - Check session\n"
        "/userbot\\_restore - Restore session\n"
        "/userbot\\_logout - Disconnect",
        parse_mode="Markdown"
    )

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(f"🪙 Balance: *{user['coins']}* coins | ⭐ Level {user['level']}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Please /start first!")

async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /menu → 📅 Daily Check-in")

async def spin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /menu → 🎰 Spin Wheel")

async def referral_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user['referral_code']}"
        await update.message.reply_text(f"🔗 Your referral link:\n`{ref_link}`\n\n+100 coins per referral!", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Please /start first!")

# --- Main ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Telethon login conversation handler (must be added before other handlers)
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            LOGIN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            LOGIN_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_otp)],
            LOGIN_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_2fa)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )
    app.add_handler(login_conv)

    # Userbot management commands
    app.add_handler(CommandHandler("userbot_status", userbot_status))
    app.add_handler(CommandHandler("userbot_restore", userbot_restore))
    app.add_handler(CommandHandler("userbot_logout", userbot_logout))

    # Original handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("spin", spin_cmd))
    app.add_handler(CommandHandler("referral", referral_cmd))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    start_health_server()

    # Schedule keep-alive ping every 5 minutes
    app.job_queue.run_repeating(keep_alive, interval=300, first=10)

    start_health_server()
    
    # Schedule keep-alive ping every 5 minutes
    app.job_queue.run_repeating(keep_alive, interval=300, first=10)
    
    start_health_server()
    
    # Schedule keep-alive ping every 5 minutes
    app.job_queue.run_repeating(keep_alive, interval=300, first=10)
    
    logger.info("Bot started with Telethon userbot support!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
