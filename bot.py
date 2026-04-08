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
    filters, ContextTypes
)
from supabase import create_client

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_user(tid):
    r = supabase.table("users").select("*").eq("telegram_id", tid).execute()
    return r.data[0] if r.data else None

def create_user(tid, uname, fname, phone=None):
    supabase.table("users").insert({"telegram_id":tid,"username":uname or "","first_name":fname or "","phone":phone,"coins":50,"streak":0,"last_daily":None,"last_spin":None,"referral_code":f"REF{tid}","referred_by":None,"level":1,"xp":0,"total_earned":50,"created_at":datetime.utcnow().isoformat()}).execute()

def update_user(tid, **kw):
    supabase.table("users").update(kw).eq("telegram_id", tid).execute()

def add_coins(tid, amt, reason=""):
    u = get_user(tid)
    if u:
        nc = u["coins"] + amt
        nt = u["total_earned"] + (amt if amt > 0 else 0)
        nx = u["xp"] + abs(amt)
        nl = 1 + nx // 500
        update_user(tid, coins=nc, total_earned=nt, xp=nx, level=nl)
        supabase.table("transactions").insert({"telegram_id":tid,"amount":amt,"reason":reason,"created_at":datetime.utcnow().isoformat()}).execute()
        return nc
    return 0

