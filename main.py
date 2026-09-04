import os
import time
import requests

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from supabase import create_client


# =========================================================
# CONFIG
# =========================================================

BALE_TOKEN = os.environ.get("BALE_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")

if not BALE_TOKEN:
    raise Exception("BALE_TOKEN is missing")

if not SUPABASE_URL:
    raise Exception("SUPABASE_URL is missing")

if not SUPABASE_SECRET_KEY:
    raise Exception("SUPABASE_SECRET_KEY is missing")


BALE_API = f"https://tapi.bale.ai/bot{BALE_TOKEN}"

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

IRAN_TZ = ZoneInfo("Asia/Tehran")


# =========================================================
# TIME
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def iran_now():
    return datetime.now(IRAN_TZ)


def to_persian_digits(value):

    if value is None:
        return ""

    table = str.maketrans(
        "0123456789",
        "۰۱۲۳۴۵۶۷۸۹"
    )

    return str(value).translate(table)


def gregorian_to_jalali(gy, gm, gd):

    g_days_in_month = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    ]

    j_days_in_month = [
        31, 31, 31, 31, 31, 31,
        30, 30, 30, 30, 30, 29
    ]

    gy -= 1600
    gm -= 1
    gd -= 1

    g_day_no = (
        365 * gy
        + (gy + 3) // 4
        - (gy + 99) // 100
        + (gy + 399) // 400
    )

    for i in range(gm):
        g_day_no += g_days_in_month[i]

    if gm > 1:

        if (
            (gy % 4 == 0 and gy % 100 != 0)
            or gy % 400 == 0
        ):
            g_day_no += 1

    g_day_no += gd

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = (
        979
        + 33 * j_np
        + 4 * (j_day_no // 1461)
    )

    j_day_no %= 1461

    if j_day_no >= 366:

        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    i = 0

    while (
        i < 11
        and j_day_no >= j_days_in_month[i]
    ):

        j_day_no -= j_days_in_month[i]
        i += 1

    jm = i + 1
    jd = j_day_no + 1

    return jy, jm, jd


def format_iran_datetime(value):

    if not value:
        return "-"

    try:

        if isinstance(value, datetime):

            dt = value

        else:

            value = str(value).strip()

            if value.endswith("Z"):
                value = value[:-1] + "+00:00"

            dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        dt = dt.astimezone(
            IRAN_TZ
        )

        jy, jm, jd = gregorian_to_jalali(
            dt.year,
            dt.month,
            dt.day
        )

        date_text = (
            f"{jy:04d}/{jm:02d}/{jd:02d}"
        )

        time_text = (
            f"{dt.hour:02d}:{dt.minute:02d}"
        )

        return (
            f"{to_persian_digits(date_text)}"
            f" - "
            f"{to_persian_digits(time_text)}"
        )

    except Exception as e:

        print(
            "FORMAT IRAN DATETIME ERROR:",
            value,
            e
        )

        return str(value)


# =========================================================
# BASIC HELPERS
# =========================================================

def clean_username(username):

    if not username:
        return None

    username = str(username).strip()

    if username.startswith("@"):
        username = username[1:]

    return username or None


def safe_text(value, default="-"):

    if value is None:
        return default

    value = str(value).strip()

    return value if value else default


# =========================================================
# BALE API
# =========================================================

def bale_request(method, data=None):

    url = f"{BALE_API}/{method}"

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=40
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):

            print(
                "BALE API ERROR:",
                method,
                result
            )

        return result

    except Exception as e:

        print(
            "BALE REQUEST ERROR:",
            method,
            e
        )

        return {
            "ok": False,
            "description": str(e)
        }


def send_message(
    chat_id,
    text,
    reply_markup=None
):

    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:

        data["reply_markup"] = reply_markup

    return bale_request(
        "sendMessage",
        data
    )


def get_chat(chat_id):

    result = bale_request(
        "getChat",
        {
            "chat_id": chat_id
        }
    )

    if result.get("ok"):

        return (
            result.get("result")
            or {}
        )

    return {}


# =========================================================
# MESSAGE LINK
# =========================================================

def build_bale_message_link(
    username,
    chat_id,
    message_id
):

    username = clean_username(
        username
    )

    if not username:
        return None

    if chat_id is None:
        return None

    if message_id is None:
        return None

    chat_id = str(chat_id).strip()
    message_id = str(message_id).strip()

    if not chat_id or not message_id:
        return None

    return (
        f"https://ble.ir/"
        f"{username}/"
        f"{chat_id}/"
        f"{message_id}"
    )


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key):

    try:

        result = (
            supabase
            .table("bot_settings")
            .select("value")
            .eq("key", key)
            .limit(1)
            .execute()
        )

        if result.data:

            return result.data[0].get(
                "value"
            )

    except Exception as e:

        print(
            "GET SETTING ERROR:",
            key,
            e
        )

    return None


def set_setting(key, value):

    try:

        existing = (
            supabase
            .table("bot_settings")
            .select("key")
            .eq("key", key)
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("bot_settings")
                .update({
                    "value": str(value)
                })
                .eq(
                    "key",
                    key
                )
                .execute()
            )

        else:

            (
                supabase
                .table("bot_settings")
                .insert({
                    "key": key,
                    "value": str(value)
                })
                .execute()
            )

        return True

    except Exception as e:

        print(
            "SET SETTING ERROR:",
            key,
            e
        )

        return False


OWNER_ID = get_setting(
    "owner_id"
)


# =========================================================
# USER TRACKING
# =========================================================

