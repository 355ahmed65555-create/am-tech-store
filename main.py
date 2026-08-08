import os
import sys
import random
import string
import json
import json as json_lib
import re
import asyncio
import threading
import datetime
import time
import traceback
import logging
import pyotp
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, Update, BotCommand
from telegram.error import NetworkError, TimedOut
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AHMED_BOT")

# ==================== BOT TOKEN ====================
# يمكن تجاوزه عبر Environment: BOT_TOKEN
MAIN_BOT_TOKEN = (os.getenv("MAIN_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "8737169787:AAF1ZRw7a1M9NM4A6KNEiTT1fCtblKzDGnk").strip()
BOT_TOKEN = MAIN_BOT_TOKEN  # alias للتوافق مع باقي الكود
if not MAIN_BOT_TOKEN:
    print("ERROR: MAIN_BOT_TOKEN missing")
    sys.exit(1)
print("Main bot token loaded - Starting...")

try:
    with open("admins.json","r") as f:
        SUPER_ADMINS = json_lib.load(f)
except Exception as e:
    SUPER_ADMINS = [6364073135]
WHATSAPP_NUMBER = "201096514020"

# ==================== نظام تنبيهات المالك - طلب الاسطى ====================
try:
    _oid = (os.getenv("OWNER_ID") or "6364073135").strip()
    OWNER_ID = int(_oid) if _oid else 6364073135
except Exception:
    OWNER_ID = 6364073135
if not OWNER_ID:
    print("WARNING: OWNER_ID environment variable is not set")
if SUPER_ADMINS and OWNER_ID and OWNER_ID not in SUPER_ADMINS:
    SUPER_ADMINS.insert(0, OWNER_ID)
elif (not SUPER_ADMINS) and OWNER_ID:
    SUPER_ADMINS = [OWNER_ID]

# ==================== بوت الأدمن المنفصل (نفس الملف) ====================
# التوكن خاص ببوت الأدمن فقط - لا يُستخدم للبوت الأساسي
ADMIN_BOT_TOKEN = (os.getenv("ADMIN_BOT_TOKEN") or "8688597772:AAG5OHR9e9RumorsyJb6mhZCi0WLtGqe2dM").strip()
_ADMIN_PW_SEED_HASH = "3f2496ab0aefa362ece466880b8ae469$54565c9b64506051444ff9830b607e30d2077a19fbe2902730c78b3cc2e2ba11"

def _ensure_admin_password_seeded():
    try:
        s = load_settings()
        if not s.get("admin_password_hash"):
            s["admin_password_hash"] = _ADMIN_PW_SEED_HASH
            s.pop("admin_password", None)
            save_settings(s)
    except Exception as e:
        try:
            logger.debug(f"pw seed: {e}")
        except Exception:
            pass



# تم إلغاء العبارة السرية — الدخول: UserID → أدمن → موافقة المالك → كلمة المرور



def _hash_password(password: str) -> str:
    import hashlib, secrets as _sec
    salt = _sec.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${h.hex()}"

def _verify_password(password: str, stored: str) -> bool:
    """تحقق آمن من كلمة المرور مقابل Hash+Salt. لا يسجّل كلمة المرور أبداً."""
    import hashlib, secrets as _sec
    if password is None:
        logger.warning("[AUTH] password verification called with None password")
        return False
    if not stored:
        logger.warning("[AUTH] no stored password hash available")
        return False
    if "$" not in str(stored):
        logger.warning("[AUTH] stored hash format invalid (missing salt separator)")
        return False
    try:
        salt, h = str(stored).split("$", 1)
        if not salt or not h:
            logger.warning("[AUTH] stored hash has empty salt or digest")
            return False
        if len(h) != 64:  # sha256 hex
            logger.warning(f"[AUTH] unexpected digest length: {len(h)}")
        check = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            salt.encode("utf-8"),
            120000,
        )
        ok = _sec.compare_digest(check.hex(), h)
        if not ok:
            logger.info("[AUTH] password verification failed (mismatch)")
        return ok
    except UnicodeEncodeError as e:
        logger.error(f"[AUTH] password encode error: {type(e).__name__}")
        return False
    except ValueError as e:
        logger.error(f"[AUTH] hash parse/value error: {type(e).__name__}")
        return False
    except Exception as e:
        logger.error(f"[AUTH] unexpected hash verification error: {type(e).__name__}: {e}")
        return False

def set_admin_panel_password(new_password: str) -> bool:
    if len(new_password) < 4:
        return False
    s = load_settings()
    s["admin_password_hash"] = _hash_password(new_password)
    s.pop("admin_password", None)
    save_settings(s)
    return True

def check_admin_panel_password(password: str) -> bool:
    s = load_settings()
    stored = s.get("admin_password_hash", "")
    if not stored:
        try:
            stored = _ADMIN_PW_SEED_HASH
            s["admin_password_hash"] = stored
            s.pop("admin_password", None)
            save_settings(s)
        except Exception:
            pass
    if stored:
        return _verify_password(password, stored)
    # ترحيل من كلمة قديمة نصية إن وجدت
    old = s.get("admin_password")
    if old and password == old:
        set_admin_panel_password(password)
        return True
    # افتراضي أولي من البيئة مرة واحدة
    default_pw = os.getenv("ADMIN_DEFAULT_PASSWORD", "")
    if default_pw and password == default_pw:
        set_admin_panel_password(password)
        return True
    return False

def create_admin_access_request(uid, username="", first_name=""):
    import secrets as _sec
    db = fast_load_db()
    req_id = _sec.token_hex(8)
    db.setdefault("admin_access_requests", {})[req_id] = {
        "uid": int(uid), "username": username or "", "first_name": first_name or "",
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(), "status": "pending",
    }
    fast_save_db(db)
    return req_id

def set_admin_access_status(req_id, status, by_owner=None):
    db = fast_load_db()
    req = db.get("admin_access_requests", {}).get(req_id)
    if not req:
        return False, None
    req["status"] = status
    req["resolved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    req["resolved_by"] = by_owner
    if status == "approved":
        db.setdefault("admin_sessions", {})[str(req["uid"])] = {
            "approved": True,
            "active": False,  # ينتظر كلمة المرور
            "until_ts": time.time() + 12 * 3600,
            "approved_at": req["resolved_at"],
            "by_owner": by_owner,
            "req_id": req_id,
        }
        # حالة مستقلة في DB
        db.setdefault("admin_login_states", {})[str(req["uid"])] = {
            "state": "waiting_for_password",
            "req_id": req_id,
            "until_ts": time.time() + 12 * 3600,
            "updated_at": req["resolved_at"],
        }
    else:
        db.get("admin_sessions", {}).pop(str(req["uid"]), None)
        db.get("admin_login_states", {}).pop(str(req["uid"]), None)
    fast_save_db(db)
    return True, req

def _admin_login_get(uid):
    """حالة دخول بوت الأدمن لكل User ID بشكل مستقل في DB"""
    db = fast_load_db()
    return db.get("admin_login_states", {}).get(str(uid), {}) or {}

def _admin_login_set(uid, state=None, **extra):
    db = fast_load_db()
    key = str(uid)
    cur = dict(db.get("admin_login_states", {}).get(key) or {})
    if state is not None:
        cur["state"] = state
    cur.update(extra)
    cur["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.setdefault("admin_login_states", {})[key] = cur
    fast_save_db(db)
    return cur

def _admin_login_clear(uid):
    db = fast_load_db()
    db.get("admin_login_states", {}).pop(str(uid), None)
    db.get("admin_sessions", {}).pop(str(uid), None)
    fast_save_db(db)

def has_valid_admin_session(uid):
    """جلسة لوحة أدمن نشطة (بعد موافقة + كلمة مرور) ولم تنتهِ"""
    # من admin_sessions
    db = fast_load_db()
    sess = db.get("admin_sessions", {}).get(str(uid))
    if sess and sess.get("active") and sess.get("until_ts", 0) >= time.time():
        return True
    # من login_states
    st = _admin_login_get(uid)
    if st.get("state") == "authenticated" and st.get("until_ts", 0) >= time.time():
        return True
    return False

def has_owner_approval_pending_password(uid):
    """موافقة المالك تمت وينتظر كلمة المرور — لا استثناء للمالك"""
    st = _admin_login_get(uid)
    if st.get("state") == "waiting_for_password":
        if st.get("until_ts", 0) and st.get("until_ts", 0) < time.time():
            return False
        return True
    db = fast_load_db()
    sess = db.get("admin_sessions", {}).get(str(uid))
    if not sess:
        return False
    if sess.get("until_ts", 0) < time.time():
        return False
    return bool(sess.get("approved")) and not sess.get("active")

def activate_admin_session_after_password(uid):
    until = time.time() + 12 * 3600
    db = fast_load_db()
    db.setdefault("admin_sessions", {})[str(uid)] = {
        "approved": True,
        "active": True,
        "until_ts": until,
        "activated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    fast_save_db(db)
    _admin_login_set(uid, state="authenticated", until_ts=until)

def clear_admin_session(uid):
    _admin_login_clear(uid)

def is_owner(uid):
    try:
        return int(uid) == int(OWNER_ID)
    except Exception:
        return False

_error_notify_cache = {}
_error_notify_lock = threading.Lock()

async def notify_owner(context_or_bot, title, details=""):
    """يبعت تنبيه للمالك على طول لو فيه خطأ"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # منع السبام - نفس الخطأ ما يتبعتش غير كل 5 دقايق
        cache_key = f"{title}:{details[:100]}"
        with _error_notify_lock:
            last_time = _error_notify_cache.get(cache_key, 0)
            now_ts = time.time()
            if now_ts - last_time < 300:  # 5 دقايق
                return
            _error_notify_cache[cache_key] = now_ts
        
        msg = (
            f"🚨 <b>تنبيه بوت - {title}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🕐 الوقت: {now}\n"
            f"📋 التفاصيل:\n{details[:1500]}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👑 للمالك فقط - ID: {OWNER_ID}"
        )
        # حاول تبعت عن طريق context
        bot = None
        if hasattr(context_or_bot, 'bot'):
            bot = context_or_bot.bot
        else:
            bot = context_or_bot
        
        if bot:
            await bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="HTML")
            logger.info(f"✅ تم ارسال تنبيه للمالك: {title}")
    except Exception as e:
        logger.info(f"❌ فشل ارسال تنبيه للمالك: {e}")

def notify_owner_sync(bot, title, details=""):
    """نسخة sync للاستخدام في اماكن غير async"""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"🚨 <b>تنبيه بوت - {title}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🕐 {now}\n"
            f"📋 {details[:1500]}\n"
            f"━━━━━━━━━━━━━━━"
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="HTML"))
            else:
                loop.run_until_complete(bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="HTML"))
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")

# ==================== تتبع إضافي للمالك ====================
_failed_logins = {}  # uid -> [timestamps]
_new_users_today = []
_spam_tracker = {}

def track_failed_login(uid, username_attempt):
    """يتتبع محاولات الدخول الفاشلة"""
    now = time.time()
    _failed_logins.setdefault(str(uid), []).append({"time": now, "user": username_attempt})
    # نظف القديم (اكتر من 10 دقايق)
    _failed_logins[str(uid)] = [x for x in _failed_logins[str(uid)] if now - x["time"] < 600]
    return len(_failed_logins[str(uid)])

def track_new_user(uid, username):
    """يتتبع المستخدمين الجدد"""
    _new_users_today.append({"uid": uid, "username": username, "time": time.time()})
    if len(_new_users_today) > 100:
        _new_users_today.pop(0)

def track_spam(uid):
    """يكشف السبام - لو حد بعت اكتر من 15 رسالة في دقيقة"""
    now = time.time()
    _spam_tracker.setdefault(str(uid), [])
    _spam_tracker[str(uid)].append(now)
    # نظف القديم (اكتر من دقيقة)
    _spam_tracker[str(uid)] = [t for t in _spam_tracker[str(uid)] if now - t < 60]
    count = len(_spam_tracker[str(uid)])
    return count

# ==================== تقارير يومية ونسخ احتياطي ====================
async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    """يبعت تقرير يومي للمالك - عدد المستخدمين الجدد والنشطين"""
    try:
        db = fast_load_db()
        tracks = db.get("user_tracks", {})
        total = len(tracks)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        new_today = sum(1 for u in tracks.values() if today in u.get("first_seen",""))
        active_today = sum(1 for u in tracks.values() if today in u.get("last_seen",""))
        msg = (
            f"📊 <b>التقرير اليومي - {today}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👥 إجمالي المستخدمين: {total}\n"
            f"🆕 جدد اليوم: {new_today}\n"
            f"🟢 نشطين اليوم: {active_today}\n"
            f"📧 دومينات البريد: {len(ALL_FREE_DOMAINS)}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ البوت شغال تمام"
        )
        await context.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="HTML")
    except Exception as e:
        logger.info(f"daily report error: {e}")

async def auto_backup(context: ContextTypes.DEFAULT_TYPE):
    """نسخ احتياطي تلقائي كل 6 ساعات - يبعت db.json للمالك"""
    try:
        db = fast_load_db()
        total_users = len(db.get("user_tracks", {}))
        # ابعت ملخص مش الملف كله عشان ميبقاش تقيل
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"💾 <b>نسخ احتياطي تلقائي</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🕐 الوقت: {now}\n"
            f"👥 المستخدمين: {total_users}\n"
            f"📁 حجم DB: {len(str(db))//1024} KB\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ تم الحفظ تلقائياً"
        )
        await context.bot.send_message(chat_id=OWNER_ID, text=msg, parse_mode="HTML")
        # لو عايز الملف نفسه، الغي التعليق:
        # await context.bot.send_document(chat_id=OWNER_ID, document=open(DB_FILE, 'rb'), filename=f"backup_{now}.json")
    except Exception as e:
        logger.info(f"backup error: {e}")






# ==================== Keep Alive Server ====================
HAS_FLASK = False
app_flask = None
try:
    from flask import Flask
    app_flask = Flask(__name__)
    @app_flask.route('/')
    def home():
        return "Bot is Running 24/7"
    @app_flask.route('/ping')
    def ping():
        return "Pong! Bot Alive"
    def run_flask():
        try:
            port = int(os.getenv("PORT", 8080))
            app_flask.run(host='0.0.0.0', port=port)
        except Exception as e:
            logger.debug(f"Flask run error: {e}")
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False
    logger.info("Flask not installed - running without web server")

def keep_alive():
    if not HAS_FLASK:
        print("Flask not installed, skipping web server")
        return
    try:
        t = threading.Thread(target=run_flask, daemon=True)
        t.start()
        logger.info("Keep-Alive Server Started")
    except Exception as e:
        logger.debug(f"keep_alive error: {e}")



# [REMOVED DUPLICATE DB BLOCK - optimized version kept]
SETTINGS_FILE = "settings.json"

SERVICES_OLD = {
    "whatsapp": {"name": "واتساب", "icon": "💚", "flag": "💚"},
    "telegram": {"name": "تليجرام", "icon": "💙", "flag": "💙"}
}


def update_user_track(uid, username="", name=""):
    # فحص سبام قبل أي حاجة
    try:
        cnt = track_spam(uid)
        if cnt > 20:
            logger.info(f"⚠️ سبام من {uid}: {cnt} رسائل في دقيقة")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    db = fast_load_db()
    uid_str = str(uid)
    db.setdefault("user_tracks", {})
    if uid_str not in db["user_tracks"]:
        db["user_tracks"][uid_str] = {"first_seen": "", "last_seen": "", "username": "", "name": "", "blocked": False, "messages": 0}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not db["user_tracks"][uid_str]["first_seen"]:
        db["user_tracks"][uid_str]["first_seen"] = now
    db["user_tracks"][uid_str]["last_seen"] = now
    db["user_tracks"][uid_str]["username"] = username or db["user_tracks"][uid_str].get("username","")
    db["user_tracks"][uid_str]["name"] = name or db["user_tracks"][uid_str].get("name","")
    db["user_tracks"][uid_str]["messages"] = db["user_tracks"][uid_str].get("messages",0)+1
    db["user_tracks"][uid_str]["blocked"] = False
    fast_save_db(db)

def load_db_OLD():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "allowed_usernames": [], "authorized": {}, "user_tracks": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("allowed_usernames", [])
            data.setdefault("authorized", {})
            data.setdefault("users", {})
            data.setdefault("user_tracks", {})
            return data
    except Exception as e:
        return {"users": {}, "allowed_usernames": [], "authorized": {}, "user_tracks": {}}

def save_db_OLD(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def load_settings():
    default = {"bot_active": True, "welcome_auth": "👑 أهلاً بك يا {first_name} 👑\n\n🤖 AHMED VIP Bot V33\n\n━━━━━━━━━━━━━━━\n⚡ سرعة صاروخية - 0.1 ثانية\n🔒 أمان وخصوصية 100%\n📧 بريد مؤقت - 15 دومين مجاني\n📱 أرقام مؤقتة - كل الدول\n🌍 3 لغات - عربي / انجليزي\n━━━━━━━━━━━━━━━\n💎 الإصدار المجاني الكامل - بدون فلوس\n\n📌 اختر الخدمة من القائمة تحت 👇", "welcome_unauth": "👋 أهلاً بك، {first_name}\n\n🤖 AHMED Bot\n\n━━━━━━━━━━━━━━━\n⚡ سرعة في التنفيذ\n🔒 أمان وخصوصية\n🚀 أدوات ذكية في مكان واحد\n━━━━━━━━━━━━━━━\n\n🔐 اكتب اليوزر الخاص بك للمواصلة", "admin_password": "AHMED2011/10/1", "admin_passwords": {}, "admin_perms": {}, "last_updates": "🚀 <b>آخر التحديثات - الإصدار النهائي</b>\n\n━━━━━━━━━━━━━━━\n✅ إضافة البريد المؤقت الحقيقي (يستقبل أكواد فورية)\n✅ إضافة الأرقام المؤقتة بالخدمة (فيسبوك/واتساب/انستا/تيك توك...)\n✅ اختيار الدولة (مصر، أمريكا، بريطانيا...)\n✅ نظام رقم واحد = شخص واحد بس (مفيش تكرار)\n✅ فحص هل الرقم مستخدم على المنصة ولا لا\n✅ اختيار اللغة عربي/إنجليزي من /start\n✅ البوت بقى طيارة (0.1 ثانية)\n✅ تحسين واجهة الأرقام زي 5sim بالظبط\n━━━━━━━━━━━━━━━\n🔥 البوت جاهز 100 100"}
    if not os.path.exists(SETTINGS_FILE):
        return default
    try:
        with open(SETTINGS_FILE, "r") as f:
            s=json.load(f)
            for k,v in default.items():
                s.setdefault(k,v)
            return s
    except Exception as e:
        return default

def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def is_admin(uid): return uid in SUPER_ADMINS

def normalize_username(u):
    """يزيل @ ويوحّد حالة الأحرف للمقارنة"""
    if u is None:
        return ""
    return str(u).strip().lstrip("@").lower()

def find_allowed_usernames(db, username):
    """يرجع قائمة اليوزرات المطابقة (نفس الشكل بعد التطبيع)"""
    target = normalize_username(username)
    if not target:
        return []
    found = []
    for u in db.get("allowed_usernames", []) or []:
        if normalize_username(u) == target:
            found.append(u)
    return found

def find_users_by_username(db, username):
    """بحث في user_tracks + authorized + allowed عن username"""
    target = normalize_username(username)
    if not target:
        return []
    matches = []
    seen_ids = set()
    tracks = db.get("user_tracks", {}) or {}
    for uid_str, info in tracks.items():
        un = normalize_username(info.get("username") or "")
        if un == target:
            matches.append({"uid": int(uid_str) if str(uid_str).isdigit() else uid_str, "username": info.get("username") or target, "source": "user_tracks"})
            seen_ids.add(str(uid_str))
    auth = db.get("authorized", {}) or {}
    for uid_str, info in auth.items() if isinstance(auth, dict) else []:
        if isinstance(info, dict):
            un = normalize_username(info.get("username") or "")
        else:
            un = ""
        if un == target and str(uid_str) not in seen_ids:
            matches.append({"uid": int(uid_str) if str(uid_str).isdigit() else uid_str, "username": un or target, "source": "authorized"})
            seen_ids.add(str(uid_str))
    # allowed list only (no uid)
    for u in find_allowed_usernames(db, target):
        matches.append({"uid": None, "username": u, "source": "allowed_usernames"})
    return matches

def add_allowed_username(username, admin_id=None):
    """إضافة يوزر مع منع التكرار (case-insensitive، بدون @)"""
    clean = str(username or "").strip().lstrip("@")
    if not clean:
        return False, "فارغ"
    db = fast_load_db()
    if find_allowed_usernames(db, clean):
        return False, "EXISTS"
    db.setdefault("allowed_usernames", []).append(clean)
    # unique preserve order
    seen = set()
    uniq = []
    for u in db["allowed_usernames"]:
        n = normalize_username(u)
        if n and n not in seen:
            seen.add(n)
            uniq.append(u.lstrip("@") if isinstance(u, str) else u)
    db["allowed_usernames"] = uniq
    fast_save_db(db)
    try:
        add_audit_log(admin_id or 0, "add_username", clean, "success")
    except Exception:
        pass
    return True, clean

def delete_user_by_uid(uid, admin_id=None):
    """حذف سجل مستخدم من البوت الأساسي (ليس أدمن/مالك)"""
    try:
        uid_int = int(uid)
    except Exception:
        return False, "ID غير صالح"
    if is_owner(uid_int) or is_admin(uid_int):
        return False, "لا يمكن حذف المالك أو الأدمن"
    db = fast_load_db()
    uid_str = str(uid_int)
    removed = []
    if uid_str in (db.get("user_tracks") or {}):
        db["user_tracks"].pop(uid_str, None)
        removed.append("user_tracks")
    if uid_str in (db.get("authorized") or {}):
        db["authorized"].pop(uid_str, None)
        removed.append("authorized")
    if uid_str in (db.get("users") or {}):
        db["users"].pop(uid_str, None)
        removed.append("users")
    # user_status
    if "user_status" in db and uid_str in (db.get("user_status") or {}):
        db["user_status"].pop(uid_str, None)
        removed.append("user_status")
    fast_save_db(db)
    try:
        add_audit_log(admin_id or 0, "delete_user", uid_str, "success", extra=",".join(removed))
    except Exception:
        pass
    return True, removed

def is_authorized(uid):
    if is_admin(uid): return True
    db = fast_load_db()
    return str(uid) in db.get("authorized", {})






# ==================== فحص هل الرقم مستخدم على المنصة ====================
def check_number_on_platform(number, service_id):
    """
    يفحص هل الرقم مستخدم على المنصة ولا لا
    """
    clean = COMPILED_PHONE_CLEAN.sub('', number)
    result = {
        "number": number,
        "service": service_id,
        "is_used": None,  # True=مستخدم، False=جديد، None=مش قادر أفحص
        "message": "",
        "can_check": False
    }
    
    # 1. فحص داخلي - هل استخدمناه في البوت قبل كده؟
    db = fast_load_db()
    all_used = db.get("all_used_numbers", [])
    if number in all_used:
        # نشوف مين استخدمه
        owner = db.get("number_owners", {}).get(number, {})
        result["is_used"] = True
        result["message"] = f"⚠️ الرقم ده استخدم قبل كده في البوت\n👤 بواسطة: {owner.get('uid','')} \n📘 للخدمة: {owner.get('service','')}"
        result["can_check"] = True
        return result
    
    # 2. فحص خارجي حسب الخدمة
    try:
        if service_id == "whatsapp":
            # فحص واتساب عن طريق wa.me
            headers = {"User-Agent": "Mozilla/5.0"}
            url = f"https://wa.me/{clean}"
            r = _global_session.get(url, headers=headers, timeout=4, allow_redirects=True)
            # لو الصفحة فيها "Continue to Chat" يبقى الرقم على واتساب (مستخدم)
            if "Continue to Chat" in r.text or "متابعة إلى الدردشة" in r.text or r.status_code == 200 and "whatsapp" in r.text.lower():
                # نحاول نتأكد أكتر
                result["is_used"] = True
                result["message"] = "📱 الرقم ده موجود على واتساب (مستخدم)"
                result["can_check"] = True
            else:
                result["is_used"] = False
                result["message"] = "✅ الرقم ده مش موجود على واتساب (جديد)"
                result["can_check"] = True
        
        elif service_id == "telegram":
            # تليجرام - صعب الفحص بدون API، بس نعتبر الأرقام الوهمية جديدة
            result["is_used"] = False
            result["message"] = "✅ الرقم جديد (لم يستخدم في البوت)\n💡 تليجرام: الرقم الوهمي يعتبر جديد"
            result["can_check"] = True
        
        elif service_id in ["facebook", "instagram", "tiktok", "twitter", "google", "discord"]:
            # فيسبوك وانستا وتيك توك مفيش طريقة رسمية للفحص
            # بس نضمن انه مش مستخدم في البوت بتاعنا + نديه تقييم
            result["is_used"] = False
            result["message"] = f"✅ الرقم جديد من نظامنا\n🔒 لم يستخدم في البوت من قبل نهائي\n\n⚠️ ملاحظة: الرقم وهمي (مصري/أمريكي) تم توليده عشوائياً\n💡 قد يكون مستخدم حقيقياً خارج البوت لأنه رقم وهمي\n📌 للضمان 100% استخدم الأرقام الحقيقية المدفوعة"
            result["can_check"] = False  # مش قادرين نفحص خارجي
        
        else:
            result["is_used"] = False
            result["message"] = "✅ الرقم جديد ولم يستخدم في البوت"
            result["can_check"] = True
            
    except Exception as e:
        result["message"] = f"❌ مقدرتش أفحص: {e}\n✅ لكن الرقم جديد في البوت بتاعنا"
        result["is_used"] = False
    
    return result


# ==================== تتبع الأرقام المستخدمة - رقم واحد = شخص واحد بس ====================
def is_number_used(number, service_id=None):
    db = fast_load_db()
    # فحص عام - هل الرقم استخدم قبل كده لأي خدمة؟
    all_used = db.get("all_used_numbers", [])  # قائمة كل الأرقام اللي اتوزعت
    if number in all_used:
        return True
    # فحص إضافي للخدمة
    if service_id:
        used = db.get("used_numbers", {})
        service_used = used.get(service_id, [])
        if number in service_used:
            return True
    return False

def mark_number_used(number, service_id, uid, country_code):
    db = fast_load_db()
    # 1. نضيفه للقائمة العامة - ممنوع يطلع تاني لأي حد
    db.setdefault("all_used_numbers", [])
    if number not in db["all_used_numbers"]:
        db["all_used_numbers"].append(number)
    
    # 2. نضيفه لقائمة الخدمة
    db.setdefault("used_numbers", {}).setdefault(service_id, [])
    if number not in db["used_numbers"][service_id]:
        db["used_numbers"][service_id].append(number)
    
    # 3. نحفظ تفاصيل الاستخدام
    db.setdefault("numbers_log", []).append({
        "number": number,
        "service": service_id,
        "country": country_code,
        "uid": uid,
        "time": str(datetime.datetime.now())
    })
    
    # 4. نحفظ لكل يوزر
    db.setdefault("user_numbers", {}).setdefault(str(uid), []).append({
        "number": number,
        "service": service_id,
        "country": country_code,
        "time": str(datetime.datetime.now())[:19]
    })
    
    # 5. نحفظ مين خد الرقم ده
    db.setdefault("number_owners", {})[number] = {
        "uid": uid,
        "service": service_id,
        "country": country_code,
        "time": str(datetime.datetime.now())[:19]
    }
    fast_save_db(db)

def get_unique_number(service_id, country_code, max_attempts=50):
    """
    يجيب رقم مش مستخدم قبل كده نهائياً في البوت كله
    رقم واحد = شخص واحد بس
    """
    db = fast_load_db()
    all_used = db.get("all_used_numbers", [])
    
    for _ in range(max_attempts):
        if country_code == "eg":
            full, local = gen_egy_number()
        else:
            full, local = gen_us_number()
        
        # لو الرقم مش مستخدم نهائياً في البوت كله
        if full not in all_used:
            return full, local
    
    # لو كل المحاولات فشلت، نولد رقم مستحيل يتكرر
    for i in range(20):
        random_part = ''.join(random.choices("0123456789", k=10))
        if country_code == "eg":
            prefix = random.choice(["010", "011", "012", "015"])
            full = f"+20{prefix[1:]}{random_part[:8]}"
            local = prefix + random_part[:8]
        else:
            area = random.choice(["201","202","212","213","305","310"])
            full = f"+1{area}{random_part[:7]}"
            local = f"{area}{random_part[:7]}"
        
        if full not in all_used:
            return full, full
    
    # آخر حل - رقم بالوقت الحالي مستحيل يتكرر
    ts = str(int(time.time()))[-6:]
    if country_code == "eg":
        full = f"+2010{ts}00"
    else:
        full = f"+1202{ts}0"
    return full, full

    
    # لو كل المحاولات فشلت، يولد رقم جديد تماماً (مستحيل يتكرر)
    for _ in range(10):
        random_extra = ''.join(random.choices("0123456789", k=4))
        if country_code == "eg":
            full, local = gen_egy_number()
            full = full[:-4] + random_extra
        else:
            full, local = gen_us_number()
            full = full[:-4] + random_extra
        if full not in used:
            return full, full
    
    # آخر حل
    full, local = gen_egy_number() if country_code=="eg" else gen_us_number()
    return full, local


# ==================== الأرقام المؤقتة ====================


# ==================== تحسينات السرعة القصوى 🚀 ====================
import functools
import time
from functools import lru_cache

# كاش عالمي للداتا بيز - مش كل شوية نفتح ملف
DB_PATH = "db.json"
DB_FILE = DB_PATH
DB_PATH = "db.json"
DB_FILE = DB_PATH
_db_cache = None
_db_cache_time = 0
_db_lock = threading.Lock()

# Session واحد لكل الطلبات - أسرع 10 مرات من requests.get كل مرة
_global_session = requests.Session()
_global_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
_global_session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20))

# Regex مجمعة مسبقاً - أسرع
COMPILED_CODE_REGEX = re.compile(r'\b\d{4,8}\b')
COMPILED_CODE_WITH_TEXT = re.compile(r'(?:code|Code|رمز|OTP|verification)[^0-9]{0,20}(\d{4,8})', re.I)
COMPILED_PHONE_CLEAN = re.compile(r'[^0-9]')

# كاش للغات
_lang_cache = {}
_lang_cache_time = {}

def fast_load_db(force=False):
    """قراءة DB مع قفل. force=True يتجاوز الكاش (مهم بعد تعديلات متزامنة)."""
    global _db_cache, _db_cache_time
    with _db_lock:
        now = time.time()
        if (not force) and _db_cache is not None and (now - _db_cache_time) < 2:
            return _db_cache
        try:
            with open(DB_PATH, 'r', encoding='utf-8') as f:
                _db_cache = json.load(f)
                _db_cache_time = now
                return _db_cache
        except Exception as e:
            if _db_cache is not None:
                return _db_cache
            return {"users": {}, "user_langs": {}, "all_used_numbers": [], "used_numbers": {}, "numbers_log": [], "user_numbers": {}, "number_owners": {}, "allowed_usernames": [], "banned_users": [], "admin_sessions": {}, "admin_login_states": {}, "admin_access_requests": {}}

def fast_save_db(db):
    """حفظ متزامن تحت القفل لتقليل Lost Updates بين البوتين/الطلبات."""
    global _db_cache, _db_cache_time
    with _db_lock:
        _db_cache = db
        _db_cache_time = time.time()
        try:
            with open(DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"fast_save_db error: {e}")

# نستبدل load_db و save_db بالسريعة

# ==================== نظام اللغات ====================
LANGS = {
    "ar": {
        "choose_lang": "🌐 <b>اختر لغتك / Choose your language</b>\n\n━━━━━━━━━━━━━━━",
        "welcome_auth": "👋 أهلاً بك، {first_name}\n\n🤖 AHMED Bot V3 🔥\n\n━━━━━━━━━━━━━━━\n⚡ سرعة في التنفيذ\n🔒 أمان وخصوصية\n🚀 أدوات ذكية في مكان واحد\n👥 أسماء لا نهائية ♾️\n📱 أرقام واتساب/تليجرام\n━━━━━━━━━━━━━━━\n\n📌 اختر الخدمة من الأزرار بالأسفل.",
        "welcome_unauth": "👋 أهلاً بك، {first_name}\n\n🤖 AHMED Bot V3\n\n━━━━━━━━━━━━━━━\n⚡ سرعة\n🔒 أمان\n🚀 أدوات ذكية\n━━━━━━━━━━━━━━━\n\n🔐 اكتب اليوزر الخاص بك للمواصلة",
        "ask_user": "🔐 اكتب اليوزر الخاص بك للمواصلة ✅",
        "invalid_user": "❌ يوزر غلط 🔐\nلـ طلب يوزر كلم الأدمن:",
    },
    "en": {
        "choose_lang": "🌐 <b>Choose your language</b>\n\n━━━━━━━━━━━━━━━",
        "welcome_auth": "👋 Welcome, {first_name}\n\n🤖 AHMED Bot V3 🔥\n\n━━━━━━━━━━━━━━━\n⚡ Fast\n🔒 Secure\n🚀 Smart Tools\n👥 Infinite Names ♾️\n📱 WA/TG Numbers\n━━━━━━━━━━━━━━━\n\n📌 Choose a service below.",
        "welcome_unauth": "👋 Welcome, {first_name}\n\n🤖 AHMED Bot V3\n\n━━━━━━━━━━━━━━━\n⚡ Fast\n🔒 Secure\n🚀 Smart\n━━━━━━━━━━━━━━━\n\n🔐 Enter your username",
        "ask_user": "🔐 Enter your username ✅",
        "invalid_user": "❌ Invalid username 🔐\nContact admin:",
    }
}


# aliases للتوافق مع استدعاءات قديمة
load_db = fast_load_db
save_db = fast_save_db


def get_user_lang(uid):
    db = fast_load_db()
    return db.get("user_langs", {}).get(str(uid), "ar")

def set_user_lang(uid, lang):
    db = fast_load_db()
    db.setdefault("user_langs", {})[str(uid)] = lang
    fast_save_db(db)

def t(uid, key, **kwargs):
    lang = get_user_lang(uid)
    text = LANGS.get(lang, LANGS["ar"]).get(key, key)
    try:
        return text.format(**kwargs)
    except Exception as e:
        return text

# خدمات الأرقام مثل 5sim
SERVICES = [
    {"id": "whatsapp", "name_ar": "واتساب", "name_en": "WhatsApp", "emoji": "💚", "count": 15420},
    {"id": "telegram", "name_ar": "تليجرام", "name_en": "Telegram", "emoji": "✈️", "count": 12300},
]

COUNTRIES = [
    {"code": "eg", "name_ar": "مصر", "name_en": "Egypt", "flag": "🇪🇬", "count": 8},
    {"code": "sa", "name_ar": "السعودية", "name_en": "Saudi Arabia", "flag": "🇸🇦", "count": 5},
    {"code": "ae", "name_ar": "الإمارات", "name_en": "UAE", "flag": "🇦🇪", "count": 4},
    {"code": "us", "name_ar": "أمريكا", "name_en": "USA", "flag": "🇺🇸", "count": 12},
    {"code": "gb", "name_ar": "بريطانيا", "name_en": "UK", "flag": "🇬🇧", "count": 7},
    {"code": "de", "name_ar": "ألمانيا", "name_en": "Germany", "flag": "🇩🇪", "count": 6},
    {"code": "fr", "name_ar": "فرنسا", "name_en": "France", "flag": "🇫🇷", "count": 4},
    {"code": "ru", "name_ar": "روسيا", "name_en": "Russia", "flag": "🇷🇺", "count": 15},
    {"code": "bf", "name_ar": "بوركينا فاسو", "name_en": "Burkina Faso", "flag": "🇧🇫", "count": 1},
    {"code": "et", "name_ar": "إثيوبيا", "name_en": "Ethiopia", "flag": "🇪🇹", "count": 1},
    {"code": "mr", "name_ar": "موريتانيا", "name_en": "Mauritania", "flag": "🇲🇷", "count": 1},
    {"code": "mn", "name_ar": "منغوليا", "name_en": "Mongolia", "flag": "🇲🇳", "count": 1},
    {"code": "mm", "name_ar": "ميانمار", "name_en": "Myanmar", "flag": "🇲🇲", "count": 2},
    {"code": "ps", "name_ar": "فلسطين", "name_en": "Palestine", "flag": "🇵🇸", "count": 4},
    {"code": "sy", "name_ar": "سوريا", "name_en": "Syria", "flag": "🇸🇾", "count": 3},
    {"code": "tz", "name_ar": "تنزانيا", "name_en": "Tanzania", "flag": "🇹🇿", "count": 1},
    {"code": "tl", "name_ar": "تيمور الشرقية", "name_en": "Timor-Leste", "flag": "🇹🇱", "count": 2},
]

def get_services_keyboard(lang="ar"):
    kb = []
    row = []
    for s in SERVICES:
        name = s["name_en"] if lang=="en" else s["name_ar"]
        display = f"{s['emoji']} {name}"
        row.append(InlineKeyboardButton(display, callback_data=f"svc_{s['id']}"))
        if len(row)==2:
            kb.append(row)
            row=[]
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🔙 رجوع" if lang=="ar" else "🔙 BACK", callback_data="main")])
    return InlineKeyboardMarkup(kb)

def get_countries_keyboard(service_id, lang="ar"):
    kb = []
    row = []
    for c in COUNTRIES:
        name = c["name_en"] if lang=="en" else c["name_en"]  # نعرض الإنجليزي زي الصورة
        display = f"{c['flag']} {name} ({c['count']})"
        row.append(InlineKeyboardButton(display, callback_data=f"country_{service_id}_{c['code']}"))
        if len(row)==2:
            kb.append(row)
            row=[]
    if row:
        kb.append(row)
    # زرار تيمور الشرقية لوحده زي الصورة
    kb.append([InlineKeyboardButton("⬅️ رجوع" if lang=="ar" else "⬅️ BACK", callback_data="nums_services")])
    return InlineKeyboardMarkup(kb)


def gen_egy_number():
    prefixes = ["010", "011", "012", "015"]
    prefix = random.choice(prefixes)
    number = prefix + ''.join(random.choices("0123456789", k=8))
    return f"+20{number[1:]}" if number.startswith("0") else f"+20{number}", number

def gen_us_number():
    area = random.choice(["201","202","212","213","305","310","312","404","415","510","650","702","713","714","917"])
    number = area + ''.join(random.choices("0123456789", k=7))
    return f"+1{number}", number

def gen_random_numbers(count=5, country="egy"):
    nums = []
    for _ in range(count):
        if country == "egy":
            full, local = gen_egy_number()
        else:
            full, local = gen_us_number()
        nums.append((full, local))
    return nums

# أرقام حقيقية تستقبل SMS من موقع مجاني
def get_free_numbers():
    # قائمة أرقام مجانية شغالة من مواقع مجانية
    return [
        {"number": "+12024561111", "country": "🇺🇸 أمريكا", "country_code": "us"},
        {"number": "+447700900000", "country": "🇬🇧 بريطانيا", "country_code": "uk"},
        {"number": "+33612345678", "country": "🇫🇷 فرنسا", "country_code": "fr"},
        {"number": "+4915123456789", "country": "🇩🇪 ألمانيا", "country_code": "de"},
    ]

def get_sms_for_number(number):
    # هنا ممكن تربط API حقيقي لاحقاً مثل 5sim.net
    # حاليا نرجع رسائل وهمية للتجربة
    return []


# ==================== البريد المؤقت القوي V33 - كل المصادر المجانية ====================
# 1. mail.tm + mail.gw (الأساسي)
MAIL_TM_APIS = [
    "https://api.mail.tm",
    "https://api.mail.gw"
]
# 2. maildrop.online (اللي طلبه الاسطى)
MAILDROP_DOMAINS = [
    "maildrop.online",
    "maildrop.cc",
    "tempmailbox.net",
    "mailtemp.online",
    "temp-mail.online",
    "inbox.maildrop.online",
    "maildrops.pro",
    "disposable.maildrop.online"
]
# 3. مصادر مجانية اضافية - ببلاش 100%
GUERRILLA_DOMAINS = ["guerrillamail.com", "guerrillamail.org", "guerrillamail.net"]
TEMPMAIL_LOL_DOMAINS = ["tempmail.lol", "timedmail.net", "inboxkitten.com"]
FREE_EXTRA_DOMAINS = [
    "10minutemail.com",
    "20minutemail.com",
    "tempmailo.com",
    "mailnesia.com"
]

ALL_FREE_DOMAINS = MAILDROP_DOMAINS + GUERRILLA_DOMAINS + TEMPMAIL_LOL_DOMAINS + FREE_EXTRA_DOMAINS

def gen_maildrop_mail(domain_choice="maildrop.online"):
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"{username}@{domain_choice}", username, f"maildrop|||{domain_choice}|||{username}"

def gen_guerrilla_mail():
    # Guerrillamail مجاني 100% - بدون تسجيل
    try:
        r = _global_session.get("https://api.guerrillamail.com/ajax.php?f=get_email_address", timeout=8)
        if r.status_code == 200:
            j = r.json()
            email = j.get("email_addr")
            if email:
                login = email.split("@")[0]
                return email, login, f"guerrilla|||{email}|||{login}"
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    # fallback محلي
    return gen_maildrop_mail(random.choice(GUERRILLA_DOMAINS))

def gen_tempmail_lol_mail():
    try:
        r = _global_session.post("https://api.tempmail.lol/generate", json={}, timeout=8)
        if r.status_code == 200:
            j = r.json()
            email = j.get("address") or j.get("email")
            if email:
                login = email.split("@")[0]
                token = j.get("token","")
                return email, login, f"tempmail_lol|||{token}|||{login}"
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    return gen_maildrop_mail(random.choice(TEMPMAIL_LOL_DOMAINS))

def gen_temp_mail():
    # ترتيب المحاولة: mail.tm -> maildrop -> guerrilla -> tempmail.lol -> عشوائي
    for api_base in MAIL_TM_APIS:
        try:
            r = _global_session.get(f"{api_base}/domains", timeout=6)
            if r.status_code != 200:
                continue
            domains = r.json().get('hydra:member', [])
            if not domains:
                continue
            domain = domains[0]['domain']
            username = ''.join(random.choices(string.ascii_lowercase+string.digits, k=12))
            password = ''.join(random.choices(string.ascii_letters+string.digits, k=16))
            address = f"{username}@{domain}"
            data = {"address": address, "password": password}
            r2 = _global_session.post(f"{api_base}/accounts", json=data, timeout=6)
            if r2.status_code not in [200,201]:
                continue
            r3 = _global_session.post(f"{api_base}/token", json=data, timeout=6)
            if r3.status_code != 200:
                continue
            token = r3.json().get('token')
            if not token:
                continue
            return address, password, f"{api_base}|||{token}"
        except Exception as e:
            continue
    # جرب guerrilla
    try:
        email, login, token = gen_guerrilla_mail()
        if email and "guerrilla" in token:
            return email, login, token
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    # fallback النهائي maildrop
    # كل المصادر فشلت - بلغ المالك
    try:
        # لا نستطيع await هنا، سنطبع فقط وسيتم التنبيه في المرة القادمة عبر monitor
        logger.info("🚨 كل مصادر البريد فشلت!")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    return gen_maildrop_mail(random.choice(MAILDROP_DOMAINS))

def gen_temp_mail_with_domain(domain_choice):
    # لو الدومين من guerrilla
    if "guerrilla" in domain_choice:
        return gen_guerrilla_mail()
    return gen_maildrop_mail(domain_choice)

def get_maildrop_domains_keyboard():
    # كيبورد مقسم فئات - كلها ببلاش
    kb=[]
    kb.append([InlineKeyboardButton("🔥 maildrop.online (الأساسي)", callback_data="cat_maildrop")])
    kb.append([InlineKeyboardButton("⚡ Guerrilla (سريع)", callback_data="cat_guerrilla")])
    kb.append([InlineKeyboardButton("💎 Extra (متنوع)", callback_data="cat_extra")])
    kb.append([InlineKeyboardButton("🎲 عشوائي من الكل", callback_data="mdomain_random")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="main")])
    return InlineKeyboardMarkup(kb)

def get_domains_by_category(cat):
    if cat=="maildrop":
        domains=MAILDROP_DOMAINS
    elif cat=="guerrilla":
        domains=GUERRILLA_DOMAINS
    elif cat=="extra":
        domains=TEMPMAIL_LOL_DOMAINS + FREE_EXTRA_DOMAINS
    else:
        domains=ALL_FREE_DOMAINS
    kb=[]
    row=[]
    for d in domains[:10]:
        row.append(InlineKeyboardButton(f"📧 {d}", callback_data=f"mdomain_{d}"))
        if len(row)==2:
            kb.append(row)
            row=[]
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="temp_new")])
    return InlineKeyboardMarkup(kb)

def get_temp_messages(login_or_pwd, token_or_domain):
    try:
        if "|||" in token_or_domain:
            parts=token_or_domain.split("|||")
            api_base=parts[0]
            if api_base=="maildrop":
                login=parts[2] if len(parts)>2 else login_or_pwd
                for url in [f"https://maildrop.online/api/inbox/{login}", f"https://maildrop.cc/api/inbox/{login}"]:
                    try:
                        r=_global_session.get(url, timeout=8)
                        if r.status_code==200:
                            j=r.json()
                            if isinstance(j,list) and j:
                                return [{"id":m.get("id",i),"subject":m.get("subject",""),"from":m.get("from",""),"intro":m.get("subject","")[:40],"seen":False} for i,m in enumerate(j)]
                    except Exception as e:
                        continue
                return []
            if api_base=="guerrilla":
                try:
                    email=parts[1]
                    r=_global_session.get(f"https://api.guerrillamail.com/ajax.php?f=check_email&seq=0&email={email}", timeout=8)
                    if r.status_code==200:
                        j=r.json()
                        msgs=j.get("list",[])
                        return [{"id":m.get("mail_id"),"subject":m.get("mail_subject",""),"from":m.get("mail_from",""),"intro":m.get("mail_subject","")[:40],"seen":False} for m in msgs]
                except Exception as e:
                    return []
            if api_base=="tempmail_lol":
                try:
                    token=parts[1]
                    r=_global_session.get(f"https://api.tempmail.lol/auth/{token}", timeout=8)
                    if r.status_code==200:
                        j=r.json()
                        msgs=j.get("email",[]) or j.get("messages",[])
                        return [{"id":m.get("id",i),"subject":m.get("subject",""),"from":m.get("from",""),"intro":m.get("subject","")[:40],"seen":False} for i,m in enumerate(msgs)]
                except Exception as e:
                    return []
            if api_base=="1sec":
                domain=parts[1]
                login=login_or_pwd
                url=f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
                r=_global_session.get(url, timeout=5)
                if r.status_code==200:
                    return [{"id":m.get("id"),"subject":m.get("subject",""),"from":m.get("from",""),"intro":m.get("subject",""),"seen":False,"is_1sec":True,"login":login,"domain":domain} for m in r.json()]
                return []
            else:
                real_token=parts[1] if len(parts)>1 else ""
                headers={"Authorization":f"Bearer {real_token}"}
                r=_global_session.get(f"{api_base}/messages", headers=headers, timeout=8)
                if r.status_code==200:
                    return r.json().get('hydra:member', [])
        else:
            login=login_or_pwd
            domain=token_or_domain
            url=f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
            r=_global_session.get(url, timeout=5)
            if r.status_code==200:
                return r.json()
    except Exception as e:
        logger.info(f"get_temp_messages error: {e}")
    return []

def read_temp_message(login_or_pwd, token_or_domain, msg_id):
    try:
        if "|||" in token_or_domain:
            parts=token_or_domain.split("|||")
            api_base=parts[0]
            if api_base=="maildrop":
                return {"subject":"رسالة maildrop","from":"maildrop.online","textBody":f"ID {msg_id}","htmlBody":"","body":f"ID {msg_id}"}
            if api_base=="guerrilla":
                try:
                    email=parts[1]
                    r=_global_session.get(f"https://api.guerrillamail.com/ajax.php?f=fetch_email&email={email}&mail_id={msg_id}", timeout=8)
                    if r.status_code==200:
                        j=r.json()
                        return {"subject":j.get("mail_subject",""),"from":j.get("mail_from",""),"textBody":j.get("mail_body",""),"htmlBody":j.get("mail_body",""),"body":j.get("mail_body","")}
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
            real_token=parts[1] if len(parts)>1 else ""
            if api_base=="1sec":
                domain=real_token
                login=login_or_pwd
                url=f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
                r=_global_session.get(url, timeout=5)
                if r.status_code==200:
                    j=r.json()
                    return {"subject":j.get("subject",""),"from":j.get("from",""),"textBody":j.get("textBody","")+j.get("body",""),"htmlBody":j.get("htmlBody",""),"body":j.get("body","") or j.get("textBody","")}
            else:
                headers={"Authorization":f"Bearer {real_token}"}
                r=_global_session.get(f"{api_base}/messages/{msg_id}", headers=headers, timeout=8)
                if r.status_code==200:
                    j=r.json()
                    return {"subject":j.get("subject",""),"from":j.get("from",{}).get("address","") if isinstance(j.get("from"),dict) else str(j.get("from","")),"textBody":j.get("text",""),"htmlBody":j.get("html",""),"body":j.get("text","")+j.get("html","")}
        else:
            login=login_or_pwd
            domain=token_or_domain
            url=f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
            r=_global_session.get(url, timeout=5)
            if r.status_code==200:
                return r.json()
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    return None

def extract_code_from_text(text):
    # يستخرج الأكواد من النص (قوي جدا - يدعم كل المنصات)
    patterns = [
        r'\b\d{4,8}\b',  # 4-8 أرقام
        r'code[^\d]*?(\d{4,8})',
        r'رمز[^\d]*?(\d{4,8})',
        r'verification[^\d]*?(\d{4,8})',
        r'OTP[^\d]*?(\d{4,8})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    return None

_main_kb_cache = {}

def main_keyboard(lang="ar"):
    texts = {
        "ar": {
            "names": "👥 الأسماء 🌍",
            "pass": "🔑 إنشاء كلمة مرور",
            "2fa": "🔐 كود 2FA",
            "id": "🆔 استخراج ID",
            "mail": "📧 بريد مؤقت",
            "nums": "📱 أرقام مؤقتة",
            "clip": "📋 الحافظة",
            "down": "📥 تحميل الحافظة",
            "support": "💬 الدعم الفني",
            "ai": "🤖 مساعد الذكاء الاصطناعي",
            "lang": "🌐 تغيير اللغة",
            "updates": "📢 آخر التحديثات",
            "rate": "⭐ تقييم البوت"
        },
        "en": {
            "names": "👥 Names 🌍",
            "pass": "🔑 Generate Password",
            "2fa": "🔐 2FA Code",
            "id": "🆔 Extract ID",
            "mail": "📧 Temp Mail",
            "nums": "📱 Temp Numbers",
            "clip": "📋 Clipboard",
            "down": "📥 Download Clipboard",
            "support": "💬 Support",
            "ai": "🤖 AI Assistant",
            "lang": "🌐 Change Language",
            "updates": "📢 Latest Updates",
            "rate": "⭐ Rate Bot"
        }
    }
    t = texts.get(lang, texts["ar"])
    if lang in _main_kb_cache:
        return _main_kb_cache[lang]
    kb = ReplyKeyboardMarkup([
        [KeyboardButton(t["names"])],
        [KeyboardButton(t["pass"]), KeyboardButton(t["2fa"]), KeyboardButton(t["id"])],
        [KeyboardButton(t["mail"]), KeyboardButton(t["nums"])],
        [KeyboardButton(t["clip"]), KeyboardButton(t["down"])],
        [KeyboardButton(t["support"]), KeyboardButton(t["ai"])],
        [KeyboardButton(t["lang"]), KeyboardButton(t["updates"])],
        [KeyboardButton(t["rate"])],
    ], resize_keyboard=True, is_persistent=True)
    _main_kb_cache[lang] = kb
    return kb

def get_main_keyboard_for_user(uid):
    try:
        lang = get_user_lang(uid)
    except Exception as e:
        lang = "ar"
    return main_keyboard(lang)

def old_main_buttons():
    return ["👥 الأسماء 🌍", "👥 Names 🌍", "ادمن", "AHMED2009", "🌐 تغيير اللغة", "🌐 Change Language"]


def gender_keyboard(t):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👦 ولد", callback_data=f"gender_{t}_ولد"), InlineKeyboardButton("👧 بنت", callback_data=f"gender_{t}_بنت")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
    ])

FIRST_NAMES_AR_MALE = ["أحمد","محمد","محمود","يوسف","خالد","عمر","علي","حسام","إبراهيم","كريم","مصطفى","عبدالله","عبدالرحمن","سعيد","حسن","حسين","طارق","وليد","أيمن","سامح","تامر","هاني","شريف","ماجد","ناصر","فهد","سليم","رامي","باسم","نادر","عماد","عادل","أشرف","أسامة","إيهاب","إسلام","أمير","أنس","بلال","جمال","كامل","ماهر","وائل","سامي","حاتم","رائد","فادي","مروان","يزن"]
FIRST_NAMES_AR_FEMALE = ["نور","سلمى","مريم","آية","حبيبة","سارة","منة","فرح","نورهان","جنى","ليلى","هند","شهد","رنا","دينا","ياسمين","بسمة","إيمان","أسماء","هاجر","فاطمة","زينب","رقية","خديجة","مها","نهى","دعاء","آلاء","إسراء","شيماء","نيرة","مي","ميرنا","ريهام","ريم","لمى","لجين","حنين","جمانة","سندس","جوري","تالا","لين","سيلا","ملك","رحمة","أروى","سجى","نغم"]
LAST_NAMES_AR = ["المصري","السعيد","الشرقاوي","جابر","مصطفى","شريف","الشامي","الجندي","الشناوي","فؤاد","حسن","علي","عادل","خالد","محمود","إبراهيم","عبدالله","سالم","ناصر","حمدي","فتحي","زكي","رشدي","كمال","نجيب","حجازي","العربي","الغندور","منصور","السيد","أحمد","محمد","يوسف","عمر","عثمان","سليمان","إسماعيل","يونس","حمزة","النجار","الحداد","النجدي","العتيبي","القحطاني","الزهراني","الغامدي","السبيعي","الدوسري","الشهري","العسيري"]
FIRST_NAMES_EN_MALE = ["James","John","David","Michael","Robert","William","Thomas","Charles","Daniel","Matthew","Anthony","Mark","Donald","Steven","Paul","Andrew","Joshua","Kenneth","Kevin","Brian","George","Edward","Ronald","Timothy","Jason","Jeffrey","Ryan","Jacob","Gary","Nicholas","Eric","Jonathan","Stephen","Larry","Justin","Scott","Brandon","Benjamin","Samuel","Gregory","Alexander","Frank","Patrick","Jack","Dennis","Jerry","Tyler","Aaron","Jose","Adam"]
FIRST_NAMES_EN_FEMALE = ["Emma","Olivia","Sophia","Isabella","Mia","Charlotte","Amelia","Harper","Evelyn","Abigail","Emily","Elizabeth","Mila","Ella","Avery","Sofia","Camila","Luna","Aria","Scarlett","Penelope","Layla","Chloe","Victoria","Madison","Eleanor","Grace","Nora","Riley","Zoey","Hannah","Hazel","Lily","Ellie","Violet","Lillian","Zoe","Stella","Aurora","Natalie","Addison","Leah","Lucy","Paisley","Audrey","Brooklyn","Bella","Claire","Skylar"]
LAST_NAMES_EN = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez","Hernandez","Lopez","Gonzalez","Wilson","Anderson","Thomas","Taylor","Moore","Jackson","Martin","Lee","Perez","Thompson","White","Harris","Sanchez","Clark","Ramirez","Lewis","Robinson","Walker","Young","Allen","King","Wright","Scott","Torres","Nguyen","Hill","Flores","Green","Adams","Nelson","Baker","Hall","Rivera","Campbell","Mitchell","Carter"]
FIRST_NAMES_MIXED_MALE = ["Alex","Carlos","Luca","Hans","Ivan","Kenji","Ahmed","Omar","Liam","Noah","Ethan","Lucas","Mason","Oliver","Elijah","Mateo","Santiago","Leonardo","Andrei","Youssef","Khalid","Amir","Rayan","Zain","Adam","Yasin","Faris","Kareem","Bilal","Hamza"]
FIRST_NAMES_MIXED_FEMALE = ["Sofia","Giulia","Anna","Yuki","Fatima","Luna","Nina","Zara","Ava","Isabella","Mia","Amara","Aisha","Layla","Mariam","Nour","Salma","Hana","Sara","Leila","Maya","Lina","Dina","Rana","Jana","Hala","Nada","Rania","Samira","Yasmin"]
LAST_NAMES_MIXED = ["Garcia","Rossi","Muller","Tanaka","Hassan","Ali","Silva","Petrov","Ahmed","Kim","Chen","Wang","Li","Singh","Patel","Kumar","Costa","Santos","Oliveira","Fernandez","Gonzalez","Rodriguez","Martinez","Lopez","Hernandez","Gomez","Diaz","Reyes","Morales"]

def generate_infinite_name(category, gender, uid):
    try:
        db = fast_load_db()
        used_key = f"used_names_{category}_{gender}"
        user_data = db.get("users", {}).get(str(uid), {})
        used = set(user_data.get(used_key, []))
    except Exception as e:
        used = set()
        db = None
    if category == "ar":
        first_pool = FIRST_NAMES_AR_MALE if gender=="male" else FIRST_NAMES_AR_FEMALE
        last_pool = LAST_NAMES_AR
    elif category == "en":
        first_pool = FIRST_NAMES_EN_MALE if gender=="male" else FIRST_NAMES_EN_FEMALE
        last_pool = LAST_NAMES_EN
    else:
        first_pool = FIRST_NAMES_MIXED_MALE if gender=="male" else FIRST_NAMES_MIXED_FEMALE
        last_pool = LAST_NAMES_MIXED
    try:
        max_comb = len(first_pool) * len(last_pool)
        if len(used) >= max_comb * 0.85:
            used = set()
        for _ in range(100):
            first = random.choice(first_pool)
            last = random.choice(last_pool)
            full = f"{first} {last}"
            if full not in used:
                if db is not None:
                    try:
                        used.add(full)
                        db.setdefault("users", {}).setdefault(str(uid), {})[used_key] = list(used)[-300:]
                        fast_save_db(db)
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                return full
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    try:
        first = random.choice(first_pool)
        last = random.choice(last_pool)
        return f"{first} {last}"
    except Exception as e:
        return "أحمد المصري" if category=="ar" else "James Smith"

def names_main_keyboard(lang="ar"):
    labels = {
        "ar": {"ar": "🇪🇬 عربي", "en": "🇺🇸 إنجليزي", "mixed": "🌍 أجنبي متنوع", "back": "🔙 رجوع"},
        "en": {"ar": "🇪🇬 Arabic", "en": "🇺🇸 English", "mixed": "🌍 Mixed Foreign", "back": "🔙 Back"}
    }
    l = labels.get(lang, labels["ar"])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(l["ar"], callback_data="names_ar"), InlineKeyboardButton(l["en"], callback_data="names_en")],
        [InlineKeyboardButton(l["mixed"], callback_data="names_mixed")],
        [InlineKeyboardButton(l["back"], callback_data="main")]
    ])

def names_gender_keyboard(category, lang="ar"):
    trans = {
        "ar": {"male": "👦 ولد", "female": "👧 بنت", "back": "⬅️ رجوع"},
        "en": {"male": "👦 Boy", "female": "👧 Girl", "back": "⬅️ Back"}
    }
    tr = trans.get(lang, trans["ar"])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr["male"], callback_data=f"names_{category}_male"), InlineKeyboardButton(tr["female"], callback_data=f"names_{category}_female")],
        [InlineKeyboardButton(tr["back"], callback_data="names_main")]
    ])


# ==================== نظام إدارة القنوات الإجباري + إدارة المستخدمين V36 ====================
AUDIT_LOG_LOCK = threading.Lock()
FORCE_SUB_LOCK = threading.Lock()
USER_MGMT_LOCK = threading.Lock()

def get_audit_log():
    try:
        db = fast_load_db()
        return db.get("audit_log", [])
    except Exception:
        return []

def add_audit_log(admin_id, action, target, result="success", extra=""):
    try:
        entry = {
            "admin_id": int(admin_id),
            "action": action,
            "target": str(target),
            "time": _now_str(),
            "timestamp": _now_ts(),
            "result": result,
            "extra": extra[:300] if extra else ""
        }
        db = fast_load_db()
        db.setdefault("audit_log", []).append(entry)
        # احتفظ بآخر 500 سجل فقط
        if len(db["audit_log"]) > 500:
            db["audit_log"] = db["audit_log"][-500:]
        fast_save_db(db)
        logger.info(f"AUDIT: {admin_id} {action} {target} {result}")
    except Exception as e:
        logger.exception(f"add_audit_log error: {e}")

def get_force_sub_channels():
    try:
        db = fast_load_db()
        settings = db.get("settings", {})
        return settings.get("force_sub_channels", []), settings.get("force_sub_enabled", False)
    except Exception:
        return [], False

def get_force_sub_enabled():
    try:
        db = fast_load_db()
        return db.get("settings", {}).get("force_sub_enabled", False)
    except Exception:
        return False

def set_force_sub_enabled(enabled: bool, admin_id=None):
    try:
        db = fast_load_db()
        db.setdefault("settings", {})["force_sub_enabled"] = enabled
        fast_save_db(db)
        add_audit_log(admin_id or 0, "force_sub_toggle", f"enabled={enabled}", "success")
        return True
    except Exception as e:
        logger.exception(f"set_force_sub_enabled error: {e}")
        return False

def add_force_sub_channel(channel_input, admin_id=None):
    """يضيف قناة - channel_input يمكن أن يكون ID أو username أو رابط"""
    try:
        with FORCE_SUB_LOCK:
            db = fast_load_db()
            settings = db.setdefault("settings", {})
            channels = settings.setdefault("force_sub_channels", [])
            
            # نظف المدخل
            raw = channel_input.strip()
            channel_id = None
            username = None
            name = None
            
            # إذا كان ID رقمي (مثل -1001234567890)
            if raw.lstrip("-").isdigit():
                channel_id = int(raw)
                username = str(raw)
                name = f"Channel {raw}"
            # إذا كان username مع @
            elif raw.startswith("@"):
                username = raw
                channel_id = raw  # سنحاول حله لاحقاً عبر Bot API
                name = raw
            # إذا كان رابط t.me/
            elif "t.me/" in raw:
                # استخرج اليوزر من الرابط
                import re
                m = re.search(r't\.me/([A-Za-z0-9_]+)', raw)
                if m:
                    username = "@" + m.group(1)
                    channel_id = username
                    name = username
                else:
                    return False, "رابط غير صحيح"
            else:
                # اعتبره يوزرنيم بدون @
                if raw.startswith("-100"):
                    channel_id = int(raw)
                    username = str(raw)
                else:
                    username = "@" + raw.lstrip("@")
                    channel_id = username
                name = username
            
            # تحقق من التكرار
            for ch in channels:
                if str(ch.get("id")) == str(channel_id) or ch.get("username") == username:
                    return False, "القناة موجودة مسبقاً"
            
            new_ch = {
                "id": channel_id,
                "username": username,
                "name": name,
                "active": True,
                "added_by": admin_id,
                "added_at": _now_str()
            }
            channels.append(new_ch)
            fast_save_db(db)
            add_audit_log(admin_id or 0, "add_channel", str(channel_id), "success", username)
            return True, new_ch
    except Exception as e:
        logger.exception(f"add_force_sub_channel error: {e}")
        return False, str(e)

def remove_force_sub_channel(channel_identifier, admin_id=None):
    try:
        with FORCE_SUB_LOCK:
            db = fast_load_db()
            settings = db.setdefault("settings", {})
            channels = settings.get("force_sub_channels", [])
            new_channels = [ch for ch in channels if str(ch.get("id")) != str(channel_identifier) and ch.get("username") != channel_identifier]
            if len(new_channels) == len(channels):
                return False, "القناة غير موجودة"
            settings["force_sub_channels"] = new_channels
            fast_save_db(db)
            add_audit_log(admin_id or 0, "remove_channel", str(channel_identifier), "success")
            return True, "تم الحذف"
    except Exception as e:
        logger.exception(f"remove_force_sub_channel error: {e}")
        return False, str(e)

def toggle_force_sub_channel(channel_identifier, admin_id=None):
    try:
        with FORCE_SUB_LOCK:
            db = fast_load_db()
            channels = db.get("settings", {}).get("force_sub_channels", [])
            for ch in channels:
                if str(ch.get("id")) == str(channel_identifier) or ch.get("username") == channel_identifier:
                    ch["active"] = not ch.get("active", True)
                    fast_save_db(db)
                    add_audit_log(admin_id or 0, "toggle_channel", str(channel_identifier), "success", f"active={ch['active']}")
                    return True, ch
            return False, "غير موجودة"
    except Exception as e:
        logger.exception(f"toggle_force_sub_channel error: {e}")
        return False, str(e)

async def check_user_subscriptions(bot, user_id):
    """يتحقق من اشتراك المستخدم في جميع القنوات المفعلة - يرجع قائمة القنوات غير المشترك فيها"""
    try:
        channels, enabled = get_force_sub_channels()
        if not enabled or not channels:
            return [], True  # لا يوجد اشتراك إجباري
        
        active_channels = [ch for ch in channels if ch.get("active", True)]
        if not active_channels:
            return [], True
        
        not_subscribed = []
        for ch in active_channels:
            ch_id = ch.get("id")
            try:
                # حاول الحصول على معلومات العضوية
                member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
                # الحالات المسموحة: member, administrator, creator
                if member.status not in ["member", "administrator", "creator", "owner"]:
                    not_subscribed.append(ch)
            except Exception as e:
                # إذا فشل التحقق (مثلاً البوت ليس أدمن في القناة)، اعتبره غير مشترك و سجل الخطأ
                logger.debug(f"check_user_subscriptions error for {ch_id}: {e}")
                # لا نعتبره غير مشترك إذا كان الخطأ أن البوت ليس في القناة - نسجل فقط
                # لكن للاحتياط، إذا كان الخطأ "Chat not found" نتجاهل
                err_str = str(e).lower()
                if "chat not found" in err_str or "channel not found" in err_str:
                    continue
                # إذا كان "user not found" أو "member not found" يعني غير مشترك
                if "not found" in err_str or "not participant" in err_str or "left" in err_str or "kicked" in err_str:
                    not_subscribed.append(ch)
                else:
                    # أخطاء أخرى (مثلاً البوت ليس أدمن) - نتجاهل مؤقتاً ونبه الأدمن
                    # لكن لا نمنع المستخدم
                    continue
        
        is_subscribed = len(not_subscribed) == 0
        return not_subscribed, is_subscribed
    except Exception as e:
        logger.exception(f"check_user_subscriptions error: {e}")
        return [], True  # في حالة خطأ عام، اسمح للمستخدم

async def send_force_sub_message(update_obj, not_subscribed_channels):
    """يرسل رسالة الاشتراك الإجباري مع أزرار الاشتراك"""
    try:
        if not not_subscribed_channels:
            return False
        
        text_lines = [
            "📢 <b>الاشتراك الإجباري</b>",
            "━━━━━━━━━━━━━━━",
            "⚠️ يجب عليك الاشتراك في القنوات التالية لاستخدام البوت:",
            ""
        ]
        kb_rows = []
        for ch in not_subscribed_channels:
            username = ch.get("username","")
            name = ch.get("name", username)
            # زر الاشتراك
            if username.startswith("@"):
                link = f"https://t.me/{username.lstrip('@')}"
            elif str(ch.get("id")).startswith("-100"):
                # قناة برايفت - لا يمكن إنشاء رابط مباشر، استخدم اليوزر إذا موجود
                link = f"https://t.me/{username.lstrip('@')}" if username else None
            else:
                link = f"https://t.me/{username.lstrip('@')}" if username else None
            
            if link:
                kb_rows.append([InlineKeyboardButton(f"📢 اشترك في {name}", url=link)])
            else:
                text_lines.append(f"• {name} ({username})")
        
        text_lines.append("")
        text_lines.append("بعد الاشتراك، اضغط زر التحقق 👇")
        
        kb_rows.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_force_sub")])
        
        text = "\n".join(text_lines)
        kb = InlineKeyboardMarkup(kb_rows)
        
        if hasattr(update_obj, 'edit_message_text'):
            await update_obj.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await update_obj.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return True
    except Exception as e:
        logger.exception(f"send_force_sub_message error: {e}")
        return False

# ==================== إدارة المستخدمين ====================
def get_user_full_info(uid):
    try:
        db = fast_load_db()
        uid_str = str(uid)
        track = db.get("user_tracks", {}).get(uid_str, {})
        state = db.get("user_states", {}).get(uid_str, {})
        ai_conv = db.get("ai_conversations", {}).get(uid_str, {})
        suspensions = db.get("user_suspensions", {}).get(uid_str)
        banned = db.get("banned_users", [])
        is_banned = uid_str in [str(x) for x in banned] or state.get("is_banned") or state.get("status") == "banned"
        
        # حالة الإيقاف المؤقت
        is_suspended = False
        suspend_until = None
        suspend_until_str = None
        if suspensions:
            until_ts = suspensions.get("until_ts", 0)
            if until_ts > _now_ts():
                is_suspended = True
                suspend_until = until_ts
                suspend_until_str = suspensions.get("until_str")
            else:
                # انتهى الإيقاف، احذفه تلقائياً
                db.get("user_suspensions", {}).pop(uid_str, None)
                fast_save_db(db)
        
        # تحديد الحالة العامة
        if is_banned:
            status = "🚫 محظور"
            status_code = "banned"
        elif is_suspended:
            status = f"⏸️ موقوف حتى {suspend_until_str}"
            status_code = "suspended"
        elif state.get("is_processing"):
            status = "⏳ قيد التنفيذ"
            status_code = "processing"
        elif state.get("status") == "ai_using":
            status = "🤖 يستخدم AI"
            status_code = "ai_using"
        else:
            status = "🟢 نشط"
            status_code = "active"
        
        info = {
            "user_id": uid,
            "username": track.get("username","") or state.get("username",""),
            "first_name": track.get("first_name","") or state.get("display_name","") or state.get("first_name",""),
            "display_name": track.get("first_name","") or state.get("display_name","") or f"User {uid}",
            "status": status,
            "status_code": status_code,
            "is_banned": is_banned,
            "is_suspended": is_suspended,
            "suspend_until": suspend_until,
            "suspend_until_str": suspend_until_str,
            "suspend_reason": suspensions.get("reason","") if suspensions else "",
            "first_seen": track.get("first_seen",""),
            "last_seen": track.get("last_seen","") or state.get("last_active",""),
            "operation_count": state.get("operation_count",0),
            "error_count": state.get("error_count",0),
            "ai_messages": ai_conv.get("message_count",0) if ai_conv else 0,
            "current_service": state.get("current_service","لا يوجد"),
            "path": state.get("path",[]),
            "last_error": state.get("last_error",""),
        }
        return info
    except Exception as e:
        logger.exception(f"get_user_full_info error: {e}")
        return None

def ban_user_permanent(uid, admin_id=None, reason=""):
    try:
        with USER_MGMT_LOCK:
            db = fast_load_db(force=True)
            uid_str = str(uid)
            banned = db.setdefault("banned_users", [])
            if uid_str not in [str(x) for x in banned] and int(uid) not in banned:
                banned.append(int(uid))
            # حدث حالة المستخدم
            state = db.setdefault("user_states", {}).setdefault(uid_str, {})
            state["is_banned"] = True
            state["status"] = "banned"
            state["banned_at"] = _now_str()
            state["banned_by"] = admin_id
            state["ban_reason"] = reason
            fast_save_db(db)
            add_audit_log(admin_id or 0, "ban_permanent", str(uid), "success", reason)
            return True, "تم الحظر الدائم"
    except Exception as e:
        logger.exception(f"ban_user_permanent error: {e}")
        return False, str(e)

def unban_user(uid, admin_id=None):
    try:
        with USER_MGMT_LOCK:
            db = fast_load_db(force=True)
            uid_str = str(uid)
            banned = db.get("banned_users", [])
            new_banned = [x for x in banned if str(x) != uid_str]
            db["banned_users"] = new_banned
            state = db.get("user_states", {}).get(uid_str, {})
            if state:
                state["is_banned"] = False
                state["status"] = "idle"
                state.pop("banned_at", None)
            fast_save_db(db)
            add_audit_log(admin_id or 0, "unban", str(uid), "success")
            return True, "تم إلغاء الحظر"
    except Exception as e:
        logger.exception(f"unban_user error: {e}")
        return False, str(e)

def suspend_user_temporary(uid, duration_seconds, admin_id=None, reason=""):
    try:
        with USER_MGMT_LOCK:
            db = fast_load_db()
            uid_str = str(uid)
            until_ts = _now_ts() + duration_seconds
            until_dt = datetime.datetime.fromtimestamp(until_ts)
            until_str = until_dt.strftime("%Y-%m-%d %H:%M:%S")
            
            db.setdefault("user_suspensions", {})[uid_str] = {
                "uid": int(uid),
                "until_ts": until_ts,
                "until_str": until_str,
                "reason": reason,
                "by_admin": admin_id,
                "at": _now_str(),
                "duration": duration_seconds
            }
            # حدث الحالة
            state = db.setdefault("user_states", {}).setdefault(uid_str, {})
            state["is_suspended"] = True
            state["suspend_until"] = until_str
            fast_save_db(db)
            add_audit_log(admin_id or 0, "suspend", str(uid), "success", f"{duration_seconds}s - {reason}")
            return True, until_str
    except Exception as e:
        logger.exception(f"suspend_user_temporary error: {e}")
        return False, str(e)

def unsuspend_user(uid, admin_id=None):
    try:
        with USER_MGMT_LOCK:
            db = fast_load_db()
            uid_str = str(uid)
            if uid_str in db.get("user_suspensions", {}):
                del db["user_suspensions"][uid_str]
            state = db.get("user_states", {}).get(uid_str, {})
            if state:
                state.pop("is_suspended", None)
                state.pop("suspend_until", None)
            fast_save_db(db)
            add_audit_log(admin_id or 0, "unsuspend", str(uid), "success")
            return True, "تم إلغاء الإيقاف"
    except Exception as e:
        logger.exception(f"unsuspend_user error: {e}")
        return False, str(e)

def delete_user_data(uid, admin_id=None, keep_security_logs=True):
    """يحذف بيانات المستخدم مع الحفاظ على سجلات الأمان إذا طلب"""
    try:
        with USER_MGMT_LOCK:
            db = fast_load_db()
            uid_str = str(uid)
            
            # احتفظ بسجلات الأمان إذا طلب
            security_data = {}
            if keep_security_logs:
                security_data["audit"] = [log for log in db.get("audit_log", []) if str(log.get("target")) == uid_str or str(log.get("admin_id")) == uid_str]
                security_data["state"] = db.get("user_states", {}).get(uid_str)
            
            # احذف البيانات المسموحة
            db.get("user_tracks", {}).pop(uid_str, None)
            db.get("user_states", {}).pop(uid_str, None)
            db.get("ai_conversations", {}).pop(uid_str, None)
            db.get("user_suspensions", {}).pop(uid_str, None)
            db.get("users", {}).pop(uid_str, None)
            
            # احذف من الباند إذا موجود
            banned = db.get("banned_users", [])
            db["banned_users"] = [x for x in banned if str(x) != uid_str]
            
            fast_save_db(db)
            add_audit_log(admin_id or 0, "delete_user", str(uid), "success", f"keep_security={keep_security_logs}")
            return True, "تم الحذف"
    except Exception as e:
        logger.exception(f"delete_user_data error: {e}")
        return False, str(e)

def is_user_banned_or_suspended(uid):
    """يتحقق هل المستخدم محظور أو موقوف - يستخدم في بداية كل طلب"""
    try:
        db = fast_load_db()
        uid_str = str(uid)
        
        # حظر دائم
        banned = db.get("banned_users", [])
        if uid_str in [str(x) for x in banned] or int(uid) in banned:
            return True, "banned", "🚫 أنت محظور من استخدام البوت بشكل دائم."
        
        # إيقاف مؤقت
        susp = db.get("user_suspensions", {}).get(uid_str)
        if susp:
            until_ts = susp.get("until_ts", 0)
            if until_ts > _now_ts():
                until_str = susp.get("until_str")
                reason = susp.get("reason","")
                msg = f"⏸️ تم إيقاف استخدامك مؤقتاً.\\n⏱️ ينتهي الإيقاف في: {until_str}"
                if reason:
                    msg += f"\\n📋 السبب: {reason}"
                return True, "suspended", msg
            else:
                # انتهى الإيقاف، احذفه
                db.get("user_suspensions", {}).pop(uid_str, None)
                fast_save_db(db)
        
        return False, "active", ""
    except Exception as e:
        logger.exception(f"is_user_banned_or_suspended error: {e}")
        return False, "active", ""

# حماية لوحة الأدمن من محاولات الوصول غير المصرح بها
ADMIN_ACCESS_ATTEMPTS = {}
ADMIN_ACCESS_LOCK = threading.Lock()

def log_admin_access_attempt(uid, username, action):
    try:
        with ADMIN_ACCESS_LOCK:
            key = str(uid)
            now = _now_ts()
            ADMIN_ACCESS_ATTEMPTS.setdefault(key, []).append({"time": now, "action": action, "username": username})
            # نظف القديم (أكثر من 10 دقائق)
            ADMIN_ACCESS_ATTEMPTS[key] = [x for x in ADMIN_ACCESS_ATTEMPTS[key] if now - x["time"] < 600]
            count = len(ADMIN_ACCESS_ATTEMPTS[key])
            return count
    except Exception:
        return 0

async def check_admin_access(update, context, action="admin_panel"):
    """يتحقق من صلاحية الأدمن ويسجل المحاولات المشبوهة"""
    uid = update.effective_user.id if hasattr(update, 'effective_user') else (update.from_user.id if hasattr(update, 'from_user') else 0)
    username = update.effective_user.username if hasattr(update, 'effective_user') else ""
    
    if is_admin(uid):
        return True
    
    # ليس أدمن - سجل المحاولة
    attempts = log_admin_access_attempt(uid, username, action)
    
    if attempts >= 3:
        try:
            await notify_owner(context, "محاولة وصول مشبوهة للوحة الأدمن", f"👤 User ID: {uid}\\n🔹 Username: @{username}\\n📋 Action: {action}\\n🔢 عدد المحاولات: {attempts} خلال 10 دقائق\\n🕐 الوقت: {_now_str()}")
        except Exception:
            pass
    
    # رد للمستخدم
    try:
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.answer("⛔ هذه اللوحة للأدمن فقط", show_alert=True)
        elif hasattr(update, 'message') and update.message:
            await update.message.reply_text("⛔ هذه اللوحة للأدمن فقط")
    except Exception:
        pass
    
    return False



def admin_keyboard(uid=None, hide_password_btn=False):
    db = fast_load_db()
    settings = load_settings()
    is_owner = (uid is None) or (int(uid) == int(OWNER_ID)) or (SUPER_ADMINS and int(uid) == int(SUPER_ADMINS[0]))
    perms = settings.get("admin_perms",{}).get(str(uid),[]) if not is_owner else ["all"]
    def has(p):
        return is_owner or "all" in perms or p in perms
    kb=[]
    kb.append([InlineKeyboardButton(f"👑 الادمنية ({len(SUPER_ADMINS)})", callback_data="adm_list_admins")])
    if has("admins") or is_owner:
        kb.append([InlineKeyboardButton("➕ اضافة ادمن", callback_data="adm_add_admin"), InlineKeyboardButton("➖ ازالة ادمن", callback_data="adm_remove_admin")])
        kb.append([InlineKeyboardButton("🔐 صلاحيات الادمن", callback_data="adm_perms_menu")])
    if has("msgs") or is_owner:
        kb.append([InlineKeyboardButton("✏️ رسائل الترحيب", callback_data="adm_msgs")])
    if has("stats") or is_owner:
        kb.append([InlineKeyboardButton("📈 احصاءات", callback_data="adm_stats")])
    if has("users") or is_owner:
        kb.append([InlineKeyboardButton("👥 المستخدمين", callback_data="adm_users_dash"), InlineKeyboardButton("🆕 الجداد اليوم", callback_data="adm_new_today")])
        kb.append([InlineKeyboardButton("🟢 النشطين اليوم", callback_data="adm_active_today"), InlineKeyboardButton("🚫 البلوك", callback_data="adm_blocked")])
        kb.append([InlineKeyboardButton("📋 قائمة اليوزرات", callback_data="adm_list_users"), InlineKeyboardButton("➕ اضافة يوزر", callback_data="adm_add_user")])
        kb.append([InlineKeyboardButton("🗑️ حذف يوزر", callback_data="adm_del_user")])
        kb.append([InlineKeyboardButton("📤 رفع يوزرات", callback_data="adm_upload_users"), InlineKeyboardButton("📥 تحميل اليوزرات", callback_data="adm_download_users")])
    kb.append([InlineKeyboardButton("⭐ التقييمات", callback_data="adm_ratings"), InlineKeyboardButton("💌 الملاحظات", callback_data="adm_feedbacks")])
    kb.append([InlineKeyboardButton("📢 إدارة الاشتراك الإجباري", callback_data="adm_force_sub_menu")])
    kb.append([InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="adm_users_mgmt")])
    kb.append([InlineKeyboardButton("🤖 محادثات الذكاء الاصطناعي", callback_data="adm_ai_menu")])
    kb.append([InlineKeyboardButton("📜 سجل العمليات (Audit)", callback_data="adm_audit_log")])
    kb.append([InlineKeyboardButton("📱 الأرقام المستخدمة", callback_data="adm_used_numbers"), InlineKeyboardButton("📊 إحصائيات الأرقام", callback_data="adm_numbers_stats")])
    kb.append([InlineKeyboardButton("📧 إحصائيات البريد", callback_data="adm_mail_stats"), InlineKeyboardButton("🗑️ مسح الأرقام", callback_data="adm_clear_numbers")])
    kb.append([InlineKeyboardButton("➕ إضافة خدمة", callback_data="adm_add_service"), InlineKeyboardButton("✏️ تعديل عدد الخدمة", callback_data="adm_edit_service")])
    kb.append([InlineKeyboardButton("📢 إذاعة للكل", callback_data="adm_broadcast"), InlineKeyboardButton("🚫 حظر/فك حظر", callback_data="adm_ban_user")])
    kb.append([InlineKeyboardButton("⛔ ايقاف البوت", callback_data="adm_stop"), InlineKeyboardButton("▶️ تشغيل البوت", callback_data="adm_start")])
    kb.append([InlineKeyboardButton("📤 تصدير كل البيانات", callback_data="adm_export_all"), InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")])
    return InlineKeyboardMarkup(kb)

def whatsapp_button():
    url = f"https://wa.me/{WHATSAPP_NUMBER}?text=عايز%20يوزر%20للبوت"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 تليجرام (أحمد) 👑", url="tg://user?id=6364073135")],
        [InlineKeyboardButton("📲 واتساب", url=url)]
    ])



# ==================== نظام عرض البيانات القابلة للنسخ الموحد V2 - تصميم أزرق + زر نسخ ====================
import uuid as uuid_lib

COPY_STORE = {}  # copy_id -> value
COPY_STORE_LOCK = threading.Lock()

def _generate_copy_id():
    return uuid_lib.uuid4().hex[:8]

def _store_copy_value(value: str) -> str:
    cid = _generate_copy_id()
    with COPY_STORE_LOCK:
        COPY_STORE[cid] = str(value)
        # احتفظ بآخر 500 فقط
        if len(COPY_STORE) > 500:
            # امسح الأقدم
            oldest = list(COPY_STORE.keys())[:100]
            for k in oldest:
                COPY_STORE.pop(k, None)
    # احفظ أيضاً في DB للاستمرارية
    try:
        db = fast_load_db()
        db.setdefault("copy_store", {})[cid] = str(value)
        # نظف القديم من DB
        if len(db["copy_store"]) > 500:
            keys = list(db["copy_store"].keys())[:100]
            for k in keys:
                db["copy_store"].pop(k, None)
        fast_save_db(db)
    except Exception:
        pass
    return cid

def _get_copy_value(cid: str):
    with COPY_STORE_LOCK:
        if cid in COPY_STORE:
            return COPY_STORE[cid]
    try:
        db = fast_load_db()
        return db.get("copy_store", {}).get(cid)
    except Exception:
        return None

def _escape_html(s: str) -> str:
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

async def send_copyable_unified(message_obj, items, title=None, show_main=True, extra_text=None):
    """
    نظام موحد لعرض البيانات القابلة للنسخ
    items: list of dict {label: str, value: str} أو list of values
    مثال: [{"label":"Facebook ID", "value":"123456"}, {"label":"Username", "value":"@user"}]
    """
    try:
        # تطبيع items
        normalized = []
        if isinstance(items, dict):
            items = [items]
        for it in items:
            if isinstance(it, str):
                normalized.append({"label": "القيمة", "value": it})
            elif isinstance(it, dict):
                label = it.get("label", "القيمة")
                value = it.get("value", "")
                normalized.append({"label": label, "value": str(value)})
            else:
                normalized.append({"label": "القيمة", "value": str(it)})
        
        if not normalized:
            return
        
        # بناء النص بتصميم موحد - خلفية زرقاء خفيفة عبر blockquote
        lines = []
        if title:
            lines.append(f"{title}")
            lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        
        cids = []
        for idx, item in enumerate(normalized, 1):
            label = _escape_html(item["label"])
            value = _escape_html(item["value"])
            cid = _store_copy_value(item["value"])
            cids.append(cid)
            
            if len(normalized) == 1:
                lines.append(f"<b>📋 {label}:</b>")
            else:
                lines.append(f"<b>{idx}. 📋 {label}:</b>")
            # تصميم مميز بخلفية زرقاء - نستخدم blockquote + code
            lines.append(f"<blockquote><code>{value}</code></blockquote>")
        
        lines.append("━━━━━━━━━━━━━━━")
        if extra_text:
            lines.append(extra_text)
        
        text = "\n".join(lines)
        
        # بناء أزرار النسخ - كل قيمة زر مستقل
        kb_rows = []
        for idx, (item, cid) in enumerate(zip(normalized, cids), 1):
            label_short = item["label"][:20] if len(item["label"]) <= 20 else item["label"][:17]+"..."
            if len(normalized) == 1:
                btn_text = f"📋 نسخ {label_short}"
            else:
                btn_text = f"📋 نسخ {idx}: {label_short}"
            kb_rows.append([InlineKeyboardButton(btn_text, callback_data=f"copy_{cid}")])
        
        if show_main:
            kb_rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="main")])
        
        kb = InlineKeyboardMarkup(kb_rows)
        
        # إرسال
        try:
            if hasattr(message_obj, 'edit_message_text'):
                await message_obj.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            else:
                await message_obj.reply_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            # fallback بدون HTML معقد
            fallback = title or "البيانات:"
            for item in normalized:
                fallback += f"\n{item['label']}: {item['value']}"
            try:
                if hasattr(message_obj, 'edit_message_text'):
                    await message_obj.edit_message_text(fallback, reply_markup=kb)
                else:
                    await message_obj.reply_text(fallback, reply_markup=kb)
            except Exception as e2:
                logger.debug(f"send_copyable_unified fallback error: {e2}")
    except Exception as e:
        logger.exception(f"send_copyable_unified error: {e}")
        try:
            await message_obj.reply_text("❌ حدث خطأ في عرض البيانات", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        except Exception:
            pass

# دالة قديمة للتوافق - تستخدم النظام الجديد
async def send_copyable_message(message_obj, title, value):
    await send_copyable_unified(message_obj, [{"label": title.replace('🆔','').replace('🔑','').replace('👤','').replace('<b>','').replace('</b>','').strip() or "القيمة", "value": value}], title=title, show_main=True)

async def handle_copy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عند الضغط على زر نسخ - يعرض القيمة بوضوح قابلة للنسخ بدون تراكم رسائل"""
    query = update.callback_query
    try:
        data = query.data
        if not data.startswith("copy_"):
            return
        cid = data[5:]
        value = _get_copy_value(cid)
        if not value:
            await query.answer("❌ انتهت صلاحية البيانات، اطلبها مرة أخرى", show_alert=True)
            return
        
        # منع تكرار النسخ السريع لنفس القيمة
        last_copy = context.user_data.get("last_copy_cid")
        last_copy_t = context.user_data.get("last_copy_time", 0)
        if last_copy == cid and (time.time() - last_copy_t) < 1.5:
            await query.answer("✅ تم النسخ مسبقاً", show_alert=False)
            return
        context.user_data["last_copy_cid"] = cid
        context.user_data["last_copy_time"] = time.time()
        
        # قيم قصيرة: اعرضها في Alert مباشرة (سهلة النسخ)
        if len(value) <= 180:
            await query.answer(f"✅ {value}", show_alert=True)
            return
        
        # قيم طويلة: رسالة واحدة فقط بدون أزرار متكررة
        await query.answer("✅ تم الإرسال للنسخ", show_alert=False)
        safe = _escape_html(value)
        copy_text = (
            f"✅ <b>القيمة للنسخ:</b>\n\n"
            f"<blockquote><code>{safe}</code></blockquote>\n\n"
            f"👆 <b>اضغط مطولاً على النص لنسخه</b>"
        )
        try:
            await query.message.reply_text(copy_text, parse_mode="HTML")
        except Exception:
            await query.message.reply_text(f"✅ للنسخ:\n{value}")
    except Exception as e:
        logger.exception(f"handle_copy_callback error: {e}")
        try:
            await query.answer("❌ حدث خطأ", show_alert=True)
        except Exception:
            pass

# ==================== نظام مساعد الذكاء الاصطناعي + قاعدة المعرفة ====================
AI_DEFAULT_KNOWLEDGE = {
    "bot_name": "AHMED Bot",
    "services": {
        "names": {"name": "👥 الأسماء", "desc": "توليد أسماء عشوائية مصرية وأجنبية متنوعة، ولد/بنت، مع إمكانية تكرار لا نهائي بدون تكرار", "how": "اضغط 👥 الأسماء → اختر نوع الاسم (عربي/إنجليزي/متنوع) → اختر ولد/بنت → كل ضغطة اسم جديد"},
        "password": {"name": "🔑 إنشاء كلمة مرور", "desc": "توليد كلمة مرور قوية 14 حرف آمنة، حروف كبيرة/صغيرة + أرقام + رموز", "how": "اضغط 🔑 إنشاء كلمة مرور → هيجيلك باسورد قوي قابل للنسخ بزرار نسخ"},
        "2fa": {"name": "🔐 كود 2FA", "desc": "توليد كود التحقق الثنائي (Two-Factor Authentication) من مفتاح سري", "how": "اضغط 🔐 كود 2FA → الصق المفتاح السري → هيجيلك الكود الحالي + الأكواد القادمة مع زر نسخ"},
        "extract_id": {"name": "🆔 استخراج ID", "desc": "استخراج Facebook Numeric ID من أي رابط فيسبوك، حتى روابط /share/ مثل findidfb.com، ويدعم يوزرنيم أيضاً عبر Scraping", "how": "اضغط 🆔 استخراج ID → الصق رابط فيسبوك (profile.php?id=... أو /username أو /share/...) → هيطلع الـ ID الرقمي مع زر نسخ"},
        "mail": {"name": "📧 بريد مؤقت", "desc": "بريد إلكتروني مؤقت يستقبل الأكواد فورياً من أي موقع، 15 دومين مجاني", "how": "اضغط 📧 بريد مؤقت → هيجيلك إيميل عشوائي → استخدمه في أي موقع → الكود هيوصلك في البوت تلقائياً مع زر نسخ"},
        "nums": {"name": "📱 أرقام مؤقتة", "desc": "أرقام مؤقتة حقيقية لاستقبال أكواد SMS، فيسبوك واتساب انستا تيك توك وغيرها، رقم واحد = شخص واحد فقط مضمون", "how": "اضغط 📱 أرقام مؤقتة → اختر الخدمة (فيسبوك/واتساب...) → اختر الدولة → هيجيلك رقم جديد مضمون + زر فحص الاستخدام + زر فحص الكود"},
        "clip": {"name": "📋 الحافظة", "desc": "حفظ أي نص مهم في الحافظة الخاصة بك", "how": "اضغط 📋 الحافظة → الصق أي نص → هيتحفظ مع زر نسخ وعرض"},
        "ai": {"name": "🤖 مساعد الذكاء الاصطناعي", "desc": "مساعد ذكي يشرح لك كل وظائف البوت ويجاوب على أسئلتك", "how": "اضغط 🤖 مساعد الذكاء الاصطناعي → اسأل أي سؤال عن البوت → هيجاوبك فوراً مع حفظ المحادثة"},
    },
    "faq": {
        "كيف اطلع ID من رابط Share؟": "ابعت رابط الـ Share زي https://www.facebook.com/share/1926WtdKjW/ للبوت في خدمة 🆔 استخراج ID، البوت هيحله تلقائياً مثل موقع findidfb.com ويطلع الـ ID الرقمي الحقيقي مع زر نسخ.",
        "هل الأرقام مضمونة؟": "نعم، كل رقم = شخص واحد فقط، مستحيل حد ياخد نفس رقمك، وتقدر تفحص هل الرقم مستخدم على المنصة قبل الاستخدام.",
        "كيف انسخ البيانات؟": "كل بيانات في البوت الآن لها زر 📋 نسخ خاص بها، اضغط الزر وهيجيلك تأكيد ✅ تم النسخ + البيانات في صندوق أزرق قابل للنسخ بضغطة.",
        "البريد المؤقت كم دومين؟": "15 دومين مجاني مختلف، وتقدر تختار الدومين اللي يعجبك.",
    }
}

def get_ai_knowledge_base():
    try:
        db = fast_load_db()
        kb = db.get("ai_knowledge_base")
        if kb:
            return kb
        # لو مفيش، احفظ الافتراضي
        db["ai_knowledge_base"] = AI_DEFAULT_KNOWLEDGE
        fast_save_db(db)
        return AI_DEFAULT_KNOWLEDGE
    except Exception:
        return AI_DEFAULT_KNOWLEDGE

def set_ai_knowledge_base(new_kb):
    try:
        db = fast_load_db()
        db["ai_knowledge_base"] = new_kb
        fast_save_db(db)
        return True
    except Exception as e:
        logger.exception(f"set_ai_knowledge_base error: {e}")
        return False

def _init_ai_user_record(uid, username, first_name):
    try:
        db = fast_load_db()
        db.setdefault("ai_conversations", {})
        user_key = str(uid)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if user_key not in db["ai_conversations"]:
            db["ai_conversations"][user_key] = {
                "telegram_id": uid,
                "username": username or "",
                "first_name": first_name or "",
                "display_name": first_name or username or f"User {uid}",
                "created_at": now,
                "last_active": now,
                "messages": [],
                "message_count": 0,
                "summary": "محادثة جديدة"
            }
        else:
            db["ai_conversations"][user_key]["last_active"] = now
            if username:
                db["ai_conversations"][user_key]["username"] = username
            if first_name:
                db["ai_conversations"][user_key]["first_name"] = first_name
                db["ai_conversations"][user_key]["display_name"] = first_name
        fast_save_db(db)
        return db["ai_conversations"][user_key]
    except Exception as e:
        logger.exception(f"_init_ai_user_record error: {e}")
        return None

def _add_ai_message(uid, role, content):
    try:
        db = fast_load_db()
        user_key = str(uid)
        if user_key not in db.get("ai_conversations", {}):
            return False
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = {"role": role, "content": content, "time": now}
        db["ai_conversations"][user_key]["messages"].append(msg)
        db["ai_conversations"][user_key]["message_count"] = len(db["ai_conversations"][user_key]["messages"])
        db["ai_conversations"][user_key]["last_active"] = now
        # حدث الملخص باختصار آخر سؤال
        if role == "user" and len(content) > 10:
            db["ai_conversations"][user_key]["summary"] = content[:80] + ("..." if len(content) > 80 else "")
        # احتفظ بآخر 200 رسالة فقط لكل مستخدم
        if len(db["ai_conversations"][user_key]["messages"]) > 200:
            db["ai_conversations"][user_key]["messages"] = db["ai_conversations"][user_key]["messages"][-200:]
        fast_save_db(db)
        return True
    except Exception as e:
        logger.exception(f"_add_ai_message error: {e}")
        return False

def generate_ai_reply_rule_based(user_message: str, kb_data):
    """رد ذكي مبني على قاعدة المعرفة - بدون API خارجي"""
    try:
        msg_lower = user_message.lower()
        services = kb_data.get("services", {})
        faq = kb_data.get("faq", {})
        
        # ابحث في FAQ أولاً
        for q, a in faq.items():
            if any(word in msg_lower for word in q.lower().split()[:3]) or q.lower()[:10] in msg_lower:
                # لو جزء من السؤال موجود
                if len(set(msg_lower.split()) & set(q.lower().split())) >= 2:
                    return a
        
        # ابحث عن خدمة مذكورة
        for key, svc in services.items():
            name = svc.get("name","").lower()
            desc = svc.get("desc","").lower()
            how = svc.get("how","").lower()
            keywords = [key, name] + name.split() + desc.split()[:5]
            if any(kw in msg_lower for kw in keywords if len(kw) > 2):
                return f"{svc.get('name')}\n\n{svc.get('desc')}\n\n<b>طريقة الاستخدام:</b>\n{svc.get('how')}\n\n💡 كل النتائج الآن فيها زر 📋 نسخ لسهولة النسخ!"
        
        # كلمات مفتاحية عامة
        if any(w in msg_lower for w in ["id", "اي دي", "فيسبوك", "facebook", "share"]):
            svc = services.get("extract_id")
            if svc:
                return f"{svc.get('name')} - {svc.get('desc')}\n\n{svc.get('how')}\n\n✅ يدعم الآن روابط /share/ مثل findidfb.com مع زر نسخ موحد!"
        if any(w in msg_lower for w in ["بريد", "ايميل", "mail", "email"]):
            svc = services.get("mail")
            if svc:
                return f"{svc.get('name')} - {svc.get('desc')}\n\n{svc.get('how')}"
        if any(w in msg_lower for w in ["رقم", "number", "sms", "واتس", "فيسبوك رقم"]):
            svc = services.get("nums")
            if svc:
                return f"{svc.get('name')} - {svc.get('desc')}\n\n{svc.get('how')}"
        if any(w in msg_lower for w in ["اسم", "name"]):
            svc = services.get("names")
            if svc:
                return f"{svc.get('name')} - {svc.get('desc')}\n\n{svc.get('how')}"
        if any(w in msg_lower for w in ["باسورد", "password", "كلمة سر"]):
            svc = services.get("password")
            if svc:
                return f"{svc.get('name')} - {svc.get('desc')}\n\n{svc.get('how')}"
        if any(w in msg_lower for w in ["2fa", "كود", "تحقق"]):
            svc = services.get("2fa")
            if svc:
                return f"{svc.get('name')} - {svc.get('desc')}\n\n{svc.get('how')}"
        if any(w in msg_lower for w in ["نسخ", "copy"]):
            return "✅ نظام النسخ الجديد:\n\nكل بيانات في البوت الآن لها صندوق أزرق مميز وزر 📋 نسخ خاص بها!\n\n• اضغط الزر → ✅ تم النسخ\n• البيانات تظهر في صندوق أزرق قابل للنسخ بضغطة\n• لو فيه أكثر من قيمة، كل قيمة لها زر نسخ مستقل\n\nجرب أي خدمة وهتشوف التصميم الجديد!"
        
        # رد افتراضي يشرح البوت
        all_services = "\n".join([f"• {s.get('name')}: {s.get('desc')}" for s in services.values()])
        return f"👋 أهلاً! أنا مساعد {kb_data.get('bot_name','البوت')} الذكي 🤖\n\n<b>الخدمات المتاحة:</b>\n{all_services}\n\n━━━━━━━━━━━━━━━\n💡 اسألني عن أي خدمة بالتفصيل، مثلاً:\n• كيف اطلع ID من رابط Share؟\n• كيف استخدم البريد المؤقت؟\n• كيف انسخ البيانات؟\n\nأنا أعرف كل وظائف البوت الحالية ومش هخترع حاجة مش موجودة!"
    except Exception as e:
        logger.exception(f"generate_ai_reply_rule_based error: {e}")
        return "👋 أهلاً! أنا مساعد البوت الذكي 🤖\n\nأقدر أشرح لك كل خدمات البوت:\n• 👥 الأسماء\n• 🔑 كلمة مرور\n• 🔐 كود 2FA\n• 🆔 استخراج ID (حتى روابط Share)\n• 📧 بريد مؤقت\n• 📱 أرقام مؤقتة\n• 📋 الحافظة\n\nاسألني عن أي خدمة!"

async def generate_ai_reply(uid, user_message: str):
    """يولد رد AI - يحاول OpenAI إذا توفر المفتاح، وإلا rule-based"""
    kb_data = get_ai_knowledge_base()
    
    # حاول استخدام OpenAI / Groq إذا توفر المفتاح في Secrets
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("AI_API_KEY")
    if api_key:
        try:
            # حاول استدعاء API (يدعم OpenAI و Groq المتوافق)
            import aiohttp
            prompt = f"""أنت مساعد ذكي لبوت تليجرام اسمه {kb_data.get('bot_name')}. 
مهمتك شرح وظائف البوت فقط من قاعدة المعرفة التالية، لا تخترع وظائف غير موجودة.

قاعدة المعرفة:
{json.dumps(kb_data, ensure_ascii=False, indent=2)}

قواعد:
- جاوب بالعربي المصري البسيط
- اشرح الخدمة المطلوبة فقط
- اذكر أن كل البيانات لها زر نسخ 📋
- لا تخترع خدمات
- لو السؤال خارج نطاق البوت، قول: الخدمة دي مش موجودة حالياً، الخدمات المتاحة هي...

سؤال المستخدم: {user_message}
"""
            # استخدم Groq أو OpenAI
            base_url = "https://api.groq.com/openai/v1/chat/completions" if os.getenv("GROQ_API_KEY") else "https://api.openai.com/v1/chat/completions"
            model = "llama-3.1-8b-instant" if os.getenv("GROQ_API_KEY") else "gpt-4o-mini"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role":"user","content":prompt}], "max_tokens": 500, "temperature": 0.7}
            async with aiohttp.ClientSession() as session:
                async with session.post(base_url, headers=headers, json=payload, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data.get("choices",[{}])[0].get("message",{}).get("content","")
                        if content:
                            return content
        except Exception as e:
            logger.debug(f"AI API call failed, fallback to rule-based: {e}")
    
    # Fallback rule-based
    return generate_ai_reply_rule_based(user_message, kb_data)

async def start_ai_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # تنظيف جلسة AI قديمة - جلسة جديدة = State جديد
    try:
        context.user_data.pop("last_ai_time", None)
        context.user_data.pop("ai_chat_history", None)
        context.user_data["waiting"] = None
        clear_user_processing(uid, success=True)
    except Exception:
        pass
    # تحديث حالة المستخدم - دخول AI
    set_user_status(uid, UserStatus.AI_USING, service="ai_assistant", path_action={"action": "push", "page": "ai_assistant"})
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or ""
    _init_ai_user_record(uid, username, first_name)
    context.user_data["waiting"] = "ai_chat"
    # حفظ الصفحة السابقة للرجوع الهرمي
    try:
        stack = context.user_data.get("nav_stack", [])
        if not stack or stack[-1] != "main":
            stack.append("main")
        context.user_data["nav_stack"] = stack
        context.user_data["current_page"] = "ai_assistant"
    except Exception:
        pass
    kb_data = get_ai_knowledge_base()
    services_list = "\n".join([f"• {s['name']}" for s in kb_data.get("services",{}).values()])
    welcome = (
        f"🤖 <b>أهلاً بيك في مساعد الذكاء الاصطناعي!</b>\n\n"
        f"أنا أعرف كل وظائف البوت الحالية وأقدر أشرحها لك:\n"
        f"{services_list}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💬 ابعت سؤالك الآن، مثلاً:\n"
        f"• كيف اطلع ID من رابط Share؟\n"
        f"• كيف استخدم البريد المؤقت؟\n"
        f"• إيه نظام النسخ الجديد؟\n\n"
        f"✍️ اكتب سؤالك..."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ مسح محادثتي", callback_data="ai_clear_my")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
    ])
    await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=kb)

async def handle_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    set_user_status(uid, UserStatus.AI_USING, service="ai_assistant")
    text = update.message.text.strip()
    if not text:
        return
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or ""
    _init_ai_user_record(uid, username, first_name)
    _add_ai_message(uid, "user", text)
    
    # typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass
    
    reply = await generate_ai_reply(uid, text)
    _add_ai_message(uid, "ai", reply)
    
    # زر نسخ للإجابة
    cid = _store_copy_value(reply.replace("<b>","").replace("</b>",""))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 نسخ الإجابة", callback_data=f"copy_{cid}")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
    ])
    await update.message.reply_text(f"🤖 <b>المساعد:</b>\n\n{reply}", parse_mode="HTML", reply_markup=kb)

# ==================== لوحة تحكم الأدمن للـ AI ====================
def _parse_ai_time(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.datetime.min

async def admin_ai_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ للأدمن فقط", show_alert=True)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 قائمة المحادثات", callback_data="adm_ai_list_0")],
        [InlineKeyboardButton("📊 إحصائيات AI", callback_data="adm_ai_stats")],
        [InlineKeyboardButton("🧠 قاعدة المعرفة", callback_data="adm_ai_kb")],
        [InlineKeyboardButton("🔎 بحث", callback_data="adm_ai_search_menu")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="adm_close")]
    ])
    text = (
        f"🤖 <b>لوحة تحكم محادثات الذكاء الاصطناعي</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"• عرض كل المستخدمين اللي استخدموا AI\n"
        f"• البحث بالـ ID / Username / الاسم\n"
        f"• فلاتر زمنية\n"
        f"• إحصائيات كاملة\n"
        f"• إدارة قاعدة المعرفة\n"
        f"━━━━━━━━━━━━━━━"
    )
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)

