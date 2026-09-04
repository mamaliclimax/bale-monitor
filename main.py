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


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

BALE_API = f"https://tapi.bale.ai/bot{BALE_TOKEN}"

IRAN_TZ = ZoneInfo("Asia/Tehran")

OWNER_ID = None

BOT_INFO = None


# =========================================================
# UI
# =========================================================

def main_menu(chat_id):

    if is_owner(chat_id):

        return {
            "keyboard": [
                [
                    {
                        "text": "📊 گزارش بازنشر"
                    },
                    {
                        "text": "📡 کانال‌ها و گروه‌ها"
                    }
                ],
                [
                    {
                        "text": "➕ افزودن مقصد"
                    },
                    {
                        "text": "➖ حذف مقصد"
                    }
                ],
                [
                    {
                        "text": "📈 وضعیت ربات"
                    },
                    {
                        "text": "⚙️ مدیریت مدیران"
                    }
                ],
                [
                    {
                        "text": "❓ راهنما"
                    }
                ]
            ],
            "resize_keyboard": True
        }

    if is_admin(chat_id):

        return {
            "keyboard": [
                [
                    {
                        "text": "📊 گزارش بازنشر"
                    },
                    {
                        "text": "📡 کانال‌ها و گروه‌ها"
                    }
                ],
                [
                    {
                        "text": "➕ افزودن مقصد"
                    },
                    {
                        "text": "➖ حذف مقصد"
                    }
                ],
                [
                    {
                        "text": "📈 وضعیت ربات"
                    }
                ],
                [
                    {
                        "text": "❓ راهنما"
                    }
                ]
            ],
            "resize_keyboard": True
        }

    return {
        "keyboard": [
            [
                {
                    "text": "🆔 شناسه من"
                },
                {
                    "text": "❓ راهنما"
                }
            ]
        ],
        "resize_keyboard": True
    }


def admin_menu(chat_id):

    return {
        "keyboard": [
            [
                {
                    "text": "📊 گزارش بازنشر"
                },
                {
                    "text": "📡 کانال‌ها و گروه‌ها"
                }
            ],
            [
                {
                    "text": "➕ افزودن مقصد"
                },
                {
                    "text": "➖ حذف مقصد"
                }
            ],
            [
                {
                    "text": "📈 وضعیت ربات"
                }
            ],
            [
                {
                    "text": "🏠 منوی اصلی"
                }
            ]
        ],
        "resize_keyboard": True
    }


def owner_menu():

    return {
        "keyboard": [
            [
                {
                    "text": "👥 مدیران ربات"
                },
                {
                    "text": "➕ افزودن مدیر"
                }
            ],
            [
                {
                    "text": "➖ حذف مدیر"
                },
                {
                    "text": "🏠 منوی اصلی"
                }
            ]
        ],
        "resize_keyboard": True
    }


# =========================================================
# BASIC
# =========================================================

def clean_username(username):

    if not username:
        return None

    username = str(username).strip()

    if username.startswith("@"):
        username = username[1:]

    return username or None


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def to_persian_digits(value):

    if value is None:
        return ""

    table = str.maketrans(
        "0123456789",
        "۰۱۲۳۴۵۶۷۸۹"
    )

    return str(value).translate(table)


# =========================================================
# JALALI
# =========================================================

def gregorian_to_jalali(
    gy,
    gm,
    gd
):

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
        (
            gy % 4 == 0
            and gy % 100 != 0
        )
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

        jy += (
            j_day_no - 1
        ) // 365

        j_day_no = (
            j_day_no - 1
        ) % 365

    i = 0

    while (
        i < 11
        and j_day_no
        >= j_days_in_month[i]
    ):

        j_day_no -= (
            j_days_in_month[i]
        )

        i += 1

    jm = i + 1
    jd = j_day_no + 1

    return jy, jm, jd


def format_iran_datetime(value):

    if not value:
        return "-"

    try:

        if isinstance(
            value,
            datetime
        ):

            dt = value

        else:

            value = str(value).strip()

            if value.endswith("Z"):

                value = (
                    value[:-1]
                    + "+00:00"
                )

            dt = datetime.fromisoformat(
                value
            )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        dt = dt.astimezone(
            IRAN_TZ
        )

        jy, jm, jd = (
            gregorian_to_jalali(
                dt.year,
                dt.month,
                dt.day
            )
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
            to_persian_digits(
                date_text
            )
            + " - "
            + to_persian_digits(
                time_text
            )
        )

    except Exception as e:

        print(
            "DATE ERROR:",
            repr(e)
        )

        return str(value)


# =========================================================
# BALE API
# =========================================================

def bale_request(
    method,
    data=None
):

    url = (
        f"{BALE_API}/{method}"
    )

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=45
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

        data["reply_markup"] = (
            reply_markup
        )

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


