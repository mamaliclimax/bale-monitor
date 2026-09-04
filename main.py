import os
import time
import traceback
import requests

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape

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
# MEMORY
# =========================================================

BOT_INFO = None
PENDING_ACTIONS = {}
LAST_UPDATE_ID = None


# =========================================================
# BASIC HELPERS
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def to_persian_digits(value):
    if value is None:
        return ""

    return str(value).translate(
        str.maketrans(
            "0123456789",
            "۰۱۲۳۴۵۶۷۸۹"
        )
    )


def clean_username(username):
    if not username:
        return None

    username = str(username).strip()

    if username.startswith("@"):
        username = username[1:]

    return username or None


def safe_text(value):
    if value is None:
        return ""

    return str(value)


def html_text(value):
    return escape(
        safe_text(value),
        quote=False
    )


def html_attr(value):
    return escape(
        safe_text(value),
        quote=True
    )


# =========================================================
# MARKDOWN HELPERS
# =========================================================

def markdown_text(value):
    """
    برای Markdown معمولی.
    کاراکترهای خاص Markdown را تا حد ممکن escape می‌کند.
    """

    if value is None:
        return ""

    text = str(value)

    replacements = {
        "\\": "\\\\",
        "_": "\\_",
        "*": "\\*",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "`": "\\`"
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def markdown_link(label, url, emoji=""):
    """
    ساخت لینک قابل کلیک با Markdown.
    """

    if not url:
        return ""

    url = str(url).strip()

    if not url:
        return ""

    # URL را دستکاری نمی‌کنیم تا لینک خراب نشود.
    return f"{emoji} [{markdown_text(label)}]({url})"


def raw_or_markdown_link(label, url, emoji=""):
    """
    اگر لینک موجود باشد Markdown Link برمی‌گرداند.
    در غیر این صورت رشته خالی.
    """

    if not url:
        return ""

    return markdown_link(
        label,
        url,
        emoji
    )


# =========================================================
# JALALI
# =========================================================

def gregorian_to_jalali(gy, gm, gd):

    g_days_in_month = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    ]

    j_days_in_month = [
        31, 31, 31, 31, 31, 31,
        30, 30, 30, 30, 30, 30
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

        date_text = f"{jy:04d}/{jm:02d}/{jd:02d}"
        time_text = f"{dt.hour:02d}:{dt.minute:02d}"

        return (
            f"{to_persian_digits(date_text)}"
            f" - "
            f"{to_persian_digits(time_text)}"
        )

    except Exception as e:

        print(
            "FORMAT DATETIME ERROR:",
            repr(e)
        )

        return str(value)


# =========================================================
# BALE API
# =========================================================

def bale_request(
    method,
    data=None,
    timeout=40
):

    url = f"{BALE_API}/{method}"

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=timeout
        )

        print(
            f"BALE {method}:",
            response.status_code
        )

        try:
            result = response.json()

        except Exception:

            print(
                "BALE RAW:",
                response.text[:2000]
            )

            return None

        if not result.get("ok"):

            print(
                f"BALE {method} ERROR:",
                result
            )

            return None

        return result.get("result")

    except Exception as e:

        print(
            f"BALE {method} EXCEPTION:",
            repr(e)
        )

        return None


# =========================================================
# BALE METHODS
# =========================================================

def get_me():

    global BOT_INFO

    if BOT_INFO:
        return BOT_INFO

    BOT_INFO = bale_request("getMe")

    if BOT_INFO:

        print("=" * 40)
        print("BOT INFORMATION")
        print(BOT_INFO)
        print("=" * 40)

    return BOT_INFO


def get_chat(chat_id):

    return bale_request(
        "getChat",
        {
            "chat_id": str(chat_id)
        }
    )


def get_chat_member(chat_id, user_id):

    return bale_request(
        "getChatMember",
        {
            "chat_id": str(chat_id),
            "user_id": str(user_id)
        }
    )


def send_message(
    chat_id,
    text,
    reply_markup=None,
    parse_mode="HTML"
):

    data = {
        "chat_id": str(chat_id),
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    if parse_mode:
        data["parse_mode"] = parse_mode

    return bale_request(
        "sendMessage",
        data
    )


def send_markdown_message(
    chat_id,
    text,
    reply_markup=None
):

    return send_message(
        chat_id,
        text,
        reply_markup,
        parse_mode="Markdown"
    )


def answer_callback_query(
    callback_query_id,
    text=None,
    show_alert=False
):

    data = {
        "callback_query_id": str(callback_query_id),
        "show_alert": show_alert
    }

    if text:
        data["text"] = text

    return bale_request(
        "answerCallbackQuery",
        data
    )


def get_updates(offset=None):

    data = {
        "timeout": 30
    }

    if offset is not None:
        data["offset"] = offset

    return bale_request(
        "getUpdates",
        data,
        timeout=45
    )


# =========================================================
# INLINE KEYBOARDS
# =========================================================

def source_report_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "📊 گزارش همین پست",
                    "callback_data": "report_selected_source"
                }
            ]
        ]
    }


def clear_reports_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "⚠️ بله، همه گزارش‌ها حذف شود",
                    "callback_data": "confirm_clear_reports"
                }
            ],
            [
                {
                    "text": "❌ انصراف",
                    "callback_data": "cancel_clear_reports"
                }
            ]
        ]
    }


# =========================================================
# MESSAGE LINK
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


def resolve_message_link(
    username,
    chat_id,
    message_id
):

    if chat_id is None or message_id is None:
        return None

    username = clean_username(username)

    # -----------------------------------------------------
    # اگر username داریم
    # -----------------------------------------------------

    if username:

        return build_bale_message_link(
            username,
            chat_id,
            message_id
        )

    # -----------------------------------------------------
    # اگر username نداریم، از getChat بگیر
    # -----------------------------------------------------

    try:

        chat = get_chat(chat_id)

        if chat:

            username = clean_username(
                chat.get("username")
            )

            if username:

                return build_bale_message_link(
                    username,
                    chat_id,
                    message_id
                )

    except Exception as e:

        print(
            "RESOLVE MESSAGE LINK ERROR:",
            repr(e)
        )

    return None


# =========================================================
# DATABASE SETTINGS
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

        data = {
            "value": str(value)
        }

        if existing.data:

            (
                supabase
                .table("bot_settings")
                .update(data)
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
            repr(e)
        )

        return False


def delete_setting(key):

    try:

        (
            supabase
            .table("bot_settings")
            .delete()
            .eq("key", key)
            .execute()
        )

        return True

    except Exception as e:

        print(
            "DELETE SETTING ERROR:",
            repr(e)
        )

        return False


# =========================================================
# OWNER / ADMIN
# =========================================================

def get_owner_id():
    return get_setting("owner_id")


def is_owner(user_id):

    owner_id = get_owner_id()

    if not owner_id:
        return False

    return str(user_id) == str(owner_id)


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
            repr(e)
        )

        return False


# =========================================================
# USERS
# =========================================================

def save_bot_user(user):

    if not user:
        return

    user_id = user.get("id")

    if user_id is None:
        return

    data = {
        "user_id": str(user_id),
        "username": clean_username(
            user.get("username")
        ),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "active": True,
        "updated_at": now_iso()
    }

    try:

        existing = (
            supabase
            .table("bot_users")
            .select("id")
            .eq("user_id", str(user_id))
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
# CHANNEL DATABASE
# =========================================================

def get_channel_by_chat_id(chat_id):

    if chat_id is None:
        return None

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:

        print(
            "GET CHANNEL BY ID ERROR:",
            repr(e)
        )

    return None


def get_channel_by_username(username):

    username = clean_username(username)

    if not username:
        return None

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("username", username)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:

        print(
            "GET CHANNEL BY USERNAME ERROR:",
            repr(e)
        )

    return None


def update_channel_row(row_id, data):

    try:

        (
            supabase
            .table("channels")
            .update(data)
            .eq("id", row_id)
            .execute()
        )

        return True

    except Exception as e:

        print(
            "UPDATE CHANNEL ERROR:",
            repr(e)
        )

        return False


# =========================================================
# REGISTER CHAT
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

        row = get_channel_by_chat_id(chat_id)

        if row:

            manually_disabled = (
                row.get("manually_disabled") is True
            )

            bot_member = row.get("bot_member")

            if bot_member is None:
                bot_member = True

            data = {
                "chat_id": chat_id,
                "username": username,
                "title": title
            }

            if manually_disabled:
                data["active"] = False

            elif bot_member is False:
                data["active"] = False

            else:
                data["active"] = True

            return update_channel_row(
                row["id"],
                data
            )

        if username:

            row = get_channel_by_username(username)

            if row:

                manually_disabled = (
                    row.get("manually_disabled") is True
                )

                bot_member = row.get("bot_member")

                if bot_member is None:
                    bot_member = True

                data = {
                    "chat_id": chat_id,
                    "username": username,
                    "title": title
                }

                if manually_disabled:
                    data["active"] = False

                elif bot_member is False:
                    data["active"] = False

                else:
                    data["active"] = True

                return update_channel_row(
                    row["id"],
                    data
                )

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
            "AUTO REGISTERED:",
            chat_id,
            title,
            username
        )

        return True

    except Exception as e:

        print(
            "AUTO REGISTER ERROR:",
            repr(e)
        )

        return False


