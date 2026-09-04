import os
import time
import hashlib
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


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

BALE_API = f"https://tapi.bale.ai/bot{BALE_TOKEN}"

IRAN_TZ = ZoneInfo("Asia/Tehran")

OWNER_ID = None


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


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def to_persian_digits(value):
    if value is None:
        return ""

    table = str.maketrans(
        "0123456789",
        "۰۱۲۳۴۵۶۷۸۹"
    )

    return str(value).translate(table)


# =========================================================
# GREGORIAN -> JALALI
# =========================================================

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

    if gm > 1 and (
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
            dt = dt.replace(tzinfo=timezone.utc)

        dt = dt.astimezone(IRAN_TZ)

        jy, jm, jd = gregorian_to_jalali(
            dt.year,
            dt.month,
            dt.day
        )

        date_text = (
            f"{jy:04d}/"
            f"{jm:02d}/"
            f"{jd:02d}"
        )

        time_text = (
            f"{dt.hour:02d}:"
            f"{dt.minute:02d}"
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
            return None

        return result.get("result")

    except Exception as e:

        print(
            "BALE REQUEST ERROR:",
            method,
            repr(e)
        )

        return None


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

    return bale_request(
        "getChat",
        {
            "chat_id": chat_id
        }
    )


# =========================================================
# BALE MESSAGE LINK
# =========================================================

def build_bale_message_link(
    username,
    chat_id,
    message_id
):

    username = clean_username(username)

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
            return result.data[0].get("value")

    except Exception as e:

        print(
            "GET SETTING ERROR:",
            key,
            repr(e)
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
                .eq("key", key)
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
            repr(e)
        )

        return False


def load_owner():

    global OWNER_ID

    value = get_setting("owner_id")

    if value:
        OWNER_ID = str(value).strip()
    else:
        OWNER_ID = None

    print(
        "OWNER_ID:",
        OWNER_ID
    )


# =========================================================
# ACCESS CONTROL
# =========================================================

def is_owner(user_id):

    if not OWNER_ID:
        return False

    return str(user_id) == str(OWNER_ID)


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
            .eq("user_id", str(user_id))
            .eq("active", True)
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
        "⛔ شما دسترسی مدیریت این ربات را ندارید."
    )


# =========================================================
# SAVE USERS
# =========================================================

def save_bot_user(chat):

    if not chat:
        return

    if chat.get("type") != "private":
        return

    user_id = chat.get("id")

    if user_id is None:
        return

    data = {
        "user_id": str(user_id),
        "username": clean_username(
            chat.get("username")
        ),
        "first_name": chat.get("first_name"),
        "last_name": chat.get("last_name"),
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
                    "id",
                    existing.data[0]["id"]
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
            "SAVE USER ERROR:",
            repr(e)
        )


# =========================================================
# CHANNEL AUTO REGISTRATION
# =========================================================

def auto_register_chat(chat):

    if not chat:
        return False

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return False

    chat_id = chat.get("id")

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
                "active,manually_disabled,bot_member"
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
                row.get("manually_disabled")
                is True
            )

            bot_member = row.get(
                "bot_member",
                True
            )

            update_data = {
                "username": username,
                "title": title,
                "chat_id": chat_id
            }

            # اگر مدیر قبلاً کانال را دستی غیرفعال کرده
            # پیام‌های بعدی نباید دوباره آن را فعال کنند.
            if manually_disabled:

                update_data["active"] = False

            # اگر ربات قبلاً از کانال خارج شده
            # پیام‌های باقی‌مانده نباید باعث فعال شدن شوند.
            elif bot_member is False:

                update_data["active"] = False

            else:

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

            return True

        # -------------------------------------------------
        # اگر با chat_id پیدا نشد، با username جستجو کن
        # -------------------------------------------------

        if username:

            result = (
                supabase
                .table("channels")
                .select(
                    "id,chat_id,username,title,"
                    "active,manually_disabled,bot_member"
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
                    row.get("manually_disabled")
                    is True
                )

                update_data = {
                    "chat_id": chat_id,
                    "username": username,
                    "title": title
                }

                if manually_disabled:
                    update_data["active"] = False
                else:
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

                return True

        # -------------------------------------------------
        # کانال جدید
        # -------------------------------------------------

        (
            supabase
            .table("channels")
            .insert({
                "chat_id": chat_id,
                "username": username,
                "title": title,
                "active": True,
                "manually_disabled": False,
                "bot_member": True
            })
            .execute()
        )

        print(
            "🟢 NEW CHAT REGISTERED:",
            chat_id,
            title
        )

        return True

    except Exception as e:

        print(
            "AUTO REGISTER CHAT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# DEACTIVATE CHAT
# =========================================================

def deactivate_chat(chat_id):

    if chat_id is None:
        return

    try:

        (
            supabase
            .table("channels")
            .update({
                "active": False,
                "bot_member": False
            })
            .eq(
                "chat_id",
                str(chat_id)
            )
            .execute()
        )

        print(
            "🔴 CHAT DEACTIVATED:",
            chat_id
        )

    except Exception as e:

        print(
            "DEACTIVATE CHAT ERROR:",
            repr(e)
        )


# =========================================================
# LIST ACTIVE CHANNELS
# =========================================================

def list_channels(chat_id):

    if not is_admin(chat_id):

        deny_access(chat_id)
        return

    try:

        result = (
            supabase
            .table("channels")
            .select(
                "id,chat_id,username,title,"
                "active,manually_disabled,bot_member"
            )
            .eq("active", True)
            .eq("manually_disabled", False)
            .eq("bot_member", True)
            .order("title")
            .execute()
        )

        rows = result.data or []

        if not rows:

            send_message(
                chat_id,
                "📭 در حال حاضر هیچ کانال یا گروه فعالی ثبت نشده است."
            )

            return

        lines = [
            "📋 <b>کانال‌ها و گروه‌های فعال</b>",
            ""
        ]

        for index, row in enumerate(
            rows,
            start=1
        ):

            title = row.get("title") or "-"

            username = clean_username(
                row.get("username")
            )

            channel_chat_id = row.get(
                "chat_id"
            )

            if username:
                name = f"@{username}"
            else:
                name = str(
                    channel_chat_id or "-"
                )

            lines.append(
                f"{to_persian_digits(index)}. "
                f"{title}\n"
                f"   {name}"
            )

        send_message(
            chat_id,
            "\n".join(lines)
        )

    except Exception as e:

        print(
            "LIST CHANNELS ERROR:",
            repr(e)
        )

        send_message(
            chat_id,
            "❌ خطا در دریافت لیست کانال‌ها."
        )


# =========================================================
# MANUAL ADD CHANNEL
# =========================================================

def manual_add_channel(
    admin_chat_id,
    target
):

    if not is_admin(admin_chat_id):

        deny_access(admin_chat_id)
        return

    target = target.strip()

    if not target:

        send_message(
            admin_chat_id,
            "فرمت صحیح:\n"
            "/addchannel @channel\n"
            "یا\n"
            "/addchannel CHAT_ID"
        )

        return

    if target.startswith("@"):

        lookup = target

    else:

        lookup = target

    chat = get_chat(lookup)

    if not chat:

        send_message(
            admin_chat_id,
            "❌ کانال یا گروه پیدا نشد.\n\n"
            "مطمئن شوید ربات داخل آن کانال/گروه عضو است "
            "و دسترسی لازم را دارد."
        )

        return

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):

        send_message(
            admin_chat_id,
            "❌ فقط گروه، سوپرگروه و کانال قابل ثبت هستند."
        )

        return

    channel_chat_id = chat.get("id")

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or username
        or str(channel_chat_id)
    )

    try:

        existing = (
            supabase
            .table("channels")
            .select("id")
            .eq(
                "chat_id",
                str(channel_chat_id)
            )
            .limit(1)
            .execute()
        )

        data = {
            "chat_id": str(channel_chat_id),
            "username": username,
            "title": title,
            "active": True,
            "manually_disabled": False,
            "bot_member": True
        }

        if existing.data:

            (
                supabase
                .table("channels")
                .update(data)
                .eq(
                    "id",
                    existing.data[0]["id"]
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

        display_name = (
            f"@{username}"
            if username
            else str(channel_chat_id)
        )

        send_message(
            admin_chat_id,
            "✅ کانال/گروه با موفقیت فعال شد.\n\n"
            f"📌 {title}\n"
            f"🔗 {display_name}"
        )

    except Exception as e:

        print(
            "MANUAL ADD CHANNEL ERROR:",
            repr(e)
        )

        send_message(
            admin_chat_id,
            "❌ خطا در ثبت کانال."
        )


# =========================================================
# MANUAL REMOVE CHANNEL
# =========================================================

def manual_remove_channel(
    admin_chat_id,
    target
):

    if not is_admin(admin_chat_id):

        deny_access(admin_chat_id)
        return

    target = target.strip()

    if not target:

        send_message(
            admin_chat_id,
            "فرمت صحیح:\n"
            "/removechannel @channel\n"
            "یا\n"
            "/removechannel CHAT_ID"
        )

        return

    username = None

    if target.startswith("@"):

        username = clean_username(target)

        query = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "username",
                username
            )
            .limit(1)
            .execute()
        )

    else:

        query = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "chat_id",
                str(target)
            )
            .limit(1)
            .execute()
        )

    if not query.data:

        send_message(
            admin_chat_id,
            "❌ این کانال در سیستم پیدا نشد."
        )

        return

    row = query.data[0]

    try:

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

        title = row.get("title") or "-"

        send_message(
            admin_chat_id,
            "✅ کانال از لیست فعال حذف شد.\n\n"
            f"📌 {title}\n\n"
            "ℹ️ سوابق بازنشر این کانال حذف نشده‌اند."
        )

    except Exception as e:

        print(
            "MANUAL REMOVE CHANNEL ERROR:",
            repr(e)
        )

        send_message(
            admin_chat_id,
            "❌ خطا در حذف کانال."
        )


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

