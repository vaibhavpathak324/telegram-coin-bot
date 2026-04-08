import os
import logging
import random
import asyncio
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
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
DATABASE_URL = os.environ.get("DATABASE_URL", "")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Auto-create tables on startup ---
def init_database():
    if not DATABASE_URL:
        logging.warning("No DATABASE_URL set, skipping table creation")
        return
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                phone TEXT,
                coins INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                last_daily TIMESTAMPTZ,
                last_spin TIMESTAMPTZ,
                referral_code TEXT UNIQUE,
                referred_by BIGINT,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);
            CREATE INDEX IF NOT EXISTS idx_users_coins ON users(coins DESC);
            CREATE INDEX IF NOT EXISTS idx_transactions_telegram_id ON transactions(telegram_id);
        """)
        for table in ['users', 'transactions']:
            cur.execute("ALTER TABLE %s ENABLE ROW LEVEL SECURITY;" % table)
            cur.execute("DROP POLICY IF EXISTS anon_all_%s ON %s;" % (table, table))
            cur.execute("CREATE POLICY anon_all_%s ON %s FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);" % (table, table))
        # Reload PostgREST schema cache
        cur.execute("NOTIFY pgrst, 'reload schema'")
        logging.info("Database tables created successfully! Schema cache reloaded.")
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Database init error: {type(e).__name__}: {e}")

init_database()

# --- Health check HTTP server for Render ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_health_server, daemon=True).start()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_user(tid):
    r = supabase.table("users").select("*").eq("telegram_id", tid).execute()
    return r.data[0] if r.data else None

def create_user(tid, uname, fname, phone=None):
    supabase.table("users").insert({"telegram_id":tid,"username":uname or "","first_name":fname or "","phone":phone,"coins":50,"streak":0,"level":1,"xp":0,"total_earned":50,"referral_code":f"REF{tid}"}).execute()

def update_user(tid, **kwargs):
    supabase.table("users").update(kwargs).eq("telegram_id", tid).execute()

def add_coins(tid, amount, reason=""):
    u = get_user(tid)
    nc = u["coins"] + amount
    ne = u["total_earned"] + (amount if amount > 0 else 0)
    nl = 1 + ne // 500
    update_user(tid, coins=nc, total_earned=ne, level=nl, xp=ne % 500)
    supabase.table("transactions").insert({"telegram_id":tid,"amount":amount,"reason":reason}).execute()
    return nc

def get_leaderboard():
    r = supabase.table("users").select("*").order("coins", desc=True).limit(10).execute()
    return r.data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = get_user(tid)
    args = context.args
    if not u:
        create_user(tid, update.effective_user.username, update.effective_user.first_name)
        if args and args[0].startswith("REF"):
            try:
                ref_tid = int(args[0][3:])
                if ref_tid != tid:
                    update_user(tid, referred_by=ref_tid)
                    add_coins(ref_tid, 100, f"Referral: {tid}")
            except: pass
        u = get_user(tid)
    kb = ReplyKeyboardMarkup([[KeyboardButton("\U0001f4f1 Share Phone", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(f"\U0001f3b0 *Welcome to CoinBot!* \U0001f4b0\n\nYou received *50 coins* to start!\n\nShare your phone for *bonus coins!*", parse_mode="Markdown", reply_markup=kb)
    await menu(update, context)

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    phone = update.message.contact.phone_number
    u = get_user(tid)
    if u and not u.get("phone"):
        update_user(tid, phone=phone)
        add_coins(tid, 25, "Phone shared")
        await update.message.reply_text("\u2705 Phone saved! +25 bonus coins!", reply_markup=ReplyKeyboardRemove())
    await menu(update, context)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = get_user(tid)
    if not u:
        await update.effective_message.reply_text("\u274c Please /start first!")
        return
    kb = [
        [InlineKeyboardButton("\U0001f4c5 Daily", callback_data="daily"), InlineKeyboardButton("\U0001f3b0 Spin", callback_data="spin")],
        [InlineKeyboardButton("\U0001f3af Tasks", callback_data="tasks"), InlineKeyboardButton("\U0001f3ae Quiz", callback_data="quiz")],
        [InlineKeyboardButton("\U0001f3b2 Coin Flip", callback_data="coinflip"), InlineKeyboardButton("\U0001f381 Mystery", callback_data="mystery")],
        [InlineKeyboardButton("\U0001f3c6 Leaderboard", callback_data="leaderboard"), InlineKeyboardButton("\U0001f465 Referral", callback_data="referral")],
        [InlineKeyboardButton("\U0001f4ca Profile", callback_data="profile")]
    ]
    txt = f"\U0001f3b0 *CoinBot Menu*\n\n\U0001fa99 Balance: *{u['coins']}* coins\n\u2b50 Level: *{u['level']}*\n\U0001f525 Streak: *{u['streak']}* days"
    if update.callback_query:
        await update.callback_query.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.effective_message.reply_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    tid = q.from_user.id
    u = get_user(tid)
    if not u:
        await q.edit_message_text("\u274c Please /start first!")
        return
    back = [[InlineKeyboardButton("\U0001f519 Back", callback_data="menu")]]

    if d == "daily":
        now = datetime.utcnow()
        last = u.get("last_daily")
        if last:
            ld = datetime.fromisoformat(last)
            if (now - ld).total_seconds() < 86400:
                h = int((86400 - (now - ld).total_seconds()) // 3600)
                await q.edit_message_text(f"\u23f3 Already claimed! Come back in *{h}h*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))
                return
            if (now - ld).total_seconds() < 172800:
                ns = u["streak"] + 1
            else:
                ns = 1
        else:
            ns = 1
        bonus = min(10 + (ns * 5), 100)
        nc = add_coins(tid, bonus, f"Daily (streak {ns})")
        update_user(tid, last_daily=now.isoformat(), streak=ns)
        await q.edit_message_text(f"\U0001f4c5 *Daily Check-in!*\n\n\U0001f525 Streak: *{ns}* days\n\U0001f4b0 Earned: *+{bonus}* coins\n\U0001fa99 Balance: *{nc}*\n\n\U0001f4a1 Longer streaks = more coins!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "spin":
        now = datetime.utcnow()
        last = u.get("last_spin")
        if last:
            ld = datetime.fromisoformat(last)
            if (now - ld).total_seconds() < 3600:
                m = int((3600 - (now - ld).total_seconds()) // 60)
                await q.edit_message_text(f"\u23f3 Spin recharging! Try in *{m} min*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))
                return
        prizes = [(5,"\U0001f34b 5 coins"),(10,"\U0001f34a 10 coins"),(15,"\U0001f347 15 coins"),(25,"\u2b50 25 coins"),(50,"\U0001f48e 50 coins"),(100,"\U0001f3c6 100 coins JACKPOT!"),(0,"\U0001f4a8 Better luck next time!"),(3,"\U0001f340 3 coins")]
        weights = [25,25,15,10,5,2,15,3]
        p = random.choices(prizes, weights=weights, k=1)[0]
        nc = add_coins(tid, p[0], "Spin") if p[0] > 0 else u["coins"]
        update_user(tid, last_spin=now.isoformat())
        await q.edit_message_text(f"\U0001f3b0 *Spin the Wheel!*\n\nResult: {p[1]}\n\U0001fa99 Balance: *{nc}*\n\n\u23f0 Next spin in 1 hour!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "tasks":
        kb = [[InlineKeyboardButton("\u2705 Watch Ad (+20)", callback_data="task_watch")],[InlineKeyboardButton("\U0001f4dd Survey (+30)", callback_data="task_survey")],[InlineKeyboardButton("\U0001f4e3 Share Bot (+15)", callback_data="task_share")],[InlineKeyboardButton("\U0001f519 Back", callback_data="menu")]]
        await q.edit_message_text("\U0001f3af *Daily Tasks*\n\nComplete tasks to earn!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("task_"):
        rw = {"task_watch":20,"task_survey":30,"task_share":15}
        nm = {"task_watch":"Watch Ad","task_survey":"Survey","task_share":"Share Bot"}
        r = rw.get(d,10); n = nm.get(d,"Task")
        nc = add_coins(tid, r, n)
        await q.edit_message_text(f"\u2705 *{n} Done!*\n\n\U0001f4b0 Earned: *+{r}* coins\n\U0001fa99 Balance: *{nc}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "quiz":
        qs = [{"q":"What is the capital of France?","o":["London","Paris","Berlin","Rome"],"a":1},{"q":"What is 15 x 7?","o":["95","105","115","85"],"a":1},{"q":"Closest planet to the Sun?","o":["Venus","Mercury","Mars","Earth"],"a":1},{"q":"What is the largest ocean?","o":["Atlantic","Indian","Pacific","Arctic"],"a":2},{"q":"How many continents?","o":["5","6","7","8"],"a":2},{"q":"Who painted the Mona Lisa?","o":["Picasso","Van Gogh","Da Vinci","Monet"],"a":2},{"q":"What is H2O?","o":["Oxygen","Hydrogen","Water","Helium"],"a":2}]
        qz = random.choice(qs)
        context.user_data["quiz_answer"] = qz["a"]
        kb = [[InlineKeyboardButton(o, callback_data=f"quiz_{i}")] for i,o in enumerate(qz["o"])]
        kb.append([InlineKeyboardButton("\U0001f519 Back", callback_data="menu")])
        await q.edit_message_text(f"\U0001f3ae *Quiz Time!*\n\n\u2753 {qz['q']}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("quiz_"):
        ch = int(d.split("_")[1])
        cor = context.user_data.get("quiz_answer", -1)
        if ch == cor:
            r = random.randint(15, 40)
            nc = add_coins(tid, r, "Quiz correct")
            txt = f"\u2705 *Correct!*\n\n\U0001f4b0 Earned: *+{r}* coins\n\U0001fa99 Balance: *{nc}*"
        else:
            txt = "\u274c *Wrong!* Better luck next time!"
        kb = [[InlineKeyboardButton("\U0001f3ae Play Again", callback_data="quiz")],[InlineKeyboardButton("\U0001f519 Back", callback_data="menu")]]
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d == "coinflip":
        kb = [[InlineKeyboardButton("\U0001fa99 Heads (Bet 10)", callback_data="flip_heads"),InlineKeyboardButton("\U0001fa99 Tails (Bet 10)", callback_data="flip_tails")],[InlineKeyboardButton("\U0001f519 Back", callback_data="menu")]]
        await q.edit_message_text(f"\U0001f3b2 *Coin Flip!*\n\nBet 10, win 20!\n\U0001fa99 Balance: *{u['coins']}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith("flip_"):
        if u["coins"] < 10:
            await q.edit_message_text("\u274c Not enough coins! Need at least 10.", reply_markup=InlineKeyboardMarkup(back))
            return
        ch = d.split("_")[1]
        res = random.choice(["heads","tails"])
        if ch == res:
            nc = add_coins(tid, 10, "Flip win")
            txt = f"\U0001f389 *{res.upper()}!* You won!\n\U0001f4b0 +10 coins\n\U0001fa99 Balance: *{nc}*"
        else:
            nc = add_coins(tid, -10, "Flip loss")
            txt = f"\U0001f614 *{res.upper()}!* You lost!\n\U0001f4b8 -10 coins\n\U0001fa99 Balance: *{nc}*"
        kb = [[InlineKeyboardButton("\U0001f3b2 Play Again", callback_data="coinflip")],[InlineKeyboardButton("\U0001f519 Back", callback_data="menu")]]
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif d == "mystery":
        if u["coins"] < 25:
            await q.edit_message_text("\u274c Mystery box costs *25 coins*. Not enough!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))
            return
        add_coins(tid, -25, "Mystery box")
        rws = [(10,"\U0001f9f8 Common: 10 coins"),(30,"\U0001f31f Uncommon: 30 coins"),(75,"\U0001f48e Rare: 75 coins"),(150,"\U0001f451 Legendary: 150 coins"),(0,"\U0001f480 Empty box!")]
        wts = [35,30,20,5,10]
        p = random.choices(rws, weights=wts, k=1)[0]
        nc = add_coins(tid, p[0], "Mystery reward") if p[0] > 0 else get_user(tid)["coins"]
        net = p[0] - 25
        e = "\U0001f4c8" if net>0 else "\U0001f4c9" if net<0 else "\u27a1\ufe0f"
        await q.edit_message_text(f"\U0001f381 *Mystery Box!*\n\nResult: {p[1]}\n{e} Net: *{'+' if net>0 else ''}{net}*\n\U0001fa99 Balance: *{nc}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f381 Open Another (25)", callback_data="mystery")],[InlineKeyboardButton("\U0001f519 Back", callback_data="menu")]]))

    elif d == "leaderboard":
        lb = get_leaderboard()
        txt = "\U0001f3c6 *Top 10 Leaderboard*\n\n"
        medals = ["\U0001f947","\U0001f948","\U0001f949"]
        for i,l in enumerate(lb):
            m = medals[i] if i < 3 else f"{i+1}."
            n = l.get("first_name") or l.get("username") or "Unknown"
            txt += f"{m} {n} \u2014 *{l['coins']}* coins (Lv.{l['level']})\n"
        if not lb: txt += "No users yet!"
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d=="referral":
        bi = await context.bot.get_me()
        rl = f"https://t.me/{bi.username}?start={u['referral_code']}"
        await q.edit_message_text(f"\U0001f465 *Referral Program*\n\nShare and earn *100 coins* per referral!\n\n\U0001f517 Your link:\n`{rl}`\n\nTap to copy!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "profile":
        cr = u.get("created_at","Unknown")[:10]
        await q.edit_message_text(f"\U0001f4ca *Your Profile*\n\n\U0001f464 Name: *{u.get('first_name','N/A')}*\n\U0001f4f1 Phone: *{u.get('phone','Not shared')}*\n\U0001fa99 Coins: *{u['coins']}*\n\u2b50 Level: *{u['level']}*\n\u2728 XP: *{u['xp']}*\n\U0001f525 Streak: *{u['streak']}* days\n\U0001f4c8 Total: *{u['total_earned']}*\n\U0001f517 Ref: `{u['referral_code']}`\n\U0001f4c5 Joined: *{cr}*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back))

    elif d == "menu":
        await menu(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\U0001f916 *CoinBot Help*\n\n\U0001f4cc *Commands:*\n/start - Start the bot\n/menu - Open main menu\n/balance - Check balance\n/help - Show this help\n\n\U0001f4a1 *Earning Methods:*\n\u2022 \U0001f4c5 Daily check-in (streak bonuses!)\n\u2022 \U0001f3b0 Spin wheel (every hour)\n\u2022 \U0001f3af Complete tasks\n\u2022 \U0001f3ae Quiz games\n\u2022 \U0001f3b2 Coin flip gambling\n\u2022 \U0001f381 Mystery boxes\n\u2022 \U0001f465 Refer friends (+100 each!)", parse_mode="Markdown")

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if u: await update.message.reply_text(f"\U0001fa99 Balance: *{u['coins']}* coins | \u2b50 Level {u['level']}", parse_mode="Markdown")
    else: await update.message.reply_text("\u274c Please /start first!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