# =========================================================
# ACTIVATE CHAT
# =========================================================

def activate_chat(
    chat,
    clear_manual=True
):

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

        row = get_channel_by_chat_id(chat_id)

        data = {
            "chat_id": chat_id,
            "username": username,
            "title": title,
            "active": True,
            "bot_member": True
        }

        if clear_manual:
            data["manually_disabled"] = False

        if row:

            return update_channel_row(
                row["id"],
                data
            )

        data["manually_disabled"] = False

        (
            supabase
            .table("channels")
            .insert(data)
            .execute()
        )

        print(
            "ACTIVATED NEW CHAT:",
            chat_id,
            title
        )

        return True

    except Exception as e:

        print(
            "ACTIVATE CHAT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# DEACTIVATE CHAT
# =========================================================

def deactivate_chat(chat_id):

    if chat_id is None:
        return False

    try:

        row = get_channel_by_chat_id(chat_id)

        if not row:
            return False

        return update_channel_row(
            row["id"],
            {
                "active": False,
                "bot_member": False
            }
        )

    except Exception as e:

        print(
            "DEACTIVATE CHAT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# MANUAL ADD
# =========================================================

def manual_add_channel(identifier):

    if not identifier:

        return (
            False,
            "❌ شناسه یا نام کاربری مقصد وارد نشده است."
        )

    identifier = str(identifier).strip()

    try:

        chat = get_chat(identifier)

        if not chat:

            return (
                False,
                "❌ مقصد پیدا نشد.\n\n"
                "مطمئن شوید ربات در مقصد عضو است "
                "و شناسه یا نام کاربری درست است."
            )

        chat_type = chat.get("type")

        if chat_type not in (
            "group",
            "supergroup",
            "channel"
        ):

            return (
                False,
                "❌ این مقصد گروه یا کانال نیست."
            )

        ok = activate_chat(
            chat,
            clear_manual=True
        )

        if not ok:

            return (
                False,
                "❌ ثبت مقصد در پایگاه داده ناموفق بود."
            )

        title = (
            chat.get("title")
            or chat.get("username")
            or chat.get("id")
        )

        return (
            True,
            "✅ <b>مقصد فعال شد</b>\n\n"
            f"📡 {html_text(title)}\n"
            f"🆔 <code>{html_text(chat.get('id'))}</code>"
        )

    except Exception as e:

        print(
            "MANUAL ADD ERROR:",
            repr(e)
        )

        return (
            False,
            "❌ هنگام افزودن مقصد خطایی رخ داد."
        )


# =========================================================
# MANUAL REMOVE
# =========================================================

def manual_remove_channel(identifier):

    if not identifier:

        return (
            False,
            "❌ شناسه مقصد وارد نشده است."
        )

    identifier = str(identifier).strip()

    try:

        row = None

        if identifier.lstrip("-").isdigit():

            row = get_channel_by_chat_id(identifier)

        else:

            row = get_channel_by_username(identifier)

        if not row:

            return (
                False,
                "❌ این مقصد در لیست ربات پیدا نشد."
            )

        ok = update_channel_row(
            row["id"],
            {
                "active": False,
                "manually_disabled": True
            }
        )

        if not ok:

            return (
                False,
                "❌ حذف مقصد ناموفق بود."
            )

        return (
            True,
            "✅ <b>مقصد حذف شد</b>\n\n"
            f"📡 {html_text(row.get('title') or row.get('username') or row.get('chat_id'))}"
        )

    except Exception as e:

        print(
            "MANUAL REMOVE ERROR:",
            repr(e)
        )

        return (
            False,
            "❌ هنگام حذف مقصد خطایی رخ داد."
        )


# =========================================================
# SYNC
# =========================================================

def sync_channels():

    bot = get_me()

    if not bot:

        return {
            "checked": 0,
            "active": 0,
            "removed": 0,
            "errors": 1
        }

    bot_id = bot.get("id")

    if bot_id is None:

        return {
            "checked": 0,
            "active": 0,
            "removed": 0,
            "errors": 1
        }

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        print(
            "SYNC FETCH ERROR:",
            repr(e)
        )

        return {
            "checked": 0,
            "active": 0,
            "removed": 0,
            "errors": 1
        }

    checked = 0
    active = 0
    removed = 0
    errors = 0

    for row in rows:

        chat_id = row.get("chat_id")

        if not chat_id:
            continue

        checked += 1

        try:

            member = get_chat_member(
                chat_id,
                bot_id
            )

            if not member:

                errors += 1
                continue

            status = str(
                member.get("status", "")
            ).lower()

            print(
                "SYNC:",
                chat_id,
                status
            )

            if status in (
                "left",
                "kicked"
            ):

                update_channel_row(
                    row["id"],
                    {
                        "active": False,
                        "bot_member": False
                    }
                )

                removed += 1
                continue

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                data = {
                    "bot_member": True
                }

                if row.get("manually_disabled") is not True:

                    data["active"] = True
                    active += 1

                update_channel_row(
                    row["id"],
                    data
                )

            time.sleep(0.15)

        except Exception as e:

            errors += 1

            print(
                "SYNC CHAT ERROR:",
                chat_id,
                repr(e)
            )

    return {
        "checked": checked,
        "active": active,
        "removed": removed,
        "errors": errors
    }


# =========================================================
# CHANNEL LIST
# =========================================================

def get_active_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("active", True)
            .eq("bot_member", True)
            .eq("manually_disabled", False)
            .order("title")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET ACTIVE CHANNELS ERROR:",
            repr(e)
        )

        return []


def get_all_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .order("title")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET ALL CHANNELS ERROR:",
            repr(e)
        )

        return []


# =========================================================
# SOURCE EXTRACTION
# =========================================================

def extract_forward(message):

    if not message:
        return None

    forward_chat = (
        message.get("forward_from_chat")
        or message.get("sender_chat")
    )

    if not forward_chat:

        forward_origin = message.get(
            "forward_origin"
        )

        if isinstance(forward_origin, dict):

            forward_chat = (
                forward_origin.get("chat")
                or forward_origin.get("sender_chat")
            )

    if not forward_chat:
        return None

    source_chat_id = forward_chat.get("id")

    source_username = clean_username(
        forward_chat.get("username")
    )

    source_title = (
        forward_chat.get("title")
        or source_username
        or source_chat_id
    )

    source_message_id = (
        message.get("forward_from_message_id")
        or message.get("forwarded_message_id")
        or message.get("forward_message_id")
    )

    if not source_message_id:

        forward_origin = message.get(
            "forward_origin"
        )

        if isinstance(forward_origin, dict):

            source_message_id = (
                forward_origin.get("message_id")
                or forward_origin.get(
                    "forward_from_message_id"
                )
            )

    if not source_message_id:
        return None

    source_link = (
        message.get("forward_link")
        or message.get("message_link")
        or message.get("link")
        or ""
    )

    if not source_link:

        source_link = resolve_message_link(
            source_username,
            source_chat_id,
            source_message_id
        )

    return {
        "channel_id": (
            str(source_chat_id)
            if source_chat_id is not None
            else None
        ),
        "message_id": str(source_message_id),
        "username": source_username,
        "title": source_title,
        "message_link": source_link
    }


# =========================================================
# SELECT SOURCE
# =========================================================