def get_me():

    global BOT_INFO

    if BOT_INFO:
        return BOT_INFO

    result = bale_request(
        "getMe",
        {}
    )

    if result:
        BOT_INFO = result

    return result


# =========================================================
# LINK
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

    chat_id = str(
        chat_id
    ).strip()

    message_id = str(
        message_id
    ).strip()

    if not chat_id:
        return None

    if not message_id:
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
            repr(e)
        )

    return None


def set_setting(
    key,
    value
):

    try:

        result = (
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

        if result.data:

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


def load_owner():

    global OWNER_ID

    value = get_setting(
        "owner_id"
    )

    if value:

        OWNER_ID = str(
            value
        ).strip()

    else:

        OWNER_ID = None

    print(
        "OWNER_ID:",
        OWNER_ID
    )


# =========================================================
# ACCESS
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

        return bool(
            result.data
        )

    except Exception as e:

        print(
            "IS ADMIN ERROR:",
            repr(e)
        )

        return False


def deny_access(chat_id):

    send_message(
        chat_id,
        "⛔ <b>دسترسی محدود است</b>\n\n"
        "این بخش فقط برای مدیران ربات فعال است.",
        main_menu(chat_id)
    )


# =========================================================
# USERS
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

        result = (
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

        if result.data:

            (
                supabase
                .table("bot_users")
                .update(data)
                .eq(
                    "id",
                    result.data[0]["id"]
                )
                .execute()
            )

        else:

            data["created_at"] = (
                now_iso()
            )

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
# CHANNEL AUTO REGISTER
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

    chat_id = str(
        chat_id
    )

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or username
        or chat_id
    )

    try:

        # =================================================
        # SEARCH BY CHAT ID
        # =================================================

        result = (
            supabase
            .table("channels")
            .select("*")
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

            bot_member = row.get(
                "bot_member"
            )

            # NULL را فعال در نظر می‌گیریم
            if bot_member is None:
                bot_member = True

            update_data = {
                "chat_id": chat_id,
                "username": username,
                "title": title
            }

            if manually_disabled:

                update_data["active"] = False

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

            print(
                "CHANNEL FOUND:",
                title,
                chat_id
            )

            return True

        # =================================================
        # SEARCH BY USERNAME
        # =================================================

        if username:

            result = (
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
                    "title": title,
                    "bot_member": True
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

                print(
                    "CHANNEL UPDATED:",
                    title
                )

                return True

        # =================================================
        # NEW CHANNEL
        # =================================================

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
            "🟢 NEW DESTINATION:",
            title,
            chat_id
        )

        return True

    except Exception as e:

        print(
            "AUTO REGISTER ERROR:",
            repr(e)
        )

        return False


# =========================================================
# DEACTIVATE
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
            "🔴 DESTINATION DEACTIVATED:",
            chat_id
        )

    except Exception as e:

        print(
            "DEACTIVATE ERROR:",
            repr(e)
        )


# =========================================================
# ACTIVE CHANNELS
# =========================================================

def get_active_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "active",
                True
            )
            .eq(
                "manually_disabled",
                False
            )
            .order(
                "title"
            )
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "ACTIVE CHANNELS ERROR:",
            repr(e)
        )

        return []


# =========================================================
# CHANNEL LIST
# =========================================================

def show_channels(chat_id):

    if not is_admin(chat_id):

        deny_access(chat_id)
        return

    rows = get_active_channels()

    if not rows:

        send_message(
            chat_id,
            "📡 <b>مقصدهای فعال</b>\n\n"
            "در حال حاضر هیچ کانال یا گروه فعالی "
            "در سیستم ثبت نشده است.\n\n"
            "➕ از گزینه «افزودن مقصد» استفاده کنید.",
            admin_menu(chat_id)
        )

        return

    text = (
        "📡 <b>کانال‌ها و گروه‌های فعال</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    for index, row in enumerate(
        rows,
        start=1
    ):

        title = (
            row.get("title")
            or "-"
        )

        username = clean_username(
            row.get("username")
        )

        channel_id = row.get(
            "chat_id"
        )

        if username:

            identity = (
                f"@{username}"
            )

        else:

            identity = (
                f"شناسه: "
                f"<code>{channel_id}</code>"
            )

        text += (
            f"🔹 <b>{to_persian_digits(index)}. "
            f"{title}</b>\n"
            f"   {identity}\n\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟢 تعداد فعال: "
        f"<b>{to_persian_digits(len(rows))}</b>\n\n"
        "ℹ️ این فهرست فقط مقصدهای فعال را نمایش می‌دهد."
    )

    send_message(
        chat_id,
        text,
        admin_menu(chat_id)
    )


# =========================================================
# MANUAL ADD
# =========================================================

