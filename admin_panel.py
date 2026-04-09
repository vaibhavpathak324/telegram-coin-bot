import os
import json
import asyncio
import logging
import time
import secrets
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, session
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# -----------------------------------------------
# Env Config
# -----------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")

# -----------------------------------------------
# Supabase client
# -----------------------------------------------
supa: Client = None

def get_supa():
    global supa
    if supa is None and SUPABASE_URL and SUPABASE_KEY:
        supa = create_client(SUPABASE_URL, SUPABASE_KEY)
    return supa

# -----------------------------------------------
# Flask App
# -----------------------------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", secrets.token_hex(32))

# -----------------------------------------------
# Auth helpers
# -----------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/panel/login")
        return f(*args, **kwargs)
    return decorated

# -----------------------------------------------
# Login / Logout
# -----------------------------------------------
@app.route("/panel/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    data = request.get_json(silent=True) or {}
    if data.get("password") == ADMIN_PASSWORD:
        session["admin_logged_in"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "Invalid password"}), 401

@app.route("/panel/logout")
def logout():
    session.clear()
    return redirect("/panel/login")

# -----------------------------------------------
# Dashboard
# -----------------------------------------------
@app.route("/panel")
@login_required
def dashboard():
    return render_template("admin.html")

# -----------------------------------------------
# API - Stats
# -----------------------------------------------
@app.route("/panel/api/stats")
@login_required
def api_stats():
    s = get_supa()
    if not s:
        return jsonify({"error": "DB not configured"}), 500
    try:
        users = s.table("users").select("*", count="exact").execute()
        total_users = users.count or 0
        user_data = users.data or []

        total_coins = sum(u.get("coins", 0) for u in user_data)

        txns = s.table("transactions").select("*", count="exact").execute()
        total_txns = txns.count or 0

        active_bots = s.table("userbot_sessions").select("*", count="exact").eq("active", True).execute()
        total_bots = active_bots.count or 0

        return jsonify({
            "total_users": total_users,
            "total_coins": total_coins,
            "total_transactions": total_txns,
            "active_userbots": total_bots
        })
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Users
# -----------------------------------------------
@app.route("/panel/api/users")
@login_required
def api_users():
    s = get_supa()
    if not s:
        return jsonify([])
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        search = request.args.get("search", "").strip()

        q = s.table("users").select("*", count="exact")
        if search:
            q = q.or_(f"username.ilike.%{<search}%,first_name.ilike.%{search}%,user_id.eq.{search}")

        start = (page - 1) * per_page
        res = q.order("coins", desc=True).range(start, start + per_page - 1).execute()

        return jsonify({
            "users": res.data or [],
            "total": res.count or 0,
            "page": page,
            "per_page": per_page
        })
    except Exception as e:
        logger.error(f"Users API error: {e}")
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Update user coins
# -----------------------------------------------
@app.route("/panel/api/users/<user_id>/coins", methods=["POST"])
@login_required
def api_update_coins(user_id):
    s = get_supa()
    if not s:
        return jsonify({"error": "DB not configured"}), 500
    data = request.get_json(silent=True) or {}
    amount = data.get("amount", 0)
    action = data.get("action", "set")  # set, add, subtract
    try:
        user = s.table("users").select("*").eq("user_id", user_id).single().execute()
        current = user.data.get("coins", 0)

        if action == "add":
            new_val = current + int(amount)
        elif action == "subtract":
            new_val = max(0, current - int(amount))
        else:
            new_val = int(amount)

        s.table("users").update({"coins": new_val}).eq("user_id", user_id).execute()
        return jsonify({"ok": True, "new_coins": new_val})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Ban/Unban user