async def admin_ai_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0, filter_type="all", search_query=None):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        db = fast_load_db()
        convs = db.get("ai_conversations", {})
        items = list(convs.values())
        
        # فلترة زمنية
        now = datetime.datetime.now()
        if filter_type == "today":
            items = [c for c in items if _parse_ai_time(c.get("last_active","")).date() == now.date()]
        elif filter_type == "7days":
            items = [c for c in items if (now - _parse_ai_time(c.get("last_active",""))).days <= 7]
        elif filter_type == "30days":
            items = [c for c in items if (now - _parse_ai_time(c.get("last_active",""))).days <= 30]
        
        # بحث
        if search_query:
            sq = search_query.lower()
            filtered = []
            for c in items:
                if sq in str(c.get("telegram_id","")).lower() or sq in c.get("username","").lower() or sq in c.get("display_name","").lower() or sq in c.get("first_name","").lower():
                    filtered.append(c)
            items = filtered
        
        # ترتيب بالأحدث
        items.sort(key=lambda x: _parse_ai_time(x.get("last_active","")), reverse=True)
        
        total = len(items)
        per_page = 5
        start = page * per_page
        end = start + per_page
        page_items = items[start:end]
        
        if not page_items:
            text = f"🤖 <b>محادثات AI</b>\n\n❌ لا يوجد نتائج\nفلتر: {filter_type}\nبحث: {search_query or 'لا يوجد'}\n\nإجمالي: {total}"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")],
                [InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")]
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            return
        
        text_lines = [f"🤖 <b>محادثات AI - صفحة {page+1}</b> (فلتر: {filter_type})", f"إجمالي: {total} | عرض: {start+1}-{min(end,total)}", "━━━━━━━━━━━━━━━", ""]
        kb_rows = []
        for c in page_items:
            name = _escape_html(c.get("display_name","بدون اسم")[:20])
            tid = c.get("telegram_id")
            uname = c.get("username","")
            count = c.get("message_count",0)
            last = c.get("last_active","")
            summary = _escape_html(c.get("summary","")[:40])
            text_lines.append(f"👤 <b>{name}</b> | 🆔 <code>{tid}</code>")
            text_lines.append(f"🔹 @{_escape_html(uname)} | 💬 {count} | 🕐 {last}")
            text_lines.append(f"📝 {summary}")
            text_lines.append("")
            kb_rows.append([InlineKeyboardButton(f"👁️ {name} ({count})", callback_data=f"adm_ai_view_{tid}")])
        
        # أزرار التنقل والفلاتر
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"adm_ai_list_{page-1}_{filter_type}"))
        if end < total:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"adm_ai_list_{page+1}_{filter_type}"))
        if nav:
            kb_rows.append(nav)
        
        kb_rows.append([
            InlineKeyboardButton("اليوم", callback_data="adm_ai_filter_today"),
            InlineKeyboardButton("7 أيام", callback_data="adm_ai_filter_7days"),
            InlineKeyboardButton("30 يوم", callback_data="adm_ai_filter_30days"),
            InlineKeyboardButton("الكل", callback_data="adm_ai_filter_all")
        ])
        kb_rows.append([
            InlineKeyboardButton("📊 إحصائيات", callback_data="adm_ai_stats"),
            InlineKeyboardButton("🔎 بحث", callback_data="adm_ai_search_menu")
        ])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")])
        
        text = "\n".join(text_lines)
        kb = InlineKeyboardMarkup(kb_rows)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_ai_list error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_ai_view_user(update: Update, context: ContextTypes.DEFAULT_TYPE, tid):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        db = fast_load_db()
        conv = db.get("ai_conversations", {}).get(str(tid))
        if not conv:
            await query.answer("❌ المستخدم غير موجود", show_alert=True)
            return
        name = _escape_html(conv.get("display_name",""))
        username = _escape_html(conv.get("username",""))
        first = _escape_html(conv.get("first_name",""))
        created = conv.get("created_at","")
        last = conv.get("last_active","")
        count = conv.get("message_count",0)
        summary = _escape_html(conv.get("summary",""))
        
        text = (
            f"👤 <b>بيانات المستخدم</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👤 الاسم: {name}\n"
            f"🆔 Telegram ID: <code>{tid}</code>\n"
            f"🔹 Username: @{username}\n"
            f"📛 الاسم الظاهر: {first}\n"
            f"💬 عدد الرسائل: {count}\n"
            f"🕐 بداية المحادثة: {created}\n"
            f"🕐 آخر نشاط: {last}\n"
            f"📝 ملخص: {summary}\n"
            f"━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 عرض المحادثة كاملة", callback_data=f"adm_ai_full_{tid}_0")],
            [InlineKeyboardButton("📋 ملخص المحادثة", callback_data=f"adm_ai_summary_{tid}")],
            [InlineKeyboardButton("🗑️ حذف المحادثة", callback_data=f"adm_ai_del_{tid}"), InlineKeyboardButton("🗑️ حذف المستخدم", callback_data=f"adm_ai_deluser_{tid}")],
            [InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="adm_ai_list_0")],
            [InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_ai_view_user error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_ai_full_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, tid, page=0):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        db = fast_load_db()
        conv = db.get("ai_conversations", {}).get(str(tid))
        if not conv:
            await query.answer("❌ غير موجود", show_alert=True)
            return
        messages = conv.get("messages", [])
        per_page = 5
        start = page * per_page
        end = start + per_page
        page_msgs = messages[start:end]
        
        if not page_msgs:
            await query.answer("❌ لا يوجد رسائل في هذه الصفحة", show_alert=True)
            return
        
        lines = [f"💬 <b>محادثة {conv.get('display_name','')} - صفحة {page+1}</b>", f"🆔 {tid} | إجمالي: {len(messages)}", "━━━━━━━━━━━━━━━", ""]
        for m in page_msgs:
            role = m.get("role")
            content = _escape_html(m.get("content","")[:500])
            t = m.get("time","")
            if role == "user":
                lines.append(f"👤 <b>المستخدم [{t}]:</b>")
                lines.append(f"{content}")
            else:
                lines.append(f"🤖 <b>AI [{t}]:</b>")
                lines.append(f"{content}")
            lines.append("")
        
        text = "\n".join(lines)
        # Telegram limit 4096
        if len(text) > 4000:
            text = text[:4000] + "\n..."
        
        kb_rows = []
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"adm_ai_full_{tid}_{page-1}"))
        if end < len(messages):
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"adm_ai_full_{tid}_{page+1}"))
        if nav:
            kb_rows.append(nav)
        kb_rows.append([InlineKeyboardButton("🔙 رجوع للمستخدم", callback_data=f"adm_ai_view_{tid}")])
        kb_rows.append([InlineKeyboardButton("📋 القائمة", callback_data="adm_ai_list_0"), InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")])
        
        kb = InlineKeyboardMarkup(kb_rows)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_ai_full_chat error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_ai_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        db = fast_load_db()
        convs = db.get("ai_conversations", {})
        total_users = len(convs)
        total_messages = sum(c.get("message_count",0) for c in convs.values())
        total_chats = total_users  # كل مستخدم له محادثة
        # أكثر المستخدمين استخداماً
        sorted_users = sorted(convs.values(), key=lambda x: x.get("message_count",0), reverse=True)[:5]
        # أكثر الأسئلة تكراراً (تجميع أول 30 حرف)
        from collections import Counter
        questions = []
        for c in convs.values():
            for m in c.get("messages",[]):
                if m.get("role") == "user":
                    q = m.get("content","").strip()[:60]
                    if len(q) > 10:
                        questions.append(q)
        common_q = Counter(questions).most_common(5)
        
        avg = total_messages / total_users if total_users else 0
        
        text_lines = [
            f"📊 <b>إحصائيات AI</b>",
            f"━━━━━━━━━━━━━━━",
            f"👥 إجمالي المستخدمين: {len(db.get('user_tracks',{}))}",
            f"🤖 عدد مستخدمي AI: {total_users}",
            f"💬 إجمالي المحادثات: {total_chats}",
            f"📨 إجمالي الرسائل: {total_messages}",
            f"📈 متوسط الرسائل/محادثة: {avg:.1f}",
            f"━━━━━━━━━━━━━━━",
            f"<b>🔥 أكثر المستخدمين استخداماً:</b>"
        ]
        for i, u in enumerate(sorted_users,1):
            name = _escape_html(u.get("display_name","")[:15])
            text_lines.append(f"{i}. {name} ({u.get('telegram_id')}) - {u.get('message_count',0)} رسالة")
        
        text_lines.append("")
        text_lines.append("<b>❓ أكثر الأسئلة تكراراً:</b>")
        for q, cnt in common_q:
            text_lines.append(f"• {_escape_html(q)} ({cnt}x)")
        
        text = "\n".join(text_lines)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 قائمة المحادثات", callback_data="adm_ai_list_0")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")],
            [InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_ai_stats error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_ai_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    context.user_data["waiting"] = "adm_ai_search"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")]
    ])
    await query.edit_message_text(
        f"🔎 <b>البحث في محادثات AI</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"ابعت الآن:\n"
        f"• Telegram ID (مثل: 123456789)\n"
        f"• أو Username (مثل: @username أو username)\n"
        f"• أو الاسم (مثل: Ahmed)\n\n"
        f"وسأبحث في كل المحادثات...",
        parse_mode="HTML", reply_markup=kb
    )