def manual_add_channel(
    admin_chat_id,
    target
):

    if not is_admin(
        admin_chat_id
    ):

        deny_access(
            admin_chat_id
        )

        return

    target = target.strip()

    if not target:

        send_message(
            admin_chat_id,
            "➕ <b>افزودن مقصد</b>\n\n"
            "شناسه یا نام کاربری کانال/گروه را ارسال کنید.\n\n"
            "مثال:\n"
            "<code>@mychannel</code>\n"
            "یا\n"
            "<code>123456789</code>",
            admin_menu(admin_chat_id)
        )

        return

    chat = get_chat(
        target
    )

    if not chat:

        send_message(
            admin_chat_id,
            "❌ <b>مقصد پیدا نشد</b>\n\n"
            "مطمئن شوید ربات داخل کانال یا گروه عضو است "
            "و شناسه صحیح را وارد کرده‌اید.",
            admin_menu(admin_chat_id)
        )

        return

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
            "❌ این مقصد قابل استفاده نیست.\n\n"
            "فقط کانال، گروه و سوپرگروه مجاز هستند.",
            admin_menu(admin_chat_id)
        )

        return

    channel_id = chat.get(
        "id"
    )

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or username
        or str(channel_id)
    )

    try:

        existing = (
            supabase
            .table("channels")
            .select("id")
            .eq(
                "chat_id",
                str(channel_id)
            )
            .limit(1)
            .execute()
        )

        data = {
            "chat_id": str(channel_id),
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

        identity = (
            f"@{username}"
            if username
            else str(channel_id)
        )

        send_message(
            admin_chat_id,
            "✅ <b>مقصد با موفقیت فعال شد</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 نام: <b>{title}</b>\n"
            f"🔗 {identity}\n\n"
            "🟢 وضعیت: فعال\n"
            "🤖 ربات: عضو مقصد است\n\n"
            "این مقصد از این لحظه در گزارش‌های جاری "
            "محاسبه می‌شود.",
            admin_menu(admin_chat_id)
        )

    except Exception as e:

        print(
            "MANUAL ADD ERROR:",
            repr(e)
        )

        send_message(
            admin_chat_id,
            "❌ خطا هنگام فعال‌سازی مقصد.",
            admin_menu(admin_chat_id)
        )


# =========================================================
# MANUAL REMOVE
# =========================================================

def manual_remove_channel(
    admin_chat_id,
    target
):

    if not is_admin(
        admin_chat_id
    ):

        deny_access(
            admin_chat_id
        )

        return

    target = target.strip()

    if not target:

        send_message(
            admin_chat_id,
            "➖ <b>حذف مقصد</b>\n\n"
            "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
            "مثال:\n"
            "<code>@mychannel</code>",
            admin_menu(admin_chat_id)
        )

        return

    if target.startswith("@"):

        username = clean_username(
            target
        )

        result = (
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

        result = (
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

    if not result.data:

        send_message(
            admin_chat_id,
            "❌ <b>مقصد پیدا نشد</b>\n\n"
            "این کانال یا گروه در فهرست سیستم وجود ندارد.",
            admin_menu(admin_chat_id)
        )

        return

    row = result.data[0]

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

        title = (
            row.get("title")
            or "-"
        )

        send_message(
            admin_chat_id,
            "🗑️ <b>مقصد غیرفعال شد</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 {title}\n\n"
            "🔴 از فهرست مقصدهای فعال حذف شد.\n"
            "📊 در گزارش‌های جاری نیز نمایش داده نمی‌شود.\n\n"
            "ℹ️ سوابق قبلی بازنشر حذف نشده‌اند.",
            admin_menu(admin_chat_id)
        )

    except Exception as e:

        print(
            "MANUAL REMOVE ERROR:",
            repr(e)
        )

        send_message(
            admin_chat_id,
            "❌ خطا هنگام حذف مقصد.",
            admin_menu(admin_chat_id)
        )


# =========================================================
# SOURCE
# =========================================================

def extract_forward(message):

    if not message:
        return {}

    forward_chat = (
        message.get(
            "forward_from_chat"
        )
        or {}
    )

    return {
        "chat": forward_chat,
        "message_id": message.get(
            "forward_from_message_id"
        )
    }


def process_private_forward(
    message
):

    chat_id = (
        message.get("chat")
        or {}
    ).get("id")

    forward = extract_forward(
        message
    )

    source_chat = (
        forward.get("chat")
        or {}
    )

    source_message_id = (
        forward.get("message_id")
    )

    if not source_message_id:

        send_message(
            chat_id,
            "❌ پیام فورواردشده معتبر نیست."
        )

        return

    source_channel_id = (
        source_chat.get("id")
    )

    source_username = clean_username(
        source_chat.get("username")
    )

    source_title = (
        source_chat.get("title")
        or source_username
        or str(source_channel_id)
    )

    if source_channel_id is None:

        send_message(
            chat_id,
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
        "🎯 <b>مبدأ جدید انتخاب شد</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>{source_title}</b>\n"
        f"🆔 پیام: <code>{source_message_id}</code>\n"
    )

    if source_username:

        text += (
            f"🔗 @{source_username}\n"
        )

    if link:

        text += (
            f"\n🔵 <a href=\"{link}\">مشاهده پست مبدأ</a>\n"
        )

    text += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "اکنون گزارش بازنشر این پست قابل مشاهده است."
    )

    send_message(
        chat_id,
        text,
        admin_menu(chat_id)
    )


# =========================================================
# MESSAGE TITLE
# =========================================================

def get_message_title(message):

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    text = str(
        text
    ).strip()

    if not text:
        return "بدون عنوان"

    title = (
        text.splitlines()[0]
        .strip()
    )

    if len(title) > 100:

        title = (
            title[:100]
            + "..."
        )

    return title


# =========================================================
# DUPLICATE
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

        return bool(
            result.data
        )

    except Exception as e:

        print(
            "DUPLICATE ERROR:",
            repr(e)
        )

        return False


# =========================================================
# PROCESS CHANNEL MESSAGE
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

    destination_id = chat.get(
        "id"
    )

    if destination_id is None:
        return

    print(
        "📥 CHANNEL UPDATE:",
        chat_type,
        destination_id,
        chat.get("title"),
        chat.get("username")
    )

    # =====================================================
    # AUTO REGISTER
    # =====================================================

    registered = auto_register_chat(
        chat
    )

    if not registered:

        print(
            "❌ AUTO REGISTER FAILED:",
            destination_id
        )

        return

    # =====================================================
    # GET DESTINATION
    # =====================================================

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "chat_id",
                str(destination_id)
            )
            .limit(1)
            .execute()
        )

        if not result.data:

            print(
                "❌ DESTINATION NOT FOUND:",
                destination_id
            )

            return

        destination = (
            result.data[0]
        )

    except Exception as e:

        print(
            "DESTINATION ERROR:",
            repr(e)
        )

        return

    # =====================================================
    # ACTIVE CHECK
    # =====================================================

    if destination.get(
        "active"
    ) is not True:

        print(
            "⛔ INACTIVE:",
            destination.get(
                "title"
            )
        )

        return

    if destination.get(
        "manually_disabled"
    ) is True:

        print(
            "⛔ MANUALLY DISABLED"
        )

        return

    # =====================================================
    # SOURCE
    # =====================================================

    source_channel_id = get_setting(
        "selected_source_channel_id"
    )

    source_message_id = get_setting(
        "selected_source_message_id"
    )

    source_username = get_setting(
        "selected_source_username"
    )

    if not source_channel_id:
        return

    if not source_message_id:
        return

    # =====================================================
    # DESTINATION MESSAGE
    # =====================================================

    destination_message_id = (
        message.get(
            "message_id"
        )
    )

    if not destination_message_id:
        return

    # =====================================================
    # DUPLICATE
    # =====================================================

    if repost_exists(
        source_channel_id,
        source_message_id,
        destination_id
    ):

        print(
            "♻️ DUPLICATE:",
            destination_id
        )

        return

    destination_username = clean_username(
        destination.get(
            "username"
        )
    )

    destination_title = (
        destination.get("title")
        or destination_username
        or str(destination_id)
    )

    message_title = (
        get_message_title(
            message
        )
    )

    # =====================================================
    # SAVE
    # =====================================================

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
                    destination_id
                ),
                "destination_username": (
                    destination_username
                ),
                "destination_message_id": str(
                    destination_message_id
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

        print(
            "✅ REPOST SAVED:",
            destination_title
        )

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            repr(e)
        )

        return

    # =====================================================
    # LINKS
    # =====================================================

    source_link = (
        build_bale_message_link(
            source_username,
            source_channel_id,
            source_message_id
        )
    )

    destination_link = (
        build_bale_message_link(
            destination_username,
            destination_id,
            destination_message_id
        )
    )

    # =====================================================
    # NOTIFY
    # =====================================================

    notify_repost(
        destination_title,
        destination_username,
        message_title,
        source_link,
        destination_link
    )