def save_bot_user(chat):

    if not chat:
        return

    user_id = chat.get("id")

    if user_id is None:
        return

    data = {
        "user_id": str(user_id),
        "username": clean_username(
            chat.get("username")
        ),
        "first_name": chat.get(
            "first_name"
        ),
        "last_name": chat.get(
            "last_name"
        ),
        "active": True,
        "updated_at": now_iso()
    }

    try:

        existing = (
            supabase
            .table("bot_users")
            .select("id")
            .eq(
                "user_id",
                str(user_id)
            )
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("bot_users")
                .update(data)
                .eq(
                    "user_id",
                    str(user_id)
                )
                .execute()
            )

        else:

            data["created_at"] = now_iso()

            (
                supabase
                .table("bot_users")
                .insert(data)
                .execute()
            )

    except Exception as e:

        print(
            "SAVE BOT USER ERROR:",
            e
        )


# =========================================================
# ACCESS CONTROL
# =========================================================

def is_owner(user_id):

    if not OWNER_ID:
        return False

    return (
        str(user_id)
        == str(OWNER_ID)
    )


def is_admin(user_id):

    if not user_id:
        return False

    if is_owner(user_id):
        return True

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq(
                "user_id",
                str(user_id)
            )
            .eq(
                "active",
                True
            )
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as e:

        print(
            "IS ADMIN ERROR:",
            e
        )

        return False


def deny_access(chat_id):

    send_message(
        chat_id,
        "⛔️ شما دسترسی استفاده از بخش مدیریت ربات را ندارید.\n\n"
        "برای مشاهده شناسه کاربری خود، دستور /myid را ارسال کنید."
    )


# =========================================================
# MY ID
# =========================================================

def show_my_id(chat_id):

    send_message(
        chat_id,
        "🆔 شناسه کاربری شما:\n\n"
        f"{chat_id}"
    )


# =========================================================
# AUTO REGISTER CHAT
# =========================================================