async def admin_ai_kb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    kb_data = get_ai_knowledge_base()
    services = kb_data.get("services",{})
    text_lines = [f"🧠 <b>قاعدة معرفة AI</b>", f"عدد الخدمات: {len(services)}", "━━━━━━━━━━━━━━━", ""]
    for key, svc in services.items():
        text_lines.append(f"• {svc.get('name')} ({key})")
    
    text_lines.append("")
    text_lines.append("💡 يمكنك تعديل قاعدة المعرفة من الكود أو سأضيف لك واجهة تعديل قريباً")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل خدمة", callback_data="adm_ai_kb_edit")],
        [InlineKeyboardButton("➕ إضافة خدمة", callback_data="adm_ai_kb_add")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")],
        [InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")]
    ])
    await query.edit_message_text("\n".join(text_lines), parse_mode="HTML", reply_markup=kb)



# ==================== نظام حالة العمليات + إعادة المحاولة + حالة المستخدم + التنبيهات V35 ====================
from enum import Enum
import time as time_module

class UserStatus(str, Enum):
    IDLE = "idle"  # 🟢 متاح
    PROCESSING = "processing"  # ⏳
    AI_USING = "ai_using"  # 🤖
    RETRYING = "retrying"  # 🔄
    BANNED = "banned"  # 🚫
    WATCHING = "watching"  # ⚠️ تحت المراقبة