# =========================================================
# NOTIFICATION
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
            str(row.get("user_id"))
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
                admin_ids
            )
        )

        text = (
            "🔔 <b>بازنشر جدید</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 مقصد: <b>{destination_title}</b>\n"
        )

        if destination_username:

            text += (
                f"🔗 @{destination_username}\n"
            )

        text += (
            f"📝 عنوان: {message_title}\n"
            f"🕐 زمان: {format_iran_datetime(now_iso())}\n"
        )

        if source_link:

            text += (
                f"\n🔵 <a href=\"{source_link}\">پست مبدأ</a>"
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
                    "ADMIN NOTIFY ERROR:",
                    admin_id,
                    repr(e)
                )

    except Exception as e:

        print(
            "NOTIFY ERROR:",
            repr(e)
        )


# =========================================================
# REPORT
# =========================================================

def report_reposts(
    chat_id
):

    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

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
            "📭 <b>هنوز مبدأی انتخاب نشده است</b>\n\n"
            "یک پست از کانال مبدأ را برای ربات فوروارد کنید "
            "تا گزارش بازنشر آن ساخته شود.",
            admin_menu(chat_id)
        )

        return

    try:

        # =================================================
        # REPOST HISTORY
        # =================================================

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

        rows = result.data or []

        # =================================================
        # ACTIVE DESTINATIONS
        # =================================================

        active_result = (
            supabase
            .table("channels")
            .select(
                "chat_id,username,title,"
                "active,manually_disabled"
            )
            .eq(
                "active",
                True
            )
            .eq(
                "manually_disabled",
                False
            )
            .execute()
        )

        active_ids = {
            str(
                row.get(
                    "chat_id"
                )
            )
            for row in (
                active_result.data or []
            )
            if row.get(
                "chat_id"
            ) is not None
        }

        # =================================================
        # ONLY ACTIVE DESTINATIONS
        # =================================================

        rows = [
            row
            for row in rows
            if str(
                row.get(
                    "destination_channel_id"
                )
            ) in active_ids
        ]

        source_link = (
            build_bale_message_link(
                source_username,
                source_channel_id,
                source_message_id
            )
        )

        text = (
            "📊 <b>گزارش بازنشر</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 مبدأ: <b>{source_title or source_username or source_channel_id}</b>\n"
            f"🆔 پیام: <code>{source_message_id}</code>\n"
            f"🟢 مقصدهای فعال: "
            f"<b>{to_persian_digits(len(rows))}</b>\n"
        )

        if source_link:

            text += (
                f"\n🔵 <a href=\"{source_link}\">مشاهده پست مبدأ</a>\n"
            )

        if not rows:

            text += (
                "\n━━━━━━━━━━━━━━━━━━\n"
                "📭 هنوز در هیچ مقصد فعالی "
                "بازنشر ثبت نشده است."
            )

            send_message(
                chat_id,
                text,
                admin_menu(chat_id)
            )

            return

        text += (
            "\n━━━━━━━━━━━━━━━━━━\n"
        )

        for index, row in enumerate(
            rows,
            start=1
        ):

            title = (
                row.get(
                    "destination_title"
                )
                or "-"
            )

            username = clean_username(
                row.get(
                    "destination_username"
                )
            )

            destination_id = row.get(
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
                    username,
                    destination_id,
                    destination_message_id
                )
            )

            text += (
                f"\n{to_persian_digits(index)}️⃣ "
                f"<b>{title}</b>\n"
            )

            if username:

                text += (
                    f"   🔗 @{username}\n"
                )

            text += (
                f"   🕐 {format_iran_datetime(created_at)}\n"
            )

            if destination_link:

                text += (
                    f"   🟢 <a href=\"{destination_link}\">مشاهده پست</a>\n"
                )

        send_message(
            chat_id,
            text,
            admin_menu(chat_id)
        )

    except Exception as e:

        print(
            "REPORT ERROR:",
            repr(e)
        )

        send_message(
            chat_id,
            "❌ خطا در تهیه گزارش.",
            admin_menu(chat_id)
        )