# -----------------------------------------------
@app.route("/panel/api/users/<user_id>/ban", methods=["POST"])
@login_required
def api_ban_user(user_id):
    s = get_supa()
    if not s:
        return jsonify({"error": "DB not configured"}), 500
    data = request.get_json(silent=True) or {}
    banned = data.get("banned", True)
    try:
        s.table("users").update({"banned": banned}).eq("user_id", user_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Transactions
# -----------------------------------------------
@app.route("/panel/api/transactions")
@login_required
def api_transactions():
    s = get_supa()
    if not s:
        return jsonify([])
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        start = (page - 1) * per_page
        res = s.table("transactions").select("*", count="exact").order("created_at", desc=True).range(start, start + per_page - 1).execute()
        return jsonify({
            "transactions": res.data or [],
            "total": res.count or 0,
            "page": page
        })
    except Exception as e:
        return jsonify([])

# -----------------------------------------------
# API - Userbot Sessions
# -----------------------------------------------
@app.route("/panel/api/userbots")
@login_required
def api_userbots():
    s = get_supa()
    if not s:
        return jsonify([])
    try:
        res = s.table("userbot_sessions").select("*").order("created_at", desc=True).execute()
        return jsonify(res.data or [])
    except Exception as e:
        return jsonify([])

# -----------------------------------------------
# API - Broadcast message
# -----------------------------------------------
@app.route("/panel/api/broadcast", methods=["POST"])
@login_required
def api_broadcast():
    import requests as http_req
    s = get_supa()
    if not s or not BOT_TOKEN:
        return jsonify({"error": "Not configured"}), 500
    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    try:
        users = s.table("users").select("user_id").execute()
        sent = 0
        failed = 0
        for u in (users.data or []):
            try:
                resp = http_req.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": u["user_id"], "text": message, "parse_mode": "HTML"},
                    timeout=10
                )
                if resp.status_code == 200:
                    sent += 1
                else:
                    failed += 1
                time.sleep(0.05)  # rate limit
            except:
                failed += 1
        return jsonify({"sent": sent, "failed": failed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Auto-Join Toggle
# -----------------------------------------------
@app.route("/panel/api/autojoin", methods=["GET", "POST"])
@login_required
def api_autojoin():
    s = get_supa()
    if not s:
        return jsonify({"error": "DB not configured"}), 500
    if request.method == "GET":
        try:
            res = s.table("bot_settings").select("*").eq("key", "auto_join_enabled").execute()
            if res.data:
                return jsonify({"enabled": res.data[0].get("value") == "true"})
            return jsonify({"enabled": False})
        except:
            return jsonify({"enabled": False})
    else:
        data = request.get_json(silent=True) or {}
        enabled = data.get("enabled", False)
        try:
            s.table("bot_settings").upsert({"key": "auto_join_enabled", "value": str(enabled).lower()}).execute()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Group management
# -----------------------------------------------
@app.route("/panel/api/groups", methods=["GET"])
@login_required
def api_groups():
    s = get_supa()
    if not s:
        return jsonify([])
    try:
        res = s.table("groups").select("*").order("created_at", desc=True).execute()
        return jsonify({"groups": res.data or []})
    except:
        return jsonify({"groups": []})

@app.route("/panel/api/groups", methods=["POST"])
@login_required
def api_add_group():
    s = get_supa()
    if not s:
        return jsonify({"error": "DB not configured"}), 500
    data = request.get_json(silent=True) or {}
    group_link = data.get("link", "").strip()
    if not group_link:
        return jsonify({"error": "No link provided"}), 400
    try:
        s.table("groups").insert({"link": group_link, "status": "pending"}).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/panel/api/groups/<group_id>", methods=["DELETE"])
@login_required
def api_delete_group(group_id):
    s = get_supa()
    if not s:
        return jsonify({"error": "DB not configured"}), 500
    try:
        s.table("groups").delete().eq("id", group_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# API - Send message to specific user
# -----------------------------------------------
@app.route("/panel/api/send_message", methods=["POST"])
@login_required
def api_send_message():
    import requests as http_req
    if not BOT_TOKEN:
        return jsonify({"error": "Bot token not configured"}), 500
    data = request.get_json(silent=True) or {}
    chat_id = data.get("chat_id", "")
    message = data.get("message", "").strip()
    if not chat_id or not message:
        return jsonify({"error": "Missing chat_id or message"}), 400
    try:
        resp = http_req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10
        )
        if resp.status_code == 200:
            return jsonify({"ok": True})
        return jsonify({"error": resp.text}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------
# Health check
# -----------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": time.time()})

@app.route("/")
def index_redirect():
    return redirect("/panel")