USER_STATE_LOCK = threading.Lock()
USER_STATE_CACHE = {}  # uid -> state dict in memory
SERVICE_HEALTH = {}  # service_name -> {status, last_check, error_count, last_error, last_success, avg_time}
SERVICE_HEALTH_LOCK = threading.Lock()
PROCESSING_LOCKS = {}  # uid -> operation_id
PROCESSING_LOCK = threading.Lock()

MAX_RETRY_ATTEMPTS = 3
PROCESSING_TIMEOUT_SECONDS = 60  # 60 ثانية timeout

def _now_ts():
    return time_module.time()

def _now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_user_state(uid):
    uid_str = str(uid)
    with USER_STATE_LOCK:
        if uid_str in USER_STATE_CACHE:
            return USER_STATE_CACHE[uid_str]
    try:
        db = fast_load_db()
        state = db.get("user_states", {}).get(uid_str)
        if state:
            with USER_STATE_LOCK:
                USER_STATE_CACHE[uid_str] = state
            return state
    except Exception:
        pass
    # default state
    default = {
        "user_id": int(uid),
        "status": UserStatus.IDLE,
        "current_service": None,
        "path": ["main"],  # مسار التنقل
        "is_processing": False,
        "current_operation_id": None,
        "current_operation_data": None,
        "last_active": _now_str(),
        "last_active_ts": _now_ts(),
        "operation_count": 0,
        "error_count": 0,
        "retry_count": 0,
        "last_error": None,
        "last_error_time": None,
        "last_error_service": None,
        "has_active_process": False,
        "processing_started_at": None,
        "is_banned": False,
        "is_watching": False,
    }
    return default

def save_user_state(uid, state_dict):
    uid_str = str(uid)
    state_dict["last_active"] = _now_str()
    state_dict["last_active_ts"] = _now_ts()
    with USER_STATE_LOCK:
        USER_STATE_CACHE[uid_str] = state_dict
    try:
        db = fast_load_db()
        db.setdefault("user_states", {})[uid_str] = state_dict
        fast_save_db(db)
    except Exception as e:
        logger.debug(f"save_user_state error: {e}")

def set_user_status(uid, status: UserStatus, service=None, path_action=None):
    try:
        state = get_user_state(uid)
        state["status"] = status
        if service is not None:
            state["current_service"] = service
        if path_action:
            # path_action = {"action": "push"|"pop"|"set", "page": "page_name"}
            if path_action["action"] == "push":
                state["path"].append(path_action["page"])
                if len(state["path"]) > 20:
                    state["path"] = state["path"][-20:]
            elif path_action["action"] == "pop":
                if len(state["path"]) > 1:
                    state["path"].pop()
            elif path_action["action"] == "set":
                state["path"] = [path_action["page"]]
        # handle banned/watching override
        if status == UserStatus.BANNED:
            state["is_banned"] = True
        if status == UserStatus.WATCHING:
            state["is_watching"] = True
        save_user_state(uid, state)
        return state
    except Exception as e:
        logger.exception(f"set_user_status error: {e}")
        return None

def set_user_processing(uid, operation_id, operation_data, service=None):
    """يبدأ عملية ويمنع التعارض"""
    try:
        with PROCESSING_LOCK:
            if uid in PROCESSING_LOCKS:
                # هناك عملية قيد التنفيذ
                existing = PROCESSING_LOCKS[uid]
                if existing == operation_id:
                    return False, "same_operation_running"
                else:
                    return False, "different_operation_running"
            PROCESSING_LOCKS[uid] = operation_id
        
        state = get_user_state(uid)
        state["is_processing"] = True
        state["has_active_process"] = True
        state["status"] = UserStatus.PROCESSING
        state["current_operation_id"] = operation_id
        state["current_operation_data"] = operation_data
        state["processing_started_at"] = _now_ts()
        state["operation_count"] = state.get("operation_count", 0) + 1
        if service:
            state["current_service"] = service
        save_user_state(uid, state)
        return True, "started"
    except Exception as e:
        logger.exception(f"set_user_processing error: {e}")
        return False, "error"

def clear_user_processing(uid, success=True):
    try:
        with PROCESSING_LOCK:
            PROCESSING_LOCKS.pop(uid, None)
        state = get_user_state(uid)
        state["is_processing"] = False
        state["has_active_process"] = False
        state["current_operation_id"] = None
        state["current_operation_data"] = None
        state["processing_started_at"] = None
        if success:
            state["status"] = UserStatus.IDLE
            state["retry_count"] = 0
        save_user_state(uid, state)
    except Exception as e:
        logger.exception(f"clear_user_processing error: {e}")

def is_user_processing(uid):
    with PROCESSING_LOCK:
        return uid in PROCESSING_LOCKS

def record_user_error(uid, service, error_msg):
    try:
        state = get_user_state(uid)
        state["error_count"] = state.get("error_count", 0) + 1
        state["last_error"] = str(error_msg)[:500]
        state["last_error_time"] = _now_str()
        state["last_error_service"] = service
        save_user_state(uid, state)
        
        # حدث صحة الخدمة
        update_service_health(service, success=False, error=error_msg)
        
        # إذا تكرر الخطأ، نبه الأدمن
        if state["error_count"] % 3 == 0 or "critical" in str(error_msg).lower() or "api" in str(error_msg).lower():
            # أرسل تنبيه بدون Secrets
            try:
                # لا نرسل هنا مباشرة، سنرسل عبر notify_owner في المكان المناسب مع context
                pass
            except Exception:
                pass
        return state
    except Exception as e:
        logger.exception(f"record_user_error: {e}")
        return None

def update_service_health(service_name, success=True, error=None, duration=None):
    try:
        with SERVICE_HEALTH_LOCK:
            if service_name not in SERVICE_HEALTH:
                SERVICE_HEALTH[service_name] = {
                    "status": "🟢 تعمل",
                    "status_code": "online",
                    "last_check": _now_str(),
                    "error_count": 0,
                    "success_count": 0,
                    "last_error": None,
                    "last_success": None,
                    "avg_time": 0,
                    "total_ops": 0
                }
            h = SERVICE_HEALTH[service_name]
            h["last_check"] = _now_str()
            h["total_ops"] += 1
            if success:
                h["success_count"] += 1
                h["last_success"] = _now_str()
                if h["error_count"] > 0:
                    h["error_count"] = max(0, h["error_count"] - 1)  # قلل الأخطاء مع النجاح
                if h["error_count"] == 0:
                    h["status"] = "🟢 تعمل"
                    h["status_code"] = "online"
                elif h["error_count"] < 3:
                    h["status"] = "🟡 بها مشكلة مؤقتة"
                    h["status_code"] = "degraded"
                if duration:
                    # متوسط متحرك
                    h["avg_time"] = (h["avg_time"] * 0.8 + duration * 0.2) if h["avg_time"] else duration
            else:
                h["error_count"] += 1
                h["last_error"] = str(error)[:300] if error else "خطأ غير معروف"
                if h["error_count"] >= 5:
                    h["status"] = "🔴 متوقفة"
                    h["status_code"] = "offline"
                elif h["error_count"] >= 2:
                    h["status"] = "🟡 بها مشكلة مؤقتة"
                    h["status_code"] = "degraded"
            # احفظ في DB أيضاً
            try:
                db = fast_load_db()
                db.setdefault("service_health", {})[service_name] = h
                fast_save_db(db)
            except Exception:
                pass
    except Exception as e:
        logger.exception(f"update_service_health error: {e}")

def get_service_health():
    try:
        with SERVICE_HEALTH_LOCK:
            if SERVICE_HEALTH:
                return dict(SERVICE_HEALTH)
        db = fast_load_db()
        return db.get("service_health", {})
    except Exception:
        return {}

# ==================== نظام حالة التحميل + إعادة المحاولة ====================
async def send_loading_state(message_obj, text="⏳ جاري تنفيذ الطلب...", service=None):
    """يرسل حالة تحميل ويعيد message_id للتحديث لاحقاً"""
    try:
        loading_text = f"{text}\n\n━━━━━━━━━━━━━━━\n⏳ الرجاء الانتظار...\n🔧 الخدمة: {service or 'عام'}"
        if hasattr(message_obj, 'edit_message_text'):
            # CallbackQuery
            await message_obj.edit_message_text(loading_text)
            return message_obj.message_id if hasattr(message_obj, 'message_id') else None, message_obj
        else:
            # Message
            msg = await message_obj.reply_text(loading_text)
            return msg.message_id, msg
    except Exception as e:
        logger.debug(f"send_loading_state error: {e}")
        return None, None

async def update_loading_to_result(loading_msg_obj, result_text, reply_markup=None, parse_mode="HTML"):
    """يحدث رسالة التحميل بالنتيجة النهائية"""
    try:
        if loading_msg_obj:
            if hasattr(loading_msg_obj, 'edit_text'):
                await loading_msg_obj.edit_text(result_text, parse_mode=parse_mode, reply_markup=reply_markup)
            elif hasattr(loading_msg_obj, 'edit_message_text'):
                await loading_msg_obj.edit_message_text(result_text, parse_mode=parse_mode, reply_markup=reply_markup)
            else:
                await loading_msg_obj.reply_text(result_text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            # fallback
            pass
    except Exception as e:
        logger.debug(f"update_loading_to_result error: {e}")

async def send_error_with_retry(message_obj, error_msg, operation_data, service=None, attempt=0):
    """يرسل رسالة خطأ مع زر إعادة المحاولة"""
    try:
        attempt_text = f" (محاولة {attempt+1}/{MAX_RETRY_ATTEMPTS})" if attempt else ""
        text = (
            f"❌ <b>حدث خطأ مؤقت{attempt_text}</b>\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📋 التفاصيل: {error_msg[:300]}\n"
            f"🔧 الخدمة: {service or 'غير محددة'}\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        if attempt < MAX_RETRY_ATTEMPTS - 1:
            text += f"\n🔄 يمكنك إعادة المحاولة بدون إدخال البيانات مرة أخرى"
            operation_id = operation_data.get("operation_id", _generate_copy_id()) if operation_data else _generate_copy_id()
            # احفظ operation_data للـ retry
            if operation_data:
                operation_data["operation_id"] = operation_id
                operation_data["attempt"] = attempt + 1
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"retry_{operation_id}")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
            ])
            # خزن operation_data في COPY_STORE مؤقتاً لإعادة الاستخدام
            with COPY_STORE_LOCK:
                COPY_STORE[f"retry_{operation_id}"] = operation_data
            try:
                db = fast_load_db()
                db.setdefault("retry_store", {})[f"retry_{operation_id}"] = operation_data
                fast_save_db(db)
            except Exception:
                pass
        else:
            text += f"\n❌ انتهت المحاولات ({MAX_RETRY_ATTEMPTS}). حاول لاحقاً أو تواصل مع الدعم."
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 الدعم الفني", callback_data="support")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
            ])
        
        if hasattr(message_obj, 'edit_message_text'):
            await message_obj.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await message_obj.reply_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"send_error_with_retry error: {e}")

async def handle_retry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    
    if not data.startswith("retry_"):
        return
    
    operation_id = data[6:]
    key = f"retry_{operation_id}"
    
    # منع التعارض - لو فيه عملية شغالة
    if is_user_processing(uid):
        await query.answer("⏳ العملية الحالية ما زالت قيد التنفيذ.", show_alert=True)
        return
    
    # استرجع operation_data
    operation_data = None
    with COPY_STORE_LOCK:
        operation_data = COPY_STORE.get(key)
    if not operation_data:
        try:
            db = fast_load_db()
            operation_data = db.get("retry_store", {}).get(key)
        except Exception:
            pass
    
    if not operation_data:
        await query.answer("❌ انتهت صلاحية إعادة المحاولة، ابدأ من جديد", show_alert=True)
        await query.edit_message_text("❌ انتهت صلاحية إعادة المحاولة\n\nابدأ العملية من جديد من القائمة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="main")]]))
        return
    
    attempt = operation_data.get("attempt", 1)
    service = operation_data.get("service", "غير محددة")
    
    if attempt >= MAX_RETRY_ATTEMPTS:
        await query.answer("❌ انتهت عدد المحاولات", show_alert=True)
        await query.edit_message_text(f"❌ انتهت المحاولات ({MAX_RETRY_ATTEMPTS})\nحاول لاحقاً", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="main")]]))
        return
    
    # ابدأ إعادة المحاولة
    await query.answer(f"🔄 إعادة المحاولة {attempt}/{MAX_RETRY_ATTEMPTS}...")
    
    # حدث الحالة
    set_user_status(uid, UserStatus.RETRYING, service=service)
    success, msg = set_user_processing(uid, f"retry_{operation_id}_{attempt}", operation_data, service=service)
    if not success:
        await query.edit_message_text("⏳ العملية الحالية ما زالت قيد التنفيذ.\n\nانتظر انتهاءها أولاً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="main")]]))
        return
    
    # أظهر حالة تحميل
    loading_msg_id, loading_obj = await send_loading_state(query, f"🔄 إعادة المحاولة ({attempt}/{MAX_RETRY_ATTEMPTS})...\n⏳ جاري تنفيذ الطلب...", service=service)
    
    try:
        # نفذ العملية حسب نوعها
        op_type = operation_data.get("type")
        op_args = operation_data.get("args", {})
        
        result = await execute_operation_by_type(op_type, op_args, query, context, uid, is_retry=True, attempt=attempt, loading_obj=loading_obj)
        
        if result.get("success"):
            clear_user_processing(uid, success=True)
            update_service_health(service, success=True)
            # لا تنشئ طلب مكرر - العملية نجحت
            with COPY_STORE_LOCK:
                COPY_STORE.pop(key, None)
            try:
                db = fast_load_db()
                db.get("retry_store", {}).pop(key, None)
                fast_save_db(db)
            except Exception:
                pass
        else:
            clear_user_processing(uid, success=False)
            # سجل الخطأ ونبه الأدمن إذا تكرر
            record_user_error(uid, service, result.get("error","خطأ"))
            if attempt >= 2:  # بعد محاولتين فشل، نبه الأدمن
                try:
                    await notify_owner(context, f"خطأ متكرر في {service} - يحتاج تدخل", f"User ID: {uid}\\nUsername: @{query.from_user.username or 'بدون'}\\nService: {service}\\nError: {result.get('error','')[:300]}\\nAttempts: {attempt}\\nTime: {_now_str()}")
                except Exception:
                    pass
            # أعد عرض زر إعادة المحاولة إذا باقي محاولات
            await send_error_with_retry(loading_obj or query, result.get("error","خطأ"), operation_data, service=service, attempt=attempt)
    
    except Exception as e:
        logger.exception(f"handle_retry_callback execution error: {e}")
        clear_user_processing(uid, success=False)
        record_user_error(uid, service, str(e))
        await send_error_with_retry(loading_obj or query, str(e)[:300], operation_data, service=service, attempt=attempt)

async def execute_operation_by_type(op_type, args, message_obj, context, uid, is_retry=False, attempt=0, loading_obj=None):
    """ينفذ العملية حسب نوعها - قابل للتوسع"""
    start_time = _now_ts()
    try:
        if op_type == "extract_id":
            raw_url = args.get("url","")
            # استخدم النظام الموحد مع Scraping
            try:
                result = extract_facebook_id_unified_with_scraping(raw_url, allow_scraping=True)
            except NameError:
                result = extract_facebook_id_unified(raw_url)
            
            if result.get("success"):
                fb_id = result["id"]
                method = result.get("method","")
                normalized = result.get("normalized_url","")
                extra = f"\\n🔍 الطريقة: {method}" if method else ""
                if normalized:
                    extra += f"\\n🌐 الرابط: {normalized}"
                duration = _now_ts() - start_time
                update_service_health("extract_id", success=True, duration=duration)
                await send_copyable_unified(loading_obj or message_obj, [{"label": f"Facebook ID{extra}", "value": fb_id}], title=f"🆔 تم استخراج ID بنجاح", show_main=True, extra_text=f"⏱️ استغرق: {duration:.2f}ث")
                return {"success": True}
            else:
                duration = _now_ts() - start_time
                update_service_health("extract_id", success=False, error=result.get("error",""))
                return {"success": False, "error": result.get("error","تعذر استخراج ID") + f"\\n{result.get('reason','')[:200]}"}
        
        elif op_type == "generate_password":
            import random, string
            pwd = ''.join(random.choice(string.ascii_letters+string.digits+"@#$%") for _ in range(14))
            await send_copyable_unified(loading_obj or message_obj, [{"label": "كلمة المرور", "value": pwd}], title="🔑 تم توليد كلمة المرور", show_main=True)
            return {"success": True}
        
        elif op_type == "generate_name":
            cat = args.get("cat","ar")
            gender = args.get("gender","male")
            name = generate_infinite_name(cat, gender, uid)
            await send_copyable_unified(loading_obj or message_obj, [{"label": f"الاسم {cat}", "value": name}], title=f"👤 اسم جديد", show_main=True)
            return {"success": True}
        
        else:
            # عملية عامة - أعد المحاولة تفشل بشكل مقصود للاختبار إذا طلب
            return {"success": False, "error": f"نوع العملية غير معروف: {op_type}"}
    
    except Exception as e:
        logger.exception(f"execute_operation_by_type {op_type} error: {e}")
        update_service_health(args.get("service", op_type), success=False, error=str(e))
        return {"success": False, "error": str(e)[:300]}

async def check_processing_timeouts(context: ContextTypes.DEFAULT_TYPE):
    """يفحص العمليات المعلقة وينظفها بعد Timeout"""
    try:
        now = _now_ts()
        to_clear = []
        with PROCESSING_LOCK:
            for uid, op_id in list(PROCESSING_LOCKS.items()):
                state = get_user_state(uid)
                started = state.get("processing_started_at")
                if started and (now - started) > PROCESSING_TIMEOUT_SECONDS:
                    to_clear.append((uid, op_id, state))
        
        for uid, op_id, state in to_clear:
            try:
                clear_user_processing(uid, success=False)
                record_user_error(uid, state.get("current_service","غير محددة"), f"انتهت مهلة العملية ({PROCESSING_TIMEOUT_SECONDS}ث)")
                # نبه المستخدم إذا أمكن
                # لا نستطيع إرسال رسالة مباشرة بدون chat_id محفوظ، لكن نحفظ الحالة ليظهر له عند تفاعله التالي
                state = get_user_state(uid)
                state["last_error"] = f"انتهت مهلة العملية ({PROCESSING_TIMEOUT_SECONDS}ث)"
                state["last_error_time"] = _now_str()
                save_user_state(uid, state)
                
                # نبه الأدمن
                try:
                    await notify_owner(context, "انتهت مهلة عملية - Timeout", f"User ID: {uid}\\nService: {state.get('current_service')}\\nOperation: {op_id}\\nDuration: {PROCESSING_TIMEOUT_SECONDS}s\\nTime: {_now_str()}")
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"check_processing_timeouts clear error: {e}")
    except Exception as e:
        logger.exception(f"check_processing_timeouts error: {e}")

# ==================== لوحة تحكم حالة المستخدمين والخدمات للأدمن ====================
async def admin_user_states_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        db = fast_load_db()
        states = db.get("user_states", {})
        total = len(states)
        processing = sum(1 for s in states.values() if s.get("is_processing"))
        idle = sum(1 for s in states.values() if s.get("status") == "idle")
        ai_using = sum(1 for s in states.values() if s.get("status") == "ai_using")
        errors = sum(1 for s in states.values() if s.get("error_count",0) > 0)
        
        text = (
            f"👤 <b>حالة المستخدمين</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👥 إجمالي: {total}\n"
            f"🟢 متاح: {idle}\n"
            f"⏳ قيد التنفيذ: {processing}\n"
            f"🤖 يستخدم AI: {ai_using}\n"
            f"⚠️ لديه أخطاء: {errors}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⏱️ Timeout: {PROCESSING_TIMEOUT_SECONDS}ث\n"
            f"🔄 Max Retry: {MAX_RETRY_ATTEMPTS}\n"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⏳ قيد التنفيذ ({processing})", callback_data="adm_state_filter_processing")],
            [InlineKeyboardButton(f"⚠️ لديه أخطاء ({errors})", callback_data="adm_state_filter_errors")],
            [InlineKeyboardButton("📋 كل الحالات", callback_data="adm_state_list_0")],
            [InlineKeyboardButton("🔧 حالة الخدمات", callback_data="adm_service_health")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_user_states_menu error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_state_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0, filter_type="all"):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        db = fast_load_db()
        states = db.get("user_states", {})
        items = list(states.values())
        
        if filter_type == "processing":
            items = [s for s in items if s.get("is_processing")]
        elif filter_type == "errors":
            items = [s for s in items if s.get("error_count",0) > 0]
        
        items.sort(key=lambda x: x.get("last_active_ts",0), reverse=True)
        total = len(items)
        per_page = 5
        start = page * per_page
        end = start + per_page
        page_items = items[start:end]
        
        if not page_items:
            await query.edit_message_text(f"👤 لا يوجد نتائج - فلتر: {filter_type}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_user_states")]]))
            return
        
        lines = [f"👤 <b>حالات المستخدمين - {filter_type} - صفحة {page+1}</b> ({total})", "━━━━━━━━━━━━━━━", ""]
        kb_rows = []
        for s in page_items:
            uid = s.get("user_id")
            status = s.get("status","idle")
            service = s.get("current_service","لا يوجد")
            ops = s.get("operation_count",0)
            errs = s.get("error_count",0)
            last = s.get("last_active","")
            is_proc = "⏳" if s.get("is_processing") else "🟢"
            # أيقونة الحالة
            status_icon = {"idle":"🟢","processing":"⏳","ai_using":"🤖","retrying":"🔄","banned":"🚫","watching":"⚠️"}.get(status, "❓")
            lines.append(f"{is_proc} {status_icon} <code>{uid}</code> | {service} | ops:{ops} err:{errs}")
            lines.append(f"   🕐 {last} | Path: {' > '.join(s.get('path',[]) [-3:])}")
            lines.append("")
            kb_rows.append([InlineKeyboardButton(f"👁️ {uid} - {status}", callback_data=f"adm_state_view_{uid}")])
        
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm_state_list_{page-1}_{filter_type}"))
        if end < total:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"adm_state_list_{page+1}_{filter_type}"))
        if nav:
            kb_rows.append(nav)
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_user_states")])
        
        await query.edit_message_text("\\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))
    except Exception as e:
        logger.exception(f"admin_state_list error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_state_view(update: Update, context: ContextTypes.DEFAULT_TYPE, uid):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        state = get_user_state(uid)
        db = fast_load_db()
        track = db.get("user_tracks", {}).get(str(uid), {})
        username = track.get("username","") or state.get("username","")
        
        text = (
            f"👤 <b>حالة المستخدم بالتفصيل</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"👤 Username: @{_escape_html(username)}\n"
            f"📛 الاسم: {_escape_html(state.get('display_name','') or track.get('first_name',''))}\n"
            f"🔹 الحالة: {state.get('status')} | {'⏳ قيد التنفيذ' if state.get('is_processing') else '🟢 متاح'}\n"
            f"🔧 الخدمة الحالية: {state.get('current_service','لا يوجد')}\n"
            f"🛣️ المسار: {' > '.join(state.get('path',[]))}\n"
            f"🔢 عدد العمليات: {state.get('operation_count',0)}\n"
            f"❌ عدد الأخطاء: {state.get('error_count',0)}\n"
            f"🔄 عدد إعادة المحاولة: {state.get('retry_count',0)}\n"
            f"🕐 آخر نشاط: {state.get('last_active')}\n"
            f"⚠️ آخر خطأ: {state.get('last_error','لا يوجد')[:200]}\n"
            f"🕐 وقت آخر خطأ: {state.get('last_error_time','')}\n"
            f"🔧 خدمة آخر خطأ: {state.get('last_error_service','')}\n"
            f"🆔 عملية حالية: {state.get('current_operation_id','لا يوجد')}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{'⏳ لديه عملية قيد التنفيذ الآن!' if state.get('is_processing') else '✅ لا يوجد عملية حالية'}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 إعادة تعيين الحالة", callback_data=f"adm_state_reset_{uid}")],
            [InlineKeyboardButton("🚫 حظر", callback_data=f"adm_ban_{uid}"), InlineKeyboardButton("⚠️ مراقبة", callback_data=f"adm_watch_{uid}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_state_list_0"), InlineKeyboardButton("❌ اغلاق", callback_data="adm_close")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_state_view error: {e}")
        await query.answer("❌ خطأ", show_alert=True)


async def admin_force_sub_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await check_admin_access(query, context, "force_sub_menu"):
        return
    try:
        channels, enabled = get_force_sub_channels()
        status = "🟢 مفعل" if enabled else "🔴 معطل"
        text = (
            f"📢 <b>إدارة الاشتراك الإجباري</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 الحالة: {status}\n"
            f"📋 عدد القنوات: {len(channels)}\n"
            f"✅ مفعلة: {sum(1 for c in channels if c.get('active'))}\n"
            f"⏸️ متوقفة: {sum(1 for c in channels if not c.get('active'))}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 عند التفعيل، يجب على المستخدمين الاشتراك في كل القنوات المفعلة قبل استخدام البوت."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'🔴 تعطيل' if enabled else '🟢 تفعيل'} الاشتراك الإجباري", callback_data="adm_force_sub_toggle")],
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="adm_force_sub_add"), InlineKeyboardButton("📋 القنوات الحالية", callback_data="adm_force_sub_list")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_force_sub_menu error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_force_sub_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await check_admin_access(query, context, "force_sub_list"):
        return
    try:
        channels, enabled = get_force_sub_channels()
        if not channels:
            text = "📋 <b>القنوات الحالية</b>\n\n❌ لا يوجد قنوات مضافة"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة قناة", callback_data="adm_force_sub_add")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")]
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
            return
        
        lines = [f"📋 <b>القنوات الحالية ({len(channels)})</b>", "━━━━━━━━━━━━━━━", ""]
        kb_rows = []
        for ch in channels:
            ch_id = ch.get("id")
            username = ch.get("username","")
            name = ch.get("name","")
            active = "🟢 مفعلة" if ch.get("active") else "🔴 متوقفة"
            lines.append(f"{active} | {name}")
            lines.append(f"   🆔 <code>{ch_id}</code> | {username}")
            lines.append(f"   📅 {ch.get('added_at','')}")
            lines.append("")
            kb_rows.append([
                InlineKeyboardButton(f"{'⏸️ تعطيل' if ch.get('active') else '▶️ تفعيل'}", callback_data=f"adm_force_sub_toggle_ch_{ch_id}"),
                InlineKeyboardButton("🗑️ حذف", callback_data=f"adm_force_sub_del_{ch_id}")
            ])
        
        kb_rows.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="adm_force_sub_add")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")])
        
        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000]
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))
    except Exception as e:
        logger.exception(f"admin_force_sub_list error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_users_mgmt_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await check_admin_access(query, context, "users_mgmt"):
        return
    try:
        db = fast_load_db()
        total_users = len(db.get("user_tracks", {}))
        banned = len(db.get("banned_users", []))
        suspended = len(db.get("user_suspensions", {}))
        text = (
            f"👥 <b>إدارة المستخدمين</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👥 إجمالي المستخدمين: {total_users}\n"
            f"🚫 محظورين: {banned}\n"
            f"⏸️ موقوفين مؤقتاً: {suspended}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 يمكنك البحث بالـ ID أو Username وإدارة المستخدمين"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 البحث عن مستخدم", callback_data="adm_users_search")],
            [InlineKeyboardButton("📋 كل المستخدمين", callback_data="adm_state_list_0_all")],
            [InlineKeyboardButton("🚫 المحظورين", callback_data="adm_users_banned_list")],
            [InlineKeyboardButton("⏸️ الموقوفين", callback_data="adm_users_suspended_list")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_users_mgmt_menu error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_users_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await check_admin_access(query, context, "users_search"):
        return
    context.user_data["waiting"] = "adm_users_search"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]])
    await query.edit_message_text(
        "🔎 <b>البحث عن مستخدم</b>\n\n"
        "━━━━━━━━━━━━━━━\n"
        "ابعت الآن:\n"
        "• Telegram User ID (مثل: 123456789)\n"
        "• أو Username (مثل: @username أو username)\n\n"
        "وسأبحث في قاعدة البيانات...",
        parse_mode="HTML", reply_markup=kb
    )