def auto_register_chat(chat):

    if not chat:
        return False

    chat_type = chat.get(
        "type"
    )

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return False

    chat_id = chat.get(
        "id"
    )

    if chat_id is None:
        return False

    chat_id = str(chat_id)

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or username
        or chat_id
    )

    try:

        result = (
            supabase
            .table("channels")
            .select(
                "id,chat_id,username,title,"
                "active,manually_disabled"
            )
            .eq(
                "chat_id",
                chat_id
            )
            .limit(1)
            .execute()
        )

        if result.data:

            row = result.data[0]

            manually_disabled = (
                row.get(
                    "manually_disabled"
                )
                is True
            )

            update_data = {
                "username": username,
                "title": title
            }

            # اگر ادمین دستی حذف کرده باشد
            # دوباره فعالش نمی‌کنیم
            if not manually_disabled:

                update_data["active"] = True

            (
                supabase
                .table("channels")
                .update(update_data)
                .eq(
                    "id",
                    row["id"]
                )
                .execute()
            )

            print(
                "CHAT AUTO UPDATE:",
                chat_type,
                chat_id,
                title
            )

            return True

        # -------------------------------------------------
        # اگر با username قبلاً ثبت شده
        # -------------------------------------------------

        if username:

            result = (
                supabase
                .table("channels")
                .select(
                    "id,chat_id,username,title,"
                    "active,manually_disabled"
                )
                .eq(
                    "username",
                    username
                )
                .limit(1)
                .execute()
            )

            if result.data:

                row = result.data[0]

                manually_disabled = (
                    row.get(
                        "manually_disabled"
                    )
                    is True
                )

                update_data = {
                    "chat_id": chat_id,
                    "username": username,
                    "title": title
                }

                if not manually_disabled:

                    update_data["active"] = True

                (
                    supabase
                    .table("channels")
                    .update(update_data)
                    .eq(
                        "id",
                        row["id"]
                    )
                    .execute()
                )

                print(
                    "CHAT FOUND BY USERNAME:",
                    username
                )

                return True

        # -------------------------------------------------
        # ثبت کاملاً جدید
        # -------------------------------------------------

        (
            supabase
            .table("channels")
            .insert({
                "chat_id": chat_id,
                "username": username,
                "title": title,
                "active": True,
                "manually_disabled": False
            })
            .execute()
        )

        print(
            "🟢 NEW CHAT REGISTERED:",
            chat_type,
            chat_id,
            title,
            username
        )

        return True

    except Exception as e:

        print(
            "AUTO REGISTER CHAT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# MANUAL ADD CHANNEL
# =========================================================

def manual_add_channel(
    admin_chat_id,
    target
):

    target = target.strip()

    if not target:

        send_message(
            admin_chat_id,
            "❌ شناسه یا username کانال/گروه را وارد کنید."
        )

        return

    # -----------------------------------------------------
    # username
    # -----------------------------------------------------

    if target.startswith("@"):

        username = clean_username(
            target
        )

        chat = get_chat(
            f"@{username}"
        )

    else:

        username = None

        # -------------------------------------------------
        # chat_id
        # -------------------------------------------------

        try:

            chat_id = int(
                target
            )

        except Exception:

            send_message(
                admin_chat_id,
                "❌ فرمت شناسه نامعتبر است.\n\n"
                "مثال:\n"
                "/addchannel @channel\n"
                "یا\n"
                "/addchannel 123456789"
            )

            return

        chat = get_chat(
            chat_id
        )

    # -----------------------------------------------------
    # اگر getChat جواب داد
    # -----------------------------------------------------

    if chat:

        chat_type = chat.get(
            "type"
        )

        if chat_type not in (
            "group",
            "supergroup",
            "channel"
        ):

            send_message(
                admin_chat_id,
                "❌ این شناسه مربوط به گروه یا کانال نیست."
            )

            return

        # دستی اضافه شده، پس فعال باشد
        chat_id = chat.get(
            "id"
        )

        username = clean_username(
            chat.get("username")
        )

        title = (
            chat.get("title")
            or username
            or str(chat_id)
        )

    else:

        # -------------------------------------------------
        # اگر getChat جواب نداد
        # برای username امکان ثبت مستقیم داریم
        # -------------------------------------------------

        if not username:

            send_message(
                admin_chat_id,
                "❌ ربات نتوانست این گروه/کانال را پیدا کند.\n\n"
                "مطمئن شوید ربات داخل آن عضو است و شناسه صحیح است."
            )

            return

        title = username
        chat_id = None

    # -----------------------------------------------------
    # ثبت
    # -----------------------------------------------------

    try:

        if chat_id is not None:

            result = (
                supabase
                .table("channels")
                .select("id")
                .eq(
                    "chat_id",
                    str(chat_id)
                )
                .limit(1)
                .execute()
            )

        else:

            result = (
                supabase
                .table("channels")
                .select("id")
                .eq(
                    "username",
                    username
                )
                .limit(1)
                .execute()
            )

        data = {
            "username": username,
            "title": title,
            "active": True,
            "manually_disabled": False
        }

        if chat_id is not None:
            data["chat_id"] = str(
                chat_id
            )

        if result.data:

            (
                supabase
                .table("channels")
                .update(data)
                .eq(
                    "id",
                    result.data[0]["id"]
                )
                .execute()
            )

        else:

            (
                supabase
                .table("channels")
                .insert(data)
                .execute()
            )

        text = (
            "✅ مقصد با موفقیت اضافه شد.\n\n"
            f"📢 {title}\n"
        )

        if username:
            text += (
                f"👤 @{username}\n"
            )

        if chat_id is not None:
            text += (
                f"🆔 {chat_id}\n"
            )

        send_message(
            admin_chat_id,
            text
        )

    except Exception as e:

        print(
            "MANUAL ADD CHANNEL ERROR:",
            repr(e)
        )

        send_message(
            admin_chat_id,
            "❌ خطا در افزودن مقصد."
        )


# =========================================================
# MANUAL REMOVE CHANNEL
# =========================================================

def manual_remove_channel(
    admin_chat_id,
    target
):

    target = target.strip()

    if not target:

        send_message(
            admin_chat_id,
            "❌ شناسه یا username مقصد را وارد کنید.\n\n"
            "مثال:\n"
            "/removechannel @channel\n"
            "یا\n"
            "/removechannel 123456789"
        )

        return

    try:

        # -------------------------------------------------
        # حذف با chat_id
        # -------------------------------------------------

        if target.lstrip("-").isdigit():

            result = (
                supabase
                .table("channels")
                .select(
                    "id,title,username,chat_id"
                )
                .eq(
                    "chat_id",
                    str(target)
                )
                .limit(1)
                .execute()
            )

        else:

            username = clean_username(
                target
            )

            result = (
                supabase
                .table("channels")
                .select(
                    "id,title,username,chat_id"
                )
                .eq(
                    "username",
                    username
                )
                .limit(1)
                .execute()
            )

        if not result.data:

            send_message(
                admin_chat_id,
                "❌ این گروه/کانال در فهرست مقصدها پیدا نشد."
            )

            return

        row = result.data[0]

        (
            supabase
            .table("channels")
            .update({
                "active": False,
                "manually_disabled": True
            })
            .eq(
                "id",
                row["id"]
            )
            .execute()
        )

        send_message(
            admin_chat_id,
            "🗑 مقصد غیرفعال شد.\n\n"
            f"📢 {safe_text(row.get('title'))}\n"
            f"🆔 {safe_text(row.get('chat_id'))}\n\n"
            "سوابق گزارش حذف نشد."
        )

    except Exception as e:

        print(
            "MANUAL REMOVE CHANNEL ERROR:",
            repr(e)
        )

        send_message(
            admin_chat_id,
            "❌ خطا در حذف مقصد."
        )


# =========================================================
# LIST CHANNELS
# =========================================================

def list_channels(chat_id):

    try:

        result = (
            supabase
            .table("channels")
            .select(
                "id,chat_id,username,title,"
                "active,manually_disabled"
            )
            .order(
                "title"
            )
            .execute()
        )

        rows = (
            result.data
            or []
        )

        if not rows:

            send_message(
                chat_id,
                "📭 هنوز هیچ گروه یا کانالی ثبت نشده است."
            )

            return

        lines = [
            "📋 فهرست گروه‌ها و کانال‌ها:",
            ""
        ]

        for index, row in enumerate(
            rows,
            start=1
        ):

            manually_disabled = (
                row.get(
                    "manually_disabled"
                )
                is True
            )

            if manually_disabled:

                status = "⛔️ غیرفعال توسط ادمین"

            elif row.get("active"):

                status = "🟢 فعال"

            else:

                status = "🔴 غیرفعال"

            username = clean_username(
                row.get("username")
            )

            username_text = (
                f"@{username}"
                if username
                else "بدون username"
            )

            lines.append(
                f"{index}. "
                f"{safe_text(row.get('title'))}\n"
                f"   {username_text}\n"
                f"   🆔 {safe_text(row.get('chat_id'))}\n"
                f"   {status}"
            )

        lines.append(
            "\n➕ افزودن دستی:\n"
            "/addchannel @username"
        )

        lines.append(
            "\n🗑 حذف دستی:\n"
            "/removechannel @username"
        )

        send_message(
            chat_id,
            "\n\n".join(lines)
        )

    except Exception as e:

        print(
            "LIST CHANNELS ERROR:",
            e
        )

        send_message(
            chat_id,
            "❌ خطا در دریافت فهرست مقصدها."
        )


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

def add_admin(
    user_id,
    username=None
):

    try:

        existing = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq(
                "user_id",
                str(user_id)
            )
            .limit(1)
            .execute()
        )

        data = {
            "user_id": str(user_id),
            "username": clean_username(
                username
            ),
            "active": True
        }

        if existing.data:

            (
                supabase
                .table("bot_admins")
                .update(data)
                .eq(
                    "user_id",
                    str(user_id)
                )
                .execute()
            )

        else:

            data["created_at"] = now_iso()

            (
                supabase
                .table("bot_admins")
                .insert(data)
                .execute()
            )

        return True

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            e
        )

        return False