def set_selected_source(
    source,
    admin_chat_id
):

    set_setting(
        "selected_source_channel_id",
        source.get("channel_id") or ""
    )

    set_setting(
        "selected_source_message_id",
        source.get("message_id") or ""
    )

    set_setting(
        "selected_source_username",
        source.get("username") or ""
    )

    set_setting(
        "selected_source_title",
        source.get("title") or ""
    )

    set_setting(
        "selected_source_message_link",
        source.get("message_link") or ""
    )

    text = (
        "✅ <b>پست مبدأ انتخاب شد</b>\n\n"
        f"📡 کانال: {html_text(source.get('title') or '-')}\n"
        f"🆔 شناسه کانال: "
        f"<code>{html_text(source.get('channel_id') or '-')}</code>\n"
        f"📝 شناسه پست: "
        f"<code>{html_text(source.get('message_id') or '-')}</code>"
    )

    send_message(
        admin_chat_id,
        text,
        source_report_keyboard()
    )

    # -----------------------------------------------------
    # لینک را جداگانه با Markdown می‌فرستیم
    # تا با HTML پیام بالا تداخل نداشته باشد.
    # -----------------------------------------------------

    if source.get("message_link"):

        link_text = markdown_link(
            "مشاهده پست مبدأ",
            source.get("message_link"),
            "🔵"
        )

        send_markdown_message(
            admin_chat_id,
            link_text
        )


def get_selected_source():

    return {
        "channel_id": get_setting(
            "selected_source_channel_id"
        ),
        "message_id": get_setting(
            "selected_source_message_id"
        ),
        "username": get_setting(
            "selected_source_username"
        ),
        "title": get_setting(
            "selected_source_title"
        ),
        "message_link": get_setting(
            "selected_source_message_link"
        )
    }


# =========================================================
# REPOST DATABASE
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


def save_repost(
    source,
    destination,
    destination_message_id,
    message_title=""
):

    try:

        destination_username = clean_username(
            destination.get("username")
        )

        destination_link = resolve_message_link(
            destination_username,
            destination.get("id"),
            destination_message_id
        )

        data = {
            "source_channel_id": source.get(
                "channel_id"
            ),
            "source_username": source.get(
                "username"
            ),
            "source_message_id": source.get(
                "message_id"
            ),
            "source_message_link": source.get(
                "message_link"
            ),
            "destination_channel_id": str(
                destination.get("id")
            ),
            "destination_username": destination_username,
            "destination_message_id": str(
                destination_message_id
            ),
            "destination_title": (
                destination.get("title")
                or destination.get("username")
                or destination.get("id")
            ),
            "message_title": message_title or "",
            "created_at": now_iso()
        }

        # -------------------------------------------------
        # اگر ستون destination_message_link در دیتابیس
        # وجود داشته باشد، لینک مقصد را نیز ذخیره می‌کنیم.
        #
        # اگر ستون وجود نداشته باشد، INSERT خطا می‌دهد.
        # بنابراین ابتدا تلاش می‌کنیم با ستون لینک ذخیره کنیم.
        # -------------------------------------------------

        if destination_link:
            data["destination_message_link"] = destination_link

        try:

            result = (
                supabase
                .table("reposts")
                .insert(data)
                .execute()
            )

            return bool(result.data)

        except Exception as first_error:

            # ---------------------------------------------
            # سازگاری با دیتابیس قدیمی که ستون
            # destination_message_link ندارد.
            # ---------------------------------------------

            print(
                "SAVE REPOST WITH LINK ERROR:",
                repr(first_error)
            )

            data.pop(
                "destination_message_link",
                None
            )

            result = (
                supabase
                .table("reposts")
                .insert(data)
                .execute()
            )

            return bool(result.data)

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            repr(e)
        )

        return False


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

    title = text.splitlines()[0].strip()

    if len(title) > 100:
        title = title[:100] + "…"

    return title


# =========================================================
# ADMIN IDS
# =========================================================

def get_admin_ids():

    ids = []

    owner_id = get_owner_id()

    if owner_id:
        ids.append(str(owner_id))

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("user_id")
            .eq("active", True)
            .execute()
        )

        for row in result.data or []:

            user_id = row.get("user_id")

            if user_id:

                user_id = str(user_id)

                if user_id not in ids:
                    ids.append(user_id)

    except Exception as e:

        print(
            "GET ADMIN IDS ERROR:",
            repr(e)
        )

    return ids


def notify_admins(text):

    for admin_id in get_admin_ids():

        try:

            send_message(
                admin_id,
                text
            )

            time.sleep(0.1)

        except Exception as e:

            print(
                "NOTIFY ERROR:",
                repr(e)
            )


# =========================================================
# REPOST ALERT
# =========================================================

def send_repost_alert(
    source,
    destination,
    message,
    destination_message_id
):

    destination_username = clean_username(
        destination.get("username")
    )

    destination_chat_id = destination.get("id")

    # =====================================================
    # لینک مقصد
    # =====================================================

    destination_link = resolve_message_link(
        destination_username,
        destination_chat_id,
        destination_message_id
    )

    # =====================================================
    # لینک مبدأ
    # =====================================================

    source_link = source.get(
        "message_link"
    )

    if not source_link:

        source_link = resolve_message_link(
            source.get("username"),
            source.get("channel_id"),
            source.get("message_id")
        )

    title = get_message_title(message)

    # -----------------------------------------------------
    # پیام اصلی گزارش با HTML
    # -----------------------------------------------------

    text = (
        "🔔 <b>بازنشر جدید شناسایی شد</b>\n\n"
        f"📡 <b>مقصد:</b> "
        f"{html_text(destination.get('title') or '-')}"
    )

    if destination_username:

        text += (
            f"\n🔖 <b>نام کاربری:</b> "
            f"@{html_text(destination_username)}"
        )

    text += (
        f"\n📝 <b>عنوان:</b> "
        f"{html_text(title)}\n"
        f"🕐 <b>زمان:</b> "
        f"{format_iran_datetime(now_iso())}"
    )

    # -----------------------------------------------------
    # پیام اصلی
    # -----------------------------------------------------

    notify_admins(text)

    # -----------------------------------------------------
    # لینک مبدأ
    # -----------------------------------------------------

    if source_link:

        source_link_text = markdown_link(
            "مشاهده پست مبدأ",
            source_link,
            "🔵"
        )

        notify_admins_markdown(
            source_link_text
        )

    # -----------------------------------------------------
    # لینک مقصد
    # -----------------------------------------------------

    if destination_link:

        destination_link_text = markdown_link(
            "مشاهده پست مقصد",
            destination_link,
            "🟢"
        )

        notify_admins_markdown(
            destination_link_text
        )

    else:

        notify_admins(
            "🟢 ⚠️ لینک مستقیم پست مقصد در دسترس نیست."
        )


def notify_admins_markdown(text):

    for admin_id in get_admin_ids():

        try:

            send_markdown_message(
                admin_id,
                text
            )

            time.sleep(0.1)

        except Exception as e:

            print(
                "NOTIFY MARKDOWN ERROR:",
                repr(e)
            )


# =========================================================
# PROCESS CHANNEL/GROUP MESSAGE
# =========================================================

def process_channel_message(message):

    if not message:
        return

    chat = message.get("chat")

    if not chat:
        return

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return

    chat_id = chat.get("id")

    if chat_id is None:
        return

    # -----------------------------------------------------
    # ثبت مقصد
    # -----------------------------------------------------

    auto_register_chat(chat)

    row = get_channel_by_chat_id(chat_id)

    if not row:
        return

    if row.get("active") is not True:
        return

    if row.get("bot_member") is False:
        return

    if row.get("manually_disabled") is True:
        return

    # -----------------------------------------------------
    # مبدأ انتخاب‌شده
    # -----------------------------------------------------

    source = get_selected_source()

    if not source.get("channel_id"):
        return

    if not source.get("message_id"):
        return

    destination_message_id = message.get(
        "message_id"
    )

    if destination_message_id is None:
        return

    # -----------------------------------------------------
    # جلوگیری از ثبت دوباره
    # -----------------------------------------------------

    if repost_exists(
        source.get("channel_id"),
        source.get("message_id"),
        str(chat_id)
    ):
        return

    destination = {
        "id": str(chat_id),
        "username": chat.get("username"),
        "title": (
            chat.get("title")
            or chat.get("username")
            or chat_id
        )
    }

    title = get_message_title(message)

    saved = save_repost(
        source,
        destination,
        destination_message_id,
        title
    )

    if not saved:
        return

    print("=" * 40)
    print("REPOST SAVED")
    print(
        "SOURCE:",
        source.get("channel_id"),
        source.get("message_id")
    )
    print(
        "DESTINATION:",
        chat_id,
        destination_message_id
    )
    print("=" * 40)

    send_repost_alert(
        source,
        destination,
        message,
        destination_message_id
    )