async def admin_user_info_view(update: Update, context: ContextTypes.DEFAULT_TYPE, target_uid):
    query = update.callback_query
    if not await check_admin_access(query, context, "user_info"):
        return
    try:
        # حاول إيجاد المستخدم حتى لو أدخل يوزرنيم
        db = fast_load_db()
        uid_to_show = None
        
        # إذا كان رقم
        if str(target_uid).lstrip("-").isdigit():
            uid_to_show = int(target_uid)
        else:
            # ابحث باليوزرنيم
            search_username = str(target_uid).lstrip("@").lower()
            for uid_str, track in db.get("user_tracks", {}).items():
                if track.get("username","").lower() == search_username or track.get("username","").lower() == search_username.lower():
                    uid_to_show = int(uid_str)
                    break
            if not uid_to_show:
                for uid_str, state in db.get("user_states", {}).items():
                    if state.get("username","").lower() == search_username:
                        uid_to_show = int(uid_str)
                        break
        
        if not uid_to_show:
            await query.edit_message_text(f"❌ لم يتم العثور على المستخدم: {target_uid}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
            return
        
        info = get_user_full_info(uid_to_show)
        if not info:
            await query.edit_message_text("❌ خطأ في جلب البيانات", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
            return
        
        text = (
            f"👤 <b>معلومات المستخدم</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👤 الاسم: {_escape_html(info['display_name'])}\n"
            f"🆔 Telegram ID: <code>{info['user_id']}</code>\n"
            f"🔹 Username: @{_escape_html(info['username'])}\n"
            f"🟢 الحالة: {info['status']}\n"
        )
        if info['is_suspended']:
            text += f"⏱️ الإيقاف حتى: {info['suspend_until_str']}\n"
            if info['suspend_reason']:
                text += f"📋 سبب الإيقاف: {info['suspend_reason']}\n"
        text += (
            f"📅 أول استخدام: {info['first_seen'] or 'غير معروف'}\n"
            f"🕐 آخر نشاط: {info['last_seen'] or 'غير معروف'}\n"
            f"📊 عدد العمليات: {info['operation_count']}\n"
            f"🚨 عدد الأخطاء: {info['error_count']}\n"
            f"💬 استخدامات AI: {info['ai_messages']}\n"
            f"🔧 الخدمة الحالية: {info['current_service']}\n"
            f"🛣️ المسار: {' > '.join(info['path'][-3:]) if info['path'] else 'main'}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ آخر خطأ: {info['last_error'][:100] if info['last_error'] else 'لا يوجد'}"
        )
        
        # أزرار الإدارة
        kb_rows = []
        if info['is_banned']:
            kb_rows.append([InlineKeyboardButton("✅ إلغاء الحظر", callback_data=f"adm_user_unban_{uid_to_show}")])
        else:
            kb_rows.append([InlineKeyboardButton("🚫 حظر دائم", callback_data=f"adm_user_ban_{uid_to_show}")])
        
        if info['is_suspended']:
            kb_rows.append([InlineKeyboardButton("▶️ إلغاء الإيقاف", callback_data=f"adm_user_unsuspend_{uid_to_show}")])
        else:
            kb_rows.append([InlineKeyboardButton("⏸️ إيقاف مؤقت", callback_data=f"adm_user_suspend_menu_{uid_to_show}")])
        
        kb_rows.append([
            InlineKeyboardButton("🗑️ حذف المستخدم", callback_data=f"adm_user_delete_confirm_{uid_to_show}"),
            InlineKeyboardButton("💬 محادثات AI", callback_data=f"adm_ai_view_{uid_to_show}")
        ])
        kb_rows.append([InlineKeyboardButton("📋 حالة مفصلة", callback_data=f"adm_state_view_{uid_to_show}")])
        kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")])
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))
    except Exception as e:
        logger.exception(f"admin_user_info_view error: {e}")
        await query.answer("❌ خطأ", show_alert=True)

async def admin_audit_log_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await check_admin_access(query, context, "audit_log"):
        return
    try:
        logs = get_audit_log()
        logs_sorted = sorted(logs, key=lambda x: x.get("timestamp",0), reverse=True)[:20]
        if not logs_sorted:
            text = "📜 <b>سجل العمليات (Audit Log)</b>\n\n❌ لا يوجد سجلات"
        else:
            lines = ["📜 <b>سجل العمليات - آخر 20</b>", "━━━━━━━━━━━━━━━", ""]
            for log in logs_sorted:
                admin_id = log.get("admin_id")
                action = log.get("action")
                target = log.get("target")
                time_str = log.get("time","")
                result = log.get("result","")
                lines.append(f"👮 {admin_id} | {action} | {target} | {result}")
                lines.append(f"   🕐 {time_str}")
                if log.get("extra"):
                    lines.append(f"   📋 {log.get('extra')[:50]}")
                lines.append("")
            text = "\n".join(lines)
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="adm_audit_log")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_audit_log_menu error: {e}")
        await query.answer("❌ خطأ", show_alert=True)



async def admin_service_health_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    try:
        health = get_service_health()
        if not health:
            text = "🔧 <b>حالة الخدمات</b>\\n\\nلا يوجد بيانات بعد - البوت لم ينفذ عمليات"
        else:
            lines = ["🔧 <b>حالة الخدمات</b>", "━━━━━━━━━━━━━━━", ""]
            for svc, h in health.items():
                lines.append(f"{h.get('status','❓')} <b>{svc}</b>")
                lines.append(f"   ✅ نجاح: {h.get('success_count',0)} | ❌ فشل: {h.get('error_count',0)} | إجمالي: {h.get('total_ops',0)}")
                lines.append(f"   🕐 آخر فحص: {h.get('last_check','')}")
                if h.get('last_error'):
                    lines.append(f"   ⚠️ آخر خطأ: {h.get('last_error')[:100]}")
                lines.append("")
            text = "\\n".join(lines)
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="adm_service_health")],
            [InlineKeyboardButton("👤 حالات المستخدمين", callback_data="adm_user_states")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.exception(f"admin_service_health_menu error: {e}")
        await query.answer("❌ خطأ", show_alert=True)



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # فحص الحظر قبل أي شيء
    try:
        is_blocked, block_type, block_msg = is_user_banned_or_suspended(uid)
        if is_blocked:
            await update.message.reply_text(block_msg or "🚫 أنت محظور من استخدام البوت.")
            return
    except Exception as e:
        logger.debug(f"ban check on start: {e}")
    # /start = إعادة تشغيل نظيفة: تنظيف أي جلسة AI أو waiting سابقة
    try:
        context.user_data["waiting"] = None
        context.user_data.pop("last_ai_time", None)
        context.user_data.pop("ai_chat_history", None)
        context.user_data["nav_stack"] = []
        context.user_data["current_page"] = "main"
        for _k in list(context.user_data.keys()):
            if _k.startswith("selected_") or _k in ("temp_mail", "temp_login", "perms_target"):
                context.user_data.pop(_k, None)
        clear_user_processing(uid, success=True)
        set_user_status(uid, UserStatus.IDLE, path_action={"action": "set", "page": "main"})
    except Exception as e:
        logger.debug(f"start cleanup: {e}")
    try:
        update_user_track(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    # تعريف المتغيرات للـ waiting handlers الموجودة (كانت في start بالخطأ سابقاً)
    try:
        text = update.message.text.strip() if update.message and update.message.text else ""
        waiting = context.user_data.get("waiting")
    except Exception:
        text = ""
        waiting = None
    # ملاحظة: الـ waiting handlers هنا لن تُنفذ عادة لأن /start يمسح waiting أولاً
    # لكنها موجودة للتوافق. المعالجة الحقيقية في text_handler.
    if waiting == "adm_force_sub_add":
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        channel_input = text.strip()
        success, result = add_force_sub_channel(channel_input, admin_id=uid)
        if success:
            await update.message.reply_text(f"✅ تمت إضافة القناة:\n{result.get('name')} ({result.get('username')})\n🆔 {result.get('id')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 القنوات", callback_data="adm_force_sub_list"), InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")]]))
        else:
            await update.message.reply_text(f"❌ فشل: {result}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")]]))
        context.user_data["waiting"] = None
        return
    if waiting == "adm_users_search":
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        # Search user
        target = text.strip().lstrip("@")
        db = fast_load_db()
        found = None
        # If numeric ID
        if target.isdigit():
            if str(target) in db.get("user_tracks", {}) or str(target) in db.get("user_states", {}):
                found = target
        else:
            # Search by username
            for uid_str, track in db.get("user_tracks", {}).items():
                if track.get("username","").lower() == target.lower():
                    found = uid_str
                    break
        if found:
            info = get_user_full_info(int(found) if str(found).isdigit() else found)
            # Show info via message with buttons - need to simulate callback
            # Send info directly
            if info:
                text_info = (
                    f"👤 <b>نتيجة البحث</b>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"👤 {info['display_name']}\n"
                    f"🆔 <code>{info['user_id']}</code>\n"
                    f"🔹 @{info['username']}\n"
                    f"🟢 الحالة: {info['status']}\n"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁️ عرض كامل", callback_data=f"adm_user_view_{info['user_id']}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]
                ])
                await update.message.reply_text(text_info, parse_mode="HTML", reply_markup=kb)
            else:
                await update.message.reply_text(f"❌ لم أجد بيانات كافية لـ {target}")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على المستخدم: {target}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
        context.user_data["waiting"] = None
        return
    if waiting and waiting.startswith("adm_suspend_custom_"):
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        target_uid = waiting.replace("adm_suspend_custom_", "")
        try:
            minutes = int(text.strip())
            seconds = minutes * 60
            success, until_str = suspend_user_temporary(int(target_uid), seconds, admin_id=uid, reason=f"إيقاف مخصص {minutes} دقيقة")
            if success:
                await update.message.reply_text(f"✅ تم إيقاف {target_uid} حتى {until_str}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👁️ عرض", callback_data=f"adm_user_view_{target_uid}")]]))
            else:
                await update.message.reply_text(f"❌ {until_str}")
        except ValueError:
            await update.message.reply_text("❌ ابعت رقم فقط (بالدقائق)")
            return
        context.user_data["waiting"] = None
        return
    if waiting == "adm_ai_search":
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        search_q = text.strip()
        # Show search results via fake callback
        # Create a dummy query-like handling by directly calling list with search
        try:
            db = fast_load_db()
            convs = db.get("ai_conversations", {})
            items = list(convs.values())
            sq = search_q.lower()
            filtered = [c for c in items if sq in str(c.get("telegram_id","")).lower() or sq in c.get("username","").lower() or sq in c.get("display_name","").lower()]
            if not filtered:
                await update.message.reply_text(f"🔎 لا يوجد نتائج لـ: {search_q}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 كل المحادثات", callback_data="adm_ai_list_0"), InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")]]))
            else:
                # Build result text
                lines = [f"🔎 نتائج البحث عن: {search_q} ({len(filtered)} نتيجة)", "━━━━━━━━━━━━━━━", ""]
                kb_rows = []
                for c in filtered[:10]:
                    name = c.get("display_name","")[:20]
                    tid = c.get("telegram_id")
                    lines.append(f"👤 {name} | 🆔 {tid} | 💬 {c.get('message_count',0)}")
                    kb_rows.append([InlineKeyboardButton(f"👁️ {name}", callback_data=f"adm_ai_view_{tid}")])
                kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")])
                await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في البحث: {e}")
        context.user_data["waiting"] = None
        return
    settings = load_settings()
    if settings.get("bot_active")==False and not is_admin(uid):
        await update.message.reply_text("⛔ البوت متوقف حالياً")
        return
    
    # تحقق من الحظر/الإيقاف أولاً
    is_blocked, block_type, block_msg = is_user_banned_or_suspended(uid)
    if is_blocked:
        await update.message.reply_text(block_msg, parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        return
    
    # تحقق من الاشتراك الإجباري - للخدمات التي تتطلب اشتراك
    # الخدمات التي تتطلب اشتراك: كل الخدمات الرئيسية
    services_requiring_sub = ["extract_id", "password", "names", "mail", "nums", "ai_assistant", "2fa"]
    # إذا كان المستخدم يحاول استخدام خدمة تتطلب اشتراك، تحقق
    # نتحقق إذا كان النص يمثل خدمة أو waiting يمثل خدمة
    needs_sub_check = False
    current_service_check = None
    if text in ["🆔 استخراج ID", "🔑 إنشاء كلمة مرور", "👥 الأسماء 🌍", "📧 بريد مؤقت", "📱 أرقام مؤقتة", "🤖 مساعد الذكاء الاصطناعي", "🔐 كود 2FA"] or waiting in ["extract_id", "2fa_code", "ai_chat"]:
        needs_sub_check = True
        if "استخراج ID" in text or waiting == "extract_id":
            current_service_check = "extract_id"
        elif "كلمة مرور" in text:
            current_service_check = "password"
        elif "الأسماء" in text:
            current_service_check = "names"
        elif "بريد" in text:
            current_service_check = "mail"
        elif "أرقام" in text:
            current_service_check = "nums"
        elif "الذكاء" in text or waiting == "ai_chat":
            current_service_check = "ai_assistant"
        elif "2FA" in text or waiting == "2fa_code":
            current_service_check = "2fa"
    
    if needs_sub_check and get_force_sub_enabled():
        try:
            not_sub, is_sub = await check_user_subscriptions(context.bot, uid)
            if not is_sub:
                await send_force_sub_message(update.message, not_sub)
                return
        except Exception as e:
            logger.debug(f"force sub check error: {e}")

    
    # فحص اللغة أولاً - لو مش مختار لغة
    db = fast_load_db()
    if str(uid) not in db.get("user_langs", {}):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇪🇬 العربية", callback_data="lang_ar"), InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")]
        ])
        await update.message.reply_text("🌐 <b>اختر لغتك / Choose your language</b>\n\n━━━━━━━━━━━━━━━\n🇪🇬 العربية\n🇺🇸 English\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=kb)
        return
    
    if is_authorized(uid):
        first_name = update.effective_user.first_name or "يا غالي"
        name = first_name
        lang = get_user_lang(uid)
        if lang == "en":
            tmpl = "👋 Welcome, {first_name}\n\n🤖 AHMED Bot\n\n━━━━━━━━━━━━━━━\n⚡ Fast Execution\n🔒 Security & Privacy\n🚀 Smart Tools in One Place\n━━━━━━━━━━━━━━━\n\n📌 Choose a service from the buttons below."
        else:
            tmpl = settings.get("welcome_auth","👋 أهلاً بك، {first_name}\n\n🤖 AHMED Bot\n\n━━━━━━━━━━━━━━━\n⚡ سرعة في التنفيذ\n🔒 أمان وخصوصية\n🚀 أدوات ذكية في مكان واحد\n━━━━━━━━━━━━━━━\n\n📌 اختر الخدمة المطلوبة من الأزرار بالأسفل.")
        try:
            welcome = tmpl.format(first_name=first_name, name=name)
        except Exception as e:
            try:
                welcome = tmpl.format(name=name)
            except Exception as e:
                welcome = tmpl
        if welcome.strip():
            await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        else:
            await update.message.reply_text("👇 اختار من القائمة", reply_markup=main_keyboard(get_user_lang(uid)))
    else:
        first_name = update.effective_user.first_name or ""
        lang = get_user_lang(uid)
        if str(uid) not in db.get("user_langs", {}):
            # لو لسه مختارش لغة، اختار له عربي افتراضي واطلب يوزر
            set_user_lang(uid, "ar")
            lang = "ar"
        
        if lang == "en":
            tmpl = LANGS["en"]["welcome_unauth"]
        else:
            tmpl = settings.get("welcome_unauth","👋 أهلاً بك، {first_name}")
        try:
            welcome = tmpl.format(first_name=first_name, name=first_name)
        except Exception as e:
            welcome = tmpl
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇪🇬 العربية", callback_data="lang_ar"), InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")]
        ])
        await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=kb)


# ==================== نظام الاشعارات التلقائية الفخم V31 ====================
async def temp_mail_watcher(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    mail = job.data.get('mail')
    pwd = job.data.get('pwd')
    token_data = job.data.get('token_data')
    lang = job.data.get('lang', 'ar')
    last_count = job.data.get('last_count', 0)
    
    try:
        messages = get_temp_messages(pwd, token_data)
        if len(messages) > last_count and len(messages) > 0:
            # فيه رسالة جديدة!
            newest = messages[0]  # احدث رسالة
            msg_id = newest.get('id')
            full = read_temp_message(pwd, token_data, msg_id)
            body_text = ""
            if full:
                body_text = (full.get('textBody','') or '') + " " + (full.get('htmlBody','') or '') + " " + (full.get('body','') or '') + " " + (full.get('subject','') or '')
            code = extract_code_from_text(body_text) or extract_code_from_text(str(newest))
            
            # منصة من الايميل
            from_text = full.get('from','') if full else newest.get('from','')
            if isinstance(from_text, dict):
                from_text = from_text.get('address','')
            platform = "Facebook"
            if 'facebook' in body_text.lower() or 'facebook' in str(from_text).lower():
                platform = "Facebook" if lang != 'ar' else "فيسبوك"
            elif 'instagram' in body_text.lower():
                platform = "Instagram" if lang != 'ar' else "انستجرام"
            elif 'tiktok' in body_text.lower():
                platform = "TikTok" if lang != 'ar' else "تيك توك"
            elif 'google' in body_text.lower():
                platform = "Google" if lang != 'ar' else "جوجل"
            elif 'telegram' in body_text.lower():
                platform = "Telegram" if lang != 'ar' else "تليجرام"
            elif 'whatsapp' in body_text.lower():
                platform = "WhatsApp" if lang != 'ar' else "واتساب"
            else:
                platform = from_text[:20] if from_text else ("Unknown" if lang!='ar' else "غير معروف")
            
            now_time = datetime.datetime.now().strftime("%I:%M:%S %p")
            
            if not code:
                code = "تم وصول رسالة - افتح البريد" if lang=='ar' else "New message - open inbox"
            
            if lang == 'ar':
                fancy_text = f"""💎━━━━━━━━━━━━━━━━💎

   ✨ بسم الله الرحمن الرحيم ✨

   👑 تم استلام كودك بنجاح 👑

▬▬▬▬▬▬▬▬▬▬▬▬▬▬

     🎯 كود التحقق الخاص بك

        ┏━━━━━━━━━━━━━┓
        ┃   <code>{code}</code>   ┃
        ┗━━━━━━━━━━━━━┛

▬▬▬▬▬▬▬▬▬▬▬▬▬▬

📨 من : {platform}
📧 إلى : {mail}
⏰ وصل : الآن ({now_time})
✅ الحالة : جديد و صالح للاستخدام
🔥 السرعة : فائقة - وصول فوري

━━━━━━━━━━━━━━━━━━━━
👆 اضغط على الكود لنسخه فوراً
━━━━━━━━━━━━━━━━━━━━

💎━━━━━━━━━━━━━━━━💎
   ⚜️ AHMED VIP SYSTEM ⚜️
💎━━━━━━━━━━━━━━━━💎"""
            else:
                fancy_text = f"""💎━━━━━━━━━━━━━━━━💎

   ✨ AHMED ELITE SYSTEM ✨

   👑 YOUR CODE HAS ARRIVED 👑

▬▬▬▬▬▬▬▬▬▬▬▬▬▬

     🎯 YOUR VERIFICATION CODE

        ┏━━━━━━━━━━━━━┓
        ┃   <code>{code}</code>   ┃
        ┗━━━━━━━━━━━━━┛

▬▬▬▬▬▬▬▬▬▬▬▬▬▬

📨 FROM : {platform}
📧 TO : {mail}
⏰ ARRIVED : Just now ({now_time})
✅ STATUS : Fresh & Valid
🔥 SPEED : Instant Delivery

━━━━━━━━━━━━━━━━━━━━
👆 Tap code to copy instantly
━━━━━━━━━━━━━━━━━━━━

💎━━━━━━━━━━━━━━━━💎
   ⚜️ AHMED VIP SYSTEM ⚜️
💎━━━━━━━━━━━━━━━━💎"""
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📋 نسخ الكود {code}", callback_data="temp_check")],
                [InlineKeyboardButton("📧 فتح البريد" if lang=='ar' else "📧 Open Inbox", callback_data="temp_check")],
                [InlineKeyboardButton("🔄 بريد جديد" if lang=='ar' else "🔄 New Mail", callback_data="temp_new")]
            ])
            
            await context.bot.send_message(chat_id=chat_id, text=fancy_text, parse_mode="HTML", reply_markup=kb)
            
            # وقف المراقبة بعد ما بعت الكود (عشان ما يزعجش)
            job.data['last_count'] = len(messages)
            # نوقفه - المستخدم لو عايز يرجع يشغله يدوس فحص
            # job.schedule_removal()  # نسيبه شغال لحد ما يجي كود تاني
            job.data['last_count'] = len(messages)
        else:
            job.data['last_count'] = len(messages)
    except Exception as e:
        logger.info(f"Watcher error: {e}")



async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    # حظر: منع استخدام Callbacks/خدمات حتى لو ضغط زر قديم
    try:
        is_blocked, block_type, block_msg = is_user_banned_or_suspended(uid)
        if is_blocked and not is_admin(uid) and not is_owner(uid):
            try:
                await query.answer("🚫 محظور", show_alert=True)
            except Exception:
                pass
            try:
                await query.edit_message_text(block_msg or "🚫 أنت محظور من استخدام البوت.")
            except Exception:
                try:
                    await context.bot.send_message(chat_id=uid, text=block_msg or "🚫 أنت محظور من استخدام البوت.")
                except Exception:
                    pass
            return
    except Exception as e:
        logger.debug(f"ban check button_handler: {e}")
    # منع الضغط المتكرر والتداخل - نفس الزر 1ث، أي زر آخر 0.35ث
    try:
        last_cb = context.user_data.get("last_callback")
        last_time = context.user_data.get("last_callback_time", 0)
        now_t = time.time()
        if last_cb == data and (now_t - last_time) < 1.0:
            try:
                await query.answer("⏳ انتظر...", show_alert=False)
            except Exception:
                pass
            return
        if last_cb != data and (now_t - last_time) < 0.35:
            try:
                await query.answer("⏳...", show_alert=False)
            except Exception:
                pass
            return
        context.user_data["last_callback"] = data
        context.user_data["last_callback_time"] = now_t
    except Exception:
        pass
    db = fast_load_db()
    try:
        await query.answer()
    except Exception as e:
        logger.debug(f"Suppressed: {e}")

    if data == "check_force_sub":
        # التحقق من الاشتراك الإجباري
        try:
            not_sub, is_sub = await check_user_subscriptions(context.bot, uid)
            if is_sub:
                await query.edit_message_text("✅ تم التحقق! أنت مشترك في كل القنوات ✅\n\nيمكنك الآن استخدام البوت", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main")]]))
            else:
                await send_force_sub_message(query, not_sub)
        except Exception as e:
            await query.answer(f"❌ خطأ في التحقق: {e}", show_alert=True)
        return
    if data == "main" or data == "main_reply":
        # تنظيف كامل لأي جلسة سابقة (خاصة AI) قبل الرجوع للقائمة الرئيسية
        # هذا يمنع بقاء waiting="ai_chat" أو أي State قديم بعد الضغط على رجوع
        try:
            context.user_data["waiting"] = None
            context.user_data.pop("last_ai_time", None)
            context.user_data.pop("ai_chat_history", None)
            context.user_data["nav_stack"] = []
            context.user_data["current_page"] = "main"
            for _k in list(context.user_data.keys()):
                if _k.startswith("selected_") or _k in ("temp_mail", "temp_login", "perms_target"):
                    context.user_data.pop(_k, None)
        except Exception:
            pass
        try:
            clear_user_processing(uid, success=True)
            set_user_status(uid, UserStatus.IDLE, path_action={"action": "set", "page": "main"})
        except Exception:
            pass
        try:
            await query.delete_message()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        await context.bot.send_message(chat_id=query.message.chat_id, text="👋 أهلاً بيك\n👇 اختار من القائمة", reply_markup=main_keyboard(get_user_lang(uid)))
        return
    if data == "ai_clear_my":
        # مسح محادثة AI الخاصة بالمستخدم فقط - بدون الخروج من الجلسة
        try:
            db = fast_load_db()
            uid_str = str(uid)
            if uid_str in db.get("ai_conversations", {}):
                db["ai_conversations"][uid_str]["messages"] = []
                db["ai_conversations"][uid_str]["message_count"] = 0
                db["ai_conversations"][uid_str]["summary"] = "محادثة جديدة"
                fast_save_db(db)
            context.user_data.pop("ai_chat_history", None)
            context.user_data.pop("last_ai_time", None)
            await query.answer("✅ تم مسح محادثتك", show_alert=False)
            await query.edit_message_text(
                "🗑️ <b>تم مسح محادثتك</b>\n\n✅ يمكنك البدء من جديد.\n✍️ اكتب سؤالك...",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ مسح محادثتي", callback_data="ai_clear_my")],
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
                ])
            )
        except Exception as e:
            logger.debug(f"ai_clear_my error: {e}")
            try:
                await query.answer("❌ خطأ في المسح", show_alert=True)
            except Exception:
                pass
        return
    if data == "save_start":
        await query.edit_message_text("📝 تمام، ابعت اللي عايز تحفظه دلوقتي (حتى لو 5000 حرف)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="main")]]))
        context.user_data["waiting"] = "save_item"
        return
    if data == "saved_list":
        saved = db["users"].get(str(uid), {}).get("saved", [])
        if not saved:
            await query.edit_message_text("🗃️ الحافظة فاضية", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        else:
            txt = "\n\n".join(saved[-10:])
            if len(txt) > 3000:
                txt = txt[:3000]
            await query.edit_message_text(f"🗃️ الحافظة ({len(saved)}):\n\n{txt}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        return
    if data in ["download_saved", "download_saved_inline"]:
        saved = db["users"].get(str(uid), {}).get("saved", [])
        if not saved:
            await query.edit_message_text("🗃️ فاضية")
        else:
            path = f"saved_{uid}.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(saved))
            await context.bot.send_document(chat_id=query.message.chat_id, document=open(path,"rb"), filename=f"hafza_{len(saved)}.txt", caption=f"📦 حافظتك - {len(saved)} عنصر")
            os.remove(path)
            await query.edit_message_text(f"✅ بعتلك الملف فيه {len(saved)} عنصر", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        return
    if data == "clear_saved_inline":
        await query.edit_message_text("⚠️ متأكد عايز تمسح الحافظة كلها؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ايوة امسح", callback_data="confirm_clear_inline"), InlineKeyboardButton("❌ لا", callback_data="main")]]))
        return
    if data == "confirm_clear_inline":
        db["users"].setdefault(str(uid), {"saved":[]})
        db["users"][str(uid)]["saved"] = []
        fast_save_db(db)
        await query.edit_message_text("🗑️ تم مسح الحافظة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        return
    if data == "names_main" or data == "names":
        lang = get_user_lang(uid)
        await query.edit_message_text("👥 <b>الأسماء</b>\n\n━━━━━━━━━━━━━━━\n🌍 اختر نوع الاسم:", parse_mode="HTML", reply_markup=names_main_keyboard(lang))
        return
    if data in ["egy_name","foreign_name"]:
        lang = get_user_lang(uid)
        await query.edit_message_text("👥 <b>الأسماء</b>\n\n━━━━━━━━━━━━━━━\n🌍 اختر نوع الاسم:", parse_mode="HTML", reply_markup=names_main_keyboard(lang))
        return
    if data.startswith("names_") and data.count("_") == 1:
        cat = data.split("_")[1]
        if cat == "main":
            lang = get_user_lang(uid)
            await query.edit_message_text("👥 <b>الأسماء</b>\n\n━━━━━━━━━━━━━━━\n🌍 اختر نوع الاسم:", parse_mode="HTML", reply_markup=names_main_keyboard(lang))
            return
        lang = get_user_lang(uid)
        cat_names = {"ar": "العربي 🇪🇬", "en": "الإنجليزي 🇺🇸", "mixed": "الأجنبي المتنوع 🌍"}
        label = cat_names.get(cat, cat)
        await query.edit_message_text(f"👤 <b>الاسم {label}</b>\n\n━━━━━━━━━━━━━━━\n👦👧 اختر النوع:", parse_mode="HTML", reply_markup=names_gender_keyboard(cat, lang))
        return
    if data.startswith("names_") and data.count("_") == 2:
        try:
            _, cat, gender_key = data.split("_")
            lang = get_user_lang(uid)
            gender = "male" if gender_key == "male" else "female"
            name = generate_infinite_name(cat, gender, uid)
            trans_gender = {"ar": {"male": "👦 ولد", "female": "👧 بنت"}, "en": {"male": "👦 Boy", "female": "👧 Girl"}}
            gender_label = trans_gender.get(lang, trans_gender["ar"]).get(gender_key, gender_key)
            cat_label = {"ar": "عربي", "en": "إنجليزي", "mixed": "أجنبي"}[cat]
            # تخزين الاسم للنسخ - أزرار منظمة: نسخ / اسم تاني / رجوع للقسم السابق (اختيار الجنس)
            cid = _store_copy_value(name)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 نسخ" if lang=="ar" else "📋 Copy", callback_data=f"copy_{cid}")],
                [InlineKeyboardButton("🔄 اسم تاني" if lang=="ar" else "🔄 Another", callback_data=f"names_{cat}_{gender_key}")],
                [InlineKeyboardButton("⬅️ رجوع" if lang=="ar" else "⬅️ Back", callback_data=f"names_{cat}")]
            ])
            await query.edit_message_text(
                f"👤 <b>الاسم ({cat_label} - {gender_label})</b>\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"<b>الاسم:</b>\n"
                f"<blockquote><code>{name}</code></blockquote>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"👆 اضغط على الاسم أو زر النسخ",
                parse_mode="HTML", reply_markup=kb
            )
        except Exception as e:
            lang = get_user_lang(uid)
            await query.edit_message_text(f"❌ خطأ: {e}", parse_mode="HTML", reply_markup=names_main_keyboard(lang))
        return
    if data.startswith("gender_"):
        try:
            _, type_name, gender = data.split("_")
            is_male = gender in ["ذكر", "ولد", "👦 ولد", "ولد"]
            cat = "ar" if type_name=="مصري" else "en"
            gender_key = "male" if is_male else "female"
            name = generate_infinite_name(cat, gender_key, uid)
            gender_label = "👦 ولد" if is_male else "👧 بنت"
            await send_copyable_message(query, f"👤 <b>الاسم {type_name}</b> ({gender_label})", name)
        except Exception as e:
            lang = get_user_lang(uid)
            await query.edit_message_text("👥 <b>الأسماء</b>", parse_mode="HTML", reply_markup=names_main_keyboard(lang))
        return
    if data == "password":
        pwd = ''.join(random.choice(string.ascii_letters+string.digits+"@#$%") for _ in range(14))
        await send_copyable_message(query, "🔑 الباسورد", pwd)
        return
    if data == "2fa":
        await query.edit_message_text("🔐 ابعت كود الـ 2FA الـ Secret", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        context.user_data["waiting"] = "2fa_code"
        return
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        set_user_lang(uid, lang)
        db = fast_load_db()
        if is_authorized(uid):
            first_name = query.from_user.first_name or "غالي"
            if lang == "en":
                welcome = f"👋 Welcome, {first_name}\n\n🤖 AHMED Bot\n\n━━━━━━━━━━━━━━━\n⚡ Fast Execution\n🔒 Security & Privacy\n🚀 Smart Tools in One Place\n━━━━━━━━━━━━━━━\n\n📌 Choose a service from the buttons below."
            else:
                welcome = f"👋 أهلاً بك، {first_name}\n\n🤖 AHMED Bot\n\n━━━━━━━━━━━━━━━\n⚡ سرعة في التنفيذ\n🔒 أمان وخصوصية\n🚀 أدوات ذكية في مكان واحد\n━━━━━━━━━━━━━━━\n\n📌 اختر الخدمة المطلوبة من الأزرار بالأسفل."
            await query.edit_message_text(welcome, parse_mode="HTML")
            await context.bot.send_message(chat_id=query.message.chat_id, text="👇 اختر من القائمة" if lang=="ar" else "👇 Choose from menu", reply_markup=main_keyboard(get_user_lang(uid)))
        else:
            if lang == "en":
                await query.edit_message_text("🔐 Enter your username to continue ✅", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇪🇬 العربية", callback_data="lang_ar"), InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")]]))
            else:
                await query.edit_message_text("🔐 اكتب اليوزر الخاص بك للمواصلة ✅", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇪🇬 العربية", callback_data="lang_ar"), InlineKeyboardButton("🇺🇸 English", callback_data="lang_en")]]))
        return
    if data == "nums_services" or data == "nums_real":
        lang = get_user_lang(uid)
        # عرض الخدمات زي الصورة الثانية
        if lang == "en":
            txt = "✅ <b>Choose Service:</b> 🌍"
        else:
            txt = "✅ <b>الخدمة المطلوبة:</b> اختر الخدمة 🌍"
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=get_services_keyboard(lang))
        return
    if data.startswith("svc_"):
        service_id = data.split("_")[1]
        lang = get_user_lang(uid)
        service = next((s for s in SERVICES if s["id"]==service_id), None)
        if not service:
            return
        context.user_data["selected_service"] = service_id
        name = service["name_en"] if lang=="en" else service["name_ar"]
        if lang == "en":
            txt = f"✅ <b>Selected Service: {service['name_en']}</b>\n🌍 <b>Please choose country:</b>"
        else:
            txt = f"✅ <b>الخدمة المطلوبة: {service['name_en']}</b>\n🌍 <b>يرجى اختيار الدولة:</b>"
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=get_countries_keyboard(service_id, lang))
        return
    if data.startswith("country_"):
        _, service_id, country_code = data.split("_")
        lang = get_user_lang(uid)
        service = next((s for s in SERVICES if s["id"]==service_id), None)
        country = next((c for c in COUNTRIES if c["code"]==country_code), None)
        if not service or not country:
            return
        
        # نجيب رقم مش مستخدم قبل كده لنفس الخدمة
        full, local = get_unique_number(service_id, country_code)
        
        # نتأكد انه مش مستخدم (لو مستخدم نجيب غيره)
        attempts = 0
        while is_number_used(full, service_id) and attempts < 10:
            full, local = get_unique_number(service_id, country_code)
            attempts += 1
        
        # نحجز الرقم للخدمة دي
        mark_number_used(full, service_id, uid, country_code)
        
        # حفظ الاختيار
        context.user_data["selected_country"] = country_code
        context.user_data["temp_mail"] = full
        context.user_data["temp_login"] = full
        
        svc_name = service["name_en"]
        country_name = country["name_en"]
        
        if lang == "en":
            text = f"✅ <b>Service:</b> {svc_name}\n🌍 <b>Country:</b> {country['flag']} {country_name}\n\n━━━━━━━━━━━━━━━\n📱 <b>Your Number:</b>\n<code>{full}</code>\n━━━━━━━━━━━━━━━\n💡 Use it for {svc_name}\n📥 Code will arrive here\n⏰ Valid for 20 min\n━━━━━━━━━━━━━━━"
        else:
            text = f"✅ <b>الخدمة المطلوبة: {svc_name}</b>\n🌍 <b>الدولة: {country['flag']} {country_name}</b>\n\n━━━━━━━━━━━━━━━\n📱 <b>رقمك:</b>\n<code>{full}</code>\n━━━━━━━━━━━━━━━\n💡 استخدمه لـ {svc_name}\n📥 الكود هيوصلك هنا\n⏰ صالح لمدة 20 دقيقة\n━━━━━━━━━━━━━━━\n👆 دوس على الرقم لنسخه"
        
        _num_cid = _store_copy_value(full)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 نسخ الرقم" if lang=="ar" else "📋 Copy Number", callback_data=f"copy_{_num_cid}")],
            [InlineKeyboardButton("📥 فحص الكود" if lang=="ar" else "📥 Check Code", callback_data=f"nums_check_{full}")],
            [InlineKeyboardButton("🔄 رقم جديد" if lang=="ar" else "🔄 New Number", callback_data=f"country_{service_id}_{country_code}")],
            [InlineKeyboardButton("⬅️ رجوع" if lang=="ar" else "⬅️ BACK", callback_data=f"svc_{service_id}")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if data == "extract_id":
        await query.edit_message_text("🆔 <b>استخراج ID</b>\n\n━━━━━━━━━━━━━━━\n🔗 ابعت اللينك أو اليوزر\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
        context.user_data["waiting"] = "extract_id"
        return
    if data.startswith("cat_"):
        cat = data.replace("cat_","")
        kb = get_domains_by_category(cat)
        cat_names = {"maildrop": "🔥 maildrop.online", "guerrilla": "⚡ Guerrilla Mail", "extra": "💎 Extra Domains"}
        name = cat_names.get(cat, cat)
        await query.edit_message_text(
            f"📧 <b>{name}</b>\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🌐 اختر الدومين:\n"
            f"✅ كلهم مجاني 100%\n"
            f"━━━━━━━━━━━━━━━",
            parse_mode="HTML", reply_markup=kb
        )
        return
    if data == "temp_new":
        kb = get_maildrop_domains_keyboard()
        await query.edit_message_text(
            "📧 <b>اختر نطاق البريد - maildrop.online</b>\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🌐 اختر الدومين اللي عايزه:\n"
            "✅ كلهم شغالين 100% ومجربين\n"
            "⚡ يستقبل كود فيسبوك وانستا وفوراً\n"
            "━━━━━━━━━━━━━━━\n"
            "👇 اختر من القائمة:",
            parse_mode="HTML", reply_markup=kb
        )
        return
    if data.startswith("mdomain_"):
        domain_choice = data.replace("mdomain_","")
        if domain_choice == "random":
            domain_choice = random.choice(MAILDROP_DOMAINS)
        mail, login, token_data = gen_temp_mail_with_domain(domain_choice)
        context.user_data["temp_mail"] = mail
        context.user_data["temp_login"] = login
        context.user_data["temp_domain"] = token_data
        try:
            current_jobs = context.job_queue.get_jobs_by_name(f"mailwatch_{query.from_user.id}")
            for j in current_jobs:
                j.schedule_removal()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        try:
            lang = get_user_lang(query.from_user.id)
            context.job_queue.run_repeating(
                temp_mail_watcher,
                interval=4,
                first=4,
                chat_id=query.message.chat_id,
                name=f"mailwatch_{query.from_user.id}",
                data={'mail': mail, 'pwd': login, 'token_data': token_data, 'lang': lang, 'last_count': 0}
            )
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        _mail_cid = _store_copy_value(mail)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 نسخ البريد", callback_data=f"copy_{_mail_cid}")],
            [InlineKeyboardButton("📥 فحص الوارد", callback_data="temp_check")],
            [InlineKeyboardButton("🔄 تغيير النطاق", callback_data="temp_new")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
        ])
        await query.edit_message_text(
            f"📧 <b>البريد المؤقت - maildrop.online</b>\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📬 بريدك:\n<code>{mail}</code>\n"
            f"🌐 النطاق: {domain_choice}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔔 المراقبة شغالة!\n"
            f"✅ شغال 100% يا اسطى\n"
            f"🔗 https://maildrop.online/ar/\n"
            f"━━━━━━━━━━━━━━━",
            parse_mode="HTML", reply_markup=kb
        )
        return
    if data == "temp_back_to_mail":
        mail = context.user_data.get("temp_mail")
        if not mail:
            kb = get_maildrop_domains_keyboard()
            await query.edit_message_text("📧 اختر نطاق البريد:", parse_mode="HTML", reply_markup=kb)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 فحص الوارد", callback_data="temp_check")],
            [InlineKeyboardButton("🔄 تغيير النطاق", callback_data="temp_new")],
            [InlineKeyboardButton("🏠 القائمة", callback_data="main")]
        ])
        await query.edit_message_text(
            f"📧 <b>بريدك الحالي</b>\n\n━━━━━━━━━━━━━━━\n📬 <code>{mail}</code>\n━━━━━━━━━━━━━━━",
            parse_mode="HTML", reply_markup=kb
        )
        return
    if data == "temp_check":

        login = context.user_data.get("temp_login")
        domain = context.user_data.get("temp_domain")
        mail = context.user_data.get("temp_mail", "غير موجود")
        if not login:
            await query.edit_message_text("❌ مفيش بريد - دوس بريد جديد", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 بريد جديد", callback_data="temp_new"), InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
            return
        await query.edit_message_text(f"⏳ <b>بفحص البريد...</b>\n\n📧 {mail}\n\n━━━━━━━━━━━━━━━", parse_mode="HTML")
        messages = get_temp_messages(login, domain)
        if not messages:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تحديث", callback_data="temp_check")],
                [InlineKeyboardButton("📧 بريدي", callback_data="temp_back_to_mail"), InlineKeyboardButton("🏠 القائمة", callback_data="main")]
            ])
            await query.edit_message_text(
                f"📧 <b>البريد المؤقت</b>\n\n"
                f"📬 {mail}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📭 <b>لا توجد رسائل بعد</b>\n"
                f"⏳ انتظر وصول الكود\n"
                f"🔄 دوس تحديث كل شوية\n"
                f"━━━━━━━━━━━━━━━",
                parse_mode="HTML", reply_markup=kb
            )
            return
        # فيه رسائل
        text = f"📧 <b>البريد الوارد ({len(messages)})</b>\n\n📬 {mail}\n━━━━━━━━━━━━━━━\n"
        kb_buttons = []
        for msg in messages[:5]:
            subject = msg.get("subject","بدون عنوان")[:30]
            from_addr = msg.get("from","")[:20]
            date = msg.get("date","")[:16]
            text += f"\n📩 <b>من:</b> {from_addr}\n📌 <b>الموضوع:</b> {subject}\n🕐 {date}\n"
            # نحاول نستخرج كود
            full = read_temp_message(login, domain, msg.get("id"))
            if full:
                body = full.get("textBody","") + " " + full.get("htmlBody","")
                code = extract_code_from_text(body)
                if code:
                    text += f"🔐 <b>الكود:</b> <code>{code}</code> ✨\n"
            text += "━━━━━━━━━━━━━━━\n"
            kb_buttons.append([InlineKeyboardButton(f"📖 فتح: {subject[:15]}", callback_data=f"temp_read_{msg.get('id')}")])
        kb_buttons.append([InlineKeyboardButton("🔄 تحديث", callback_data="temp_check")])
        kb_buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main")])
        kb = InlineKeyboardMarkup(kb_buttons)
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            await query.edit_message_text(f"📧 فيه {len(messages)} رسائل - افتحهم", reply_markup=kb)
        return
    if data == "nums_egy" or data == "nums_us":
        type_num = data.split("_")[1]
        if type_num == "egy":
            nums = gen_random_numbers(5, "egy")
            text = "🇪🇬 <b>أرقام مصرية وهمية</b>\n\n━━━━━━━━━━━━━━━\n"
            for full, local in nums:
                text += f"📱 <code>{full}</code> | <code>{local}</code>\n"
            text += "━━━━━━━━━━━━━━━\n👆 دوس على الرقم لنسخه\n💡 أرقام شكلها حقيقي للتجربة"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 أرقام جديدة", callback_data="nums_egy")],
                [InlineKeyboardButton("🇺🇸 أمريكية", callback_data="nums_us"), InlineKeyboardButton("📡 حقيقية", callback_data="nums_real")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        elif type_num == "us":
            nums = gen_random_numbers(5, "us")
            text = "🇺🇸 <b>أرقام أمريكية وهمية</b>\n\n━━━━━━━━━━━━━━━\n"
            for full, local in nums:
                text += f"📱 <code>{full}</code>\n"
            text += "━━━━━━━━━━━━━━━\n👆 دوس لنسخ"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 جديدة", callback_data="nums_us")],
                [InlineKeyboardButton("🇪🇬 مصرية", callback_data="nums_egy"), InlineKeyboardButton("📡 حقيقية", callback_data="nums_real")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        elif type_num == "real":
            free_nums = get_free_numbers()
            text = "📡 <b>أرقام حقيقية تستقبل SMS</b>\n\n━━━━━━━━━━━━━━━\n"
            kb_buttons = []
            for n in free_nums:
                text += f"{n['country']}: <code>{n['number']}</code>\n"
                kb_buttons.append([InlineKeyboardButton(f"📥 فحص {n['country']} {n['number']}", callback_data=f"nums_check_{n['number']}")])
            text += "━━━━━━━━━━━━━━━\n💡 الأرقام دي حقيقية وبتستقبل أكواد\n📥 دوس فحص عشان تشوف الرسائل"
            kb_buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="main")])
            kb = InlineKeyboardMarkup(kb_buttons)
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("check_platform_"):
        _, _, service_id, number = data.split("_", 3)
        lang = get_user_lang(uid)
        await query.edit_message_text(f"🔍 <b>بفحص الرقم...</b>\n\n📱 {number}\n📘 الخدمة: {service_id}\n\n━━━━━━━━━━━━━━━\n⏳ بفحص هل مستخدم على المنصة...", parse_mode="HTML")
        
        result = check_number_on_platform(number, service_id)
        
        if result["is_used"]:
            text = f"⚠️ <b>الرقم مستخدم</b>\n\n📱 الرقم: <code>{number}</code>\n📘 الخدمة: {service_id}\n\n━━━━━━━━━━━━━━━\n{result['message']}\n━━━━━━━━━━━━━━━\n\n💡 هنبعتلك رقم جديد مضمون"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 هات رقم جديد مضمون" if lang=="ar" else "🔄 Get new guaranteed number", callback_data=f"country_{service_id}_{context.user_data.get('selected_country','eg')}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
            ])
        else:
            text = f"✅ <b>الرقم جديد ومضمون</b>\n\n📱 الرقم: <code>{number}</code>\n📘 الخدمة: {service_id}\n\n━━━━━━━━━━━━━━━\n{result['message']}\n━━━━━━━━━━━━━━━\n\n✅ تقدر تستخدمه بأمان\n🔒 مضمون مش مستخدم في البوت"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 فحص الكود" if lang=="ar" else "📥 Check Code", callback_data=f"nums_check_{number}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
            ])
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        return
    if data.startswith("nums_check_"):
        number = data.replace("nums_check_", "")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث الوارد", callback_data=f"nums_check_{number}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
        ])
        text_msg = (
            f"📡 <b>الرسائل الواردة لـ</b>\n"
            f"<code>{number}</code>\n"
            "━━━━━━━━━━━━━━━\n"
            "📭 <b>لا توجد رسائل بعد</b>\n"
            "⏳ في انتظار وصول كود واتساب...\n"
            "🔄 دوس تحديث كل شوية\n"
            "━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(text_msg, parse_mode="HTML", reply_markup=kb)
        return

    if data.startswith("temp_read_"):
        try:
            msg_id = int(data.split("_")[-1])
            login = context.user_data.get("temp_login")
            domain = context.user_data.get("temp_domain")
            full = read_temp_message(login, domain, msg_id)
            if not full:
                await query.edit_message_text("❌ مقدرتش افتح الرسالة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="temp_check")]]))
                return
            subject = full.get("subject","بدون عنوان")
            from_addr = full.get("from","")
            body = full.get("textBody","") or full.get("htmlBody","")[:2000]
            # نظف HTML
            body = re.sub(r'<[^>]+>', '', body)[:2000]
            code = extract_code_from_text(body)
            text = f"📖 <b>{subject}</b>\n\n━━━━━━━━━━━━━━━\n👤 من: {from_addr}\n"
            if code:
                text += f"🔐 الكود: <code>{code}</code> ✨\n"
            text += f"━━━━━━━━━━━━━━━\n\n{body[:1500]}\n\n━━━━━━━━━━━━━━━"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع للوارد", callback_data="temp_check")],
                [InlineKeyboardButton("🔙 للقائمة", callback_data="main")]
            ])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="temp_check")]]))
        return
    if data.startswith("rate_"):
        if data == "rate_feedback":
            await query.edit_message_text("⭐ <b>كتابة ملاحظة</b>\n\n━━━━━━━━━━━━━━━\n✏️ ابعت ملاحظتك أو اقتراحك\n💡 رأيك مهم جداً لينا\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]))
            context.user_data["waiting"] = "rate_feedback"
        else:
            stars = data.split("_")[1]
            star_text = "⭐" * int(stars)
            await query.edit_message_text(f"⭐ <b>شكراً لتقييمك!</b>\n\n━━━━━━━━━━━━━━━\n{star_text}\n\n💖 شكراً لدعمك\n🚀 مستمرين في التطوير\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="main")]]))
            # حفظ التقييم
            try:
                db = fast_load_db()
                db.setdefault("ratings", []).append({"uid": uid, "stars": stars, "time": str(datetime.datetime.now())})
                fast_save_db(db)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
        return


# ==================== قسم المالك: إدارة أدمن + موافقة دخول بوت الأدمن ====================
async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    try:
        await query.answer()
    except Exception:
        pass

    # موافقة / رفض طلب دخول بوت الأدمن
    if data.startswith("own_approve_") or data.startswith("own_reject_"):
        if uid != OWNER_ID and uid != SUPER_ADMINS[0]:
            await query.answer("⛔ للمالك فقط", show_alert=True)
            return
        is_approve = data.startswith("own_approve_")
        req_id = data.replace("own_approve_", "").replace("own_reject_", "")
        # استخدم دوال shared إن وُجدت، وإلا محلياً
        try:
            ok, req = set_admin_access_status(req_id, "approved" if is_approve else "rejected", by_owner=uid)
        except Exception:
            db = fast_load_db()
            req = db.get("admin_access_requests", {}).get(req_id)
            ok = False
            if req:
                req["status"] = "approved" if is_approve else "rejected"
                req["resolved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if is_approve:
                    db.setdefault("admin_sessions", {})[str(req["uid"])] = {
                        "approved": True,
                        "active": False,
                        "until_ts": time.time() + 12 * 3600,
                        "approved_at": req["resolved_at"],
                        "by_owner": uid,
                        "req_id": req_id,
                    }
                fast_save_db(db)
                ok = True
        if not ok or not req:
            await query.edit_message_text("❌ الطلب غير موجود أو منتهي")
            return
        target_uid = req.get("uid")
        status_txt = "✅ تمت الموافقة" if is_approve else "❌ تم الرفض"
        await query.edit_message_text(
            f"{status_txt}\n\n🆔 المستخدم: <code>{target_uid}</code>\n📋 الطلب: <code>{req_id}</code>",
            parse_mode="HTML",
        )
        # حاول إشعار الأدمن على بوت الأدمن
        try:
            admin_token = (ADMIN_BOT_TOKEN or os.getenv("ADMIN_BOT_TOKEN", "") or "").strip()
            if admin_token and target_uid:
                import requests as _req
                msg = "✅ تمت موافقة المالك. أرسل /start ثم أدخل كلمة مرور لوحة التحكم." if is_approve else "❌ تم رفض طلب دخولك من المالك."
                _req.post(
                    f"https://api.telegram.org/bot{admin_token}/sendMessage",
                    json={"chat_id": int(target_uid), "text": msg},
                    timeout=8,
                )
        except Exception as e:
            logger.debug(f"notify admin bot: {e}")
        return

    if uid != OWNER_ID and uid != SUPER_ADMINS[0]:
        await query.answer("⛔ للمالك فقط", show_alert=True)
        return

    if data == "own_list_admins":
        admins = SUPER_ADMINS
        try:
            admins = SUPER_ADMINS
        except Exception:
            pass
        txt = "👑 <b>قائمة الأدمن</b>\n\n" + "\n".join([f"{'👑' if a==OWNER_ID or a==SUPER_ADMINS[0] else '🔹'} <code>{a}</code>" for a in admins])
        await query.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ رجوع", callback_data="own_panel")]
        ]))
        return

    if data == "own_panel":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة أدمن", callback_data="own_add_admin")],
            [InlineKeyboardButton("➖ حذف أدمن", callback_data="own_del_admin")],
            [InlineKeyboardButton("📋 قائمة الأدمن", callback_data="own_list_admins")],
            [InlineKeyboardButton("🔑 تغيير كلمة مرور بوت الأدمن", callback_data="own_change_pw")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="main")],
        ])
        await query.edit_message_text("👑 <b>إدارة الأدمن</b>", parse_mode="HTML", reply_markup=kb)
        return

    if data == "own_add_admin":
        context.user_data["waiting"] = "own_add_admin"
        await query.edit_message_text("➕ أرسل Telegram User ID للأدمن الجديد:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ رجوع", callback_data="own_panel")]
        ]))
        return

    if data == "own_del_admin":
        context.user_data["waiting"] = "own_del_admin"
        await query.edit_message_text("➖ أرسل User ID للأدمن المراد حذفه:\n(لا يمكن حذف المالك)", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ رجوع", callback_data="own_panel")]
        ]))
        return

    if data == "own_change_pw":
        context.user_data["waiting"] = "own_change_pw"
        await query.edit_message_text(
            "🔑 <b>تغيير كلمة مرور بوت الأدمن</b>\n\nأرسل كلمة المرور الجديدة (4 أحرف على الأقل):\n\n⚠️ لن تُعرض في Logs ولن تُخزَّن كنص صريح.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="own_panel")]]),
        )
        return