def remove_admin(user_id):

    try:

        (
            supabase
            .table("bot_admins")
            .update({
                "active": False
            })
            .eq(
                "user_id",
                str(user_id)
            )
            .execute()
        )

        return True

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            e
        )

        return False


def list_admins(chat_id):

    try:

        result = (
            supabase
            .table("bot_admins")
            .select(
                "user_id,username,"
                "first_name,active"
            )
            .eq(
                "active",
                True
            )
            .order(
                "created_at"
            )
            .execute()
        )

        rows = (
            result.data
            or []
        )

        lines = [
            "👥 مدیران فعال:",
            ""
        ]

        if OWNER_ID:

            lines.append(
                f"👑 مالک ربات: {OWNER_ID}"
            )

        for row in rows:

            username = clean_username(
                row.get("username")
            )

            username_text = (
                f"@{username}"
                if username
                else ""
            )

            name = (
                row.get("first_name")
                or username_text
                or row.get("user_id")
            )

            lines.append(
                f"👤 {name} "
                f"{username_text}\n"
                f"🆔 {row.get('user_id')}"
            )

        send_message(
            chat_id,
            "\n\n".join(lines)
        )

    except Exception as e:

        print(
            "LIST ADMINS ERROR:",
            e
        )

        send_message(
            chat_id,
            "❌ خطا در دریافت مدیران."
        )


def find_user_by_username(
    username
):

    username = clean_username(
        username
    )

    if not username:
        return None

    try:

        result = (
            supabase
            .table("bot_users")
            .select(
                "user_id,username,first_name"
            )
            .eq(
                "username",
                username
            )
            .eq(
                "active",
                True
            )
            .limit(1)
            .execute()
        )

        if result.data:

            return result.data[0]

    except Exception as e:

        print(
            "FIND USER ERROR:",
            e
        )

    return None


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(message):

    if not message:
        return {}

    result = {
        "message_id": None,
        "chat_id": None,
        "username": None,
        "title": None
    }

    origin = (
        message.get(
            "forward_origin"
        )
        or {}
    )

    if origin:

        result["message_id"] = (
            origin.get(
                "message_id"
            )
            or message.get(
                "forwarded_message_id"
            )
        )

        chat = (
            origin.get("chat")
            or {}
        )

        result["chat_id"] = chat.get(
            "id"
        )

        result["username"] = (
            clean_username(
                chat.get("username")
            )
        )

        result["title"] = (
            chat.get("title")
        )

        return result

    forward_from_chat = (
        message.get(
            "forward_from_chat"
        )
        or {}
    )

    forward_from = (
        message.get(
            "forward_from"
        )
        or {}
    )

    result["message_id"] = (
        message.get(
            "forwarded_message_id"
        )
        or message.get(
            "forward_message_id"
        )
    )

    result["chat_id"] = (
        forward_from_chat.get("id")
        or forward_from.get("id")
        or forward_from_chat.get("chat_id")
    )

    result["username"] = (
        clean_username(
            forward_from_chat.get(
                "username"
            )
        )
        or clean_username(
            forward_from.get(
                "username"
            )
        )
    )

    result["title"] = (
        forward_from_chat.get(
            "title"
        )
        or forward_from.get(
            "first_name"
        )
    )

    return result


# =========================================================
# MESSAGE TITLE
# =========================================================

def get_message_title(message):

    if not message:
        return "بدون عنوان"

    if message.get("text"):

        text = str(
            message.get("text")
        ).strip()

        if text:

            first_line = (
                text
                .split("\n", 1)[0]
                .strip()
            )

            if len(first_line) > 100:

                first_line = (
                    first_line[:100]
                    + "..."
                )

            return first_line

    if message.get("caption"):

        caption = str(
            message.get("caption")
        ).strip()

        if caption:

            first_line = (
                caption
                .split("\n", 1)[0]
                .strip()
            )

            if len(first_line) > 100:

                first_line = (
                    first_line[:100]
                    + "..."
                )

            return first_line

    if message.get("photo"):
        return "تصویر"

    if message.get("video"):
        return "ویدئو"

    if message.get("document"):
        return "فایل"

    if message.get("audio"):
        return "فایل صوتی"

    if message.get("voice"):
        return "پیام صوتی"

    return "بدون عنوان"


# =========================================================
# PROCESS PRIVATE FORWARD
# =========================================================