def list_admins(chat_id):

    if not is_owner(chat_id):

        deny_access(chat_id)
        return

    try:

        result = (
            supabase
            .table("bot_admins")
            .select(
                "user_id,username,first_name,active"
            )
            .eq(
                "active",
                True
            )
            .order("first_name")
            .execute()
        )

        rows = result.data or []

        lines = [
            "👮 <b>مدیران ربات</b>",
            ""
        ]

        if OWNER_ID:

            lines.append(
                f"👑 مالک: "
                f"<code>{OWNER_ID}</code>"
            )

        for index, row in enumerate(
            rows,
            start=1
        ):

            user_id = row.get(
                "user_id"
            )

            username = clean_username(
                row.get("username")
            )

            first_name = (
                row.get("first_name")
                or "-"
            )

            if username:
                display = f"@{username}"
            else:
                display = first_name

            lines.append(
                f"{to_persian_digits(index)}. "
                f"{display} - "
                f"<code>{user_id}</code>"
            )

        send_message(
            chat_id,
            "\n".join(lines)
        )

    except Exception as e:

        print(
            "LIST ADMINS ERROR:",
            repr(e)
        )


def add_admin(
    owner_chat_id,
    target
):

    if not is_owner(owner_chat_id):

        deny_access(owner_chat_id)
        return

    target = target.strip()

    if not target:

        send_message(
            owner_chat_id,
            "فرمت:\n"
            "/addadmin USER_ID\n\n"
            "یا نام کاربری ثبت‌شده"
        )

        return

    user_id = None
    user = None

    # ---------------------------------------------
    # numeric user id
    # ---------------------------------------------

    if target.lstrip("-").isdigit():

        user_id = str(target)

    else:

        username = clean_username(target)

        try:

            result = (
                supabase
                .table("bot_users")
                .select("*")
                .eq(
                    "username",
                    username
                )
                .limit(1)
                .execute()
            )

            if result.data:

                user = result.data[0]

                user_id = str(
                    user.get("user_id")
                )

        except Exception as e:

            print(
                "FIND USER ERROR:",
                repr(e)
            )

    if not user_id:

        send_message(
            owner_chat_id,
            "❌ کاربر پیدا نشد.\n\n"
            "بهتر است کاربر ابتدا /myid را برای ربات ارسال کند."
        )

        return

    try:

        existing = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq(
                "user_id",
                user_id
            )
            .limit(1)
            .execute()
        )

        data = {
            "user_id": user_id,
            "username": (
                user.get("username")
                if user
                else None
            ),
            "first_name": (
                user.get("first_name")
                if user
                else None
            ),
            "active": True
        }

        if existing.data:

            (
                supabase
                .table("bot_admins")
                .update(data)
                .eq(
                    "id",
                    existing.data[0]["id"]
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

        send_message(
            owner_chat_id,
            "✅ کاربر با موفقیت مدیر شد.\n\n"
            f"👤 شناسه: <code>{user_id}</code>"
        )

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            repr(e)
        )

        send_message(
            owner_chat_id,
            "❌ خطا در افزودن مدیر."
        )


def remove_admin(
    owner_chat_id,
    target
):

    if not is_owner(owner_chat_id):

        deny_access(owner_chat_id)
        return

    target = target.strip()

    if not target:

        send_message(
            owner_chat_id,
            "فرمت:\n"
            "/removeadmin USER_ID"
        )

        return

    user_id = str(target)

    try:

        (
            supabase
            .table("bot_admins")
            .update({
                "active": False
            })
            .eq(
                "user_id",
                user_id
            )
            .execute()
        )

        send_message(
            owner_chat_id,
            "✅ دسترسی مدیر حذف شد."
        )

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            repr(e)
        )

        send_message(
            owner_chat_id,
            "❌ خطا در حذف مدیر."
        )