# =========================================================
# STATUS
# =========================================================

def show_status(
    chat_id
):

    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    try:

        channels = get_active_channels()

        total_result = (
            supabase
            .table("channels")
            .select("id")
            .execute()
        )

        total = len(
            total_result.data or []
        )

        source_title = get_setting(
            "selected_source_title"
        )

        repost_result = (
            supabase
            .table("reposts")
            .select("id")
            .execute()
        )

        repost_count = len(
            repost_result.data or []
        )

        text = (
            "📈 <b>وضعیت ربات</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 مقصدهای فعال: "
            f"<b>{to_persian_digits(len(channels))}</b>\n"
            f"📚 کل مقصدهای ثبت‌شده: "
            f"<b>{to_persian_digits(total)}</b>\n"
            f"🔄 کل سوابق بازنشر: "
            f"<b>{to_persian_digits(repost_count)}</b>\n\n"
            f"🎯 مبدأ فعلی:\n"
            f"<b>{source_title or 'انتخاب نشده'}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🤖 سیستم ثبت خودکار مقصدها فعال است."
        )

        send_message(
            chat_id,
            text,
            admin_menu(chat_id)
        )

    except Exception as e:

        print(
            "STATUS ERROR:",
            repr(e)
        )


# =========================================================
# ADMIN LIST
# =========================================================

