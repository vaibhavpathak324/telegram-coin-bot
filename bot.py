import os
import logging
import random
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from supabase import create_client, Client
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def get_user(user_id: int) -> dict:
    if not supabase: return None
    try:
        res = supabase.table("users").select("*").eq("telegram_id", str(user_id)).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"get_user error: {e}")
        return None

def create_user(user_id: int, username: str = "", first_name: str = "") -> dict:
    if not supabase: return None
    try:
        data = {"telegram_id": str(user_id), "username": username or "", "first_name": first_name or "", "coins": 0, "streak": 0, "last_daily": None, "referral_code": f"ref_{user_id}", "referred_by": None, "banned": False, "created_at": datetime.utcnow().isoformat()}
        res = supabase.table("users").insert(data).execute()
        return res.data[0] if res.data else data
    except Exception as e:
        logger.error(f"create_user error: {e}")
        return None

def ensure_user(user_id: int, username: str = "", first_name: str = "") -> dict:
    user = get_user(user_id)
    if not user: user = create_user(user_id, username, first_name)
    return user

def update_coins(user_id: int, amount: int):
    if not supabase: return
    try:
        user = get_user(user_id)
        if user:
            new_coins = max(0, user.get("coins", 0) + amount)
            supabase.table("users").update({"coins": new_coins}).eq("telegram_id", str(user_id)).execute()
    except Exception as e:
        logger.error(f"update_coins error: {e}")

def log_transaction(user_id: int, tx_type: str, amount: int, details: str = ""):
    if not supabase: return
    try:
        supabase.table("transactions").insert({"telegram_id": str(user_id), "type": tx_type, "amount": amount, "details": details, "created_at": datetime.utcnow().isoformat()}).execute()
    except Exception as e:
        logger.error(f"log_transaction error: {e}")

def get_leaderboard(limit: int = 10):
    if not supabase: return []
    try:
        res = supabase.table("users").select("*").order("coins", desc=True).limit(limit).execute()
        return res.data or []
    except: return []

def get_userbot_session(user_id: int):
    if not supabase: return None
    try:
        res = supabase.table("userbot_sessions").select("*").eq("telegram_id", str(user_id)).execute()
        return res.data[0] if res.data else None
    except: return None

def save_userbot_session(user_id: int, phone: str, session_string: str):
    if not supabase: return
    try:
        existing = get_userbot_session(user_id)
        data = {"telegram_id": str(user_id), "phone": phone, "session_string": session_string, "active": True, "created_at": datetime.utcnow().isoformat()}
        if existing:
            supabase.table("userbot_sessions").update(data).eq("telegram_id", str(user_id)).execute()
        else:
            supabase.table("userbot_sessions").insert(data).execute()
    except Exception as e:
        logger.error(f"save_userbot_session error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username, user.first_name)
    if context.args and context.args[0].startswith("ref_"):
        referrer_id = context.args[0].replace("ref_", "")
        try:
            u = get_user(user.id)
            if u and not u.get("referred_by"):
                supabase.table("users").update({"referred_by": referrer_id}).eq("telegram_id", str(user.id)).execute()
                update_coins(int(referrer_id), 50)
                update_coins(user.id, 25)
                log_transaction(int(referrer_id), "referral_bonus", 50, f"Referred {user.id}")
                log_transaction(user.id, "referral_bonus", 25, f"Referred by {referrer_id}")
        except: pass
    keyboard = [[KeyboardButton("\ud83d\udcb0 Balance"), KeyboardButton("\ud83c\udfb0 Spin")], [KeyboardButton("\ud83d\udcca Leaderboard"), KeyboardButton("\ud83c\udf81 Daily")], [KeyboardButton("\ud83d\udc65 Referral"), KeyboardButton("\u2139\ufe0f Help")]]
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("\ud83d\udd10 Admin Panel")])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(f"\u2b50 Welcome to Coin Bot, {user.first_name}!\n\nEarn coins by spinning, completing daily check-ins, and referring friends!\n\nUse the buttons below to get started.", reply_markup=reply_markup)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user.id, user.username, user.first_name)
    coins = u.get("coins", 0) if u else 0
    streak = u.get("streak", 0) if u else 0
    await update.message.reply_text(f"\ud83d\udcb0 Your Balance\n\nCoins: {coins:,}\nDaily Streak: {streak} days")