# =========================================================
# MY ID
# =========================================================

def show_my_id(chat_id):

    send_message(
        chat_id,
        "🆔 شناسه کاربری شما:\n\n"
        f"<code>{chat_id}</code>\n\n"
        "این عدد را برای مدیر ربات ارسال کنید."
    )


# =========================================================
# MESSAGE TITLE
# =========================================================

def get_message_title(message):

    if not message:
        return "بدون عنوان"

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    text = str(text).strip()

    if not text:

        return "بدون عنوان"

    first_line = text.splitlines()[0].strip()

    if len(first_line) > 100:

        first_line = first_line[:100] + "..."

    return first_line


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(message):

    if not message:
        return {}

    forward = (
        message.get("forward_from_chat")
        or message.get("forward_from")
        or {}
    )

    return {
        "chat": forward,
        "message_id": message.get(
            "forward_from_message_id"
        )
    }


# =========================================================
# SOURCE SELECTION
# =========================================================

def process_private_forward(message):

    forward = extract_forward(message)

    source_chat = forward.get(
        "chat"
    ) or {}

    source_message_id = forward.get(
        "message_id"
    )

    if not source_message_id:

        send_message(
            message["chat"]["id"],
            "❌ پیام فورواردشده معتبر نیست."
        )

        return

    source_channel_id = source_chat.get(
        "id"
    )

    source_username = clean_username(
        source_chat.get("username")
    )

    source_title = (
        source_chat.get("title")
        or source_username
        or str(source_channel_id or "")
    )

    if source_channel_id is None:

        send_message(
            message["chat"]["id"],
            "❌ اطلاعات کانال مبدأ دریافت نشد."
        )

        return

    set_setting(
        "selected_source_channel_id",
        source_channel_id
    )

    set_setting(
        "selected_source_message_id",
        source_message_id
    )

    set_setting(
        "selected_source_username",
        source_username or ""
    )

    set_setting(
        "selected_source_title",
        source_title
    )

    link = build_bale_message_link(
        source_username,
        source_channel_id,
        source_message_id
    )

    text = (
        "✅ <b>پیام مبدأ با موفقیت انتخاب شد.</b>\n\n"
        f"📌 عنوان: {source_title}\n"
        f"🆔 شناسه کانال: <code>{source_channel_id}</code>\n"
        f"🆔 شناسه پیام: <code>{source_message_id}</code>"
    )

    if link:

        text += (
            f"\n\n🔗 <a href=\"{link}\">مشاهده پست مبدأ</a>"
        )

    send_message(
        message["chat"]["id"],
        text
    )