def list_admins(
    chat_id
):

    if not is_owner(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("*")
            .eq(
                "active",
                True
            )
            .order(
                "first_name"
            )
            .execute()
        )

        rows = result.data or []

        text = (
            "👥 <b>مدیران ربات</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        text += (
            f"👑 مالک:\n"
            f"<code>{OWNER_ID or '-'}</code>\n\n"
        )

        if not rows:

            text += (
                "👤 مدیر دیگری ثبت نشده است."
            )

        else:

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
                    row.get(
                        "first_name"
                    )
                    or "بدون نام"
                )

                text += (
                    f"{to_persian_digits(index)}. "
                    f"<b>{first_name}</b>\n"
                )

                if username:

                    text += (
                        f"   @{username}\n"
                    )

                text += (
                    f"   🆔 <code>{user_id}</code>\n\n"
                )

        send_message(
            chat_id,
            text,
            owner_menu()
        )

    except Exception as e:

        print(
            "LIST ADMINS ERROR:",
            repr(e)
        )


# =========================================================
# ADD ADMIN
# =========================================================

def add_admin(
    owner_chat_id,
    target
):

    if not is_owner(
        owner_chat_id
    ):

        deny_access(
            owner_chat_id
        )

        return

    target = target.strip()

    if not target:

        send_message(
            owner_chat_id,
            "➕ <b>افزودن مدیر</b>\n\n"
            "شناسه عددی کاربر را ارسال کنید.\n\n"
            "مثال:\n"
            "<code>123456789</code>\n\n"
            "کاربر می‌تواند با /myid شناسه خود را دریافت کند.",
            owner_menu()
        )

        return

    user = None
    user_id = None

    if target.lstrip("-").isdigit():

        user_id = str(
            target
        )

    else:

        username = clean_username(
            target
        )

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
                    user.get(
                        "user_id"
                    )
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
            "از کاربر بخواهید ابتدا /myid را برای ربات ارسال کند.",
            owner_menu()
        )

        return

    if is_owner(
        user_id
    ):

        send_message(
            owner_chat_id,
            "ℹ️ این کاربر مالک اصلی ربات است.",
            owner_menu()
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

            data["created_at"] = (
                now_iso()
            )

            (
                supabase
                .table("bot_admins")
                .insert(data)
                .execute()
            )

        send_message(
            owner_chat_id,
            "✅ <b>مدیر با موفقیت اضافه شد</b>\n\n"
            f"🆔 شناسه: <code>{user_id}</code>",
            owner_menu()
        )

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            repr(e)
        )

        send_message(
            owner_chat_id,
            "❌ خطا در افزودن مدیر.",
            owner_menu()
        )


# =========================================================
# REMOVE ADMIN
# =========================================================

def remove_admin(
    owner_chat_id,
    target
):

    if not is_owner(
        owner_chat_id
    ):

        deny_access(
            owner_chat_id
        )

        return

    target = target.strip()

    if not target:

        send_message(
            owner_chat_id,
            "➖ <b>حذف مدیر</b>\n\n"
            "شناسه عددی مدیر را ارسال کنید.",
            owner_menu()
        )

        return

    if not target.lstrip("-").isdigit():

        send_message(
            owner_chat_id,
            "❌ برای حذف مدیر، شناسه عددی کاربر را وارد کنید.",
            owner_menu()
        )

        return

    user_id = str(
        target
    )

    if is_owner(
        user_id
    ):

        send_message(
            owner_chat_id,
            "⛔ امکان حذف مالک اصلی وجود ندارد.",
            owner_menu()
        )

        return

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
            "✅ دسترسی مدیر حذف شد.\n\n"
            f"🆔 <code>{user_id}</code>",
            owner_menu()
        )

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            repr(e)
        )

        send_message(
            owner_chat_id,
            "❌ خطا در حذف مدیر.",
            owner_menu()
        )


# =========================================================
# MY ID
# =========================================================

def show_my_id(
    chat_id
):

    send_message(
        chat_id,
        "🆔 <b>شناسه کاربری شما</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>{chat_id}</code>\n\n"
        "این شناسه را برای مالک ربات ارسال کنید "
        "تا در صورت نیاز دسترسی مدیریت برای شما فعال شود.",
        main_menu(chat_id)
    )


# =========================================================
# HELP
# =========================================================