def get_leaderboard():
    return supabase.table("users").select("first_name,username,coins,level").order("coins", desc=True).limit(10).execute().data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    user = get_user(tid)
    if context.args and not user:
        rc = context.args[0]
        ref = supabase.table("users").select("telegram_id").eq("referral_code", rc).execute()
        if ref.data:
            add_coins(ref.data[0]["telegram_id"], 100, "Referral bonus")
    if user and user.get("phone"):
        await update.message.reply_text(f"\ud83c\udf89 Welcome back, {update.effective_user.first_name}!\n\ud83d\udcb0 You have *{user['coins']}* coins\n\u2b50 Level {user['level']}\n\nUse /menu to see all options!", parse_mode="Markdown")
        return
    btn = KeyboardButton("\ud83d\udcf1 Share Contact", request_contact=True)
    mk = ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(f"\ud83d\udc4b Hey {update.effective_user.first_name}!\n\n\ud83e\udd16 Welcome to *CoinBot* \u2014 earn coins, level up, compete!\n\n\ud83c\udf81 Share your contact to get *50 coin welcome bonus*!", parse_mode="Markdown", reply_markup=mk)

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = update.message.contact
    tid = update.effective_user.id
    u = get_user(tid)
    if not u:
        create_user(tid, update.effective_user.username, update.effective_user.first_name, c.phone_number)
        await update.message.reply_text("\u2705 Account created! You earned *50 welcome coins*! \ud83c\udf89\nUse /menu to explore!", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    else:
        update_user(tid, phone=c.phone_number)
        await update.message.reply_text("\ud83d\udcf1 Contact updated! Use /menu to continue.", reply_markup=ReplyKeyboardRemove())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("\ud83d\udcb0 Balance", callback_data="balance"), InlineKeyboardButton("\ud83c\udfb0 Spin Wheel", callback_data="spin")],
        [InlineKeyboardButton("\ud83d\udcc5 Daily Check-in", callback_data="daily"), InlineKeyboardButton("\ud83c\udfaf Tasks", callback_data="tasks")],
        [InlineKeyboardButton("\ud83c\udfae Quiz Game", callback_data="quiz"), InlineKeyboardButton("\ud83c\udfb2 Coin Flip", callback_data="coinflip")],
        [InlineKeyboardButton("\ud83c\udfc6 Leaderboard", callback_data="leaderboard"), InlineKeyboardButton("\ud83d\udc65 Referral", callback_data="referral")],
        [InlineKeyboardButton("\ud83c\udf81 Mystery Box", callback_data="mystery"), InlineKeyboardButton("\ud83d\udcca Profile", callback_data="profile")],
    ]
    mk = InlineKeyboardMarkup(kb)
    txt = "\ud83e\udd16 *CoinBot Menu*\n\nChoose an option:"
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, reply_markup=mk, parse_mode="Markdown")
    else:
        await update.message.reply_text(txt, reply_markup=mk, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.from_user.id
    u = get_user(tid)
    if not u:
        await q.edit_message_text("\u274c Please /start first and share your contact!")
        return
    d = q.data
    back = [[InlineKeyboardButton("\ud83d\udd19 Back to Menu", callback_data="menu")]]

    if d == "balance":
        await q.edit_message_text(f"\ud83d\udcb0 *Your Balance*\n\n\ud83e\ude99 Coins: *{u['coins']}*\n\u2b50 Level: *{u['level']}*\n\u2728 XP: *{u['xp']}*\n\ud83d\udcc8 Total Earned: *{u['total_earned']}*\n\ud83d\udd25 Streak: *{u['streak']}* days", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "daily":
        now = datetime.utcnow()
        last = u.get("last_daily")
        if last:
            ld = datetime.fromisoformat(last)
            if (now - ld).total_seconds() < 86400:
                rem = 86400 - (now - ld).total_seconds()
                h, m = int(rem // 3600), int((rem % 3600) // 60)
                await q.edit_message_text(f"\u23f3 Already checked in! Come back in *{h}h {m}m*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))
                return
            ns = u["streak"] + 1 if (now - ld).total_seconds() < 172800 else 1
        else:
            ns = 1
        bonus = min(10 + (ns * 5), 100)
        nc = add_coins(tid, bonus, f"Daily (streak {ns})")
        update_user(tid, last_daily=now.isoformat(), streak=ns)
        await q.edit_message_text(f"\ud83d\udcc5 *Daily Check-in!*\n\n\ud83d\udd25 Streak: *{ns}* days\n\ud83d\udcb0 Earned: *+{bonus}* coins\n\ud83e\ude99 Balance: *{nc}*\n\n\ud83d\udca1 Longer streaks = more coins!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "spin":
        now = datetime.utcnow()
        last = u.get("last_spin")
        if last:
            ld = datetime.fromisoformat(last)
            if (now - ld).total_seconds() < 3600:
                m = int((3600 - (now - ld).total_seconds()) // 60)
                await q.edit_message_text(f"\u23f3 Spin recharging! Try in *{m} min*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))
                return
        prizes = [(5,"\ud83c\udf4b 5 coins"),(10,"\ud83c\udf4a 10 coins"),(15,"\ud83c\udf47 15 coins"),(25,"\u2b50 25 coins"),(50,"\ud83d\udc8e 50 coins"),(100,"\ud83c\udfc6 100 coins JACKPOT!"),(0,"\ud83d\udca8 Better luck next time!"),(3,"\ud83c\udf40 3 coins")]
        weights = [25,25,15,10,5,2,15,3]
        p = random.choices(prizes, weights=weights, k=1)[0]
        nc = add_coins(tid, p[0], "Spin") if p[0] > 0 else u["coins"]
        update_user(tid, last_spin=now.isoformat())
        await q.edit_message_text(f"\ud83c\udfb0 *Spin the Wheel!*\n\nResult: {p[1]}\n\ud83e\ude99 Balance: *{nc}*\n\n\u23f0 Next spin in 1 hour!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "tasks":
        kb = [[InlineKeyboardButton("\u2705 Watch Ad (+20)", callback_data="task_watch")],[InlineKeyboardButton("\ud83d\udcdd Survey (+30)", callback_data="task_survey")],[InlineKeyboardButton("\ud83d\udce3 Share Bot (+15)", callback_data="task_share")],[InlineKeyboardButton("\ud83d\udd19 Back", callback_data="menu")]]
        await q.edit_message_text("\ud83c\udfaf *Daily Tasks*\n\nComplete tasks to earn!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("task_"):
        rw = {"task_watch":20,"task_survey":30,"task_share":15}
        nm = {"task_watch":"Watch Ad","task_survey":"Survey","task_share":"Share Bot"}
        r = rw.get(d,10); n = nm.get(d,"Task")
        nc = add_coins(tid, r, n)
        await q.edit_message_text(f"\u2705 *{n} Done!*\n\n\ud83d\udcb0 Earned: *+{r}* coins\n\ud83e\ude99 Balance: *{nc}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "quiz":
        qs = [{"q":"What is the capital of France?","o":["London","Paris","Berlin","Rome"],"a":1},{"q":"What is 15 x 7?","o":["95","105","115","85"],"a":1},{"q":"Closest planet to the Sun?","o":["Venus","Mercury","Mars","Earth"],"a":1},{"q":"What is the largest ocean?","o":["Atlantic","Indian","Pacific","Arctic"],"a":2},{"q":"How many continents?","o":["5","6","7","8"],"a":2},{"q":"Who painted the Mona Lisa?","o":["Picasso","Van Gogh","Da Vinci","Monet"],"a":2},{"q":"What is H2O?","o":["Oxygen","Hydrogen","Water","Helium"],"a":2}]
        qz = random.choice(qs)
        context.user_data["quiz_answer"] = qz["a"]
        kb = [[InlineKeyboardButton(o, callback_data=f"quiz_{i}")] for i,o in enumerate(qz["o"])]
        kb.append([InlineKeyboardButton("\ud83d\udd19 Back", callback_data="menu")])
        await q.edit_message_text(f"\ud83c\udfae *Quiz Time!*\n\n\u2753 {qz['q']}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("quiz_"):
        ch = int(d.split("_")[1])
        cor = context.user_data.get("quiz_answer", -1)
        if ch == cor:
            r = random.randint(15, 40)
            nc = add_coins(tid, r, "Quiz correct")
            txt = f"\u2705 *Correct!*\n\n\ud83d\udcb0 Earned: *+{r}* coins\n\ud83e\ude99 Balance: *{nc}*"
        else:
            txt = "\u274c *Wrong!* Better luck next time!"
        kb = [[InlineKeyboardButton("\ud83c\udfae Play Again", callback_data="quiz")],[InlineKeyboardButton("\ud83d\udd19 Back", callback_data="menu")]]
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d == "coinflip":
        kb = [[InlineKeyboardButton("\ud83e\ude99 Heads (Bet 10)", callback_data="flip_heads"),InlineKeyboardButton("\ud83e\ude99 Tails (Bet 10)", callback_data="flip_tails")],[InlineKeyboardButton("\ud83d\udd19 Back", callback_data="menu")]]
        await q.edit_message_text(f"\ud83c\udfb2 *Coin Flip!*\n\nBet 10, win 20!\n\ud83e\ude99 Balance: *{u['coins']}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("flip_"):
        if u["coins"] < 10:
            await q.edit_message_text("\u274c Not enough coins! Need at least 10.", reply_markup=InlineKeyboardMarkup(back))
            return
        ch = d.split("_")[1]
        res = random.choice(["heads","tails"])
        if ch == res:
            nc = add_coins(tid, 10, "Flip win")
            txt = f"\ud83c\udf89 *{res.upper()}!* You won!\n\ud83d\udcb0 +10 coins\n\ud83e\ude99 Balance: *{nc}*"
        else:
            nc = add_coins(tid, -10, "Flip loss")
            txt = f"\ud83d\ude14 *{res.upper()}!* You lost!\n\ud83d\udcb8 -10 coins\n\ud83e\ude99 Balance: *{nc}*"
        kb = [[InlineKeyboardButton("\ud83c\udfb2 Play Again", callback_data="coinflip")],[InlineKeyboardButton("\ud83d\udd19 Back", callback_data="menu")]]
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d == "mystery":
        if u["coins"] < 25:
            await q.edit_message_text("\u274c Mystery box costs *25 coins*. Not enough!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))
            return
        add_coins(tid, -25, "Mystery box")
        rws = [(10,"\ud83e\uddf8 Common: 10 coins"),(30,"\ud83c\udf1f Uncommon: 30 coins"),(75,"\ud83d\udc8e Rare: 75 coins"),(150,"\ud83d\udc51 Legendary: 150 coins"),(0,"\ud83d\udc80 Empty box!")]
        wts = [35,30,20,5,10]
        p = random.choices(rws, weights=wts, k=1)[0]
        nc = add_coins(tid, p[0], "Mystery reward") if p[0] > 0 else get_user(tid)["coins"]
        net = p[0] - 25
        e = "\ud83d\udcc8" if net>0 else "\ud83d\udcc9" if net<0 else "\u27a1\ufe0f"
        await q.edit_message_text(f"\ud83c\udf81 *Mystery Box!*\n\nResult: {p[1]}\n{e} Net: *{'+' if net>0 else ''}{net}*\n\ud83e\ude99 Balance: *{nc}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\ud83c\udf81 Open Another (25)", callback_data="mystery")],[InlineKeyboardButton("\ud83d\udd19 Back", callback_data="menu")]]))

    elif d == "leaderboard":
        lb = get_leaderboard()
        txt = "\ud83c\udfc6 *Top 10 Leaderboard*\n\n"
        medals = ["\ud83e\udd47","\ud83e\udd48","\ud83e\udd49"]
        for i,l in enumerate(lb):
            m = medals[i] if i < 3 else f"{i+1}."
            n = l.get("first_name") or l.get("username") or "Unknown"
            txt += f"{m} {n} \u2014 *{l['coins']}* coins (Lv.{l['level']})\n"
        if not lb: txt += "No users yet!"
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "referral":
        bi = await context.bot.get_me()
        rl = f"https://t.me/{bi.username}?start={u['referral_code']}"
        await q.edit_message_text(f"\ud83d\udc65 *Referral Program*\n\nShare and earn *100 coins* per referral!\n\n\ud83d\udd17 Your link:\n`{rl}`\n\nTap to copy!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "profile":
        cr = u.get("created_at","Unknown")[:10]
        await q.edit_message_text(f"\ud83d\udcca *Your Profile*\n\n\ud83d\udc64 Name: *{u.get('first_name','N/A')}*\n\ud83d\udcf1 Phone: *{u.get('phone','Not shared')}*\n\ud83e\ude99 Coins: *{u['coins']}*\n\u2b50 Level: *{u['level']}*\n\u2728 XP: *{u['xp']}*\n\ud83d\udd25 Streak: *{u['streak']}* days\n\ud83d\udcc8 Total: *{u['total_earned']}*\n\ud83d\udd17 Ref: `{u['referral_code']}`\n\ud83d\udcc5 Joined: *{cr}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "menu":
        await menu(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\ud83e\udd16 *CoinBot Help*\n\n\ud83d\udccc *Commands:*\n/start - Start the bot\n/menu - Open main menu\n/balance - Check balance\n/help - Show this help\n\n\ud83d\udca1 *Earning Methods:*\n\u2022 \ud83d\udcc5 Daily check-in (streak bonuses!)\n\u2022 \ud83c\udfb0 Spin wheel (every hour)\n\u2022 \ud83c\udfaf Complete tasks\n\u2022 \ud83c\udfae Quiz games\n\u2022 \ud83c\udfb2 Coin flip gambling\n\u2022 \ud83c\udf81 Mystery boxes\n\u2022 \ud83d\udc65 Refer friends (+100 each!)", parse_mode="Markdown")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if u: await update.message.reply_text(f"\ud83e\ude99 Balance: *{u['coins']}* coins | \u2b50 Level {u['level']}", parse_mode="Markdown")
    else: await update.message.reply_text("\u274c Please /start first!")

async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /menu \u2192 \ud83d\udcc5 Daily Check-in")

async def spin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /menu \u2192 \ud83c\udfb0 Spin Wheel")

async def referral_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if u:
        bi = await context.bot.get_me()
        rl = f"https://t.me/{bi.username}?start={u['referral_code']}"
        await update.message.reply_text(f"\ud83d\udd17 Your referral link:\n`{rl}`\n\n+100 coins per referral!", parse_mode="Markdown")
    else: await update.message.reply_text("\u274c Please /start first!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("spin", spin_cmd))
    app.add_handler(CommandHandler("referral", referral_cmd))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