# =========================================================
# MEMBERSHIP UPDATE
# =========================================================

def handle_bot_membership_update(update):

    bot = get_me()

    if not bot:
        return False

    bot_id = str(bot.get("id"))

    # -----------------------------------------------------
    # my_chat_member
    # -----------------------------------------------------

    my_chat_member = update.get(
        "my_chat_member"
    )

    if my_chat_member:

        print("🔥 FOUND my_chat_member")
        print(my_chat_member)

        chat = my_chat_member.get("chat")

        new_member = (
            my_chat_member.get("new_chat_member")
            or {}
        )

        user = (
            new_member.get("user")
            or {}
        )

        if (
            chat
            and str(user.get("id")) == bot_id
        ):

            status = str(
                new_member.get("status", "")
            ).lower()

            print(
                "BOT MEMBERSHIP:",
                chat.get("id"),
                status
            )

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                activate_chat(
                    chat,
                    clear_manual=True
                )

            elif status in (
                "left",
                "kicked"
            ):

                deactivate_chat(
                    chat.get("id")
                )

            return True

    # -----------------------------------------------------
    # chat_member
    # -----------------------------------------------------

    chat_member = update.get(
        "chat_member"
    )

    if chat_member:

        print("🔥 FOUND chat_member")
        print(chat_member)

        chat = chat_member.get("chat")

        new_member = (
            chat_member.get("new_chat_member")
            or {}
        )

        user = (
            new_member.get("user")
            or {}
        )

        if (
            chat
            and str(user.get("id")) == bot_id
        ):

            status = str(
                new_member.get("status", "")
            ).lower()

            print(
                "BOT CHAT MEMBER:",
                chat.get("id"),
                status
            )

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                activate_chat(
                    chat,
                    clear_manual=True
                )

            elif status in (
                "left",
                "kicked"
            ):

                deactivate_chat(
                    chat.get("id")
                )

            return True

    return False


# =========================================================
# GROUP SERVICE MESSAGE
# =========================================================

def handle_group_service_message(message):

    if not message:
        return False

    chat = message.get("chat")

    if not chat:
        return False

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup"
    ):
        return False

    bot = get_me()

    if not bot:
        return False

    bot_id = str(bot.get("id"))

    # -----------------------------------------------------
    # BOT ADDED
    # -----------------------------------------------------

    new_members = (
        message.get("new_chat_members")
        or []
    )

    if isinstance(new_members, dict):
        new_members = [new_members]

    for member in new_members:

        if not isinstance(member, dict):
            continue

        member_id = member.get("id")

        user_obj = member.get("user")

        if isinstance(user_obj, dict):

            member_id = (
                user_obj.get("id")
                or member_id
            )

        if str(member_id) == bot_id:

            print("=" * 40)
            print("🔥 BOT ADDED TO GROUP")
            print("CHAT:", chat)
            print("=" * 40)

            activate_chat(
                chat,
                clear_manual=True
            )

            return True

    # -----------------------------------------------------
    # BOT REMOVED
    # -----------------------------------------------------

    left_member = message.get(
        "left_chat_member"
    )

    if left_member:

        member_id = None

        if isinstance(left_member, dict):

            member_id = left_member.get("id")

            user_obj = left_member.get("user")

            if isinstance(user_obj, dict):

                member_id = (
                    user_obj.get("id")
                    or member_id
                )

        if str(member_id) == bot_id:

            print("=" * 40)
            print("🔴 BOT REMOVED FROM GROUP")
            print("CHAT:", chat)
            print("=" * 40)

            deactivate_chat(
                chat.get("id")
            )

            return True

    return False


# =========================================================
# REPORT FOR SELECTED SOURCE
# =========================================================