def show_help(
    chat_id
):

    if is_admin(
        chat_id
    ):

        text = (
            "❓ <b>راهنمای ربات</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🎯 <b>انتخاب مبدأ</b>\n"
            "یک پست از کانال مبدأ را برای ربات فوروارد کنید.\n\n"
            "📡 <b>مقصدها</b>\n"
            "هر کانال یا گروهی که ربات در آن فعالیت کند "
            "می‌تواند به عنوان مقصد ثبت شود.\n\n"
            "📊 <b>گزارش</b>\n"
            "فقط مقصدهای فعال در گزارش جاری نمایش داده می‌شوند.\n\n"
            "➕ <b>افزودن مقصد</b>\n"
            "یک کانال یا گروه را دوباره فعال می‌کند.\n\n"
            "➖ <b>حذف مقصد</b>\n"
            "مقصد را غیرفعال می‌کند اما سوابق قبلی حذف نمی‌شوند.\n\n"
            "🔄 <b>ثبت خودکار</b>\n"
            "ربات اطلاعات مقصدهای جدید را هنگام دریافت پیام "
            "از آنها ثبت می‌کند."
        )

    else:

        text = (
            "❓ <b>راهنما</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🆔 برای دریافت شناسه کاربری خود، "
            "گزینه «شناسه من» را بزنید.\n\n"
            "برای دسترسی به بخش مدیریت، "
            "باید توسط مالک ربات به عنوان مدیر اضافه شوید."
        )

    send_message(
        chat_id,
        text,
        main_menu(chat_id)
    )


# =========================================================
# COMMAND PARSER
# =========================================================

def get_command(
    text
):

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

    return (
        command.lower(),
        parts[1:]
    )


# =========================================================
# TEXT MENU HANDLER
# =========================================================

def process_menu_text(
    chat_id,
    text
):

    text = text.strip()

    if text == "🆔 شناسه من":

        show_my_id(
            chat_id
        )

        return True

    if text == "📊 گزارش بازنشر":

        report_reposts(
            chat_id
        )

        return True

    if text == "📡 کانال‌ها و گروه‌ها":

        show_channels(
            chat_id
        )

        return True

    if text == "📈 وضعیت ربات":

        show_status(
            chat_id
        )

        return True

    if text == "❓ راهنما":

        show_help(
            chat_id
        )

        return True

    if text == "🏠 منوی اصلی":

        send_message(
            chat_id,
            "🏠 <b>منوی اصلی</b>\n\n"
            "گزینه موردنظر را انتخاب کنید.",
            main_menu(chat_id)
        )

        return True

    if text == "➕ افزودن مقصد":

        if not is_admin(chat_id):

            deny_access(chat_id)
            return True

        send_message(
            chat_id,
            "➕ <b>افزودن مقصد</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "نام کاربری یا شناسه کانال/گروه را ارسال کنید.\n\n"
            "مثال:\n"
            "<code>@mychannel</code>\n\n"
            "یا:\n"
            "<code>123456789</code>",
            admin_menu(chat_id)
        )

        set_setting(
            f"awaiting_action_{chat_id}",
            "add_channel"
        )

        return True

    if text == "➖ حذف مقصد":

        if not is_admin(chat_id):

            deny_access(chat_id)
            return True

        send_message(
            chat_id,
            "➖ <b>حذف مقصد</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
            "مثال:\n"
            "<code>@mychannel</code>",
            admin_menu(chat_id)
        )

        set_setting(
            f"awaiting_action_{chat_id}",
            "remove_channel"
        )

        return True

    if text == "⚙️ مدیریت مدیران":

        if not is_owner(chat_id):

            deny_access(chat_id)
            return True

        send_message(
            chat_id,
            "⚙️ <b>مدیریت مدیران</b>\n\n"
            "از گزینه‌های زیر استفاده کنید.",
            owner_menu()
        )

        return True

    if text == "👥 مدیران ربات":

        list_admins(
            chat_id
        )

        return True

    if text == "➕ افزودن مدیر":

        if not is_owner(chat_id):

            deny_access(chat_id)
            return True

        send_message(
            chat_id,
            "➕ <b>افزودن مدیر</b>\n\n"
            "شناسه عددی کاربر را ارسال کنید.",
            owner_menu()
        )

        set_setting(
            f"awaiting_action_{chat_id}",
            "add_admin"
        )

        return True

    if text == "➖ حذف مدیر":

        if not is_owner(chat_id):

            deny_access(chat_id)
            return True

        send_message(
            chat_id,
            "➖ <b>حذف مدیر</b>\n\n"
            "شناسه عددی مدیر را ارسال کنید.",
            owner_menu()
        )

        set_setting(
            f"awaiting_action_{chat_id}",
            "remove_admin"
        )

        return True

    return False


# =========================================================
# COMMAND PROCESSOR
# =========================================================