async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user.id, user.username, user.first_name)
    if not u:
        await update.message.reply_text("Error loading profile.")
        return
    outcomes = [(50, "\ud83c\udf1f Jackpot! +50 coins!", 5), (25, "\ud83c\udf89 Big win! +25 coins!", 10), (10, "\u2728 Nice! +10 coins!", 25), (5, "\ud83d\udc4d +5 coins!", 30), (1, "\ud83e\udd37 +1 coin", 20), (0, "\ud83d\udca8 Nothing this time!", 10)]
    weights = [o[2] for o in outcomes]
    result = random.choices(outcomes, weights=weights, k=1)[0]
    amount, msg, _ = result
    if amount > 0:
        update_coins(user.id, amount)
        log_transaction(user.id, "spin", amount)
    await update.message.reply_text(f"\ud83c\udfb0 Spin Result\n\n{msg}")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user.id, user.username, user.first_name)
    if not u:
        await update.message.reply_text("Error loading profile.")
        return
    last_daily = u.get("last_daily")
    now = datetime.utcnow()
    if last_daily:
        try:
            last_dt = datetime.fromisoformat(last_daily.replace("Z", ""))
            if (now - last_dt).total_seconds() < 86400:
                remaining = 86400 - (now - last_dt).total_seconds()
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                await update.message.reply_text(f"\u23f0 Come back in {hours}h {mins}m for your daily reward!")
                return
            streak = u.get("streak", 0) + 1 if (now - last_dt).total_seconds() < 172800 else 1
        except: streak = 1
    else: streak = 1
    reward = min(10 + (streak * 2), 50)
    update_coins(user.id, reward)
    log_transaction(user.id, "daily", reward, f"Streak: {streak}")
    supabase.table("users").update({"last_daily": now.isoformat(), "streak": streak}).eq("telegram_id", str(user.id)).execute()
    await update.message.reply_text(f"\ud83c\udf81 Daily Reward!\n\nStreak: {streak} days\nReward: +{reward} coins\nBonus increases with streak!")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = get_leaderboard(10)
    if not top:
        await update.message.reply_text("No users yet!")
        return
    medals = ["\ud83e\udd47", "\ud83e\udd48", "\ud83e\udd49"]
    lines = ["\ud83c\udfc6 Leaderboard\n"]
    for i, u in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = u.get("first_name") or u.get("username") or "User"
        coins = u.get("coins", 0)
        lines.append(f"{medal} {name}: {coins:,} coins")
    await update.message.reply_text("\n".join(lines))

async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = ensure_user(user.id, user.username, user.first_name)
    ref_code = u.get("referral_code", f"ref_{user.id}") if u else f"ref_{user.id}"
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={ref_code}"
    await update.message.reply_text(f"\ud83d\udc65 Referral Program\n\nShare your link:\n{link}\n\nYou get 50 coins per referral!\nYour friend gets 25 coins!")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\u2139\ufe0f Help\n\nCommands:\n/start - Start the bot\n/balance - Check your coins\n/spin - Spin for coins\n/daily - Daily reward\n/leaderboard - Top users\n/referral - Get referral link\n/transfer <user_id> <amount> - Send coins\n/help - This message")