def generate_report():

    source = get_selected_source()

    if not source.get("channel_id"):

        return (
            "📊 <b>گزارش بازنشر</b>\n\n"
            "⚠️ هنوز پست مبدأ انتخاب نشده است.\n\n"
            "یک پست را از کانال مبدأ برای ربات "
            "Forward کنید."
        )

    source_channel_id = str(
        source.get("channel_id")
    )

    source_message_id = str(
        source.get("message_id")
    )

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_channel_id",
                source_channel_id
            )
            .eq(
                "source_message_id",
                source_message_id
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        print(
            "REPORT FETCH ERROR:",
            repr(e)
        )

        return "❌ خطا در دریافت گزارش."

    # -----------------------------------------------------
    # فقط مقصدهای فعال
    # -----------------------------------------------------

    active_channels = get_active_channels()

    active_ids = {
        str(row.get("chat_id"))
        for row in active_channels
        if row.get("chat_id")
    }

    rows = [
        row
        for row in rows
        if str(
            row.get("destination_channel_id")
        ) in active_ids
    ]

    # =====================================================
    # SOURCE LINK
    # =====================================================

    source_link = source.get(
        "message_link"
    )

    if not source_link:

        source_link = resolve_message_link(
            source.get("username"),
            source.get("channel_id"),
            source.get("message_id")
        )

        if source_link:

            set_setting(
                "selected_source_message_link",
                source_link
            )

    # =====================================================
    # HEADER
    # =====================================================

    text = (
        "📊 <b>گزارش همین پست</b>\n\n"
        f"📡 <b>مبدأ:</b> "
        f"{html_text(source.get('title') or '-')}\n"
        f"🆔 <b>شناسه پست:</b> "
        f"<code>{html_text(source_message_id)}</code>\n"
    )

    # -----------------------------------------------------
    # لینک مبدأ
    # -----------------------------------------------------

    if source_link:

        text += (
            "\n"
            "🔵 <b>مشاهده پست مبدأ:</b>\n"
            f"<code>{html_text(source_link)}</code>\n"
        )

    else:

        text += (
            "\n🔵 ⚠️ لینک پست مبدأ در دسترس نیست.\n"
        )

    # =====================================================
    # COUNT
    # =====================================================

    text += (
        f"\n📈 <b>تعداد بازنشر فعال:</b> "
        f"{to_persian_digits(len(rows))}\n"
    )

    if not rows:

        return text + (
            "\nℹ️ هنوز بازنشری از این پست "
            "در مقصدهای فعال ثبت نشده است."
        )

    text += "\n"

    # =====================================================
    # DESTINATIONS
    # =====================================================

    for index, row in enumerate(
        rows,
        start=1
    ):

        destination_title = (
            row.get("destination_title")
            or "-"
        )

        destination_username = clean_username(
            row.get("destination_username")
        )

        destination_chat_id = row.get(
            "destination_channel_id"
        )

        destination_message_id = row.get(
            "destination_message_id"
        )

        # -------------------------------------------------
        # اول لینک ذخیره‌شده را بررسی می‌کنیم
        # -------------------------------------------------

        destination_link = (
            row.get("destination_message_link")
            or ""
        )

        # -------------------------------------------------
        # اگر لینک ذخیره‌شده نداریم، دوباره بساز
        # -------------------------------------------------

        if not destination_link:

            destination_link = resolve_message_link(
                destination_username,
                destination_chat_id,
                destination_message_id
            )

        message_title = (
            row.get("message_title")
            or "بدون عنوان"
        )

        created_at = format_iran_datetime(
            row.get("created_at")
        )

        text += (
            f"<b>{to_persian_digits(index)}.</b> "
            f"📡 {html_text(destination_title)}\n"
        )

        if destination_username:

            text += (
                f"   🔖 @{html_text(destination_username)}\n"
            )

        text += (
            f"   📝 {html_text(message_title)}\n"
            f"   🕐 {html_text(created_at)}\n"
        )

        # -------------------------------------------------
        # لینک مقصد
        # -------------------------------------------------

        if destination_link:

            text += (
                f"   🟢 <b>مشاهده پست مقصد:</b>\n"
                f"   <code>{html_text(destination_link)}</code>\n"
            )

        else:

            text += (
                "   🟢 ⚠️ لینک مستقیم مقصد در دسترس نیست.\n"
            )

        text += "\n"

    return text


def generate_report_markdown():

    """
    نسخه Markdown گزارش.
    برای اینکه لینک‌ها واقعاً به صورت
    [مشاهده پست](URL)
    نمایش داده شوند.
    """

    source = get_selected_source()

    if not source.get("channel_id"):

        return (
            "📊 *گزارش بازنشر*\n\n"
            "⚠️ هنوز پست مبدأ انتخاب نشده است.\n\n"
            "یک پست را از کانال مبدأ برای ربات "
            "Forward کنید."
        )

    source_channel_id = str(
        source.get("channel_id")
    )

    source_message_id = str(
        source.get("message_id")
    )

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_channel_id",
                source_channel_id
            )
            .eq(
                "source_message_id",
                source_message_id
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        print(
            "REPORT MARKDOWN FETCH ERROR:",
            repr(e)
        )

        return "❌ خطا در دریافت گزارش."

    # -----------------------------------------------------
    # فقط مقصدهای فعال
    # -----------------------------------------------------

    active_channels = get_active_channels()

    active_ids = {
        str(row.get("chat_id"))
        for row in active_channels
        if row.get("chat_id")
    }

    rows = [
        row
        for row in rows
        if str(
            row.get("destination_channel_id")
        ) in active_ids
    ]

    # =====================================================
    # SOURCE LINK
    # =====================================================

    source_link = source.get(
        "message_link"
    )

    if not source_link:

        source_link = resolve_message_link(
            source.get("username"),
            source.get("channel_id"),
            source.get("message_id")
        )

        if source_link:

            set_setting(
                "selected_source_message_link",
                source_link
            )

    # =====================================================
    # HEADER
    # =====================================================

    text = (
        "📊 *گزارش همین پست*\n\n"
        f"📡 *مبدأ:* "
        f"{markdown_text(source.get('title') or '-')}\n"
        f"🆔 *شناسه پست:* "
        f"`{markdown_text(source_message_id)}`\n"
    )

    if source_link:

        text += (
            "\n"
            + markdown_link(
                "مشاهده پست مبدأ",
                source_link,
                "🔵"
            )
            + "\n"
        )

    else:

        text += (
            "\n🔵 ⚠️ لینک پست مبدأ در دسترس نیست.\n"
        )

    # =====================================================
    # COUNT
    # =====================================================

    text += (
        f"\n📈 *تعداد بازنشر فعال:* "
        f"{to_persian_digits(len(rows))}\n"
    )

    if not rows:

        text += (
            "\nℹ️ هنوز بازنشری از این پست "
            "در مقصدهای فعال ثبت نشده است."
        )

        return text

    text += "\n"

    # =====================================================
    # DESTINATIONS
    # =====================================================

    for index, row in enumerate(
        rows,
        start=1
    ):

        destination_title = (
            row.get("destination_title")
            or "-"
        )

        destination_username = clean_username(
            row.get("destination_username")
        )

        destination_chat_id = row.get(
            "destination_channel_id"
        )

        destination_message_id = row.get(
            "destination_message_id"
        )

        # -------------------------------------------------
        # لینک ذخیره‌شده
        # -------------------------------------------------

        destination_link = (
            row.get("destination_message_link")
            or ""
        )

        # -------------------------------------------------
        # اگر موجود نبود، دوباره بساز
        # -------------------------------------------------

        if not destination_link:

            destination_link = resolve_message_link(
                destination_username,
                destination_chat_id,
                destination_message_id
            )

        message_title = (
            row.get("message_title")
            or "بدون عنوان"
        )

        created_at = format_iran_datetime(
            row.get("created_at")
        )

        text += (
            f"*{to_persian_digits(index)}.* "
            f"📡 {markdown_text(destination_title)}\n"
        )

        if destination_username:

            text += (
                f"   🔖 @{markdown_text(destination_username)}\n"
            )

        text += (
            f"   📝 {markdown_text(message_title)}\n"
            f"   🕐 {markdown_text(created_at)}\n"
        )

        if destination_link:

            text += (
                "   "
                + markdown_link(
                    "مشاهده پست مقصد",
                    destination_link,
                    "🟢"
                )
                + "\n"
            )

        else:

            text += (
                "   🟢 ⚠️ لینک مستقیم مقصد در دسترس نیست.\n"
            )

        text += "\n"

    return text


# =========================================================
# DELETE ALL REPORTS
# =========================================================

def get_reposts_count():

    try:

        result = (
            supabase
            .table("reposts")
            .select("id")
            .execute()
        )

        return len(result.data or [])

    except Exception as e:

        print(
            "GET REPOST COUNT ERROR:",
            repr(e)
        )

        return None


def delete_all_reports():

    try:

        count = get_reposts_count()

        if count is None:
            return False, 0

        if count == 0:
            return True, 0

        (
            supabase
            .table("reposts")
            .delete()
            .gt("id", 0)
            .execute()
        )

        print(
            "ALL REPORTS DELETED:",
            count
        )

        return True, count

    except Exception as e:

        print(
            "DELETE ALL REPORTS ERROR:",
            repr(e)
        )

        return False, 0


# =========================================================
# CHANNEL LIST
# =========================================================

def generate_channels_list():

    rows = get_active_channels()

    text = (
        "📡 <b>کانال‌ها و گروه‌های فعال</b>\n\n"
    )

    if not rows:

        return (
            text
            + "⚠️ هنوز مقصد فعالی ثبت نشده است.\n\n"
            "ربات را به مقصد اضافه کنید "
            "یا از گزینه «➕ افزودن مقصد» استفاده کنید."
        )

    text += (
        f"تعداد مقصدهای فعال: "
        f"<b>{to_persian_digits(len(rows))}</b>\n\n"
    )

    for index, row in enumerate(
        rows,
        start=1
    ):

        title = (
            row.get("title")
            or row.get("username")
            or row.get("chat_id")
            or "-"
        )

        username = clean_username(
            row.get("username")
        )

        chat_id = row.get("chat_id")

        text += (
            f"<b>{to_persian_digits(index)}.</b> "
            f"📡 {html_text(title)}\n"
        )

        if username:

            text += (
                f"   🔖 @{html_text(username)}\n"
            )

        text += (
            f"   🆔 <code>"
            f"{html_text(chat_id or '-')}"
            f"</code>\n\n"
        )

    return text


# =========================================================
# STATUS
# =========================================================

def generate_status():

    active = get_active_channels()
    all_channels = get_all_channels()
    source = get_selected_source()
    admins = get_admin_ids()
    bot = get_me()

    bot_name = (
        bot.get("first_name")
        if bot
        else "-"
    )

    return (
        "📈 <b>وضعیت ربات</b>\n\n"
        f"🤖 ربات: <b>{html_text(bot_name)}</b>\n"
        f"📡 مقصدهای فعال: "
        f"<b>{to_persian_digits(len(active))}</b>\n"
        f"🗂 کل مقصدهای ثبت‌شده: "
        f"<b>{to_persian_digits(len(all_channels))}</b>\n"
        f"👥 مدیران: "
        f"<b>{to_persian_digits(len(admins))}</b>\n\n"
        f"📌 مبدأ فعلی: "
        f"<b>{html_text(source.get('title') or 'انتخاب نشده')}</b>"
    )


# =========================================================
# MAIN KEYBOARD
# =========================================================

def main_keyboard(user_id):

    if is_owner(user_id):

        keyboard = [
            [
                {"text": "📊 گزارش بازنشر"},
                {"text": "📡 کانال‌ها و گروه‌ها"}
            ],
            [
                {"text": "➕ افزودن مقصد"},
                {"text": "➖ حذف مقصد"}
            ],
            [
                {"text": "🔄 همگام‌سازی"},
                {"text": "📈 وضعیت ربات"}
            ],
            [
                {"text": "🗑️ پاک کردن کلیه گزارش‌ها"}
            ],
            [
                {"text": "⚙️ مدیریت مدیران"},
                {"text": "❓ راهنما"}
            ]
        ]

    elif is_admin(user_id):

        keyboard = [
            [
                {"text": "📊 گزارش بازنشر"},
                {"text": "📡 کانال‌ها و گروه‌ها"}
            ],
            [
                {"text": "➕ افزودن مقصد"},
                {"text": "➖ حذف مقصد"}
            ],
            [
                {"text": "🔄 همگام‌سازی"},
                {"text": "📈 وضعیت ربات"}
            ],
            [
                {"text": "❓ راهنما"}
            ]
        ]

    else:

        keyboard = [
            [
                {"text": "🆔 شناسه من"},
                {"text": "❓ راهنما"}
            ]
        ]

    return {
        "keyboard": keyboard,
        "resize_keyboard": True
    }


def admin_keyboard():

    return {
        "keyboard": [
            [
                {"text": "👥 مدیران ربات"},
                {"text": "➕ افزودن مدیر"}
            ],
            [
                {"text": "➖ حذف مدیر"}
            ],
            [
                {"text": "🏠 منوی اصلی"}
            ]
        ],
        "resize_keyboard": True
    }


# =========================================================
# START
# =========================================================

def send_start(chat_id, user_id):

    if is_owner(user_id):

        text = (
            "👋 <b>سلام مدیر ارشد</b>\n\n"
            "به پنل مدیریت ربات بازنشر خوش آمدید.\n\n"
            "از منوی زیر می‌توانید مقصدها، "
            "گزارش‌ها و مدیران ربات را مدیریت کنید."
        )

    elif is_admin(user_id):

        text = (
            "👋 <b>سلام مدیر</b>\n\n"
            "به پنل مدیریت ربات خوش آمدید.\n\n"
            "می‌توانید گزارش بازنشر را ببینید، "
            "مقصدها را مدیریت کنید و وضعیت ربات "
            "را بررسی نمایید."
        )

    else:

        text = (
            "👋 <b>سلام!</b>\n\n"
            "به ربات بازنشر خوش آمدید.\n\n"
            "برای مشاهده شناسه کاربری خود "
            "از گزینه «🆔 شناسه من» استفاده کنید."
        )

    send_message(
        chat_id,
        text,
        main_keyboard(user_id)
    )


# =========================================================
# HELP
# =========================================================

def send_help(chat_id, user_id):

    if is_admin(user_id):

        text = (
            "❓ <b>راهنمای ربات</b>\n\n"
            "🔹 <b>انتخاب پست مبدأ</b>\n"
            "یک پست را از کانال مبدأ به صورت "
            "Forward برای ربات ارسال کنید.\n\n"
            "🔹 <b>گزارش همین پست</b>\n"
            "بعد از ارسال پست مبدأ، دکمه "
            "«📊 گزارش همین پست» زیر پیام ظاهر می‌شود.\n\n"
            "🔹 <b>افزودن مقصد</b>\n"
            "از گزینه «➕ افزودن مقصد» استفاده کنید "
            "یا دستور زیر را بفرستید:\n"
            "<code>/addchannel @username</code>\n\n"
            "🔹 <b>حذف مقصد</b>\n"
            "<code>/removechannel @username</code>\n\n"
            "🔹 <b>گزارش کلی</b>\n"
            "از «📊 گزارش بازنشر» استفاده کنید.\n\n"
            "🔹 <b>پاک کردن گزارش‌ها</b>\n"
            "فقط مالک ربات می‌تواند همه گزارش‌های "
            "قبلی را حذف کند.\n\n"
            "🔹 <b>همگام‌سازی</b>\n"
            "برای بررسی مقصدهای ثبت‌شده از گزینه "
            "«🔄 همگام‌سازی» استفاده کنید.\n\n"
            "🔹 <b>شناسه من</b>\n"
            "<code>/myid</code>"
        )

    else:

        text = (
            "❓ <b>راهنما</b>\n\n"
            "🆔 برای مشاهده شناسه کاربری:\n"
            "<code>/myid</code>"
        )

    send_message(
        chat_id,
        text,
        main_keyboard(user_id)
    )


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

def list_admins():

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("*")
            .eq("active", True)
            .order("created_at")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "LIST ADMINS ERROR:",
            repr(e)
        )

        return []