def process_command(
    chat_id,
    text,
    username=None
):

    command, args = get_command(
        text
    )

    if not command:
        return

    if command == "/myid":

        show_my_id(
            chat_id
        )

        return

    if command == "/start":

        if is_admin(chat_id):

            send_message(
                chat_id,
                "🤖 <b>سامانه مدیریت بازنشر</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "به پنل مدیریت خوش آمدید.\n\n"
                "📊 گزارش بازنشرها را ببینید\n"
                "📡 مقصدهای فعال را مدیریت کنید\n"
                "🎯 مبدأ بازنشر را انتخاب کنید\n"
                "📈 وضعیت سامانه را بررسی کنید\n\n"
                "یک گزینه را از منوی پایین انتخاب کنید.",
                main_menu(chat_id)
            )

        else:

            send_message(
                chat_id,
                "👋 <b>سلام!</b>\n\n"
                "شما به پنل عمومی ربات دسترسی دارید.\n\n"
                "برای دریافت شناسه خود، "
                "گزینه «شناسه من» را انتخاب کنید.",
                main_menu(chat_id)
            )

        return

    if command == "/channels":

        show_channels(
            chat_id
        )

        return

    if command == "/report":

        report_reposts(
            chat_id
        )

        return

    if command == "/status":

        show_status(
            chat_id
        )

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

    if command == "/admins":

        list_admins(
            chat_id
        )

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
        "NEW UPDATE:",
        update
    )

    print(
        "========================================"
    )

    # =====================================================
    # MEMBERSHIP UPDATE
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
                "MEMBERSHIP:",
                chat.get("id"),
                chat.get("title"),
                status
            )

            if status in (
                "left",
                "kicked"
            ):

                deactivate_chat(
                    chat.get("id")
                )

            else:

                auto_register_chat(
                    chat
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

        # -----------------------------------------------
        # pending action
        # -----------------------------------------------

        pending_action = get_setting(
            f"awaiting_action_{chat_id}"
        )

        if pending_action and text:

            set_setting(
                f"awaiting_action_{chat_id}",
                ""
            )

            if pending_action == "add_channel":

                manual_add_channel(
                    chat_id,
                    text
                )

                return

            if pending_action == "remove_channel":

                manual_remove_channel(
                    chat_id,
                    text
                )

                return

            if pending_action == "add_admin":

                add_admin(
                    chat_id,
                    text
                )

                return

            if pending_action == "remove_admin":

                remove_admin(
                    chat_id,
                    text
                )

                return

        # -----------------------------------------------
        # public id
        # -----------------------------------------------

        command, args = get_command(
            text
        )

        if command == "/myid":

            show_my_id(
                chat_id
            )

            return

        # -----------------------------------------------
        # forward
        # -----------------------------------------------

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

        # -----------------------------------------------
        # menu
        # -----------------------------------------------

        if text:

            if process_menu_text(
                chat_id,
                text
            ):

                return

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
            "📥 DESTINATION UPDATE:",
            chat_type,
            chat_id,
            chat.get("title")
        )

        # -----------------------------------------------
        # register automatically
        # -----------------------------------------------

        auto_register_chat(
            chat
        )

        # -----------------------------------------------
        # new members
        # -----------------------------------------------

        new_members = (
            message.get(
                "new_chat_members"
            )
            or []
        )

        if new_members:

            bot = get_me()

            if bot:

                bot_id = str(
                    bot.get("id")
                )

                for member in new_members:

                    if str(
                        member.get("id")
                    ) == bot_id:

                        print(
                            "🤖 BOT ADDED:",
                            chat_id
                        )

                        try:

                            result = (
                                supabase
                                .table("channels")
                                .select(
                                    "id,manually_disabled"
                                )
                                .eq(
                                    "chat_id",
                                    str(chat_id)
                                )
                                .limit(1)
                                .execute()
                            )

                            if result.data:

                                row = result.data[0]

                                (
                                    supabase
                                    .table("channels")
                                    .update({
                                        "active": True,
                                        "bot_member": True,
                                        "manually_disabled": False
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
                                "BOT ADD DB ERROR:",
                                repr(e)
                            )

        # -----------------------------------------------
        # bot left
        # -----------------------------------------------

        left_member = message.get(
            "left_chat_member"
        )

        if left_member:

            bot = get_me()

            if bot:

                bot_id = str(
                    bot.get("id")
                )

                if str(
                    left_member.get("id")
                ) == bot_id:

                    print(
                        "🔴 BOT LEFT:",
                        chat_id
                    )

                    deactivate_chat(
                        chat_id
                    )

                    return

        # -----------------------------------------------
        # process post
        # -----------------------------------------------

        process_channel_message(
            message
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

    load_owner()

    bot = get_me()

    print(
        "========================================"
    )

    print(
        "🤖 BALE REPOST MANAGER"
    )

    print(
        "BOT:",
        bot
    )

    print(
        "OWNER:",
        OWNER_ID
    )

    print(
        "========================================"
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
                        "UPDATE ERROR:",
                        repr(e)
                    )

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "MAIN ERROR:",
                repr(e)
            )

            time.sleep(5)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