# =========================================================
# DUPLICATE CHECK
# =========================================================

def repost_exists(
    source_channel_id,
    source_message_id,
    destination_channel_id
):

    try:

        result = (
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
                str(destination_channel_id)
            )
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as e:

        print(
            "REPOST EXISTS ERROR:",
            repr(e)
        )

        return False


# =========================================================
# PROCESS CHANNEL MESSAGE
# =========================================================

def process_channel_message(message):

    if not message:
        return

    chat = message.get("chat") or {}

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return

    destination_channel_id = chat.get(
        "id"
    )

    if destination_channel_id is None:
        return

    # اول ثبت/بررسی کانال
    auto_register_chat(chat)

    # -----------------------------------------------------
    # دریافت مقصد
    # -----------------------------------------------------

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "chat_id",
                str(destination_channel_id)
            )
            .limit(1)
            .execute()
        )

        if not result.data:
            return

        destination = result.data[0]

    except Exception as e:

        print(
            "GET DESTINATION ERROR:",
            repr(e)
        )

        return

    # -----------------------------------------------------
    # اگر غیرفعال است، هیچ کاری نکن
    # -----------------------------------------------------

    if destination.get("active") is not True:
        return

    if destination.get(
        "manually_disabled"
    ) is True:
        return

    if destination.get(
        "bot_member"
    ) is False:
        return

    # -----------------------------------------------------
    # منبع انتخاب‌شده
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
    # پیام فعلی
    # -----------------------------------------------------

    message_id = message.get(
        "message_id"
    )

    if not message_id:
        return

    message_title = get_message_title(
        message
    )

    # -----------------------------------------------------
    # duplicate
    # -----------------------------------------------------

    if repost_exists(
        source_channel_id,
        source_message_id,
        destination_channel_id
    ):
        return

    # -----------------------------------------------------
    # destination information
    # -----------------------------------------------------

    destination_username = clean_username(
        destination.get("username")
    )

    destination_title = (
        destination.get("title")
        or destination_username
        or str(destination_channel_id)
    )

    # -----------------------------------------------------
    # save repost
    # -----------------------------------------------------

    try:

        (
            supabase
            .table("reposts")
            .insert({
                "source_channel_id": str(
                    source_channel_id
                ),
                "source_username": (
                    clean_username(
                        source_username
                    )
                ),
                "source_message_id": str(
                    source_message_id
                ),
                "destination_channel_id": str(
                    destination_channel_id
                ),
                "destination_username": (
                    destination_username
                ),
                "destination_message_id": str(
                    message_id
                ),
                "destination_title": (
                    destination_title
                ),
                "message_title": (
                    message_title
                ),
                "created_at": now_iso()
            })
            .execute()
        )

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            repr(e)
        )

        return

    # -----------------------------------------------------
    # links
    # -----------------------------------------------------

    source_link = build_bale_message_link(
        source_username,
        source_channel_id,
        source_message_id
    )

    destination_link = build_bale_message_link(
        destination_username,
        destination_channel_id,
        message_id
    )

    # -----------------------------------------------------
    # notify admins
    # -----------------------------------------------------

    notify_repost(
        destination_title,
        destination_username,
        message_title,
        source_link,
        destination_link
    )