def process_private_forward(message):

    chat = (
        message.get("chat")
        or {}
    )

    forward = extract_forward(
        message
    )

    source_message_id = (
        forward.get(
            "message_id"
        )
    )

    source_chat_id = (
        forward.get(
            "chat_id"
        )
    )

    source_username = (
        clean_username(
            forward.get("username")
        )
    )

    source_title = (
        forward.get("title")
        or "کانال منبع"
    )

    if not source_message_id:

        send_message(
            chat.get("id"),
            "❌ نتوانستم شناسه پیام فورواردشده را پیدا کنم."
        )

        return

    if not source_chat_id:

        send_message(
            chat.get("id"),
            "❌ نتوانستم کانال منبع را تشخیص دهم."
        )

        return

    message_title = get_message_title(
        message
    )

    source_link = build_bale_message_link(
        source_username,
        source_chat_id,
        source_message_id
    )

    set_setting(
        "selected_source_message_id",
        source_message_id
    )

    set_setting(
        "selected_source_channel_id",
        source_chat_id
    )

    set_setting(
        "selected_source_username",
        source_username or ""
    )

    set_setting(
        "selected_source_title",
        source_title
    )

    set_setting(
        "selected_source_message_title",
        message_title
    )

    set_setting(
        "selected_source_link",
        source_link or ""
    )

    text = (
        "✅ پیام منبع انتخاب شد.\n\n"
        f"📢 کانال: {safe_text(source_title)}\n"
        f"🆔 شناسه کانال: {source_chat_id}\n"
        f"📝 عنوان: {message_title}\n"
        f"🔢 شناسه پیام: {source_message_id}"
    )

    if source_link:

        text += (
            f"\n🔗 لینک پیام:\n"
            f"{source_link}"
        )

    text += (
        "\n\n"
        "اکنون /report را ارسال کنید."
    )

    send_message(
        chat.get("id"),
        text
    )


# =========================================================
# RESOLVE DESTINATION
# =========================================================

def resolve_destination_channel(
    chat
):

    if not chat:
        return None

    chat_id = chat.get(
        "id"
    )

    if chat_id is None:
        return None

    chat_id = str(chat_id)

    try:

        result = (
            supabase
            .table("channels")
            .select(
                "id,chat_id,username,title,"
                "active,manually_disabled"
            )
            .eq(
                "chat_id",
                chat_id
            )
            .limit(1)
            .execute()
        )

        if result.data:

            return result.data[0]

    except Exception as e:

        print(
            "RESOLVE DESTINATION ERROR:",
            e
        )

    return None


# =========================================================
# SAVE REPOST
# =========================================================

def save_repost(
    source_channel_id,
    source_username,
    source_message_id,
    destination_channel_id,
    destination_username,
    destination_message_id,
    destination_title,
    message_title
):

    try:

        data = {
            "source_channel_id": str(
                source_channel_id
            ),
            "source_username": clean_username(
                source_username
            ),
            "source_message_id": str(
                source_message_id
            ),
            "destination_channel_id": str(
                destination_channel_id
            ),
            "destination_username": clean_username(
                destination_username
            ),
            "destination_message_id": str(
                destination_message_id
            ),
            "destination_title": destination_title,
            "message_title": message_title,
            "created_at": now_iso()
        }

        (
            supabase
            .table("reposts")
            .insert(data)
            .execute()
        )

        return True

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            e
        )

        return False


# =========================================================
# PROCESS DESTINATION MESSAGE
# =========================================================

def process_channel_message(
    message
):

    if not message:
        return

    chat = (
        message.get("chat")
        or {}
    )

    chat_type = chat.get(
        "type"
    )

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return

    chat_id = chat.get(
        "id"
    )

    message_id = message.get(
        "message_id"
    )

    if chat_id is None:
        return

    if message_id is None:
        return

    # -----------------------------------------------------
    # ثبت خودکار
    # -----------------------------------------------------

    auto_register_chat(
        chat
    )

    # -----------------------------------------------------
    # دریافت مقصد
    # -----------------------------------------------------

    destination = resolve_destination_channel(
        chat
    )

    if not destination:

        print(
            "DESTINATION NOT FOUND:",
            chat_id
        )

        return

    # -----------------------------------------------------
    # اگر دستی حذف شده
    # -----------------------------------------------------

    if destination.get(
        "manually_disabled"
    ) is True:

        print(
            "DESTINATION MANUALLY DISABLED:",
            chat_id
        )

        return

    if not destination.get(
        "active"
    ):

        return

    # -----------------------------------------------------
    # منبع
    # -----------------------------------------------------

    source_message_id = get_setting(
        "selected_source_message_id"
    )

    source_channel_id = get_setting(
        "selected_source_channel_id"
    )

    source_username = get_setting(
        "selected_source_username"
    )

    if not source_message_id:
        return

    if not source_channel_id:
        return

    # -----------------------------------------------------
    # عنوان
    # -----------------------------------------------------

    message_title = get_message_title(
        message
    )

    # -----------------------------------------------------
    # Duplicate
    # -----------------------------------------------------

    try:

        existing = (
            supabase
            .table("reposts")
            .select("id")
            .eq(
                "source_channel_id",
                str(source_channel_id)
            )
            .eq(
                "source_message_id",
                str(source_message_id)
            )
            .eq(
                "destination_channel_id",
                str(chat_id)
            )
            .eq(
                "destination_message_id",
                str(message_id)
            )
            .limit(1)
            .execute()
        )

        if existing.data:

            return

    except Exception as e:

        print(
            "CHECK DUPLICATE ERROR:",
            e
        )

    # -----------------------------------------------------
    # ذخیره
    # -----------------------------------------------------

    saved = save_repost(
        source_channel_id,
        source_username,
        source_message_id,
        chat_id,
        chat.get("username"),
        message_id,
        (
            chat.get("title")
            or destination.get("title")
            or "بدون عنوان"
        ),
        message_title
    )

    if saved:

        notify_admins_repost(
            source_channel_id,
            source_username,
            source_message_id,
            destination,
            chat,
            message_id,
            message_title
        )


# =========================================================
# NOTIFY ADMINS
# =========================================================