def generate_admins():

    rows = list_admins()

    text = (
        "👥 <b>مدیران ربات</b>\n\n"
    )

    owner_id = get_owner_id()

    text += (
        "👑 مالک:\n"
        f"<code>{html_text(owner_id or '-')}</code>\n\n"
    )

    if not rows:

        text += "هنوز مدیر دیگری ثبت نشده است."

        return text

    for index, row in enumerate(
        rows,
        start=1
    ):

        name = (
            row.get("first_name")
            or row.get("username")
            or row.get("user_id")
        )

        username = clean_username(
            row.get("username")
        )

        text += (
            f"{to_persian_digits(index)}. "
            f"👤 {html_text(name)}"
        )

        if username:

            text += (
                f" (@{html_text(username)})"
            )

        text += (
            f"\n   🆔 "
            f"<code>{html_text(row.get('user_id'))}</code>\n\n"
        )

    return text


def add_admin(user_id):

    user_id = str(user_id).strip()

    if not user_id:
        return False

    try:

        existing = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("bot_admins")
                .update({
                    "active": True
                })
                .eq(
                    "id",
                    existing.data[0]["id"]
                )
                .execute()
            )

        else:

            (
                supabase
                .table("bot_admins")
                .insert({
                    "user_id": user_id,
                    "active": True,
                    "created_at": now_iso()
                })
                .execute()
            )

        return True

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            repr(e)
        )

        return False


def remove_admin(user_id):

    user_id = str(user_id).strip()

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

        return True

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            repr(e)
        )

        return False


# =========================================================
# COMMAND HANDLER
# =========================================================