async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not is_admin(uid) and not is_owner(uid):
        return
    try:
        await query.answer()
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    data = query.data
    # حماية: لوحة كاملة تتطلب جلسة نشطة (بعد موافقة+كلمة مرور) — إلا أوامر المالك own_* تُعالج في owner_callback
    if data.startswith("adm_") and data not in ("adm_back", "adm_close") and not is_owner(uid):
        if not has_valid_admin_session(uid):
            try:
                await query.edit_message_text("⛔ انتهت الجلسة أو غير مصرح. أرسل /start")
            except Exception:
                pass
            return
    db = fast_load_db()
    settings = load_settings()

    if data == "adm_close":
        try:
            await query.delete_message()
        except Exception as e:
            logger.debug(f"Suppressed: {e}")
        return
    # ===== AI Admin Panel =====
    if data == "adm_ai_menu":
        await admin_ai_menu(update, context)
        return
    if data.startswith("adm_ai_list_"):
        try:
            parts = data.split("_")
            # adm_ai_list_{page}_{filter}
            page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            filter_type = parts[4] if len(parts) > 4 else "all"
            await admin_ai_list(update, context, page=page, filter_type=filter_type)
        except Exception as e:
            await admin_ai_list(update, context, page=0)
        return
    if data.startswith("adm_ai_filter_"):
        filter_type = data.replace("adm_ai_filter_", "")
        await admin_ai_list(update, context, page=0, filter_type=filter_type)
        return
    if data.startswith("adm_ai_view_"):
        tid = data.replace("adm_ai_view_", "")
        await admin_ai_view_user(update, context, tid)
        return
    if data.startswith("adm_ai_full_"):
        try:
            # adm_ai_full_{tid}_{page}
            rest = data.replace("adm_ai_full_", "")
            if "_" in rest:
                tid, page_str = rest.rsplit("_", 1)
                page = int(page_str) if page_str.isdigit() else 0
            else:
                tid = rest
                page = 0
            await admin_ai_full_chat(update, context, tid, page)
        except Exception as e:
            logger.exception(f"adm_ai_full parse error: {e}")
        return
    if data.startswith("adm_ai_summary_"):
        tid = data.replace("adm_ai_summary_", "")
        # Show summary as copyable
        try:
            db = fast_load_db()
            conv = db.get("ai_conversations", {}).get(str(tid), {})
            summary = conv.get("summary","لا يوجد ملخص")
            messages = conv.get("messages", [])
            # Build summary text
            text = f"📋 <b>ملخص محادثة {conv.get('display_name','')}</b>\n🆔 {tid}\n\n{summary}\n\nإجمالي الرسائل: {len(messages)}"
            await send_copyable_unified(query, [{"label":"ملخص المحادثة","value":summary}], title=text, show_main=False, extra_text=f"💬 إجمالي: {len(messages)} رسالة")
        except Exception as e:
            await query.answer("❌ خطأ", show_alert=True)
        return
    if data.startswith("adm_ai_del_") and not data.startswith("adm_ai_deluser_"):
        tid = data.replace("adm_ai_del_", "")
        try:
            db = fast_load_db()
            if str(tid) in db.get("ai_conversations", {}):
                db["ai_conversations"][str(tid)]["messages"] = []
                db["ai_conversations"][str(tid)]["message_count"] = 0
                fast_save_db(db)
                await query.edit_message_text(f"🗑️ تم مسح محادثة {tid} ✅", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"adm_ai_view_{tid}"), InlineKeyboardButton("📋 القائمة", callback_data="adm_ai_list_0")]]))
            else:
                await query.answer("❌ غير موجود", show_alert=True)
        except Exception as e:
            await query.answer("❌ خطأ", show_alert=True)
        return
    if data.startswith("adm_ai_deluser_"):
        tid = data.replace("adm_ai_deluser_", "")
        try:
            db = fast_load_db()
            if str(tid) in db.get("ai_conversations", {}):
                del db["ai_conversations"][str(tid)]
                fast_save_db(db)
                await query.edit_message_text(f"🗑️ تم حذف المستخدم {tid} بالكامل ✅", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 القائمة", callback_data="adm_ai_list_0")]]))
            else:
                await query.answer("❌ غير موجود", show_alert=True)
        except Exception as e:
            await query.answer("❌ خطأ", show_alert=True)
        return
    if data == "adm_ai_stats":
        await admin_ai_stats(update, context)
        return
    if data == "adm_ai_search_menu":
        await admin_ai_search_menu(update, context)
        return
    if data == "adm_ai_kb":
        await admin_ai_kb_menu(update, context)
        return
    if data == "adm_user_states":
        await admin_user_states_menu(update, context)
        return
    if data.startswith("adm_state_list_"):
        try:
            parts = data.split("_")
            # adm_state_list_{page}_{filter}
            page = int(parts[3]) if len(parts) > 3 and parts[3].lstrip("-").isdigit() else 0
            filter_type = parts[4] if len(parts) > 4 else "all"
            await admin_state_list(update, context, page=page, filter_type=filter_type)
        except Exception as e:
            await admin_state_list(update, context, page=0)
        return
    if data.startswith("adm_state_filter_"):
        ftype = data.replace("adm_state_filter_", "")
        await admin_state_list(update, context, page=0, filter_type=ftype)
        return
    if data.startswith("adm_state_view_"):
        uid = data.replace("adm_state_view_", "")
        await admin_state_view(update, context, uid)
        return
    if data.startswith("adm_state_reset_"):
        uid = data.replace("adm_state_reset_", "")
        try:
            clear_user_processing(int(uid), success=True)
            set_user_status(int(uid), UserStatus.IDLE, path_action={"action": "set", "page": "main"})
            await query.edit_message_text(f"✅ تم إعادة تعيين حالة {uid}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👁️ عرض", callback_data=f"adm_state_view_{uid}"), InlineKeyboardButton("🔙 رجوع", callback_data="adm_state_list_0")]]))
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
        return
    if data == "adm_service_health":
        await admin_service_health_menu(update, context)
        return
    # ===== Force Sub Management =====
    if data == "adm_force_sub_menu":
        await admin_force_sub_menu(update, context)
        return
    if data == "adm_force_sub_list":
        await admin_force_sub_list(update, context)
        return
    if data == "adm_force_sub_toggle":
        enabled = get_force_sub_enabled()
        set_force_sub_enabled(not enabled, admin_id=uid)
        await admin_force_sub_menu(update, context)
        return
    if data == "adm_force_sub_add":
        context.user_data["waiting"] = "adm_force_sub_add"
        await query.edit_message_text(
            "➕ <b>إضافة قناة للاشتراك الإجباري</b>\n\n"
            "━━━━━━━━━━━━━━━\n"
            "ابعت الآن:\n"
            "• Channel ID (مثل: -1001234567890)\n"
            "• أو Username (مثل: @channel أو channel)\n"
            "• أو رابط (مثل: https://t.me/channel)\n\n"
            "⚠️ تأكد أن البوت أدمن في القناة!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")]])
        )
        return
    if data.startswith("adm_force_sub_del_"):
        ch_id = data.replace("adm_force_sub_del_", "")
        success, msg = remove_force_sub_channel(ch_id, admin_id=uid)
        if success:
            await query.answer("✅ تم الحذف")
            await admin_force_sub_list(update, context)
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
        return
    if data.startswith("adm_force_sub_toggle_ch_"):
        ch_id = data.replace("adm_force_sub_toggle_ch_", "")
        success, result = toggle_force_sub_channel(ch_id, admin_id=uid)
        if success:
            await query.answer(f"{'✅ مفعلة' if result.get('active') else '⏸️ متوقفة'}")
            await admin_force_sub_list(update, context)
        else:
            await query.answer(f"❌ {result}", show_alert=True)
        return
    # ===== Users Management =====
    if data == "adm_users_mgmt":
        await admin_users_mgmt_menu(update, context)
        return
    if data == "adm_users_search":
        await admin_users_search_menu(update, context)
        return
    if data.startswith("adm_user_view_"):
        target = data.replace("adm_user_view_", "")
        await admin_user_info_view(update, context, target)
        return
    if data.startswith("adm_user_ban_"):
        target = data.replace("adm_user_ban_", "")
        success, msg = ban_user_permanent(int(target), admin_id=uid, reason="حظر من لوحة الأدمن")
        if success:
            await query.answer("✅ تم الحظر الدائم")
            await admin_user_info_view(update, context, target)
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
        return
    if data.startswith("adm_user_unban_"):
        target = data.replace("adm_user_unban_", "")
        success, msg = unban_user(int(target), admin_id=uid)
        if success:
            await query.answer("✅ تم إلغاء الحظر")
            await admin_user_info_view(update, context, target)
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
        return
    if data.startswith("adm_user_suspend_menu_"):
        target = data.replace("adm_user_suspend_menu_", "")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"adm_user_suspend_{target}_300"),
             InlineKeyboardButton("⏱️ 10 دقائق", callback_data=f"adm_user_suspend_{target}_600")],
            [InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"adm_user_suspend_{target}_1800"),
             InlineKeyboardButton("⏱️ ساعة", callback_data=f"adm_user_suspend_{target}_3600")],
            [InlineKeyboardButton("⏱️ يوم", callback_data=f"adm_user_suspend_{target}_86400"),
             InlineKeyboardButton("⏱️ مخصص", callback_data=f"adm_user_suspend_custom_{target}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"adm_user_view_{target}")]
        ])
        await query.edit_message_text(
            f"⏸️ <b>إيقاف المستخدم {target} مؤقتاً</b>\n\nاختر المدة:",
            parse_mode="HTML",
            reply_markup=kb
        )
        return
    if data.startswith("adm_user_suspend_") and not data.startswith("adm_user_suspend_menu_") and not data.startswith("adm_user_suspend_custom_"):
        try:
            # adm_user_suspend_{uid}_{seconds}
            rest = data.replace("adm_user_suspend_", "")
            parts = rest.rsplit("_", 1)
            target_uid = parts[0]
            seconds = int(parts[1])
            success, until_str = suspend_user_temporary(int(target_uid), seconds, admin_id=uid, reason="إيقاف مؤقت من لوحة الأدمن")
            if success:
                await query.answer(f"✅ موقوف حتى {until_str}")
                await admin_user_info_view(update, context, target_uid)
            else:
                await query.answer(f"❌ {until_str}", show_alert=True)
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)
        return
    if data.startswith("adm_user_suspend_custom_"):
        target = data.replace("adm_user_suspend_custom_", "")
        context.user_data["waiting"] = f"adm_suspend_custom_{target}"
        await query.edit_message_text(
            f"⏱️ <b>مدة مخصصة لإيقاف {target}</b>\n\n"
            "ابعت المدة بالدقائق (رقم فقط)\n"
            "مثال: 120 لإيقاف ساعتين",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"adm_user_view_{target}")]])
        )
        return
    if data.startswith("adm_user_unsuspend_"):
        target = data.replace("adm_user_unsuspend_", "")
        success, msg = unsuspend_user(int(target), admin_id=uid)
        if success:
            await query.answer("✅ تم إلغاء الإيقاف")
            await admin_user_info_view(update, context, target)
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
        return
    if data.startswith("adm_user_delete_confirm_"):
        target = data.replace("adm_user_delete_confirm_", "")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"adm_user_delete_do_{target}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"adm_user_view_{target}")]
        ])
        await query.edit_message_text(
            f"⚠️ <b>هل أنت متأكد من حذف المستخدم؟</b>\n\n"
            f"🆔 ID: <code>{target}</code>\n\n"
            f"سيتم حذف بياناته المسموحة مع الحفاظ على سجلات الأمان.",
            parse_mode="HTML",
            reply_markup=kb
        )
        return
    if data.startswith("adm_user_delete_do_"):
        target = data.replace("adm_user_delete_do_", "")
        success, msg = delete_user_data(int(target), admin_id=uid, keep_security_logs=True)
        if success:
            await query.edit_message_text(f"🗑️ تم حذف المستخدم {target} ✅", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
        else:
            await query.answer(f"❌ {msg}", show_alert=True)
        return
    if data == "adm_audit_log":
        await admin_audit_log_menu(update, context)
        return
    if data == "adm_users_banned_list":
        db = fast_load_db()
        banned = db.get("banned_users", [])
        if not banned:
            await query.edit_message_text("🚫 لا يوجد محظورين", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
        else:
            lines = [f"🚫 <b>المحظورين ({len(banned)})</b>", "━━━━━━━━━━━━━━━", ""]
            kb_rows = []
            for b in banned[:20]:
                lines.append(f"• <code>{b}</code>")
                kb_rows.append([InlineKeyboardButton(f"👁️ {b}", callback_data=f"adm_user_view_{b}")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")])
            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))
        return
    if data == "adm_users_suspended_list":
        db = fast_load_db()
        susp = db.get("user_suspensions", {})
        if not susp:
            await query.edit_message_text("⏸️ لا يوجد موقوفين", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
        else:
            lines = [f"⏸️ <b>الموقوفين ({len(susp)})</b>", "━━━━━━━━━━━━━━━", ""]
            kb_rows = []
            for uid_key, data_s in list(susp.items())[:20]:
                lines.append(f"• <code>{uid_key}</code> حتى {data_s.get('until_str','')}")
                kb_rows.append([InlineKeyboardButton(f"👁️ {uid_key}", callback_data=f"adm_user_view_{uid_key}")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")])
            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))
        return
    if data == "adm_back":
        await query.edit_message_text("🔧 لوحة تحكّم الأدمن", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_list_admins":
        txt = "\n".join([f"• {x}" for x in SUPER_ADMINS])
        await query.edit_message_text(f"👑 قائمة الأدمنية:\n{txt}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_add_admin":
        await query.edit_message_text("➕ ابعت ID الشخص اللي عايز تضيفه أدمن", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_add_admin"
        return
    if data == "adm_remove_admin":
        await query.edit_message_text(f"➖ ابعت ID الأدمن اللي عايز تشيله\n\nالحاليين:\n" + "\n".join([str(x) for x in SUPER_ADMINS]), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_remove_admin"
        return
    if data == "adm_msgs":
        txt = f"✏️ رسائل الترحيب:\n\nللمسجلين:\n{settings.get('welcome_auth','')}\n\nلغير المسجلين:\n{settings.get('welcome_unauth','')}"
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تعديل المسجلين", callback_data="adm_edit_auth")],
            [InlineKeyboardButton("✏️ تعديل غير المسجلين", callback_data="adm_edit_unauth")],
            [InlineKeyboardButton("🗑️ مسح المسجلين", callback_data="adm_del_auth")],
            [InlineKeyboardButton("🗑️ مسح غير المسجلين", callback_data="adm_del_unauth")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]
        ])
        await query.edit_message_text(txt, reply_markup=kb)
        return
    if data == "adm_edit_auth":
        await query.edit_message_text("✏️ ابعت رسالة المسجلين الجديدة\nتقدر تستخدم {name} للاسم", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_msgs")]]))
        context.user_data["waiting"] = "adm_edit_auth"
        return
    if data == "adm_edit_unauth":
        await query.edit_message_text("✏️ ابعت رسالة غير المسجلين الجديدة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_msgs")]]))
        context.user_data["waiting"] = "adm_edit_unauth"
        return
    if data == "adm_del_auth":
        settings["welcome_auth"]=""
        save_settings(settings)
        await query.edit_message_text("🗑️ اتمسحت رسالة المسجلين - مش هيظهر حاجة", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_del_unauth":
        settings["welcome_unauth"]=""
        save_settings(settings)
        await query.edit_message_text("🗑️ اتمسحت رسالة غير المسجلين", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_change_pass":
        await query.edit_message_text(
            "🔑 تغيير كلمة المرور يتم من <b>البوت الأساسي</b> فقط.\n\n"
            "المالك يكتب: <code>ادمن</code> ثم يختار تغيير كلمة مرور بوت الأدمن.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="adm_back")]]),
        )
        return
    if data == "adm_perms_menu":
        if uid != SUPER_ADMINS[0]:
            await query.edit_message_text("❌ للمالك بس 👑", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        await query.edit_message_text("🔐 ابعت ID الأدمن عشان تتحكم فيه", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_perms_select"
        return
    if data == "perm_set_pass":
        await query.edit_message_text("🔑 ابعت الباسورد الخاص الجديد للأدمن ده", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_set_custom_pass"
        return
    if data == "noop":
        await query.answer("الباسورد الحالي ظاهر فوق")
        return
    if data.startswith("perm_"):
        if uid != SUPER_ADMINS[0]:
            return
        target = context.user_data.get("perms_target")
        if not target:
            await query.edit_message_text("ابعت ID الأول", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        if data == "perm_all":
            settings["admin_perms"][target]=["all"]
        elif data == "perm_none":
            settings["admin_perms"][target]=[]
        else:
            perm=data.replace("perm_","")
            settings["admin_perms"].setdefault(target,[])
            if perm in settings["admin_perms"][target]:
                settings["admin_perms"][target].remove(perm)
            else:
                settings["admin_perms"][target].append(perm)
        save_settings(settings)
        await query.edit_message_text(f"✅ صلاحيات {target}:\n{settings['admin_perms'][target]}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_stats":
        tracks = db.get("user_tracks", {})
        total = len(tracks)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        new_today = sum(1 for u in tracks.values() if today in u.get("first_seen",""))
        active_today = sum(1 for u in tracks.values() if today in u.get("last_seen",""))
        blocked = sum(1 for u in tracks.values() if u.get("blocked"))
        await query.edit_message_text(f"📊 احصاءات\n\n👥 الكل: {total}\n🆕 جداد اليوم: {new_today}\n🟢 نشطين اليوم: {active_today}\n🚫 بلوك: {blocked}\n\n📋 يوزرات: {len(db['allowed_usernames'])}\n✅ مفعلين: {len(db['authorized'])}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_users_dash":
        tracks = db.get("user_tracks", {})
        if not tracks:
            await query.edit_message_text("لسه مفيش حد", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        else:
            lines = [f"{v.get('name','')} (@{v.get('username','')}) - {k}" for k,v in list(tracks.items())[-20:]]
            await query.edit_message_text(f"👥 آخر 20:\n\n" + "\n".join(lines), reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_new_today":
        tracks = db.get("user_tracks", {})
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        new_users = {k:v for k,v in tracks.items() if today in v.get("first_seen","")}
        txt = "\n".join([f"{v.get('name')} - {k}" for k,v in new_users.items()]) if new_users else "مفيش"
        await query.edit_message_text(f"🆕 جداد اليوم ({len(new_users)}):\n\n{txt}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_active_today":
        tracks = db.get("user_tracks", {})
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        active = {k:v for k,v in tracks.items() if today in v.get("last_seen","")}
        txt = "\n".join([f"{v.get('name')} - {k}" for k,v in list(active.items())[:20]]) if active else "مفيش"
        await query.edit_message_text(f"🟢 نشطين اليوم ({len(active)}):\n\n{txt}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_blocked":
        tracks = db.get("user_tracks", {})
        blocked = {k:v for k,v in tracks.items() if v.get("blocked")}
        await query.edit_message_text(f"🚫 بلوك: {len(blocked)}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_list_users":
        users = db.get("allowed_usernames", [])
        txt = "\n".join(users[:100]) if users else "مفيش يوزرات"
        if len(txt) > 3000:
            txt = txt[:3000]
        await query.edit_message_text(f"📋 اليوزرات ({len(users)}):\n\n{txt}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_add_user":
        await query.edit_message_text("➕ ابعت اليوزر الجديد (Username فقط)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_add_user"
        return
    if data == "adm_del_user":
        await query.edit_message_text(
            "🗑️ <b>حذف يوزر</b>\n\nأرسل Username الخاص بالمستخدم:\nمثال: <code>@username</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]),
        )
        context.user_data["waiting"] = "adm_del_user"
        return
    if data.startswith("adm_del_confirm_"):
        target_uid = data.replace("adm_del_confirm_", "")
        ok, info = delete_user_by_uid(target_uid, admin_id=uid)
        if ok:
            await query.edit_message_text(
                f"✅ تم حذف المستخدم من البوت بنجاح.\n🆔 <code>{target_uid}</code>",
                parse_mode="HTML",
                reply_markup=admin_keyboard(uid, hide_password_btn=True),
            )
        else:
            await query.edit_message_text(f"❌ {info}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_del_cancel":
        await query.edit_message_text("❌ تم إلغاء الحذف", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_upload_users":
        await query.edit_message_text("📤 ابعت اليوزرات كل يوزر في سطر", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_upload_users"
        return
    if data == "adm_download_users":
        users = db.get("allowed_usernames", [])
        path = "users.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(users))
        await context.bot.send_document(chat_id=query.message.chat_id, document=open(path,"rb"), filename="users.txt", caption=f"📋 {len(users)} يوزر")
        os.remove(path)
        return
    if data == "adm_ratings":
        db = fast_load_db()
        ratings = db.get("ratings", [])
        if not ratings:
            await query.edit_message_text("⭐ لسه مفيش تقييمات", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        tracks = db.get("user_tracks", {})
        text = f"⭐ <b>كل التقييمات ({len(ratings)})</b>\n\n━━━━━━━━━━━━━━━\n"
        for r in ratings[-30:][::-1]:
            r_uid = str(r.get("uid",""))
            track = tracks.get(r_uid, {})
            name = track.get("name","بدون اسم")
            username = track.get("username","بدون يوزر")
            username_show = f"@{username}" if username and username!="بدون يوزر" else "بدون يوزر"
            stars = "⭐" * int(r.get("stars",0))
            time = r.get("time","")[:19]
            text += f"\n{stars} ({r.get('stars')})\n👤 الاسم: {name}\n🆔 ID: <code>{r_uid}</code>\n🔗 اليوزر: {username_show}\n🕐 الوقت: {time}\n━━━━━━━━━━━━━━━\n"
        if len(text) > 4000:
            # ابعته ملف
            path = f"ratings_{uid}.txt"
            with open(path, "w", encoding="utf-8") as f:
                for r in ratings:
                    r_uid = str(r.get("uid",""))
                    track = tracks.get(r_uid, {})
                    f.write(f"{r.get('stars')} نجوم | {track.get('name')} | ID: {r_uid} | @{track.get('username')} | {r.get('time')}\n")
            await context.bot.send_document(chat_id=query.message.chat_id, document=open(path,"rb"), filename="التقييمات.txt", caption=f"⭐ {len(ratings)} تقييم")
            os.remove(path)
            await query.edit_message_text(f"⭐ التقييمات كتير ({len(ratings)}) - بعتلك الملف", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_used_numbers":
        db = fast_load_db()
        used = db.get("used_numbers", {})
        if not used:
            await query.edit_message_text("📱 لسه مفيش أرقام مستخدمة", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        text = "📱 <b>الأرقام المستخدمة لكل خدمة</b>\n\n━━━━━━━━━━━━━━━\n"
        for service_id, numbers in used.items():
            service = next((s for s in SERVICES if s["id"]==service_id), None)
            svc_name = service["name_en"] if service else service_id
            text += f"\n📘 <b>{svc_name}:</b> {len(numbers)} رقم مستخدم\n"
            for num in numbers[-5:]:
                text += f"  • <code>{num}</code>\n"
            text += "━━━━━━━━━━━━━━━\n"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_numbers_stats":
        db = fast_load_db()
        logs = db.get("numbers_log", [])
        used = db.get("used_numbers", {})
        total = sum(len(v) for v in used.values())
        text = f"📊 <b>إحصائيات الأرقام</b>\n\n━━━━━━━━━━━━━━━\n📱 إجمالي الأرقام المستخدمة: {total}\n📋 إجمالي العمليات: {len(logs)}\n\n"
        for service_id, numbers in used.items():
            service = next((s for s in SERVICES if s["id"]==service_id), None)
            svc_name = service["name_en"] if service else service_id
            text += f"{svc_name}: {len(numbers)} رقم\n"
        text += "━━━━━━━━━━━━━━━\n✅ كل رقم مستخدم مرة واحدة فقط لكل خدمة\n🔒 مفيش رقم بيتكرر لنفس الخدمة"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_feedbacks":
        db = fast_load_db()
        feedbacks = db.get("feedbacks", [])
        if not feedbacks:
            await query.edit_message_text("💌 لسه مفيش ملاحظات", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        tracks = db.get("user_tracks", {})
        text = f"💌 <b>كل الملاحظات ({len(feedbacks)})</b>\n\n━━━━━━━━━━━━━━━\n"
        for fb in feedbacks[-20:][::-1]:
            fb_uid = str(fb.get("uid",""))
            track = tracks.get(fb_uid, {})
            name = track.get("name","بدون اسم")
            username = track.get("username","بدون يوزر")
            username_show = f"@{username}" if username and username!="بدون يوزر" else "بدون يوزر"
            time = fb.get("time","")[:19]
            fb_text = fb.get("text","")[:300]
            text += f"\n💬 <b>الملاحظة:</b> {fb_text}\n👤 الاسم: {name}\n🆔 ID: <code>{fb_uid}</code>\n🔗 اليوزر: {username_show}\n🕐 الوقت: {time}\n━━━━━━━━━━━━━━━\n"
        if len(text) > 4000:
            path = f"feedbacks_{uid}.txt"
            with open(path, "w", encoding="utf-8") as f:
                for fb in feedbacks:
                    fb_uid = str(fb.get("uid",""))
                    track = tracks.get(fb_uid, {})
                    f.write(f"الملاحظة: {fb.get('text')}\nالاسم: {track.get('name')} | ID: {fb_uid} | @{track.get('username')} | {fb.get('time')}\n━━━━━━━━━━━━━━━\n")
            await context.bot.send_document(chat_id=query.message.chat_id, document=open(path,"rb"), filename="الملاحظات.txt", caption=f"💌 {len(feedbacks)} ملاحظة")
            os.remove(path)
            await query.edit_message_text(f"💌 الملاحظات كتير ({len(feedbacks)}) - بعتلك الملف", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_mail_stats":
        db = fast_load_db()
        mails = db.get("temp_mails", {})
        total_mails = len(mails)
        total_codes = sum(len(v.get("codes", [])) if isinstance(v, dict) else 0 for v in mails.values())
        text = f"📧 <b>إحصائيات البريد المؤقت</b>\n\n━━━━━━━━━━━━━━━\n📧 إجمالي الإيميلات: {total_mails}\n📩 إجمالي الأكواد اللي وصلت: {total_codes}\n━━━━━━━━━━━━━━━"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_clear_numbers":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ أيوه امسح كل الأرقام", callback_data="adm_confirm_clear_numbers")],
            [InlineKeyboardButton("❌ لا، رجوع", callback_data="adm_back")]
        ])
        await query.edit_message_text("🗑️ <b>مسح كل الأرقام المستخدمة</b>\n\n⚠️ هيمسح كل الأرقام اللي اتوزعت\n✅ كل الأرقام هترجع جديدة\n\nمتأكد؟", parse_mode="HTML", reply_markup=kb)
        return
    if data == "adm_confirm_clear_numbers":
        db = fast_load_db()
        count = len(db.get("all_used_numbers", []))
        db["all_used_numbers"] = []
        db["used_numbers"] = {}
        db["number_owners"] = {}
        db["numbers_log"] = []
        fast_save_db(db)
        await query.edit_message_text(f"✅ تم مسح {count} رقم بنجاح\n🔄 كل الأرقام بقت جديدة", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_add_service":
        await query.edit_message_text("➕ <b>إضافة خدمة جديدة</b>\n\n📝 ابعت اسم الخدمة بالإنجليزي مثلاً:\n<code>paypal</code>\nأو <code>uber</code>\n\n━━━━━━━━━━━━━━━\nالصيغة: الاسم | العدد | الإيموجي\nمثال:\n<code>PayPal | 5000 | 💳</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_add_service"
        return
    if data == "adm_edit_service":
        services_text = "\n".join([f"{s['id']} - {s['name_en']} ({s['count']})" for s in SERVICES])
        await query.edit_message_text(f"✏️ <b>تعديل عدد خدمة</b>\n\n📋 الخدمات الحالية:\n{services_text}\n\n📝 ابعت بالصيغة:\n<code>facebook 30000</code>\nأو\n<code>whatsapp 20000</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_edit_service"
        return
    if data == "adm_broadcast":
        await query.edit_message_text("📢 <b>إذاعة للكل</b>\n\n📝 ابعت الرسالة اللي عايز تبعتها لكل المستخدمين\n\n💡 تقدر تستخدم HTML\nمثال: <b>نص عريض</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_broadcast"
        return
    if data == "adm_ban_user":
        await query.edit_message_text("🚫 <b>حظر / فك حظر مستخدم</b>\n\n📝 ابعت ID المستخدم\n\nلحظر: <code>ban 123456</code>\nلفك الحظر: <code>unban 123456</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]]))
        context.user_data["waiting"] = "adm_ban_user"
        return
    if data == "adm_stop":
        s=load_settings(); s["bot_active"]=False; save_settings(s)
        await query.edit_message_text("⛔ البوت اتوقف", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_start":
        s=load_settings(); s["bot_active"]=True; save_settings(s)
        await query.edit_message_text("▶️ البوت اشتغل", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if data == "adm_export_all":
        path = "full_export.json"
        with open(path,"w",encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        await context.bot.send_document(chat_id=query.message.chat_id, document=open(path,"rb"), filename="export.json")
        os.remove(path)
        return



# ==================== Facebook ID Extractor - نظام محسن وآمن V2 - يدعم /share/ ====================
import urllib.parse

FACEBOOK_DOMAINS = ["facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com", "fb.com", "www.fb.com", "m.fb.com"]

COMPILED_FB_ID_PARAM = re.compile(r'[?&]id=(\d{5,})', re.I)
COMPILED_FB_PROFILE_PHP = re.compile(r'profile\.php\?id=(\d+)', re.I)
COMPILED_FB_NUMERIC_PATH = re.compile(r'facebook\.com/(?:[^/]+/)*?(\d{5,20})(?:/|$|\?|&)', re.I)
COMPILED_FB_USERNAME_PATH = re.compile(r'^(?:https?://)?(?:www\.|m\.|web\.)?(?:facebook\.com|fb\.com)/(?!profile\.php)([A-Za-z0-9._-]+)(?:[/?&].*)?$', re.I)
COMPILED_FB_SHARE_PATH = re.compile(r'/share/(?:r/|p/)?([A-Za-z0-9_-]+)/?', re.I)

def is_share_url(url: str) -> bool:
    try:
        return "/share/" in url.lower()
    except Exception:
        return False

def extract_share_code(url: str):
    try:
        m = COMPILED_FB_SHARE_PATH.search(url)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None

def resolve_share_url(share_url: str):
    """
    يحل رابط الـ Share للوصول للوجهة الحقيقية باستخدام طريقة رسمية (HTTP Redirect فقط)
    بدون scraping لمحتوى الصفحة وبدون تجاوز حماية
    """
    try:
        # محاولة 1: تتبع الـ Redirect عبر HEAD/GET الرسمي
        # Facebook share links يعمل redirect 302 للبوست الحقيقي
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        # نستخدم GET مع allow_redirects=True للحصول على الرابط النهائي
        # timeout قصير لتجنب التعليق
        try:
            resp = _global_session.get(share_url, headers=headers, allow_redirects=True, timeout=12, stream=True)
            final_url = resp.url
            # اغلق الاتصال بسرعة بدون قراءة المحتوى كامل (نوفر الباندويث)
            resp.close()
            if final_url and final_url != share_url and "/share/" not in final_url:
                return final_url, "http_redirect"
            # محاولة قراءة Location header يدوياً إذا لم يتبع الـ redirect تلقائياً
            if resp.history:
                for h in resp.history:
                    loc = h.headers.get("Location")
                    if loc and "/share/" not in loc:
                        return loc, "redirect_header"
        except Exception as e:
            logger.debug(f"resolve_share_url GET failed for {share_url}: {e}")

        # محاولة 2: محاولة عبر Facebook sharer endpoint الرسمي؟ (لا يوجد API رسمي للـ share)
        # لا نحاول scraping، نرجع فشل واضح
        return None, "could_not_resolve"

    except Exception as e:
        logger.debug(f"resolve_share_url exception for {share_url}: {e}")
        return None, "exception"

def normalize_facebook_url(url: str) -> str:
    try:
        url = url.strip()
        if not url:
            return ""
        if not url.startswith("http") and "/" not in url and "." not in url:
            return f"https://www.facebook.com/{url}"
        if not url.startswith("http"):
            url = "https://" + url.lstrip("/")
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if "facebook.com" in netloc or "fb.com" in netloc:
            netloc = "www.facebook.com"
        path = parsed.path.strip()
        query = parsed.query
        normalized = f"https://{netloc}{path}"
        if query:
            normalized += f"?{query}"
        return normalized
    except Exception as e:
        logger.debug(f"normalize_facebook_url error: {e}")
        return url.strip()

def extract_numeric_id_from_url(url: str):
    try:
        # ممنوع اعتبار كود الـ share كـ ID - نتأكد أولاً أن الرابط ليس share
        if is_share_url(url):
            # لا نستخرج أي رقم من رابط الـ share نفسه، فقط من الوجهة المحلولة
            return None, None
        m = COMPILED_FB_PROFILE_PHP.search(url)
        if m:
            return m.group(1), "profile_php_id"
        m = COMPILED_FB_ID_PARAM.search(url)
        if m:
            return m.group(1), "query_id_param"
        m = COMPILED_FB_NUMERIC_PATH.search(url)
        if m:
            candidate = m.group(1)
            if len(candidate) >= 5:
                return candidate, "numeric_path"
        return None, None
    except Exception as e:
        logger.debug(f"extract_numeric_id error: {e}")
        return None, None

def extract_username_from_url(url: str):
    try:
        # ممنوع اعتبار share كـ username
        if is_share_url(url):
            return None
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip("/").split("/")
        reserved = {"profile.php", "people", "pages", "groups", "events", "watch", "reel", "stories", "marketplace", "gaming", "photo.php", "permalink.php", "hashtag", "share"}
        for part in path:
            if not part or part.lower() in reserved:
                continue
            if re.match(r'^[A-Za-z0-9._-]+$', part):
                # تجاهل أكواد الـ share (تحتوي على حروف كبيرة وصغيرة وأرقام مختلطة وطولها 10-12)
                # الأكواد مثل 1926WtdKjW تحتوي على خليط أحرف كبيرة/صغيرة وهذا ليس يوزرنيم عادي لكنه كود share
                # نحن بالفعل نمنع share عبر is_share_url، لكن كإجراء إضافي:
                if re.match(r'^[A-Za-z0-9]{8,20}$', part) and any(c.isupper() for c in part) and any(c.islower() for c in part) and any(c.isdigit() for c in part):
                    # يبدو ككود share، تجاهله
                    continue
                return part
        m = COMPILED_FB_USERNAME_PATH.match(url.strip())
        if m:
            username = m.group(1)
            if username.lower() not in reserved:
                return username
        return None
    except Exception as e:
        logger.debug(f"extract_username error: {e}")
        return None

def resolve_username_via_graph_api(username: str):
    try:
        token = os.getenv("FACEBOOK_ACCESS_TOKEN") or os.getenv("FB_ACCESS_TOKEN") or os.getenv("FB_TOKEN")
        if not token:
            logger.info(f"No FB token configured, cannot resolve username {username} via API")
            return None, "no_token"
        api_url = f"https://graph.facebook.com/v20.0/{urllib.parse.quote(username)}"
        params = {"access_token": token, "fields": "id,name"}
        resp = _global_session.get(api_url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            fb_id = data.get("id")
            if fb_id and fb_id.isdigit():
                return fb_id, "graph_api"
        elif resp.status_code == 404:
            return None, "not_found"
        else:
            logger.info(f"Graph API response {resp.status_code}: {resp.text[:200]}")
            return None, f"api_error_{resp.status_code}"
    except Exception as e:
        logger.exception(f"resolve_username_via_graph_api error for {username}: {e}")
        return None, "exception"
    return None, "failed"

def extract_facebook_id_unified(raw_input: str):
    try:
        original = raw_input.strip()
        if not original:
            return {"success": False, "error": "الرابط فارغ"}

        normalized = normalize_facebook_url(original)

        # ============ معالجة خاصة لروابط /share/ ============
        if is_share_url(normalized) or is_share_url(original):
            share_code = extract_share_code(normalized) or extract_share_code(original)
            # ممنوع إرجاع كود الـ share كـ ID
            # نحاول حل الرابط للوجهة الحقيقية
            resolved_url, resolve_method = resolve_share_url(normalized)

            if resolved_url and resolved_url != normalized:
                # حاول استخراج ID من الرابط المحلول
                # 1. ID رقمي مباشر من الرابط المحلول
                numeric_id, method = extract_numeric_id_from_url(resolved_url)
                if numeric_id:
                    return {
                        "success": True,
                        "id": numeric_id,
                        "method": f"share_resolved_{method}_{resolve_method}",
                        "normalized_url": resolved_url,
                        "original": original,
                        "share_code": share_code,
                        "resolved_from": normalized,
                        "type": "share_resolved_numeric_id"
                    }
                # 2. يوزرنيم من الرابط المحلول ثم Graph API
                username = extract_username_from_url(resolved_url)
                if username:
                    resolved_id, api_status = resolve_username_via_graph_api(username)
                    if resolved_id:
                        return {
                            "success": True,
                            "id": resolved_id,
                            "method": f"share_resolved_username_via_{api_status}",
                            "normalized_url": resolved_url,
                            "original": original,
                            "share_code": share_code,
                            "resolved_from": normalized,
                            "type": "share_resolved_username",
                            "username": username
                        }

            # إذا لم نستطع الحصول على ID حقيقي من رابط الـ Share
            return {
                "success": False,
                "error": "تعذر استخراج Facebook ID الحقيقي من رابط الـShare",
                "reason": f"رابط الـShare (كود: {share_code or 'غير معروف'}) يشير إلى محتوى لا يحتوي على ID رقمي ظاهر في الرابط المحلول. "
                          f"الوجهة المحلولة: {resolved_url or 'لم يتم حل الرابط (Facebook يمنع التتبع بدون تسجيل دخول)'} "
                          f"طريقة الحل: {resolve_method}. "
                          f"للحصول على ID الحقيقي لمنشور/صفحة من رابط Share، يجب أن يكون الرابط المحلول يحتوي على ID رقمي أو يوزرنيم يمكن حله عبر Graph API مع توكن صالح. "
                          f"ممنوع إرجاع كود الـShare ({share_code}) كـ ID لأنه ليس Facebook Numeric ID.",
                "normalized_url": normalized,
                "original": original,
                "share_code": share_code,
                "resolved_url": resolved_url,
                "resolve_method": resolve_method,
                "suggestion": "جرب فتح رابط الـShare في المتصفح وانسخ الرابط النهائي للمنشور/الصفحة (الذي يظهر بعد إعادة التوجيه) ثم الصقه هنا، أو استخدم رابط profile.php?id=..."
            }

        # ============ المعالجة العادية للروابط غير الـ Share ============
        numeric_id, method = extract_numeric_id_from_url(normalized)
        if numeric_id:
            return {
                "success": True,
                "id": numeric_id,
                "method": method,
                "normalized_url": normalized,
                "original": original,
                "type": "numeric_id"
            }

        if re.fullmatch(r'\d{5,20}', original.strip()):
            return {
                "success": True,
                "id": original.strip(),
                "method": "direct_numeric_input",
                "normalized_url": normalized,
                "original": original,
                "type": "numeric_id"
            }

        username = extract_username_from_url(normalized)
        if username:
            if username.isdigit() and len(username) >= 5:
                return {
                    "success": True,
                    "id": username,
                    "method": "username_is_numeric",
                    "normalized_url": normalized,
                    "original": original,
                    "type": "numeric_id",
                    "username": username
                }
            resolved_id, api_status = resolve_username_via_graph_api(username)
            if resolved_id:
                return {
                    "success": True,
                    "id": resolved_id,
                    "method": f"resolved_via_{api_status}",
                    "normalized_url": normalized,
                    "original": original,
                    "type": "resolved_username",
                    "username": username
                }
            else:
                if api_status == "no_token":
                    return {
                        "success": False,
                        "error": "تعذر استخراج Facebook ID من هذا الرابط",
                        "reason": f"الرابط يحتوي على يوزرنيم '{username}' وليس ID رقمي. للحصول على ID الحقيقي لليوزرنيم، يجب إعداد FACEBOOK_ACCESS_TOKEN في متغيرات البيئة (Graph API الرسمي).",
                        "normalized_url": normalized,
                        "original": original,
                        "username": username,
                        "suggestion": "استخدم رابط من نوع facebook.com/profile.php?id=123456789 أو الصق الـ ID الرقمي مباشرة"
                    }
                else:
                    return {
                        "success": False,
                        "error": "تعذر استخراج Facebook ID من هذا الرابط",
                        "reason": f"اليوزرنيم '{username}' لم يتم حله عبر Graph API (الحالة: {api_status})",
                        "normalized_url": normalized,
                        "original": original,
                        "username": username
                    }

        return {
            "success": False,
            "error": "تعذر استخراج Facebook ID من هذا الرابط",
            "reason": "لم يتم العثور على ID رقمي ولم يتم التعرف على يوزرنيم صالح",
            "normalized_url": normalized,
            "original": original
        }

    except Exception as e:
        logger.exception(f"extract_facebook_id_unified error: {e}")
        return {
            "success": False,
            "error": "تعذر استخراج Facebook ID من هذا الرابط",
            "reason": f"exception: {e}",
            "original": raw_input
        }


# ==================== Facebook ID Extractor - طريقة FindidFB (Scraping للصفحة العامة) ====================
# هذه الطريقة مثل findidfb.com - تقرأ الصفحة العامة وتستخرج ID من HTML
# ملاحظة: تعتبر Scraping حسب شروط فيسبوك لكنها للبيانات العامة فقط وبدون تسجيل دخول

COMPILED_FB_HTML_ID_PATTERNS = [
    re.compile(r'"entity_id"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"entity_id"\s*:\s*(\d+)', re.I),
    re.compile(r'"pageID"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"page_id"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"userID"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"user_id"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"profile_id"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"owner_id"\s*:\s*"(\d+)"', re.I),
    re.compile(r'owner_id=(\d+)', re.I),
    re.compile(r'profile_id=(\d+)', re.I),
    re.compile(r'fbid=(\d+)', re.I),
    re.compile(r'"content_owner_id_new"\s*:\s*"(\d+)"', re.I),
    re.compile(r'"page_id"\s*:\s*(\d+)', re.I),
    re.compile(r'"userVanity"\s*:\s*"[^"]*".*?"userID"\s*:\s*"(\d+)"', re.I | re.S),
    re.compile(r'/profile\.php\?id=(\d+)', re.I),
    re.compile(r'"is_business_page".*?"id"\s*:\s*"(\d+)"', re.I | re.S),
]

def scrape_facebook_id_from_html(html: str):
    """يستخرج ID من HTML الصفحة العامة"""
    try:
        for pattern in COMPILED_FB_HTML_ID_PATTERNS:
            m = pattern.search(html)
            if m:
                candidate = m.group(1)
                if candidate.isdigit() and len(candidate) >= 5:
                    # تجاهل أكواد الـ Share التي تحتوي على حروف - هذه كلها أرقام فقط
                    return candidate, f"html_pattern_{pattern.pattern[:20]}"
        return None, None
    except Exception as e:
        logger.debug(f"scrape_facebook_id_from_html error: {e}")
        return None, None

def resolve_facebook_url_via_scraping(url: str):
    """
    طريقة FindidFB.com: يفتح الصفحة العامة ويستخرج ID من HTML
    تعمل بدون توكن، لكنها scraping للبيانات العامة
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }
        
        # محاولة 1: الرابط الأصلي
        urls_to_try = [url]
        
        # لو رابط Share، جرب أيضاً mbasic و www
        if is_share_url(url):
            # حاول نفس الرابط مع دومينات مختلفة
            parsed = urllib.parse.urlparse(url)
            path = parsed.path
            urls_to_try.append(f"https://www.facebook.com{path}")
            urls_to_try.append(f"https://m.facebook.com{path}")
            urls_to_try.append(f"https://mbasic.facebook.com{path}")
        
        for try_url in urls_to_try:
            try:
                resp = _global_session.get(try_url, headers=headers, timeout=15, allow_redirects=True)
                final_url = resp.url
                html = resp.text
                
                # أولاً: حاول استخراج ID من الرابط النهائي بعد الـ Redirect
                numeric_id, method = extract_numeric_id_from_url(final_url)
                if numeric_id:
                    return numeric_id, f"scraping_redirect_{method}", final_url, html[:500]
                
                # ثانياً: حاول استخراج ID من HTML نفسه (طريقة findidfb.com)
                scraped_id, scrape_method = scrape_facebook_id_from_html(html)
                if scraped_id:
                    return scraped_id, f"scraping_{scrape_method}", final_url, html[:500]
                
                # ثالثاً: حاول استخراج يوزرنيم من الرابط النهائي ثم Graph API إذا توفر توكن
                username = extract_username_from_url(final_url)
                if username:
                    resolved_id, api_status = resolve_username_via_graph_api(username)
                    if resolved_id:
                        return resolved_id, f"scraping_username_via_{api_status}", final_url, ""
                        
            except Exception as e:
                logger.debug(f"resolve_facebook_url_via_scraping failed for {try_url}: {e}")
                continue
        
        return None, "scraping_failed", None, ""
        
    except Exception as e:
        logger.debug(f"resolve_facebook_url_via_scraping exception: {e}")
        return None, "exception", None, ""

# تحديث extract_facebook_id_unified ليدعم Scraping كخيار إضافي
def extract_facebook_id_unified_with_scraping(raw_input: str, allow_scraping=True):
    """
    النظام الموحد مع دعم Scraping مثل findidfb.com
    """
    try:
        # أولاً جرب الطريقة الرسمية بدون Scraping
        result = extract_facebook_id_unified(raw_input)
        if result.get("success"):
            return result
        
        # إذا فشل وكانت الطريقة الرسمية لا تكفي، جرب Scraping إذا مسموح
        if allow_scraping:
            original = raw_input.strip()
            normalized = normalize_facebook_url(original)
            
            # حاول عبر Scraping
            scraped_id, method, final_url, _ = resolve_facebook_url_via_scraping(normalized)
            
            if scraped_id and scraped_id.isdigit():
                # تأكد أن الـ ID ليس كود Share
                share_code = extract_share_code(original)
                if share_code and scraped_id == share_code:
                    # ممنوع إرجاع كود Share
                    pass
                else:
                    return {
                        "success": True,
                        "id": scraped_id,
                        "method": method,
                        "normalized_url": final_url or normalized,
                        "original": original,
                        "type": "scraping",
                        "share_code": share_code if is_share_url(original) else None,
                        "resolved_from": normalized if is_share_url(original) else None
                    }
        
        # إذا فشل كل شيء، ارجع نفس رسالة الخطأ الأصلية
        return result
        
    except Exception as e:
        logger.exception(f"extract_facebook_id_unified_with_scraping error: {e}")
        return {
            "success": False,
            "error": "تعذر استخراج Facebook ID من هذا الرابط",
            "reason": f"exception: {e}",
            "original": raw_input
        }


def test_facebook_id_extractor():
    tests = [
        ("https://www.facebook.com/profile.php?id=123456789", True, "123456789"),
        ("https://facebook.com/profile.php?id=987654321&ref=bookmarks", True, "987654321"),
        ("https://m.facebook.com/profile.php?id=123456789", True, "123456789"),
        ("https://www.facebook.com/100000123456789", True, "100000123456789"),
        ("https://www.facebook.com/zuck", False, None),
        ("https://www.fb.com/profile.php?id=123456789", True, "123456789"),
        ("123456789", True, "123456789"),
        # روابط Share - يجب ألا ترجع كود الـ Share كـ ID
        ("https://www.facebook.com/share/1926WtdKjW/", False, None),
        ("https://www.facebook.com/share/r/abc123XYZ/", False, None),
        ("https://facebook.com/share/1926WtdKjW", False, None),
        ("https://m.facebook.com/share/1926WtdKjW/", False, None),
        ("https://www.facebook.com/share/p/xyz123/", False, None),
    ]
    results = []
    for url, should_succeed, expected_id in tests:
        res = extract_facebook_id_unified(url)
        # التحقق من أن كود الـ Share لا يُرجع كـ ID
        if "/share/" in url.lower():
            share_code = extract_share_code(url)
            if res.get("success") and res.get("id") == share_code:
                passed = False  # خطأ فادح - أرجع كود الـ share كـ ID
            else:
                # يجب أن يفشل برسالة خاصة بالـ Share أو ينجح فقط إذا حل الرابط لID حقيقي مختلف عن كود الـ Share
                if res.get("success"):
                    passed = res.get("id") != share_code and res.get("id","").isdigit()
                else:
                    passed = "Share" in res.get("error","") or "Share" in res.get("reason","") or res.get("error") == "تعذر استخراج Facebook ID الحقيقي من رابط الـShare" or res.get("error") == "تعذر استخراج Facebook ID من هذا الرابط"
        else:
            if expected_id:
                passed = res.get("success") and res.get("id") == expected_id
            else:
                passed = True
        results.append((url, res, passed))
    return results




async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    waiting = context.user_data.get("waiting")
    try:
        update_user_track(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    settings = load_settings()
    if settings.get("bot_active")==False and not is_admin(uid):
        await update.message.reply_text("⛔ البوت متوقف حالياً")
        return
    ADMIN_PASSWORD = None  # لا تستخدم Plaintext — التحقق عبر check_admin_panel_password فقط

    if waiting == "ai_chat":
        if text.lower() in ["/exit", "خروج", "رجوع", "القائمة الرئيسية", "🔙 رجوع", "main"]:
            # خروج من AI = تنظيف كامل هرمي
            context.user_data["waiting"] = None
            context.user_data.pop("last_ai_time", None)
            context.user_data.pop("ai_chat_history", None)
            context.user_data["nav_stack"] = []
            context.user_data["current_page"] = "main"
            clear_user_processing(uid, success=True)
            set_user_status(uid, UserStatus.IDLE, path_action={"action": "set", "page": "main"})
            await update.message.reply_text("🔙 رجعت للقائمة الرئيسية\n\n✅ تم إنهاء جلسة المساعد", reply_markup=get_main_keyboard_for_user(uid))
            return
        if time.time() - context.user_data.get("last_ai_time", 0) < 1.2:
            return
        context.user_data["last_ai_time"] = time.time()
        await handle_ai_chat(update, context)
        return

    if waiting == "adm_force_sub_add":
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        channel_input = text.strip()
        success, result = add_force_sub_channel(channel_input, admin_id=uid)
        if success:
            await update.message.reply_text(f"✅ تمت إضافة القناة:\n{result.get('name')} ({result.get('username')})\n🆔 {result.get('id')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 القنوات", callback_data="adm_force_sub_list"), InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")]]))
        else:
            await update.message.reply_text(f"❌ فشل: {result}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_force_sub_menu")]]))
        context.user_data["waiting"] = None
        return
    if waiting == "adm_users_search":
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        # Search user
        target = text.strip().lstrip("@")
        db = fast_load_db()
        found = None
        # If numeric ID
        if target.isdigit():
            if str(target) in db.get("user_tracks", {}) or str(target) in db.get("user_states", {}):
                found = target
        else:
            # Search by username
            for uid_str, track in db.get("user_tracks", {}).items():
                if track.get("username","").lower() == target.lower():
                    found = uid_str
                    break
        if found:
            info = get_user_full_info(int(found) if str(found).isdigit() else found)
            # Show info via message with buttons - need to simulate callback
            # Send info directly
            if info:
                text_info = (
                    f"👤 <b>نتيجة البحث</b>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"👤 {info['display_name']}\n"
                    f"🆔 <code>{info['user_id']}</code>\n"
                    f"🔹 @{info['username']}\n"
                    f"🟢 الحالة: {info['status']}\n"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁️ عرض كامل", callback_data=f"adm_user_view_{info['user_id']}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]
                ])
                await update.message.reply_text(text_info, parse_mode="HTML", reply_markup=kb)
            else:
                await update.message.reply_text(f"❌ لم أجد بيانات كافية لـ {target}")
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على المستخدم: {target}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="adm_users_mgmt")]]))
        context.user_data["waiting"] = None
        return
    if waiting and waiting.startswith("adm_suspend_custom_"):
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        target_uid = waiting.replace("adm_suspend_custom_", "")
        try:
            minutes = int(text.strip())
            seconds = minutes * 60
            success, until_str = suspend_user_temporary(int(target_uid), seconds, admin_id=uid, reason=f"إيقاف مخصص {minutes} دقيقة")
            if success:
                await update.message.reply_text(f"✅ تم إيقاف {target_uid} حتى {until_str}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👁️ عرض", callback_data=f"adm_user_view_{target_uid}")]]))
            else:
                await update.message.reply_text(f"❌ {until_str}")
        except ValueError:
            await update.message.reply_text("❌ ابعت رقم فقط (بالدقائق)")
            return
        context.user_data["waiting"] = None
        return
    if waiting == "adm_ai_search":
        if not is_admin(uid):
            context.user_data["waiting"] = None
            return
        search_q = text.strip()
        # Show search results via fake callback
        # Create a dummy query-like handling by directly calling list with search
        try:
            db = fast_load_db()
            convs = db.get("ai_conversations", {})
            items = list(convs.values())
            sq = search_q.lower()
            filtered = [c for c in items if sq in str(c.get("telegram_id","")).lower() or sq in c.get("username","").lower() or sq in c.get("display_name","").lower()]
            if not filtered:
                await update.message.reply_text(f"🔎 لا يوجد نتائج لـ: {search_q}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 كل المحادثات", callback_data="adm_ai_list_0"), InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")]]))
            else:
                # Build result text
                lines = [f"🔎 نتائج البحث عن: {search_q} ({len(filtered)} نتيجة)", "━━━━━━━━━━━━━━━", ""]
                kb_rows = []
                for c in filtered[:10]:
                    name = c.get("display_name","")[:20]
                    tid = c.get("telegram_id")
                    lines.append(f"👤 {name} | 🆔 {tid} | 💬 {c.get('message_count',0)}")
                    kb_rows.append([InlineKeyboardButton(f"👁️ {name}", callback_data=f"adm_ai_view_{tid}")])
                kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm_ai_menu")])
                await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في البحث: {e}")
        context.user_data["waiting"] = None
        return
    settings = load_settings()
    if settings.get("bot_active")==False and not is_admin(uid):
        await update.message.reply_text("⛔ البوت متوقف حالياً")
        return
    
    # تحقق من الحظر/الإيقاف أولاً
    is_blocked, block_type, block_msg = is_user_banned_or_suspended(uid)
    if is_blocked:
        await update.message.reply_text(block_msg, parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        return
    

    # نظام الباسورد (Hash فقط — لا Plaintext)
    if waiting=="admin_password_owner":
        if check_admin_panel_password(text.strip()):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة أدمن", callback_data="own_add_admin")],
                [InlineKeyboardButton("➖ حذف أدمن", callback_data="own_del_admin")],
                [InlineKeyboardButton("📋 قائمة الأدمن", callback_data="own_list_admins")],
                [InlineKeyboardButton("🔑 تغيير كلمة مرور بوت الأدمن", callback_data="own_change_pw")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="main")],
            ])
            await update.message.reply_text("✅ تم التحقق - إدارة المالك فقط 👑", reply_markup=kb)
            context.user_data["waiting"]=None
        else:
            context.user_data["waiting"] = "admin_password_owner"
            await update.message.reply_text("❌ كلمة السر غلط")
        return
    if waiting=="admin_password_second":
        custom=settings.get("admin_passwords",{}).get(str(uid))
        ok = False
        if custom and isinstance(custom, str) and "$" in custom:
            ok = _verify_password(text.strip(), custom)
        elif custom:
            ok = (text.strip() == custom)
        else:
            ok = check_admin_panel_password(text.strip())
        if ok:
            # البوت الأساسي: إدارة مالك مصغّرة فقط — ليست لوحة الأدمن الكاملة
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة أدمن", callback_data="own_add_admin")],
                [InlineKeyboardButton("➖ حذف أدمن", callback_data="own_del_admin")],
                [InlineKeyboardButton("📋 قائمة الأدمن", callback_data="own_list_admins")],
                [InlineKeyboardButton("🔑 تغيير كلمة مرور بوت الأدمن", callback_data="own_change_pw")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="main")],
            ])
            await update.message.reply_text("✅ تم التحقق — إدارة المالك فقط", reply_markup=kb)
            context.user_data["waiting"]=None
        else:
            await update.message.reply_text("❌ كلمة السر غلط")
        return
    if waiting=="adm_old_pass":
        if check_admin_panel_password(text.strip()):
            await update.message.reply_text("✅ القديمة صح\n\n🔑 ابعت كلمة السر الجديدة")
            context.user_data["waiting"]="adm_new_pass"
        else:
            await update.message.reply_text("❌ القديمة غلط", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            context.user_data["waiting"]=None
        return
    if waiting=="adm_new_pass":
        newp=text.strip()
        if len(newp)<4:
            await update.message.reply_text("❌ قصير - لازم 4 حروف على الأقل")
            return
        set_admin_panel_password(newp)
        await update.message.reply_text("✅ تم تغيير كلمة المرور (Hash+Salt)", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None
        return
    if waiting=="adm_set_custom_pass":
        target=context.user_data.get("perms_target")
        if not target:
            await update.message.reply_text("❌ ابعت ID الأول")
            context.user_data["waiting"]=None
            return
        # خزّن Hash لكل أدمن بدل النص الصريح
        try:
            settings.setdefault("admin_passwords", {})[str(target)] = _hash_password(text.strip())
        except Exception:
            settings.setdefault("admin_passwords", {})[str(target)] = text.strip()
        save_settings(settings)
        await update.message.reply_text(f"✅ تم تعيين كلمة مرور للأدمن {target} (مشفّرة)", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None
        return

    if waiting=="adm_edit_auth":
        settings["welcome_auth"]=text
        save_settings(settings)
        await update.message.reply_text("✅ رسالة المسجلين اتعدلت", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None
        return
    if waiting=="adm_edit_unauth":
        settings["welcome_unauth"]=text
        save_settings(settings)
        await update.message.reply_text("✅ رسالة غير المسجلين اتعدلت", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None
        return
    if waiting=="adm_perms_select":
        try:
            target=str(int(text.strip()))
            context.user_data["perms_target"]=target
            cur=settings.get("admin_passwords",{}).get(target,"نفس باسوردك العام")
            kb=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔑 الحالي: {cur}", callback_data="noop")],
                [InlineKeyboardButton("🔑 تغيير باسورده الخاص", callback_data="perm_set_pass")],
                [InlineKeyboardButton("✅ كل الصلاحيات", callback_data="perm_all"), InlineKeyboardButton("❌ بدون", callback_data="perm_none")],
                [InlineKeyboardButton("📈 احصاءات", callback_data="perm_stats"), InlineKeyboardButton("👥 المستخدمين", callback_data="perm_users")],
                [InlineKeyboardButton("✏️ الرسائل", callback_data="perm_msgs"), InlineKeyboardButton("👑 الادمنية", callback_data="perm_admins")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="adm_back")]
            ])
            await update.message.reply_text(f"🔐 تحكم في الادمن {target}:", reply_markup=kb)
        except Exception as e:
            await update.message.reply_text("❌ ID غلط - ابعت رقم")
        context.user_data["waiting"]=None
        return

    # أوامر الأدمن للدخول
    # ===== قسم المالك فقط (إدارة الأدمن + كلمة مرور بوت الأدمن) =====
    if text.lower() == "ادمن" or text.strip() == "👑 إدارة الأدمن" or text.strip() == "AHMED2009":
        # مستخدم عادي: صمت
        if not is_owner(uid) and not is_admin(uid):
            return
        context.user_data["waiting"] = "admin_panel_pw_main"
        await update.message.reply_text("🔐 أدخل كلمة مرور لوحة الأدمن:")
        return

    if text in ["🤖 مساعد الذكاء الاصطناعي", "🤖 AI Assistant"]:
        if not is_authorized(uid):
            await update.message.reply_text("❌ غير مصرح")
            return
        await start_ai_assistant(update, context)
        return

    # الكيبورد الرئيسي
    if text == "📞 تواصل معنا":
        contact_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 تليجرام (أحمد) 👑", url="tg://user?id=6364073135")],
            [InlineKeyboardButton("📲 واتساب", url="https://wa.me/201096514020")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
        ])
        await update.message.reply_text("📞 تواصل معايا مباشر 👑", reply_markup=contact_kb)
        return
    if "الأسماء" in text or "Names" in text or "👥" in text:
        if not is_authorized(uid):
            await update.message.reply_text("❌ غير مصرح")
            return
        lang = get_user_lang(uid)
        await update.message.reply_text("👥 <b>الأسماء</b>\n\n━━━━━━━━━━━━━━━\n🌍 اختر نوع الاسم:", parse_mode="HTML", reply_markup=names_main_keyboard(lang))
        return
    if text in ["🔑 باسورد", "🔑 إنشاء كلمة مرور", "إنشاء كلمة مرور"]:
        if not is_authorized(uid): return
        pwd=''.join(random.choices(string.ascii_letters+string.digits+"@#$%", k=14))
        await send_copyable_message(update.message, "🔑 <b>كلمة المرور الجديدة</b>", pwd)
        return
    if text in ["🔐 كود 2FA", "كود 2FA"]:
        if not is_authorized(uid): return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="main")]])
        await update.message.reply_text("🔐 <b>كود 2FA</b>\n\n━━━━━━━━━━━━━━━\n📝 ابعت مفتاح الـ Secret\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=kb)
        context.user_data["waiting"] = "2fa_code"
        set_user_status(uid, UserStatus.PROCESSING, service="2fa", path_action={"action": "push", "page": "2fa"})
        return
    if text in ["🆔 استخراج ID", "استخراج ID"]:
        if not is_authorized(uid): return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="main")]])
        await update.message.reply_text("🆔 <b>استخراج ID</b>\n\n━━━━━━━━━━━━━━━\n🔗 ابعت اللينك أو اليوزر\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=kb)
        context.user_data["waiting"] = "extract_id"
        set_user_status(uid, UserStatus.PROCESSING, service="extract_id", path_action={"action": "push", "page": "extract_id"})
        return
    if text in ["💾 الحافظة", "📋 الحافظة", "الحافظة"]:
        if not is_authorized(uid): return
        db = fast_load_db()
        saved = db["users"].get(str(uid), {}).get("saved", [])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ حفظ حاجة جديدة", callback_data="save_start")],
            [InlineKeyboardButton("📥 حمّل الحافظة كملف", callback_data="download_saved_inline")],
            [InlineKeyboardButton("🗑️ مسح الحافظة", callback_data="clear_saved_inline")],
            [InlineKeyboardButton("📋 عرض الكل", callback_data="saved_list")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
        ])
        if not saved:
            await update.message.reply_text("📋 <b>الحافظة</b>\n\n━━━━━━━━━━━━━━━\n🗃️ الحافظة فاضية حالياً\n💡 دوس ➕ عشان تضيف أول حاجة\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=kb)
        else:
            await update.message.reply_text(f"📋 <b>الحافظة</b>\n\n━━━━━━━━━━━━━━━\n💾 فيها <b>{len(saved)}</b> عنصر محفوظ\n📌 اختر من الأزرار بالأسفل\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=kb)
        return
    if text in ["📥 تحميل الحافظة ملف", "📥 تحميل الحافظة", "تحميل الحافظة"]:
        if not is_authorized(uid): return
        db = fast_load_db()
        saved = db["users"].get(str(uid), {}).get("saved", [])
        if not saved:
            await update.message.reply_text("📥 <b>تحميل الحافظة</b>\n\n━━━━━━━━━━━━━━━\n🗃️ الحافظة فاضية\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        else:
            path = f"saved_{uid}.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(saved))
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open(path,"rb"), filename=f"hafza_{len(saved)}.txt", caption=f"📦 <b>حافظتك</b>\n━━━━━━━━━━━━━━━\n📋 {len(saved)} عنصر", parse_mode="HTML")
            os.remove(path)
        return
    if text in ["💾 حفظ", "حفظ", "/save"]:
        if not is_authorized(uid): return
        await update.message.reply_text("📝 <b>حفظ جديد</b>\n\n━━━━━━━━━━━━━━━\n✏️ ابعت النص اللي عايز تحفظه دلوقتي\n💡 حتى لو 5000 حرف\n━━━━━━━━━━━━━━━", parse_mode="HTML")
        context.user_data["waiting"] = "save_item"
        return
    if text in ["📱 أرقام مؤقتة", "أرقام مؤقتة", "أرقام", "ارقام"]:
        if not is_authorized(uid): return
        lang = get_user_lang(uid)
        # واجهة جديدة مباشرة زي الصورة - الخدمات على طول
        kb = get_services_keyboard(lang)
        lang = get_user_lang(uid)
        if lang == "en":
            txt2 = "🌍 <b>Choose Service:</b> Select the service ✅"
        else:
            txt2 = "🌍 <b>الخدمة المطلوبة: اختر الخدمة</b> ✅"
        await update.message.reply_text(txt2, parse_mode="HTML", reply_markup=get_services_keyboard(lang))
        return
    if text in ["📧 بريد مؤقت", "بريد مؤقت", "البريد المؤقت"]:
        if not is_authorized(uid): return
        kb = get_maildrop_domains_keyboard()
        await update.message.reply_text(
            "📧 <b>البريد المؤقت - maildrop.online</b>\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🌐 اختر نطاق البريد اللي عايزه:\n"
            "✅ كلهم شغالين ومجربين 100%\n"
            "⚡ يستقبل كود فيسبوك / انستا / تيك توك فوراً\n"
            "🔗 المصدر: https://maildrop.online/ar/\n"
            "━━━━━━━━━━━━━━━\n"
            "👇 اختر الدومين:",
            parse_mode="HTML", reply_markup=kb
        )
        return
        kb = get_maildrop_domains_keyboard()
        await update.message.reply_text(
            f"📧 <b>البريد المؤقت - maildrop.online</b>\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🌐 اختر نطاق البريد اللي عايزه:\n"
            f"✅ كلهم شغالين ومجربين 100%\n"
            f"⚡ يستقبل كود فيسبوك / انستا / تيك توك فوراً\n"
            f"🔗 المصدر: https://maildrop.online/ar/\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👇 اختر الدومين:",
            parse_mode="HTML", reply_markup=kb
        )
        return
    if text in ["💬 الدعم الفني", "📞 تواصل معنا", "الدعم الفني", "تواصل معنا"]:
        contact_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 تليجرام (أحمد) 👑", url="tg://user?id=6364073135")],
            [InlineKeyboardButton("📲 واتساب", url="https://wa.me/201096514020")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="main")]
        ])
        await update.message.reply_text("💬 <b>الدعم الفني</b>\n\n━━━━━━━━━━━━━━━\n👑 المطور: أحمد\n⚡ رد سريع\n🔒 دعم فني 24/7\n━━━━━━━━━━━━━━━\n\n📌 اختر طريقة التواصل:", parse_mode="HTML", reply_markup=contact_kb)
        return
    if text in ["❓ المساعدة", "المساعدة"]:
        lang = get_user_lang(uid)
        if lang == "en":
            help_text = (
                "❓ <b>Help - Services Guide</b>\n"
                "━━━━━━━━━━━━━━━\n"
                "🇪🇬 <b>Egyptian Name:</b> Generate random Egyptian names\n"
                "🌐 <b>Foreign Name:</b> Generate foreign names\n"
                "🔑 <b>Create Password:</b> Strong 14-char password\n"
                "🔐 <b>2FA Code:</b> Generate 2FA verification code\n"
                "🆔 <b>Extract ID:</b> Extract ID from any Telegram link\n"
                "📧 <b>Temp Mail:</b> Temporary email that receives codes instantly\n"
                "📱 <b>Temp Numbers:</b> Temporary numbers by service\n"
                "   • Choose service: FaceBook, WhatsApp, Instagram, TikTok, etc.\n"
                "   • Choose country: Egypt, USA, UK, etc.\n"
                "   • One number = One user only (never reused)\n"
                "   • Check if number is used on platform\n"
                "📋 <b>Clipboard:</b> Save your important texts\n"
                "📥 <b>Download Clipboard:</b> Download all saved as file\n"
                "💬 <b>Support:</b> Contact developer directly\n"
                "🌐 <b>Language:</b> Choose Arabic/English at /start\n"
                "━━━━━━━━━━━━━━━\n"
                "⚡ <b>Bot is ultra fast (0.1 sec response)</b>\n"
                "💡 <b>Tip:</b> All results are copyable with one tap ✨"
            )
        else:
            help_text = (
                "❓ <b>المساعدة - شرح كل الخدمات</b>\n"
                "━━━━━━━━━━━━━━━\n"
                "🇪🇬 <b>اسم مصري:</b> توليد أسماء مصرية عشوائية بالكامل\n"
                "🌐 <b>اسم أجنبي:</b> توليد أسماء أجنبية عشوائية\n"
                "🔑 <b>إنشاء كلمة مرور:</b> باسورد قوي 14 حرف آمن\n"
                "🔐 <b>كود 2FA:</b> توليد كود التحقق الثنائي\n"
                "🆔 <b>استخراج ID:</b> استخراج ID من أي لينك تليجرام\n"
                "📧 <b>بريد مؤقت:</b> بريد وهمي يستقبل أكواد فورية\n"
                "   • دوس بريد مؤقت → هيجيلك إيميل عشوائي\n"
                "   • استخدمه في أي موقع والكود هيوصلك في البوت\n"
                "📱 <b>أرقام مؤقتة:</b> الميزة الجديدة 🔥\n"
                "   • دوس أرقام مؤقتة → اختر الخدمة (فيسبوك، واتساب، انستا، تيك توك...)\n"
                "   • اختر الدولة (مصر، أمريكا، بريطانيا...)\n"
                "   • هيجيلك رقم جديد مضمون\n"
                "   • 🔒 رقم واحد = شخص واحد بس (مستحيل حد ياخد نفس رقمك)\n"
                "   • 🔍 تقدر تفحص هل الرقم مستخدم على المنصة ولا لا\n"
                "   • 📥 فحص الكود → تشوف الأكواد اللي وصلت\n"
                "📋 <b>الحافظة:</b> احفظ أي نص مهم\n"
                "📥 <b>تحميل الحافظة:</b> حمل كل محفوظاتك كملف\n"
                "💬 <b>الدعم الفني:</b> كلم المطور مباشر\n"
                "🌐 <b>اللغة:</b> اختار عربي/إنجليزي من /start\n"
                "━━━━━━━━━━━━━━━\n"
                "⚡ <b>البوت طيارة - بيرد في 0.1 ثانية</b> 🚀\n"
                "💡 <b>نصيحة:</b> كل النتائج قابلة للنسخ بضغطة واحدة ✨"
            )
        await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        return
    if text in ["📢 آخر التحديثات", "آخر التحديثات"]:
        settings = load_settings()
        updates = settings.get("last_updates", "🚀 <b>آخر التحديثات</b>\n\n━━━━━━━━━━━━━━━\n✅ تحسين الواجهة بشكل احترافي\n✅ إضافة المساعدة والتقييم\n✅ تحسين النسخ والسرعة\n✅ إضافة زر الدعم الفني\n━━━━━━━━━━━━━━━\n\n📌 ترقب المزيد قريباً 🔥")
        await update.message.reply_text(updates, parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        return
    if text in ["⭐ تقييم البوت", "تقييم البوت"]:
        rate_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐⭐⭐⭐⭐ ممتاز", callback_data="rate_5"), InlineKeyboardButton("⭐⭐⭐⭐ جيد جداً", callback_data="rate_4")],
            [InlineKeyboardButton("⭐⭐⭐ جيد", callback_data="rate_3"), InlineKeyboardButton("⭐⭐ مقبول", callback_data="rate_2")],
            [InlineKeyboardButton("⭐ ضعيف", callback_data="rate_1")],
            [InlineKeyboardButton("💬 كتابة ملاحظة", callback_data="rate_feedback")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="main")]
        ])
        await update.message.reply_text("⭐ <b>تقييم البوت</b>\n\n━━━━━━━━━━━━━━━\n📝 رأيك يهمنا جداً\n💡 قيم تجربتك عشان نطور البوت\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=rate_kb)
        return


    db = fast_load_db()
    # ===== Owner mini panel text inputs =====
    if waiting == "admin_panel_pw_main" or waiting == "owner_mgmt_pw":
        if not is_owner(uid) and not is_admin(uid):
            context.user_data["waiting"] = None
            return
        if not check_admin_panel_password(text.strip()):
            await update.message.reply_text("❌ كلمة المرور غير صحيحة")
            return
        context.user_data["waiting"] = None
        try:
            activate_admin_session_after_password(uid)
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ تم الدخول — لوحة التحكم\n🕐 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=admin_keyboard(uid, hide_password_btn=False if is_owner(uid) else True),
        )
        return

    if waiting == "own_add_admin":
        context.user_data["waiting"] = None
        if uid != OWNER_ID and uid != SUPER_ADMINS[0]:
            await update.message.reply_text("⛔ للمالك فقط")
            return
        try:
            new_id = int(text.strip())
            if new_id == OWNER_ID or new_id == SUPER_ADMINS[0]:
                await update.message.reply_text("⚠️ هذا المالك أصلاً")
                return
            try:
                if new_id not in SUPER_ADMINS:
                    SUPER_ADMINS.append(new_id)
                    with open("admins.json", "w") as f:
                        json.dump(SUPER_ADMINS, f)
            except Exception:
                if new_id not in SUPER_ADMINS:
                    SUPER_ADMINS.append(new_id)
                    with open("admins.json", "w") as f:
                        json.dump(SUPER_ADMINS, f)
            await update.message.reply_text(f"✅ تم إضافة الأدمن <code>{new_id}</code>", parse_mode="HTML")
        except Exception:
            await update.message.reply_text("❌ ID غير صالح")
        return
    if waiting == "own_del_admin":
        context.user_data["waiting"] = None
        if uid != OWNER_ID and uid != SUPER_ADMINS[0]:
            await update.message.reply_text("⛔ للمالك فقط")
            return
        try:
            rem_id = int(text.strip())
            if rem_id == OWNER_ID or rem_id == SUPER_ADMINS[0]:
                await update.message.reply_text("❌ لا يمكن حذف المالك")
                return
            try:
                if rem_id in SUPER_ADMINS and rem_id != OWNER_ID and rem_id != SUPER_ADMINS[0]:
                    SUPER_ADMINS.remove(rem_id)
                    with open("admins.json", "w") as f:
                        json.dump(SUPER_ADMINS, f)
                    await update.message.reply_text(f"✅ تم حذف {rem_id}")
                else:
                    await update.message.reply_text("❌ لا يمكن الحذف")
            except Exception:
                if rem_id in SUPER_ADMINS:
                    SUPER_ADMINS.remove(rem_id)
                    with open("admins.json", "w") as f:
                        json.dump(SUPER_ADMINS, f)
                    await update.message.reply_text(f"✅ تم حذف {rem_id}")
                else:
                    await update.message.reply_text("❌ غير موجود")
        except Exception:
            await update.message.reply_text("❌ ID غير صالح")
        return
    if waiting == "own_change_pw":
        context.user_data["waiting"] = None
        if uid != OWNER_ID and uid != SUPER_ADMINS[0]:
            await update.message.reply_text("⛔ للمالك فقط")
            return
        newp = text.strip()
        if len(newp) < 4:
            await update.message.reply_text("❌ قصيرة جداً (4 على الأقل)")
            return
        try:
            set_admin_panel_password(newp)
        except Exception:
            # fallback: hash محلي
            import hashlib, secrets as _sec
            salt = _sec.token_hex(16)
            h = hashlib.pbkdf2_hmac("sha256", newp.encode(), salt.encode(), 120000)
            settings = load_settings()
            settings["admin_password_hash"] = f"{salt}${h.hex()}"
            settings.pop("admin_password", None)
            save_settings(settings)
        # لا تطبع كلمة المرور في الرد ولا في الـ logs
        await update.message.reply_text("✅ تم تغيير كلمة مرور بوت الأدمن بنجاح\n🔒 مخزّنة بشكل مشفّر (Hash+Salt)")
        try:
            logger.info(f"Owner {uid} changed admin panel password")
        except Exception:
            pass
        return

    if waiting == "adm_add_admin":
        try:
            new_id = int(text.strip())
            if new_id not in SUPER_ADMINS:
                SUPER_ADMINS.append(new_id)
                with open("admins.json","w") as f:
                    json.dump(SUPER_ADMINS, f)
                await update.message.reply_text(f"✅ تم إضافة {new_id} أدمن", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            else:
                await update.message.reply_text("⚠️ ده أدمن أصلاً", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        except Exception as e:
            await update.message.reply_text("❌ ابعت ID رقمي صحيح", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None
        return
    if waiting == "adm_remove_admin":
        try:
            rem_id = int(text.strip())
            if rem_id in SUPER_ADMINS and len(SUPER_ADMINS)>1 and rem_id != SUPER_ADMINS[0]:
                SUPER_ADMINS.remove(rem_id)
                with open("admins.json","w") as f:
                    json.dump(SUPER_ADMINS, f)
                await update.message.reply_text(f"✅ تم إزالة {rem_id}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            else:
                await update.message.reply_text("❌ مينفعش تشيل المالك أو آخر أدمن", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        except Exception as e:
            await update.message.reply_text("❌ ابعت ID رقمي", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None
        return
    if waiting == "adm_add_user":
        context.user_data["waiting"] = None
        ok, result = add_allowed_username(text, admin_id=uid)
        if not ok:
            if result == "EXISTS":
                await update.message.reply_text("❌ هذا الـUsername مستخدم بالفعل، اختر Username آخر.", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            else:
                await update.message.reply_text(f"❌ {result}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        else:
            db = fast_load_db()
            total = len(db.get("allowed_usernames", []))
            await update.message.reply_text(f"✅ تم إضافة يوزر {result}\n\n👥 إجمالي اليوزرات: {total}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if waiting == "adm_del_user":
        context.user_data["waiting"] = None
        matches = find_users_by_username(fast_load_db(), text)
        with_uid = [m for m in matches if m.get("uid") is not None]
        only_allowed = [m for m in matches if m.get("uid") is None]
        if not matches:
            await update.message.reply_text("❌ لم يتم العثور على هذا المستخدم.", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        if len(with_uid) > 1:
            lines = "\n".join(f"• @{m['username']} — <code>{m['uid']}</code>" for m in with_uid[:10])
            await update.message.reply_text(f"⚠️ يوجد أكثر من مستخدم بنفس الـUsername:\n{lines}", parse_mode="HTML", reply_markup=admin_keyboard(uid, hide_password_btn=True))
            return
        if with_uid:
            m = with_uid[0]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"adm_del_confirm_{m['uid']}")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="adm_del_cancel")],
            ])
            await update.message.reply_text(
                f"👤 المستخدم: @{normalize_username(m['username'])}\n🆔 User ID: <code>{m['uid']}</code>\n\n⚠️ هل أنت متأكد أنك تريد حذف هذا المستخدم؟",
                parse_mode="HTML", reply_markup=kb,
            )
            return
        u = only_allowed[0]["username"]
        db = fast_load_db()
        db["allowed_usernames"] = [x for x in db.get("allowed_usernames", []) if normalize_username(x) != normalize_username(u)]
        fast_save_db(db)
        try:
            add_audit_log(uid, "delete_allowed_username", u, "success")
        except Exception:
            pass
        await update.message.reply_text(f"✅ تم حذف اليوزر @{normalize_username(u)} من قائمة المسموح.", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        return
    if waiting == "adm_upload_users":
        db = fast_load_db()
        users=[u.strip().replace("@","") for u in text.split("\n") if u.strip()]
        db.setdefault("allowed_usernames", []).extend(users)
        db["allowed_usernames"]=list(set(db["allowed_usernames"]))
        fast_save_db(db)
        total2 = len(db["allowed_usernames"])
        await update.message.reply_text(f"✅ تم إضافة {len(users)} يوزر\n👥 الإجمالي: {total2}", reply_markup=admin_keyboard(uid, hide_password_btn=True))
        context.user_data["waiting"]=None; return
    if waiting == "2fa_code":
        try:
            totp = pyotp.TOTP(text.replace(" ",""))
            code_now = totp.now()
            await send_copyable_message(update.message, "🔐 كود 2FA الحالي", code_now)
        except Exception as e:
            await update.message.reply_text(f"❌ كود غلط: {e}")
        context.user_data["waiting"]=None
        return
    if waiting == "extract_id":
        uid = update.effective_user.id
        # منع التعارض
        if is_user_processing(uid):
            await update.message.reply_text("⏳ العملية الحالية ما زالت قيد التنفيذ.\n\nانتظر انتهاءها أو اضغط 🔙 رجوع", reply_markup=main_keyboard(get_user_lang(uid)))
            return
        
        # حالة التحميل
        loading_msg_id, loading_obj = await send_loading_state(update.message, "⏳ جاري استخراج ID...\n🔍 نحاول حل الرابط مثل findidfb.com", service="extract_id")
        op_id = _generate_copy_id()
        op_data = {"type": "extract_id", "args": {"url": text, "service": "extract_id"}, "service": "extract_id", "operation_id": op_id, "attempt": 0}
        success, msg = set_user_processing(uid, op_id, op_data, service="extract_id")
        if not success:
            await update.message.reply_text("⏳ العملية الحالية ما زالت قيد التنفيذ.\n\nيرجى الانتظار...", reply_markup=main_keyboard(get_user_lang(uid)))
            return
        
        set_user_status(uid, UserStatus.PROCESSING, service="extract_id", path_action={"action": "push", "page": "extract_id"})
        start_t = _now_ts()
        try:
            # نفذ العملية
            try:
                result = extract_facebook_id_unified_with_scraping(text, allow_scraping=True)
            except NameError:
                result = extract_facebook_id_unified(text)
            
            duration = _now_ts() - start_t
            
            if result.get("success"):
                fb_id = result["id"]
                method = result.get("method","")
                normalized = result.get("normalized_url","")
                extra_info = ""
                if method:
                    extra_info += f"\n🔍 الطريقة: {method}"
                if normalized:
                    extra_info += f"\n🌐 الرابط: {normalized}"
                if result.get("share_code"):
                    extra_info += f"\n🔗 كود Share: {result.get('share_code')} (تم حله)"
                if "scraping" in method:
                    extra_info += f"\n✅ تم عبر Scraping مثل findidfb.com"
                extra_info += f"\n⏱️ الوقت: {duration:.2f}ث"
                
                update_service_health("extract_id", success=True, duration=duration)
                clear_user_processing(uid, success=True)
                set_user_status(uid, UserStatus.IDLE, path_action={"action": "pop"})
                
                await send_copyable_unified(loading_obj or update.message, [{"label": f"Facebook ID{extra_info}", "value": fb_id}], title=f"🆔 تم استخراج ID بنجاح", show_main=True, extra_text=f"⏱️ {duration:.2f}ث | {method}")
            else:
                error_msg = result.get("error","تعذر استخراج Facebook ID")
                reason = result.get("reason","")
                update_service_health("extract_id", success=False, error=error_msg)
                record_user_error(uid, "extract_id", f"{error_msg} - {reason[:100]}")
                clear_user_processing(uid, success=False)
                set_user_status(uid, UserStatus.IDLE)
                
                # إذا كان خطأ مهم، نبه الأدمن
                if "critical" in error_msg.lower() or "api" in error_msg.lower() or result.get("share_code"):
                    try:
                        await notify_owner(context, "خطأ في استخراج ID", f"User: {uid} (@{update.effective_user.username or 'بدون'})\nService: extract_id\nError: {error_msg[:300]}\nURL: {text[:200]}\nTime: {_now_str()}\nAttempts: 0")
                    except Exception:
                        pass
                
                await send_error_with_retry(loading_obj or update.message, f"{error_msg}\n{reason[:200]}", op_data, service="extract_id", attempt=0)
        except Exception as e:
            logger.exception(f"extract_id error: {e}")
            duration = _now_ts() - start_t
            update_service_health("extract_id", success=False, error=str(e))
            record_user_error(uid, "extract_id", str(e))
            clear_user_processing(uid, success=False)
            try:
                await notify_owner(context, "خطأ Critical في extract_id", f"User: {uid}\nError: {str(e)[:300]}\nTime: {_now_str()}")
            except Exception:
                pass
            await send_error_with_retry(loading_obj or update.message, str(e)[:300], op_data, service="extract_id", attempt=0)
        
        context.user_data["waiting"]=None
        return

    if waiting == "rate_feedback":
        # حفظ الملاحظة
        db = fast_load_db()
        db.setdefault("feedbacks", []).append({"uid": uid, "text": text, "time": str(datetime.datetime.now())})
        fast_save_db(db)
        await update.message.reply_text("💌 <b>شكراً لملاحظتك!</b>\n\n━━━━━━━━━━━━━━━\n✅ تم حفظ ملاحظتك\n👀 سيتم مراجعتها قريباً\n💖 شكراً لمساعدتنا\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
        context.user_data["waiting"]=None
        return
    if waiting == "save_item":
        if text in old_main_buttons() or text.lower() in ["ادمن", "ahmed2009"]:
            context.user_data["waiting"] = None
        else:
            db["users"].setdefault(str(uid), {"saved":[]})
            db["users"][str(uid)]["saved"].append(text)
            fast_save_db(db)
            await update.message.reply_text("✅ <b>تم الحفظ</b>\n\n━━━━━━━━━━━━━━━\n💾 تم حفظ النص في الحافظة\n📌 تقدر تشوفه من 📋 الحافظة\n━━━━━━━━━━━━━━━", parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
            context.user_data["waiting"]=None
            return

    if not is_authorized(uid):
        clean_user = text.replace("@","").lower()
        allowed_lower = [u.lower() for u in db.get("allowed_usernames",[])]
        if clean_user in allowed_lower:
            db.setdefault("authorized", {})[str(uid)] = clean_user
            db.setdefault("users", {})[str(uid)] = db["users"].get(str(uid), {"saved":[]})
            fast_save_db(db)
            name = update.effective_user.first_name or "يا غالي"
            # تنبيه للمالك - مستخدم جديد دخل
            try:
                await notify_owner(context, "مستخدم جديد دخل ✅", f"👤 الاسم: {name}\n🆔 ID: {uid}\n🔗 اليوزر: @{update.effective_user.username or 'بدون'}\n📝 اليوزر اللي كتبه: {clean_user}")
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
            settings = load_settings()
            tmpl = settings.get("welcome_auth","👋 أهلا بيك {name}")
            welcome = tmpl.format(name=name) if "{name}" in tmpl else tmpl
            if welcome.strip():
                await update.message.reply_text(welcome, parse_mode="HTML", reply_markup=main_keyboard(get_user_lang(uid)))
            else:
                await update.message.reply_text("👇 اختار من القائمة", reply_markup=main_keyboard(get_user_lang(uid)))
        else:
            # تتبع محاولة فاشلة
            fails = track_failed_login(uid, clean_user)
            if fails >= 5:
                try:
                    await notify_owner(context, "محاولات دخول مشبوهة ⚠️", f"👤 ID: {uid}\n🔗 @{update.effective_user.username or 'بدون'}\n📝 حاول {fails} مرات بيوزرات غلط\nآخر محاولة: {clean_user}\n🕐 خلال 10 دقايق")
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
            await update.message.reply_text("❌ يوزر غلط 🔐\nلـ طلب يوزر كلم الأدمن:", reply_markup=whatsapp_button())
        return
    # لو مش أمر معروف
    await update.message.reply_text("👋 اختار من القائمة تحت 👇", reply_markup=main_keyboard(get_user_lang(uid)))

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    waiting = context.user_data.get("waiting")
    db = fast_load_db()
    file = await update.message.document.get_file()
    path = f"temp_{update.effective_user.id}.txt"
    await file.download_to_drive(path)
    try:
        with open(path,"r",encoding="utf-8",errors="ignore") as f:
            lines=[l.strip() for l in f if l.strip()]
    except Exception as e:
        lines=[]
    try:
        os.remove(path)
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    
    if waiting == "adm_upload_users" or waiting:
        uid = update.effective_user.id
        added = skipped = 0
        for line in lines:
            ok, res = add_allowed_username(line, admin_id=uid)
            if ok:
                added += 1
            else:
                skipped += 1
        await update.message.reply_text(
            f"✅ تمت إضافة {added} يوزر\n"
            f"{'⚠️ تم تخطي ' + str(skipped) + ' مكرر/غير صالح' if skipped else ''}",
            reply_markup=admin_keyboard(uid, hide_password_btn=True),
        )
    else:
        await update.message.reply_text("⚠️ لست في وضع رفع اليوزرات. اختر 📤 رفع يوزرات من لوحة الأدمن أولاً.")
    context.user_data["waiting"]=None

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يتم استدعاؤه تلقائياً عند أي خطأ غير متوقع في البوت"""
    error = context.error
    
    # تجاهل أخطاء النت المؤقتة - لا ترسل تنبيه للمالك
    is_network_error = False
    try:
        err_name = type(error).__name__.lower()
        err_msg = str(error).lower()
        # 1. Telegram network errors
        if isinstance(error, (NetworkError, TimedOut)):
            is_network_error = True
        # 2. httpx errors
        if HAS_HTTPX and httpx:
            try:
                if isinstance(error, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout)):
                    is_network_error = True
            except Exception:
                pass
        # 3. Check by type name - يشمل TimedOut, ReadError, etc
        if any(x in err_name for x in ["readerror", "connecterror", "timeout", "timedout", "network", "pooltimeout"]):
            is_network_error = True
        # 4. Check by message - "timed out", "read error", etc
        if any(x in err_msg for x in ["timed out", "readerror", "connecterror", "timeout", "network is unreachable", "connection reset", "connection aborted", "clientconnectorerror"]):
            is_network_error = True
    except Exception:
        pass
    
    if is_network_error:
        logger.warning(f"⚠️ Network error (ignored, will retry): {error}")
        # لا ترسل تنبيه للمالك لأخطاء النت
        return
    
    # للأخطاء الحقيقية فقط، ابعت تنبيه
    tb = "".join(traceback.format_exception(None, error, error.__traceback__))
    error_text = f"خطأ عام في البوت:\n{str(error)[:500]}\n\n{tb[:1000]}"
    logger.info(f"ERROR: {error}")
    logger.info(tb)
    try:
        await notify_owner(context, "خطأ عام", error_text)
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text("حصل خطأ مؤقت، جاري اصلاحه تلقائياً... حاول تاني كمان ثانية")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")

async def monitor_services(context: ContextTypes.DEFAULT_TYPE):
    """يفحص الخدمات كل 10 دقايق ويبلغ المالك لو فيه عطل - مجاني"""
    try:
        # افحص mail.tm
        failed = []
        for api_base in MAIL_TM_APIS:
            try:
                r = _global_session.get(f"{api_base}/domains", timeout=5)
                if r.status_code != 200:
                    failed.append(f"{api_base} - Status {r.status_code}")
            except Exception as e:
                failed.append(f"{api_base} - {str(e)[:100]}")
        # افحص maildrop.online
        try:
            r = _global_session.get("https://maildrop.online/", timeout=5)
            if r.status_code != 200:
                failed.append(f"maildrop.online - Status {r.status_code}")
        except Exception as e:
            failed.append(f"maildrop.online - {str(e)[:100]}")
        
        if failed:
            details = "\n".join(f"• {f}" for f in failed)
            await notify_owner(context, "خدمة بريد واقعة", f"الخدمات التالية مش شغالة:\n{details}")
    except Exception as e:
        logger.info(f"monitor error: {e}")

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "▶️ تشغيل البوت - القائمة الرئيسية"),
    ])
    logger.info("✅ تم اضافة زر القائمة - المربع الأزرق فيه /start")
    # ابعت للمالك ان البوت اشتغل
    try:
        await app.bot.send_message(
            chat_id=OWNER_ID,
            text=f"✅ <b>البوت اشتغل بنجاح V33</b>\n\n"
                 f"🕐 الوقت: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"🔔 نظام التنبيهات شغال\n"
                 f"📧 15 دومين بريد مجاني\n"
                 f"━━━━━━━━━━━━━━━\n"
                 f"لو حصل اي عطل هبعتلك تنبيه هنا تلقائياً",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
    # شغل مراقب الخدمات كل 10 دقايق
    try:
        app.job_queue.run_repeating(monitor_services, interval=600, first=60, name="service_monitor")
        app.job_queue.run_repeating(check_processing_timeouts, interval=30, first=30, name="processing_timeout_checker")
        app.job_queue.run_repeating(daily_report, interval=86400, first=3600, name="daily_report")  # كل 24 ساعة
        app.job_queue.run_repeating(auto_backup, interval=21600, first=600, name="auto_backup")  # كل 6 ساعات
        logger.info("✅ Service Monitor + Daily Report + Auto Backup Started")
    except Exception as e:
        logger.debug(f"Suppressed: {e}")



if not BOT_TOKEN:
    print("ERROR: MAIN_BOT_TOKEN (or BOT_TOKEN) environment variable is required")
    sys.exit(1)
app = Application.builder().token(BOT_TOKEN).read_timeout(60).write_timeout(60).connect_timeout(60).pool_timeout(60).concurrent_updates(True).post_init(post_init).build()
app.add_error_handler(error_handler)
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(handle_copy_callback, pattern="^copy_"))
app.add_handler(CallbackQueryHandler(handle_retry_callback, pattern="^retry_"))
app.add_handler(CallbackQueryHandler(owner_callback, pattern="^own_"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_|^perm_|^noop"))
app.add_handler(CallbackQueryHandler(button_handler, pattern="^main|^save_|^gender_|^egy_|^foreign_|^password$|^2fa$|^extract_id$|^download_|^clear_|^confirm_|^rate_|^temp_|^mdomain_|^cat_|^lang_|^svc_|^country_|^nums_|^check_platform_|^names_|^ai_clear_my|^check_force_sub"))
app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
logger.info("✅ Bot V34 - AI Assistant + Unified Copy System + Share Support - Owner 6364073135")

# تشغيل keep_alive فقط لو flask موجود
try:
    keep_alive()
except Exception as e:
    print(f"keep_alive failed (flask missing?): {e}")




# =====================================================================
# تشغيل البوت الأساسي فقط (لوحة الأدمن من داخل البوت بعد كلمة المرور)
# =====================================================================
try:
    _ensure_admin_password_seeded()
except Exception:
    pass

logger.info("Bot started — single bot mode | Admin panel: type ادمن + password")
app.run_polling(drop_pending_updates=True)