def notify_admins_repost(
    source_channel_id,
    source_username,
    source_message_id,
    destination,
    chat,
    destination_message_id,
    message_title
):

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("user_id")
            .eq(
                "active",
                True
            )
            .execute()
        )

        admin_ids = [
            row.get("user_id")
            for row in (
                result.data or []
            )
            if row.get("user_id")
        ]

        if OWNER_ID:

            admin_ids.append(
                str(OWNER_ID)
            )

        admin_ids = list(
            dict.fromkeys(
                str(x)
                for x in admin_ids
            )
        )

        destination_chat_id = (
            destination.get(
                "chat_id"
            )
            or chat.get("id")
        )

        destination_username = (
            destination.get(
                "username"
            )
            or chat.get("username")
        )

        destination_title = (
            destination.get(
                "title"
            )
            or chat.get("title")
            or "بدون عنوان"
        )

        destination_link = (
            build_bale_message_link(
                destination_username,
                destination_chat_id,
                destination_message_id
            )
        )

        source_link = (
            build_bale_message_link(
                source_username,
                source_channel_id,
                source_message_id
            )
        )

        iran_time = format_iran_datetime(
            now_iso()
        )

        text = (
            "🚨 بازنشر جدید شناسایی شد\n\n"
            f"📢 مقصد: {destination_title}\n"
        )

        if destination_username:

            text += (
                f"👤 @{destination_username}\n"
            )

        text += (
            f"🆔 شناسه مقصد: "
            f"{destination_chat_id}\n"
            f"📝 عنوان پیام: "
            f"{message_title}\n"
            f"🕐 زمان: "
            f"{iran_time}\n"
        )

        if source_link:

            text += (
                f"\n🔗 پیام منبع:\n"
                f"{source_link}\n"
            )

        if destination_link:

            text += (
                f"\n🔗 پیام مقصد:\n"
                f"{destination_link}"
            )

        for admin_id in admin_ids:

            send_message(
                admin_id,
                text
            )

    except Exception as e:

        print(
            "NOTIFY ADMINS ERROR:",
            e
        )


# =========================================================
# REPORT
# =========================================================

def report_reposts(
    chat_id
):

    source_channel_id = get_setting(
        "selected_source_channel_id"
    )

    source_message_id = get_setting(
        "selected_source_message_id"
    )

    source_username = get_setting(
        "selected_source_username"
    )

    source_title = get_setting(
        "selected_source_title"
    )

    source_message_title = get_setting(
        "selected_source_message_title"
    )

    if (
        not source_channel_id
        or not source_message_id
    ):

        send_message(
            chat_id,
            "📭 هنوز پیام منبعی انتخاب نشده است.\n\n"
            "ابتدا پیام موردنظر را Forward کنید."
        )

        return

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_channel_id",
                str(source_channel_id)
            )
            .eq(
                "source_message_id",
                str(source_message_id)
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        rows = (
            result.data
            or []
        )

        source_link = build_bale_message_link(
            source_username,
            source_channel_id,
            source_message_id
        )

        header = (
            "📊 گزارش بازنشر\n\n"
            f"📢 منبع: "
            f"{safe_text(source_title)}\n"
            f"📝 پیام: "
            f"{safe_text(source_message_title)}\n"
            f"🔢 شناسه پیام: "
            f"{source_message_id}\n"
        )

        if source_link:

            header += (
                f"🔗 لینک منبع:\n"
                f"{source_link}\n"
            )

        if not rows:

            send_message(
                chat_id,
                header
                + "\n"
                + "❌ تاکنون بازنشری برای این پیام ثبت نشده است."
            )

            return

        header += (
            f"\n📌 تعداد بازنشرها: "
            f"{to_persian_digits(len(rows))}\n\n"
        )

        lines = []

        for index, row in enumerate(
            rows,
            start=1
        ):

            destination_title = (
                row.get(
                    "destination_title"
                )
                or "بدون عنوان"
            )

            destination_username = (
                clean_username(
                    row.get(
                        "destination_username"
                    )
                )
            )

            destination_channel_id = (
                row.get(
                    "destination_channel_id"
                )
            )

            destination_message_id = (
                row.get(
                    "destination_message_id"
                )
            )

            destination_link = (
                build_bale_message_link(
                    destination_username,
                    destination_channel_id,
                    destination_message_id
                )
            )

            created_at = format_iran_datetime(
                row.get(
                    "created_at"
                )
            )

            block = (
                f"🔹 بازنشر "
                f"{to_persian_digits(index)}\n"
                f"📢 {destination_title}\n"
                f"🕐 {created_at}\n"
            )

            if destination_username:

                block += (
                    f"👤 @{destination_username}\n"
                )

            if destination_link:

                block += (
                    f"🔗 {destination_link}\n"
                )

            lines.append(
                block
            )

        send_message(
            chat_id,
            header
            + "\n".join(lines)
        )

    except Exception as e:

        print(
            "REPORT ERROR:",
            e
        )

        send_message(
            chat_id,
            "❌ خطا در تهیه گزارش."
        )


# =========================================================
# STATUS
# =========================================================

def show_status(
    chat_id
):

    try:

        channels_result = (
            supabase
            .table("channels")
            .select(
                "id,chat_id,title,username,"
                "active,manually_disabled"
            )
            .execute()
        )

        channels = (
            channels_result.data
            or []
        )

        active_count = sum(
            1
            for x in channels
            if (
                x.get("active")
                and not x.get(
                    "manually_disabled"
                )
            )
        )

        repost_result = (
            supabase
            .table("reposts")
            .select("id")
            .execute()
        )

        repost_count = len(
            repost_result.data
            or []
        )

        source_title = get_setting(
            "selected_source_title"
        )

        source_message_id = get_setting(
            "selected_source_message_id"
        )

        text = (
            "📊 وضعیت ربات\n\n"
            f"📢 تعداد مقصدها: "
            f"{to_persian_digits(len(channels))}\n"
            f"🟢 مقصدهای فعال: "
            f"{to_persian_digits(active_count)}\n"
            f"🔁 تعداد بازنشرها: "
            f"{to_persian_digits(repost_count)}\n\n"
            f"🎯 منبع انتخاب‌شده: "
            f"{safe_text(source_title)}\n"
            f"🔢 شناسه پیام: "
            f"{safe_text(source_message_id)}"
        )

        send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "STATUS ERROR:",
            e
        )

        send_message(
            chat_id,
            "❌ خطا در دریافت وضعیت."
        )