# =========================================================
# NOTIFY ADMINS
# =========================================================

def notify_repost(
    destination_title,
    destination_username,
    message_title,
    source_link,
    destination_link
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

        # حذف duplicate
        admin_ids = list(
            dict.fromkeys(
                str(x)
                for x in admin_ids
            )
        )

        text = (
            "🔔 <b>بازنشر جدید</b>\n\n"
            f"📌 مقصد: {destination_title}"
        )

        if destination_username:

            text += (
                f" (@{destination_username})"
            )

        text += (
            f"\n📝 عنوان: {message_title}"
            f"\n🕐 زمان: {format_iran_datetime(now_iso())}"
        )

        if source_link:

            text += (
                f"\n\n🔵 <a href=\"{source_link}\">پست مبدأ</a>"
            )

        if destination_link:

            text += (
                f"\n🟢 <a href=\"{destination_link}\">پست مقصد</a>"
            )

        for admin_id in admin_ids:

            try:

                send_message(
                    admin_id,
                    text
                )

            except Exception as e:

                print(
                    "NOTIFY ADMIN ERROR:",
                    admin_id,
                    repr(e)
                )

    except Exception as e:

        print(
            "NOTIFY ADMINS ERROR:",
            repr(e)
        )


# =========================================================
# REPORT
# =========================================================

def report_reposts(chat_id):

    if not is_admin(chat_id):

        deny_access(chat_id)
        return

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

    if not source_channel_id or not source_message_id:

        send_message(
            chat_id,
            "📭 هنوز هیچ پیام مبدئی انتخاب نشده است."
        )

        return

    try:

        # -------------------------------------------------
        # همه repostهای مربوط به پست
        # -------------------------------------------------

        repost_result = (
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

        rows = repost_result.data or []

        # -------------------------------------------------
        # فقط مقصدهای فعال
        # -------------------------------------------------

        active_result = (
            supabase
            .table("channels")
            .select(
                "chat_id,username,title,"
                "active,manually_disabled,bot_member"
            )
            .eq(
                "active",
                True
            )
            .eq(
                "manually_disabled",
                False
            )
            .eq(
                "bot_member",
                True
            )
            .execute()
        )

        active_chat_ids = {
            str(row.get("chat_id"))
            for row in (
                active_result.data or []
            )
            if row.get("chat_id") is not None
        }

        # -------------------------------------------------
        # حذف مقصدهای غیرفعال از گزارش جاری
        # -------------------------------------------------

        rows = [
            row
            for row in rows
            if str(
                row.get(
                    "destination_channel_id"
                )
            ) in active_chat_ids
        ]

        # -------------------------------------------------
        # source link
        # -------------------------------------------------

        source_link = build_bale_message_link(
            source_username,
            source_channel_id,
            source_message_id
        )

        text = (
            "📊 <b>گزارش بازنشر</b>\n\n"
            f"📌 مبدأ: {source_title or source_username or source_channel_id}"
            f"\n🆔 پیام: <code>{source_message_id}</code>"
            f"\n📈 تعداد مقصدهای فعال: "
            f"{to_persian_digits(len(rows))}"
        )

        if source_link:

            text += (
                f"\n🔵 <a href=\"{source_link}\">مشاهده پست مبدأ</a>"
            )

        if not rows:

            text += (
                "\n\n📭 این پست در حال حاضر "
                "هیچ مقصد فعال ثبت‌شده‌ای ندارد."
            )

            send_message(
                chat_id,
                text
            )

            return

        text += "\n\n"

        for index, row in enumerate(
            rows,
            start=1
        ):

            destination_title = (
                row.get(
                    "destination_title"
                )
                or "-"
            )

            destination_username = clean_username(
                row.get(
                    "destination_username"
                )
            )

            destination_channel_id = row.get(
                "destination_channel_id"
            )

            destination_message_id = row.get(
                "destination_message_id"
            )

            created_at = row.get(
                "created_at"
            )

            destination_link = (
                build_bale_message_link(
                    destination_username,
                    destination_channel_id,
                    destination_message_id
                )
            )

            text += (
                f"{to_persian_digits(index)}. "
                f"<b>{destination_title}</b>"
            )

            if destination_username:

                text += (
                    f" (@{destination_username})"
                )

            text += (
                f"\n   🕐 {format_iran_datetime(created_at)}"
            )

            if destination_link:

                text += (
                    f"\n   🟢 <a href=\"{destination_link}\">مشاهده پست</a>"
                )

            text += "\n\n"

        send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "REPORT ERROR:",
            repr(e)
        )

        send_message(
            chat_id,
            "❌ خطا در تهیه گزارش."
        )


# =========================================================
# STATUS
# =========================================================

def show_status(chat_id):

    if not is_admin(chat_id):

        deny_access(chat_id)
        return

    try:

        active_result = (
            supabase
            .table("channels")
            .select("id")
            .eq(
                "active",
                True
            )
            .eq(
                "manually_disabled",
                False
            )
            .eq(
                "bot_member",
                True
            )
            .execute()
        )

        active_count = len(
            active_result.data or []
        )

        inactive_result = (
            supabase
            .table("channels")
            .select("id")
            .eq(
                "active",
                False
            )
            .execute()
        )

        inactive_count = len(
            inactive_result.data or []
        )

        selected_source = get_setting(
            "selected_source_title"
        )

        text = (
            "📊 <b>وضعیت ربات</b>\n\n"
            f"🟢 مقصدهای فعال: "
            f"{to_persian_digits(active_count)}\n"
            f"🔴 مقصدهای غیرفعال: "
            f"{to_persian_digits(inactive_count)}\n"
            f"📌 مبدأ فعلی: "
            f"{selected_source or 'انتخاب نشده'}"
        )

        send_message(
            chat_id,
            text
        )

    except Exception as e:

        print(
            "STATUS ERROR:",
            repr(e)
        )


# =========================================================
# COMMAND PARSER
# =========================================================

def get_command(text):

    if not text:
        return None, []

    text = text.strip()

    if not text.startswith("/"):
        return None, []

    parts = text.split()

    command = parts[0]

    if "@" in command:

        command = command.split(
            "@",
            1
        )[0]

    command = command.lower()

    args = parts[1:]

    return command, args


# =========================================================
# COMMANDS
# =========================================================

def process_command(
    chat_id,
    text,
    username=None
):

    command, args = get_command(text)

    if not command:
        return

    # -----------------------------------------------------
    # PUBLIC
    # -----------------------------------------------------

    if command == "/myid":

        show_my_id(chat_id)
        return

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    if command == "/start":

        if is_admin(chat_id):

            send_message(
                chat_id,
                "🤖 <b>ربات مدیریت بازنشر</b>\n\n"
                "دستورات اصلی:\n\n"
                "/channels\n"
                "/report\n"
                "/status\n"
                "/addchannel @channel\n"
                "/removechannel @channel\n"
                "/myid"
            )

            if is_owner(chat_id):

                send_message(
                    chat_id,
                    "👑 دستورات مالک:\n\n"
                    "/admins\n"
                    "/addadmin USER_ID\n"
                    "/removeadmin USER_ID"
                )

        else:

            send_message(
                chat_id,
                "سلام 👋\n\n"
                "برای مشاهده شناسه کاربری خود:\n"
                "/myid"
            )

        return

    # -----------------------------------------------------
    # ALL MANAGEMENT COMMANDS
    # -----------------------------------------------------

    if command == "/channels":

        list_channels(chat_id)
        return

    if command == "/report":

        report_reposts(chat_id)
        return

    if command == "/status":

        show_status(chat_id)
        return

    if command == "/addchannel":

        manual_add_channel(
            chat_id,
            " ".join(args)
        )

        return

    if command == "/removechannel":

        manual_remove_channel(
            chat_id,
            " ".join(args)
        )

        return

    # -----------------------------------------------------
    # OWNER
    # -----------------------------------------------------

    if command == "/admins":

        list_admins(chat_id)
        return

    if command == "/addadmin":

        add_admin(
            chat_id,
            " ".join(args)
        )

        return

    if command == "/removeadmin":

        remove_admin(
            chat_id,
            " ".join(args)
        )

        return


# =========================================================
# PROCESS UPDATE
# =========================================================

def process_update(update):

    if not update:
        return

    # -----------------------------------------------------
    # Membership update
    # -----------------------------------------------------

    my_chat_member = update.get(
        "my_chat_member"
    )

    if my_chat_member:

        chat = (
            my_chat_member.get("chat")
            or {}
        )

        chat_type = chat.get(
            "type"
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

            if status in (
                "left",
                "kicked"
            ):

                deactivate_chat(
                    chat.get("id")
                )

            else:

                # ربات دوباره وارد شده
                # فقط در صورتی فعال کن که
                # مدیر قبلاً دستی غیرفعالش نکرده باشد.

                try:

                    result = (
                        supabase
                        .table("channels")
                        .select(
                            "id,manually_disabled"
                        )
                        .eq(
                            "chat_id",
                            str(chat.get("id"))
                        )
                        .limit(1)
                        .execute()
                    )

                    if result.data:

                        row = result.data[0]

                        if row.get(
                            "manually_disabled"
                        ) is not True:

                            (
                                supabase
                                .table("channels")
                                .update({
                                    "active": True,
                                    "bot_member": True
                                })
                                .eq(
                                    "id",
                                    row["id"]
                                )
                                .execute()
                            )

                    else:

                        auto_register_chat(
                            chat
                        )

                except Exception as e:

                    print(
                        "MEMBERSHIP UPDATE ERROR:",
                        repr(e)
                    )

        return

    # -----------------------------------------------------
    # message
    # -----------------------------------------------------

    message = update.get(
        "message"
    )

    # -----------------------------------------------------
    # channel_post
    # -----------------------------------------------------

    if not message:

        message = update.get(
            "channel_post"
        )

    if not message:
        return

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
        return

    # -----------------------------------------------------
    # PRIVATE
    # -----------------------------------------------------

    if chat_type == "private":

        save_bot_user(chat)

        text = (
            message.get("text")
            or ""
        )

        command, _ = get_command(
            text
        )

        if command == "/myid":

            show_my_id(chat_id)
            return

        forward = extract_forward(
            message
        )

        if forward.get("message_id"):

            if not is_admin(chat_id):

                deny_access(chat_id)
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

    # -----------------------------------------------------
    # GROUP / SUPERGROUP / CHANNEL
    # -----------------------------------------------------

    if chat_type in (
        "group",
        "supergroup",
        "channel"
    ):

        auto_register_chat(
            chat
        )

        process_channel_message(
            message
        )

        return


# =========================================================
# GET UPDATES
# =========================================================

def get_updates(offset=None):

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
# MAIN LOOP
# =========================================================

def main():

    load_owner()

    print(
        "===================================="
    )

    print(
        "🤖 BALE REPOST BOT STARTED"
    )

    print(
        "OWNER:",
        OWNER_ID
    )

    print(
        "===================================="
    )

    offset = None

    while True:

        try:

            updates = get_updates(
                offset
            )

            if not updates:

                time.sleep(1)

                continue

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
                        "PROCESS UPDATE ERROR:",
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