def handle_command(
    message,
    chat_id,
    user
):

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:
        return False

    parts = text.split()

    if not parts:
        return False

    command = parts[0].lower()

    user_id = (
        user.get("id")
        if user
        else None
    )

    if command.startswith("/start"):

        send_start(
            chat_id,
            user_id
        )

        return True

    if command.startswith("/myid"):

        send_message(
            chat_id,
            "🆔 <b>شناسه کاربری شما:</b>\n\n"
            f"<code>{html_text(user_id)}</code>"
        )

        return True

    if command.startswith("/cancel"):

        PENDING_ACTIONS.pop(
            str(chat_id),
            None
        )

        send_message(
            chat_id,
            "❌ عملیات لغو شد.",
            main_keyboard(user_id)
        )

        return True

    if not is_admin(user_id):

        send_message(
            chat_id,
            "⛔ شما دسترسی مدیریتی ندارید."
        )

        return True

    if command.startswith("/report"):

        send_markdown_message(
            chat_id,
            generate_report_markdown(),
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/channels"):

        send_message(
            chat_id,
            generate_channels_list(),
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/status"):

        send_message(
            chat_id,
            generate_status(),
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/clearreports"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات می‌تواند "
                "همه گزارش‌ها را حذف کند."
            )

            return True

        send_message(
            chat_id,
            "⚠️ <b>حذف کلیه گزارش‌ها</b>\n\n"
            "با تأیید این عملیات، تمام گزارش‌های "
            "بازنشر قبلی از جدول گزارش‌ها حذف می‌شوند.\n\n"
            "این عملیات قابل بازگشت نیست.",
            clear_reports_keyboard()
        )

        return True

    if command.startswith("/addchannel"):

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "add_channel"

            send_message(
                chat_id,
                "➕ <b>افزودن مقصد</b>\n\n"
                "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
                "مثال:\n"
                "<code>@example</code>\n\n"
                "یا:\n"
                "<code>-100123456789</code>\n\n"
                "برای انصراف /cancel را بفرستید."
            )

        else:

            ok, result_text = manual_add_channel(
                parts[1]
            )

            send_message(
                chat_id,
                result_text,
                main_keyboard(user_id)
            )

        return True

    if command.startswith("/removechannel"):

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "remove_channel"

            send_message(
                chat_id,
                "➖ <b>حذف مقصد</b>\n\n"
                "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
                "برای انصراف /cancel را بفرستید."
            )

        else:

            ok, result_text = manual_remove_channel(
                parts[1]
            )

            send_message(
                chat_id,
                result_text,
                main_keyboard(user_id)
            )

        return True

    if command.startswith("/syncchannels"):

        send_message(
            chat_id,
            "⏳ در حال بررسی وضعیت مقصدهای ثبت‌شده..."
        )

        result = sync_channels()

        text = (
            "🔄 <b>همگام‌سازی انجام شد</b>\n\n"
            f"🔍 بررسی‌شده: "
            f"{to_persian_digits(result['checked'])}\n"
            f"🟢 فعال: "
            f"{to_persian_digits(result['active'])}\n"
            f"🔴 خارج‌شده: "
            f"{to_persian_digits(result['removed'])}\n"
            f"⚠️ خطا: "
            f"{to_persian_digits(result['errors'])}"
        )

        send_message(
            chat_id,
            text,
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/admins"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return True

        send_message(
            chat_id,
            generate_admins(),
            admin_keyboard()
        )

        return True

    if command.startswith("/addadmin"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return True

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "add_admin"

            send_message(
                chat_id,
                "➕ <b>افزودن مدیر</b>\n\n"
                "شناسه عددی کاربر را ارسال کنید."
            )

        else:

            if add_admin(parts[1]):

                send_message(
                    chat_id,
                    "✅ مدیر با موفقیت اضافه شد.",
                    admin_keyboard()
                )

            else:

                send_message(
                    chat_id,
                    "❌ افزودن مدیر ناموفق بود.",
                    admin_keyboard()
                )

        return True

    if command.startswith("/removeadmin"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return True

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "remove_admin"

            send_message(
                chat_id,
                "➖ <b>حذف مدیر</b>\n\n"
                "شناسه عددی مدیر را ارسال کنید."
            )

        else:

            if remove_admin(parts[1]):

                send_message(
                    chat_id,
                    "✅ مدیر حذف شد.",
                    admin_keyboard()
                )

            else:

                send_message(
                    chat_id,
                    "❌ حذف مدیر ناموفق بود.",
                    admin_keyboard()
                )

        return True

    return False


# =========================================================
# BUTTON HANDLER
# =========================================================

def handle_button(
    message,
    chat_id,
    user
):

    text = (
        message.get("text")
        or ""
    ).strip()

    user_id = (
        user.get("id")
        if user
        else None
    )

    if text == "🆔 شناسه من":

        send_message(
            chat_id,
            "🆔 <b>شناسه کاربری شما:</b>\n\n"
            f"<code>{html_text(user_id)}</code>"
        )

        return True

    if text == "❓ راهنما":

        send_help(
            chat_id,
            user_id
        )

        return True

    if not is_admin(user_id):

        send_message(
            chat_id,
            "⛔ دسترسی شما محدود است."
        )

        return True

    if text == "📊 گزارش بازنشر":

        send_markdown_message(
            chat_id,
            generate_report_markdown(),
            main_keyboard(user_id)
        )

        return True

    if text == "📡 کانال‌ها و گروه‌ها":

        send_message(
            chat_id,
            generate_channels_list(),
            main_keyboard(user_id)
        )

        return True

    if text == "➕ افزودن مقصد":

        PENDING_ACTIONS[
            str(chat_id)
        ] = "add_channel"

        send_message(
            chat_id,
            "➕ <b>افزودن مقصد</b>\n\n"
            "نام کاربری مقصد با @ یا شناسه عددی را "
            "ارسال کنید.\n\n"
            "مثال:\n"
            "<code>@example</code>\n\n"
            "یا:\n"
            "<code>-100123456789</code>\n\n"
            "برای انصراف /cancel را بفرستید."
        )

        return True

    if text == "➖ حذف مقصد":

        PENDING_ACTIONS[
            str(chat_id)
        ] = "remove_channel"

        send_message(
            chat_id,
            "➖ <b>حذف مقصد</b>\n\n"
            "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
            "برای انصراف /cancel را بفرستید."
        )

        return True

    if text == "🔄 همگام‌سازی":

        send_message(
            chat_id,
            "⏳ در حال بررسی وضعیت مقصدهای ثبت‌شده..."
        )

        result = sync_channels()

        send_message(
            chat_id,
            "🔄 <b>همگام‌سازی انجام شد</b>\n\n"
            f"🔍 بررسی‌شده: "
            f"{to_persian_digits(result['checked'])}\n"
            f"🟢 فعال: "
            f"{to_persian_digits(result['active'])}\n"
            f"🔴 خارج‌شده: "
            f"{to_persian_digits(result['removed'])}\n"
            f"⚠️ خطا: "
            f"{to_persian_digits(result['errors'])}",
            main_keyboard(user_id)
        )

        return True

    if text == "📈 وضعیت ربات":

        send_message(
            chat_id,
            generate_status(),
            main_keyboard(user_id)
        )

        return True

    if text == "🗑️ پاک کردن کلیه گزارش‌ها":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات می‌تواند "
                "همه گزارش‌ها را حذف کند."
            )

            return True

        send_message(
            chat_id,
            "⚠️ <b>حذف کلیه گزارش‌ها</b>\n\n"
            "تمام گزارش‌های بازنشر قبلی حذف خواهند شد.\n\n"
            "❗ این عملیات قابل بازگشت نیست.\n\n"
            "آیا مطمئن هستید؟",
            clear_reports_keyboard()
        )

        return True

    if text == "⚙️ مدیریت مدیران":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات به مدیریت مدیران دسترسی دارد."
            )

            return True

        send_message(
            chat_id,
            "⚙️ <b>مدیریت مدیران</b>\n\n"
            "از منوی زیر استفاده کنید.",
            admin_keyboard()
        )

        return True

    if text == "👥 مدیران ربات":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        send_message(
            chat_id,
            generate_admins(),
            admin_keyboard()
        )

        return True

    if text == "➕ افزودن مدیر":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS[
            str(chat_id)
        ] = "add_admin"

        send_message(
            chat_id,
            "➕ <b>افزودن مدیر</b>\n\n"
            "شناسه عددی کاربر را ارسال کنید."
        )

        return True

    if text == "➖ حذف مدیر":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS[
            str(chat_id)
        ] = "remove_admin"

        send_message(
            chat_id,
            "➖ <b>حذف مدیر</b>\n\n"
            "شناسه عددی مدیر را ارسال کنید."
        )

        return True

    if text == "🏠 منوی اصلی":

        send_start(
            chat_id,
            user_id
        )

        return True

    return False


# =========================================================
# CALLBACK QUERY HANDLER
# =========================================================

def process_callback_query(callback_query):

    if not callback_query:
        return

    callback_id = callback_query.get("id")

    data = (
        callback_query.get("data")
        or ""
    )

    from_user = (
        callback_query.get("from")
        or {}
    )

    user_id = from_user.get("id")

    message = (
        callback_query.get("message")
        or {}
    )

    chat = (
        message.get("chat")
        or {}
    )

    chat_id = chat.get("id")

    # -----------------------------------------------------
    # پاسخ اولیه
    # -----------------------------------------------------

    if callback_id:

        try:

            answer_callback_query(
                callback_id
            )

        except Exception as e:

            print(
                "CALLBACK ANSWER ERROR:",
                repr(e)
            )

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    if data == "report_selected_source":

        if not is_admin(user_id):

            if callback_id:

                answer_callback_query(
                    callback_id,
                    "⛔ شما دسترسی مدیریتی ندارید.",
                    True
                )

            return

        if chat_id is None:
            return

        send_markdown_message(
            chat_id,
            generate_report_markdown(),
            main_keyboard(user_id)
        )

        return

    # -----------------------------------------------------
    # CONFIRM DELETE
    # -----------------------------------------------------

    if data == "confirm_clear_reports":

        if not is_owner(user_id):

            if callback_id:

                answer_callback_query(
                    callback_id,
                    "⛔ فقط مالک ربات اجازه دارد.",
                    True
                )

            return

        ok, count = delete_all_reports()

        if ok:

            if count:

                text = (
                    "✅ <b>گزارش‌ها پاک شدند.</b>\n\n"
                    f"🗑 تعداد گزارش‌های حذف‌شده: "
                    f"<b>{to_persian_digits(count)}</b>\n\n"
                    "گزارش‌های جدید از این لحظه دوباره "
                    "ثبت خواهند شد."
                )

            else:

                text = (
                    "ℹ️ <b>گزارشی برای حذف وجود نداشت.</b>"
                )

        else:

            text = (
                "❌ <b>حذف گزارش‌ها ناموفق بود.</b>\n\n"
                "لطفاً لاگ ربات را بررسی کنید."
            )

        send_message(
            chat_id,
            text,
            main_keyboard(user_id)
        )

        return

    # -----------------------------------------------------
    # CANCEL DELETE
    # -----------------------------------------------------

    if data == "cancel_clear_reports":

        if not is_owner(user_id):
            return

        send_message(
            chat_id,
            "❌ عملیات حذف گزارش‌ها لغو شد.",
            main_keyboard(user_id)
        )

        return


# =========================================================
# PENDING ACTION
# =========================================================

def handle_pending_action(
    message,
    chat_id,
    user
):

    key = str(chat_id)

    action = PENDING_ACTIONS.get(key)

    if not action:
        return False

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:
        return False

    user_id = (
        user.get("id")
        if user
        else None
    )

    if text.lower() in (
        "/cancel",
        "لغو",
        "انصراف"
    ):

        PENDING_ACTIONS.pop(
            key,
            None
        )

        send_message(
            chat_id,
            "❌ عملیات لغو شد.",
            main_keyboard(user_id)
        )

        return True

    if action == "add_channel":

        PENDING_ACTIONS.pop(
            key,
            None
        )

        ok, result_text = manual_add_channel(
            text
        )

        send_message(
            chat_id,
            result_text,
            main_keyboard(user_id)
        )

        return True

    if action == "remove_channel":

        PENDING_ACTIONS.pop(
            key,
            None
        )

        ok, result_text = manual_remove_channel(
            text
        )

        send_message(
            chat_id,
            result_text,
            main_keyboard(user_id)
        )

        return True

    if action == "add_admin":

        if not is_owner(user_id):

            PENDING_ACTIONS.pop(
                key,
                None
            )

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS.pop(
            key,
            None
        )

        if add_admin(text):

            send_message(
                chat_id,
                "✅ مدیر با موفقیت اضافه شد.",
                admin_keyboard()
            )

        else:

            send_message(
                chat_id,
                "❌ افزودن مدیر ناموفق بود.",
                admin_keyboard()
            )

        return True

    if action == "remove_admin":

        if not is_owner(user_id):

            PENDING_ACTIONS.pop(
                key,
                None
            )

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS.pop(
            key,
            None
        )

        if remove_admin(text):

            send_message(
                chat_id,
                "✅ مدیر حذف شد.",
                admin_keyboard()
            )

        else:

            send_message(
                chat_id,
                "❌ حذف مدیر ناموفق بود.",
                admin_keyboard()
            )

        return True

    return False


# =========================================================
# PRIVATE MESSAGE
# =========================================================

def process_private_message(message):

    if not message:
        return

    chat = message.get("chat")

    user = (
        message.get("from")
        or {}
    )

    if not chat:
        return

    chat_id = chat.get("id")

    if chat_id is None:
        return

    save_bot_user(user)

    user_id = user.get("id")

    text = (
        message.get("text")
        or ""
    ).strip()

    # -----------------------------------------------------
    # COMMAND
    # -----------------------------------------------------

    if text.startswith("/"):

        if handle_command(
            message,
            chat_id,
            user
        ):
            return

    # -----------------------------------------------------
    # PENDING ACTION
    # -----------------------------------------------------

    if handle_pending_action(
        message,
        chat_id,
        user
    ):
        return

    # -----------------------------------------------------
    # BUTTON
    # -----------------------------------------------------

    if text:

        if handle_button(
            message,
            chat_id,
            user
        ):
            return

    # -----------------------------------------------------
    # FORWARD SOURCE
    # -----------------------------------------------------

    source = extract_forward(message)

    if source:

        if not is_admin(user_id):
            return

        set_selected_source(
            source,
            chat_id
        )


# =========================================================
# DEBUG UPDATE
# =========================================================

def print_update_debug(update):

    print("\n")
    print("=" * 100)
    print("🔥🔥🔥 NEW BALE UPDATE 🔥🔥🔥")
    print("=" * 100)

    print(
        "UPDATE ID:",
        update.get("update_id")
    )

    print(
        "UPDATE KEYS:",
        list(update.keys())
    )

    print("-" * 100)

    if "message" in update:

        print("MESSAGE:")
        print(update["message"])

    if "channel_post" in update:

        print("CHANNEL POST:")
        print(update["channel_post"])

    if "callback_query" in update:

        print("CALLBACK QUERY:")
        print(update["callback_query"])

    if "my_chat_member" in update:

        print("MY CHAT MEMBER:")
        print(update["my_chat_member"])

    if "chat_member" in update:

        print("CHAT MEMBER:")
        print(update["chat_member"])

    if "chat_join_request" in update:

        print("CHAT JOIN REQUEST:")
        print(update["chat_join_request"])

    print("=" * 100)
    print("🔥 END UPDATE")
    print("=" * 100)
    print("\n")


# =========================================================
# PROCESS UPDATE
# =========================================================

def process_update(update):

    print_update_debug(update)

    # -----------------------------------------------------
    # CALLBACK
    # -----------------------------------------------------

    callback_query = update.get(
        "callback_query"
    )

    if callback_query:

        try:

            process_callback_query(
                callback_query
            )

        except Exception as e:

            print(
                "CALLBACK PROCESS ERROR:",
                repr(e)
            )

            traceback.print_exc()

        return

    # -----------------------------------------------------
    # MEMBERSHIP
    # -----------------------------------------------------

    try:

        if handle_bot_membership_update(
            update
        ):
            return

    except Exception as e:

        print(
            "MEMBERSHIP UPDATE ERROR:",
            repr(e)
        )

        traceback.print_exc()

    # -----------------------------------------------------
    # MESSAGE
    # -----------------------------------------------------

    message = update.get("message")

    if not message:

        message = update.get(
            "channel_post"
        )

    if not message:
        return

    chat = message.get("chat")

    if not chat:
        return

    chat_type = chat.get("type")

    # -----------------------------------------------------
    # GROUP SERVICE
    # -----------------------------------------------------

    if chat_type in (
        "group",
        "supergroup"
    ):

        try:

            if handle_group_service_message(
                message
            ):
                return

        except Exception as e:

            print(
                "GROUP SERVICE ERROR:",
                repr(e)
            )

            traceback.print_exc()

    # -----------------------------------------------------
    # PRIVATE
    # -----------------------------------------------------

    if chat_type == "private":

        process_private_message(
            message
        )

        return

    # -----------------------------------------------------
    # GROUP / CHANNEL
    # -----------------------------------------------------

    if chat_type in (
        "group",
        "supergroup",
        "channel"
    ):

        process_channel_message(
            message
        )


# =========================================================
# INITIALIZE
# =========================================================

def initialize():

    print(
        "\n"
        "======================================"
    )

    print(
        "🚀 BALE REPOST BOT STARTING..."
    )

    print(
        "======================================"
    )

    bot = get_me()

    if not bot:

        raise Exception(
            "Bot authentication failed"
        )

    print(
        "BOT ID:",
        bot.get("id")
    )

    print(
        "BOT USERNAME:",
        bot.get("username")
    )

    owner_id = get_owner_id()

    if not owner_id:

        print(
            "⚠️ WARNING: owner_id is not configured."
        )

        print(
            "Set bot_settings.owner_id in Supabase."
        )

    else:

        print(
            "OWNER ID:",
            owner_id
        )

    print(
        "======================================"
    )

    print(
        "BOT IS READY"
    )

    print(
        "======================================"
    )


# =========================================================
# MAIN LOOP
# =========================================================

def main():

    global LAST_UPDATE_ID

    initialize()

    offset = None

    while True:

        try:

            updates = get_updates(
                offset
            )

            if updates is None:

                time.sleep(2)

                continue

            if not updates:
                continue

            print(
                f"📥 RECEIVED {len(updates)} UPDATE(S)"
            )

            for update in updates:

                try:

                    update_id = update.get(
                        "update_id"
                    )

                    if update_id is not None:

                        LAST_UPDATE_ID = update_id

                        offset = (
                            int(update_id) + 1
                        )

                    process_update(
                        update
                    )

                except Exception as e:

                    print(
                        "❌ PROCESS UPDATE ERROR:",
                        repr(e)
                    )

                    traceback.print_exc()

        except KeyboardInterrupt:

            print(
                "🛑 BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "❌ MAIN LOOP ERROR:",
                repr(e)
            )

            traceback.print_exc()

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