# =========================================================
# START MENU
# =========================================================

def start_menu(
    chat_id
):

    if is_owner(chat_id):

        text = (
            "👑 پنل مدیریت ربات\n\n"

            "📊 /report\n"
            "گزارش بازنشر پیام انتخاب‌شده\n\n"

            "📋 /channels\n"
            "فهرست گروه‌ها و کانال‌ها\n\n"

            "➕ /addchannel @username\n"
            "افزودن دستی مقصد\n\n"

            "🗑 /removechannel @username\n"
            "حذف دستی مقصد\n\n"

            "📈 /status\n"
            "وضعیت ربات\n\n"

            "👥 /admins\n"
            "فهرست مدیران\n\n"

            "➕ /addadmin USER_ID\n"
            "افزودن مدیر\n\n"

            "➖ /removeadmin USER_ID\n"
            "حذف مدیر\n\n"

            "🆔 /myid\n"
            "شناسه کاربری"
        )

    elif is_admin(chat_id):

        text = (
            "🛠 پنل مدیریت\n\n"

            "📊 /report\n"
            "گزارش بازنشر\n\n"

            "📋 /channels\n"
            "فهرست مقصدها\n\n"

            "➕ /addchannel @username\n"
            "افزودن دستی مقصد\n\n"

            "🗑 /removechannel @username\n"
            "حذف دستی مقصد\n\n"

            "📈 /status\n"
            "وضعیت ربات\n\n"

            "🆔 /myid\n"
            "شناسه کاربری"
        )

    else:

        text = (
            "سلام 👋\n\n"
            "🆔 برای مشاهده شناسه کاربری "
            "خود /myid را ارسال کنید."
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# COMMAND PROCESSOR
# =========================================================

def process_command(
    chat_id,
    text,
    username=None
):

    if not text:
        return

    parts = (
        text.strip()
        .split()
    )

    if not parts:
        return

    command = parts[0].lower()

    if "@" in command:

        command = (
            command
            .split("@", 1)[0]
        )

    args = parts[1:]

    # =====================================================
    # MY ID
    # =====================================================

    if command == "/myid":

        show_my_id(
            chat_id
        )

        return

    # =====================================================
    # ACCESS
    # =====================================================

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    # =====================================================
    # START
    # =====================================================

    if command == "/start":

        start_menu(
            chat_id
        )

        return

    # =====================================================
    # REPORT
    # =====================================================

    if command == "/report":

        report_reposts(
            chat_id
        )

        return

    # =====================================================
    # CHANNELS
    # =====================================================

    if command == "/channels":

        list_channels(
            chat_id
        )

        return

    # =====================================================
    # ADD CHANNEL
    # =====================================================

    if command == "/addchannel":

        if not args:

            send_message(
                chat_id,
                "❌ username یا شناسه مقصد را وارد کنید.\n\n"
                "مثال:\n"
                "/addchannel @channel"
            )

            return

        manual_add_channel(
            chat_id,
            args[0]
        )

        return

    # =====================================================
    # REMOVE CHANNEL
    # =====================================================

    if command == "/removechannel":

        if not args:

            send_message(
                chat_id,
                "❌ username یا شناسه مقصد را وارد کنید.\n\n"
                "مثال:\n"
                "/removechannel @channel"
            )

            return

        manual_remove_channel(
            chat_id,
            args[0]
        )

        return

    # =====================================================
    # STATUS
    # =====================================================

    if command == "/status":

        show_status(
            chat_id
        )

        return

    # =====================================================
    # ADMINS
    # =====================================================

    if command == "/admins":

        if not is_owner(chat_id):

            deny_access(
                chat_id
            )

            return

        list_admins(
            chat_id
        )

        return

    # =====================================================
    # ADD ADMIN
    # =====================================================

    if command == "/addadmin":

        if not is_owner(chat_id):

            deny_access(
                chat_id
            )

            return

        if not args:

            send_message(
                chat_id,
                "❌ شناسه کاربر را وارد کنید.\n\n"
                "مثال:\n"
                "/addadmin 123456789"
            )

            return

        target = args[0]

        if target.isdigit():

            target_user_id = target
            target_username = None

        else:

            found = find_user_by_username(
                target
            )

            if not found:

                send_message(
                    chat_id,
                    "❌ کاربر در فهرست کاربران ربات پیدا نشد."
                )

                return

            target_user_id = found.get(
                "user_id"
            )

            target_username = found.get(
                "username"
            )

        if str(target_user_id) == str(
            OWNER_ID
        ):

            send_message(
                chat_id,
                "ℹ️ این کاربر مالک ربات است."
            )

            return

        if add_admin(
            target_user_id,
            target_username
        ):

            send_message(
                chat_id,
                "✅ مدیر اضافه شد.\n\n"
                f"🆔 {target_user_id}"
            )

        else:

            send_message(
                chat_id,
                "❌ افزودن مدیر انجام نشد."
            )

        return

    # =====================================================
    # REMOVE ADMIN
    # =====================================================

    if command == "/removeadmin":

        if not is_owner(chat_id):

            deny_access(
                chat_id
            )

            return

        if not args:

            send_message(
                chat_id,
                "❌ شناسه مدیر را وارد کنید."
            )

            return

        target_user_id = args[0]

        if str(target_user_id) == str(
            OWNER_ID
        ):

            send_message(
                chat_id,
                "❌ مالک ربات قابل حذف نیست."
            )

            return

        if remove_admin(
            target_user_id
        ):

            send_message(
                chat_id,
                "✅ دسترسی مدیر حذف شد."
            )

        else:

            send_message(
                chat_id,
                "❌ حذف مدیر انجام نشد."
            )

        return

    # =====================================================
    # UNKNOWN
    # =====================================================

    send_message(
        chat_id,
        "❓ دستور نامعتبر است.\n\n"
        "برای مشاهده راهنما /start را ارسال کنید."
    )


# =========================================================
# UPDATE PROCESSOR
# =========================================================

def process_update(
    update
):

    if not update:
        return

    print(
        "\n========================================"
    )

    print(
        "NEW UPDATE:"
    )

    print(
        update
    )

    # =====================================================
    # MY CHAT MEMBER
    # =====================================================

    my_chat_member = update.get(
        "my_chat_member"
    )

    if my_chat_member:

        chat = (
            my_chat_member.get(
                "chat"
            )
            or {}
        )

        chat_type = chat.get(
            "type"
        )

        print(
            "MY_CHAT_MEMBER CHAT:",
            chat
        )

        if chat_type in (
            "group",
            "supergroup",
            "channel"
        ):

            new_member = (
                my_chat_member.get(
                    "new_chat_member"
                )
                or {}
            )

            status = new_member.get(
                "status"
            )

            print(
                "BOT MEMBERSHIP STATUS:",
                status
            )

            if status not in (
                "left",
                "kicked"
            ):

                auto_register_chat(
                    chat
                )

            else:

                deactivate_chat(
                    chat.get("id")
                )

        return

    # =====================================================
    # MESSAGE
    # =====================================================

    message = update.get(
        "message"
    )

    # =====================================================
    # CHANNEL POST
    # =====================================================

    if not message:

        message = update.get(
            "channel_post"
        )

    if not message:

        print(
            "NO MESSAGE / CHANNEL_POST"
        )

        return

    # =====================================================
    # CHAT
    # =====================================================

    chat = (
        message.get("chat")
        or {}
    )

    chat_id = chat.get(
        "id"
    )

    chat_type = chat.get(
        "type"
    )

    if chat_id is None:

        print(
            "CHAT ID MISSING"
        )

        return

    print(
        "CHAT TYPE:",
        chat_type
    )

    print(
        "CHAT ID:",
        chat_id
    )

    print(
        "CHAT TITLE:",
        chat.get("title")
    )

    print(
        "CHAT USERNAME:",
        chat.get("username")
    )

    # =====================================================
    # PRIVATE
    # =====================================================

    if chat_type == "private":

        save_bot_user(
            chat
        )

        text = (
            message.get("text")
            or ""
        )

        first_command = ""

        if text.strip():

            first_command = (
                text.strip()
                .split()[0]
                .lower()
            )

            if "@" in first_command:

                first_command = (
                    first_command
                    .split("@", 1)[0]
                )

        # /myid آزاد
        if first_command == "/myid":

            show_my_id(
                chat_id
            )

            return

        # Forward
        forward = extract_forward(
            message
        )

        if forward.get(
            "message_id"
        ):

            if not is_admin(
                chat_id
            ):

                deny_access(
                    chat_id
                )

                return

            process_private_forward(
                message
            )

            return

        if text:

            process_command(
                chat_id,
                text,
                chat.get("username")
            )

        return

    # =====================================================
    # GROUP / SUPERGROUP / CHANNEL
    # =====================================================

    if chat_type in (
        "group",
        "supergroup",
        "channel"
    ):

        print(
            "📢 GROUP/CHANNEL UPDATE DETECTED"
        )

        # ثبت خودکار
        auto_register_chat(
            chat
        )

        # پردازش گزارش
        process_channel_message(
            message
        )

        return

    print(
        "UNKNOWN CHAT TYPE:",
        chat_type
    )


# =========================================================
# DEACTIVATE CHAT
# =========================================================

def deactivate_chat(
    chat_id
):

    if chat_id is None:
        return

    try:

        (
            supabase
            .table("channels")
            .update({
                "active": False
            })
            .eq(
                "chat_id",
                str(chat_id)
            )
            .execute()
        )

        print(
            "CHAT DEACTIVATED:",
            chat_id
        )

    except Exception as e:

        print(
            "DEACTIVATE CHAT ERROR:",
            e
        )


# =========================================================
# GET UPDATES
# =========================================================

def get_updates(
    offset=None
):

    data = {
        "timeout": 30,

        "allowed_updates": [
            "message",
            "channel_post",
            "my_chat_member"
        ]
    }

    if offset is not None:

        data["offset"] = offset

    return bale_request(
        "getUpdates",
        data
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "========================================"
    )

    print(
        "BALE REPOST MONITOR"
    )

    print(
        "AUTO GROUP/CHANNEL REGISTRATION: ON"
    )

    print(
        "MANUAL CHANNEL MANAGEMENT: ON"
    )

    print(
        "========================================"
    )

    offset = None

    while True:

        try:

            result = get_updates(
                offset
            )

            if not result.get("ok"):

                time.sleep(3)

                continue

            updates = (
                result.get("result")
                or []
            )

            for update in updates:

                try:

                    update_id = update.get(
                        "update_id"
                    )

                    if update_id is not None:

                        offset = (
                            update_id + 1
                        )

                    process_update(
                        update
                    )

                except Exception as e:

                    print(
                        "UPDATE PROCESS ERROR:",
                        repr(e)
                    )

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                repr(e)
            )

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