async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /transfer <user_id> <amount>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Invalid user_id or amount.")
        return
    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return
    sender = ensure_user(user.id, user.username, user.first_name)
    if not sender or sender.get("coins", 0) < amount:
        await update.message.reply_text("Insufficient coins.")
        return
    receiver = get_user(target_id)
    if not receiver:
        await update.message.reply_text("Recipient not found.")
        return
    update_coins(user.id, -amount)
    update_coins(target_id, amount)
    log_transaction(user.id, "transfer_out", -amount, f"To {target_id}")
    log_transaction(target_id, "transfer_in", amount, f"From {user.id}")
    await update.message.reply_text(f"\u2705 Sent {amount} coins to user {target_id}!")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not supabase:
        await update.message.reply_text("DB not configured.")
        return
    try:
        users = supabase.table("users").select("*", count="exact").execute()
        total_users = users.count or 0
        total_coins = sum(u.get("coins", 0) for u in (users.data or []))
        txns = supabase.table("transactions").select("*", count="exact").execute()
        total_txns = txns.count or 0
        await update.message.reply_text(f"\ud83d\udcca Admin Stats\n\nUsers: {total_users}\nTotal Coins: {total_coins:,}\nTransactions: {total_txns}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    if not supabase:
        await update.message.reply_text("DB not configured.")
        return
    try:
        users = supabase.table("users").select("telegram_id").execute()
        sent = 0
        for u in (users.data or []):
            try:
                await context.bot.send_message(chat_id=int(u["telegram_id"]), text=msg)
                sent += 1
            except: pass
        await update.message.reply_text(f"\u2705 Broadcast sent to {sent} users.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addcoins <user_id> <amount>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        update_coins(target_id, amount)
        log_transaction(target_id, "admin_add", amount, "By admin")
        await update.message.reply_text(f"\u2705 Added {amount} coins to {target_id}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        supabase.table("users").update({"banned": True}).eq("telegram_id", context.args[0]).execute()
        await update.message.reply_text(f"\u2705 Banned user {context.args[0]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        supabase.table("users").update({"banned": False}).eq("telegram_id", context.args[0]).execute()
        await update.message.reply_text(f"\u2705 Unbanned user {context.args[0]}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

USERBOT_STATES = {}

async def userbot_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USERBOT_STATES[user_id] = {"step": "phone"}
    await update.message.reply_text("\ud83d\udcf1 Userbot Login\n\nSend your phone number (with country code, e.g. +91xxxxxxxxxx):")

async def handle_userbot_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in USERBOT_STATES: return False
    state = USERBOT_STATES[user_id]
    text = update.message.text.strip()
    if state["step"] == "phone":
        if not API_ID or not API_HASH:
            await update.message.reply_text("\u274c API_ID/API_HASH not configured.")
            del USERBOT_STATES[user_id]
            return True
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            result = await client.send_code_request(text)
            state["phone"] = text
            state["client"] = client
            state["phone_code_hash"] = result.phone_code_hash
            state["step"] = "code"
            await update.message.reply_text("\u2705 Code sent! Enter the code you received:")
        except Exception as e:
            await update.message.reply_text(f"\u274c Error: {e}")
            del USERBOT_STATES[user_id]
        return True
    elif state["step"] == "code":
        try:
            client = state["client"]
            await client.sign_in(state["phone"], text, phone_code_hash=state["phone_code_hash"])
            from telethon.sessions import StringSession
            session_str = client.session.save()
            save_userbot_session(user_id, state["phone"], session_str)
            await client.disconnect()
            await update.message.reply_text("\u2705 Userbot logged in successfully!")
            del USERBOT_STATES[user_id]
        except Exception as e:
            if "password" in str(e).lower():
                state["step"] = "2fa"
                await update.message.reply_text("\ud83d\udd10 2FA enabled. Enter your password:")
            else:
                await update.message.reply_text(f"\u274c Error: {e}")
                del USERBOT_STATES[user_id]
        return True
    elif state["step"] == "2fa":
        try:
            client = state["client"]
            await client.sign_in(password=text)
            from telethon.sessions import StringSession
            session_str = client.session.save()
            save_userbot_session(user_id, state["phone"], session_str)
            await client.disconnect()
            await update.message.reply_text("\u2705 Userbot logged in successfully!")
            del USERBOT_STATES[user_id]
        except Exception as e:
            await update.message.reply_text(f"\u274c Error: {e}")
            del USERBOT_STATES[user_id]
        return True
    return False

async def admin_panel_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("\u26d4 Admin only.")
        return
    panel_url = os.getenv("RENDER_EXTERNAL_URL", "https://telegram-coin-bot-hxxv.onrender.com")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("\ud83d\udd10 Open Admin Panel", url=f"{panel_url}/panel")],
        [InlineKeyboardButton("\ud83d\udcca Quick Stats", callback_data="admin_quick_stats")]
    ])
    await update.message.reply_text("\ud83d\udd10 Admin Panel\n\nManage users, view stats, and more:", reply_markup=keyboard)

async def admin_quick_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    if not supabase:
        await query.edit_message_text("DB not configured.")
        return
    try:
        users = supabase.table("users").select("*", count="exact").execute()
        total_users = users.count or 0
        total_coins = sum(u.get("coins", 0) for u in (users.data or []))
        txns = supabase.table("transactions").select("*", count="exact").execute()
        total_txns = txns.count or 0
        panel_url = os.getenv("RENDER_EXTERNAL_URL", "https://telegram-coin-bot-hxxv.onrender.com")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("\ud83d\udd10 Open Full Panel", url=f"{panel_url}/panel")]])
        await query.edit_message_text(f"\ud83d\udcca Quick Stats\n\n\ud83d\udc65 Users: {total_users}\n\ud83d\udcb0 Total Coins: {total_coins:,}\n\ud83d\udcdd Transactions: {total_txns}\n\nOpen the full panel for more details:", reply_markup=keyboard)
    except Exception as e:
        await query.edit_message_text(f"Error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user = update.effective_user
    u = ensure_user(user.id, user.username, user.first_name)
    if u and u.get("banned"):
        await update.message.reply_text("\u26d4 You are banned.")
        return
    handled = await handle_userbot_flow(update, context)
    if handled: return
    text = update.message.text
    if text == "\ud83d\udcb0 Balance": await balance(update, context)
    elif text == "\ud83c\udfb0 Spin": await spin(update, context)
    elif text == "\ud83c\udf81 Daily": await daily(update, context)
    elif text == "\ud83d\udcca Leaderboard": await leaderboard(update, context)
    elif text == "\ud83d\udc65 Referral": await referral(update, context)
    elif text == "\u2139\ufe0f Help": await help_cmd(update, context)
    elif text == "\ud83d\udd10 Admin Panel": await admin_panel_btn(update, context)

def start_admin_panel():
    try:
        from admin_panel import app
        port = int(os.getenv("PORT", "10000"))
        logger.info(f"Starting admin panel on port {port}")
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Admin panel error: {e}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    admin_thread = threading.Thread(target=start_admin_panel, daemon=True)
    admin_thread.start()
    logger.info("Admin panel thread started")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("spin", spin))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("transfer", transfer))
    app.add_handler(CommandHandler("adminstats", admin_stats))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("addcoins", admin_addcoins))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("userbotlogin", userbot_login))
    app.add_handler(CallbackQueryHandler(admin_quick_stats_callback, pattern="^admin_quick_stats$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
