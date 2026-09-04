import os
import time
import re
import hashlib
import requests

from datetime import datetime, timezone, timedelta
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

OWNER_ID = None


# =========================================================
# BALE API
# =========================================================

def bale(method, data=None):

    try:

        url = f"{BALE_API}/{method}"

        response = requests.post(
            url,
            json=data or {},
            timeout=30
        )

        result = response.json()

        print("\n========== BALE API ==========")
        print("METHOD:", method)
        print("RESULT:", result)
        print("==============================\n")

        return result

    except Exception as e:

        print(
            "BALE ERROR:",
            method,
            e
        )

        return {
            "ok": False,
            "error": str(e)
        }


def send_message(chat_id, text):

    return bale(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


# =========================================================
# DATE
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

    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
    )

    for i in range(gm2):
        g_day_no += g_days_in_month[i]

    if gm2 > 1 and (
        gy % 4 == 0
        and (gy % 100 != 0 or gy % 400 == 0)
    ):
        g_day_no += 1

    g_day_no += gd2

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


def to_shamsi(value):

    if not value:
        return ""

    try:

        if isinstance(value, str):

            value = value.replace(
                "Z",
                "+00:00"
            )

            dt = datetime.fromisoformat(
                value
            )

        else:

            dt = value

        if dt.tzinfo:

            dt = dt.astimezone(
                timezone.utc
            )

        iran_time = (
            dt + timedelta(
                hours=3,
                minutes=30
            )
        )

        jy, jm, jd = gregorian_to_jalali(
            iran_time.year,
            iran_time.month,
            iran_time.day
        )

        return (
            f"{jy:04d}/{jm:02d}/{jd:02d} "
            f"{iran_time.hour:02d}:"
            f"{iran_time.minute:02d}"
        )

    except Exception as e:

        print(
            "DATE ERROR:",
            e
        )

        return str(value)


def now_shamsi():

    return to_shamsi(
        datetime.now(timezone.utc)
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
            .eq(
                "key",
                key
            )
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
            e
        )

    return None


def save_setting(key, value):

    try:

        (
            supabase
            .table("bot_settings")
            .upsert(
                {
                    "key": key,
                    "value": str(value)
                }
            )
            .execute()
        )

        return True

    except Exception as e:

        print(
            "SAVE SETTING ERROR:",
            e
        )

        return False


# =========================================================
# OWNER
# =========================================================

def load_owner():

    global OWNER_ID

    value = get_setting(
        "owner_id"
    )

    if value:

        try:

            OWNER_ID = int(
                value
            )

        except Exception:

            OWNER_ID = None

    print(
        "OWNER:",
        OWNER_ID
    )


# =========================================================
# ADMIN SYSTEM
# =========================================================

def is_owner(user_id):

    if OWNER_ID is None:
        return False

    return str(user_id) == str(
        OWNER_ID
    )


def is_admin(user_id):

    if not user_id:
        return False

    # مالک همیشه ادمین است
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
            e
        )

        return False


def deny_access(chat_id):

    send_message(
        chat_id,
        "⛔ شما مجاز به استفاده از این ربات نیستید."
    )


def add_admin(
    user_id,
    username=None,
    first_name=None
):

    if not user_id:
        return False, "شناسه کاربر نامعتبر است."

    try:

        data = {
            "user_id": str(user_id),
            "username": username,
            "first_name": first_name,
            "active": True
        }

        (
            supabase
            .table("bot_admins")
            .upsert(
                data,
                on_conflict="user_id"
            )
            .execute()
        )

        return (
            True,
            "ادمین با موفقیت اضافه شد."
        )

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            e
        )

        return (
            False,
            f"❌ خطا:\n{e}"
        )


def remove_admin(
    user_id
):

    if is_owner(
        user_id
    ):

        return (
            False,
            "❌ مالک اصلی را نمی‌توان حذف کرد."
        )

    try:

        (
            supabase
            .table("bot_admins")
            .update(
                {
                    "active": False
                }
            )
            .eq(
                "user_id",
                str(user_id)
            )
            .execute()
        )

        return (
            True,
            "ادمین حذف شد."
        )

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            e
        )

        return (
            False,
            f"❌ خطا:\n{e}"
        )


def get_admins():

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
                "created_at",
                desc=False
            )
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET ADMINS ERROR:",
            e
        )

        return []


def find_user(
    username
):

    username = clean_username(
        username
    )

    if not username:
        return None

    try:

        result = bale(
            "getChat",
            {
                "chat_id": "@" + username
            }
        )

        if result.get("ok"):

            chat = result.get(
                "result"
            )

            if chat:

                return chat

    except Exception as e:

        print(
            "FIND USER ERROR:",
            e
        )

    return None


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

    admins = get_admins()

    text = (
        "👮 فهرست ادمین‌ها\n\n"
    )

    if OWNER_ID:

        text += (
            "👑 مالک اصلی\n"
            f"🆔 {OWNER_ID}\n\n"
        )

    if not admins:

        text += (
            "ادمین دیگری ثبت نشده است."
        )

        send_message(
            chat_id,
            text
        )

        return

    for index, admin in enumerate(
        admins,
        start=1
    ):

        username = clean_username(
            admin.get(
                "username"
            )
        )

        first_name = (
            admin.get(
                "first_name"
            )
            or "بدون نام"
        )

        text += (
            f"{index}️⃣ {first_name}\n"
            f"   🆔 {admin.get('user_id')}\n"
        )

        if username:

            text += (
                f"   🔹 @{username}\n"
            )

        text += "\n"

    send_message(
        chat_id,
        text
    )


# =========================================================
# USERNAME
# =========================================================

def clean_username(username):

    if not username:
        return None

    username = str(
        username
    ).strip()

    username = username.replace(
        "https://ble.ir/",
        ""
    )

    username = username.replace(
        "http://ble.ir/",
        ""
    )

    username = username.replace(
        "https://www.ble.ir/",
        ""
    )

    username = username.replace(
        "http://www.ble.ir/",
        ""
    )

    username = username.strip(
        "/"
    )

    if username.startswith("@"):

        username = username[1:]

    if "/" in username:

        username = username.split(
            "/"
        )[0]

    return username or None


# =========================================================
# CHANNEL ID
# =========================================================

def channel_db_id(username):

    return hashlib.sha256(
        username.lower().encode(
            "utf-8"
        )
    ).hexdigest()[:32]


# =========================================================
# CHANNELS
# =========================================================

def get_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "active",
                True
            )
            .limit(100)
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET CHANNELS ERROR:",
            e
        )

        return []


def get_channel_by_username(
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
            .table("channels")
            .select("*")
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
            "CHANNEL USERNAME ERROR:",
            e
        )

    return None


def get_channel_by_chat_id(
    chat_id
):

    if not chat_id:
        return None

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq(
                "chat_id",
                str(chat_id)
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
            "CHANNEL CHAT ID ERROR:",
            e
        )

    return None


def get_chat(identifier):

    if not identifier:
        return None

    try:

        result = bale(
            "getChat",
            {
                "chat_id": identifier
            }
        )

        if result.get("ok"):

            return result.get(
                "result"
            )

    except Exception as e:

        print(
            "GET CHAT ERROR:",
            e
        )

    return None


# =========================================================
# ADD CHANNEL
# =========================================================

def add_channel(
    username
):

    username = clean_username(
        username
    )

    if not username:

        return (
            False,
            "نام کانال معتبر نیست."
        )

    try:

        existing = (
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

        chat = get_chat(
            "@" + username
        )

        if not chat:

            return (
                False,
                "❌ کانال پیدا نشد یا ربات به آن دسترسی ندارد."
            )

        chat_id = chat.get(
            "id"
        )

        title = (
            chat.get(
                "title"
            )
            or username
        )

        if existing.data:

            update_data = {
                "active": True,
                "title": title
            }

            if chat_id:

                update_data["chat_id"] = str(
                    chat_id
                )

            (
                supabase
                .table("channels")
                .update(update_data)
                .eq(
                    "username",
                    username
                )
                .execute()
            )

            return (
                True,
                f"کانال «{title}» فعال شد."
            )

        active = (
            supabase
            .table("channels")
            .select("id")
            .eq(
                "active",
                True
            )
            .execute()
        )

        if len(
            active.data or []
        ) >= 100:

            return (
                False,
                "❌ حداکثر ۱۰۰ کانال قابل مانیتور است."
            )

        data = {
            "id": channel_db_id(
                username
            ),
            "username": username,
            "title": title,
            "active": True
        }

        if chat_id:

            data["chat_id"] = str(
                chat_id
            )

        (
            supabase
            .table("channels")
            .insert(data)
            .execute()
        )

        return (
            True,
            f"کانال «{title}» اضافه شد."
        )

    except Exception as e:

        print(
            "ADD CHANNEL ERROR:",
            e
        )

        return (
            False,
            f"❌ خطا:\n{e}"
        )


def remove_channel(
    username
):

    username = clean_username(
        username
    )

    try:

        (
            supabase
            .table("channels")
            .update(
                {
                    "active": False
                }
            )
            .eq(
                "username",
                username
            )
            .execute()
        )

        return True

    except Exception as e:

        print(
            "REMOVE CHANNEL ERROR:",
            e
        )

        return False


# =========================================================
# SOURCE
# =========================================================

def get_source():

    username = get_setting(
        "source_username"
    )

    channel_id = get_setting(
        "source_channel_id"
    )

    title = get_setting(
        "source_title"
    )

    if not username and not channel_id:

        return None

    return {
        "username": username,
        "channel_id": channel_id,
        "title": title
    }


def save_source(
    chat
):

    if not chat:
        return False

    chat_id = chat.get(
        "id"
    )

    username = clean_username(
        chat.get(
            "username"
        )
    )

    title = (
        chat.get(
            "title"
        )
        or username
        or "کانال مرجع"
    )

    if chat_id:

        save_setting(
            "source_channel_id",
            chat_id
        )

    if username:

        save_setting(
            "source_username",
            username
        )

    save_setting(
        "source_title",
        title
    )

    return True


# =========================================================
# LINK
# =========================================================

def normalize_ble_link(
    link
):

    if not link:
        return None

    try:

        link = str(
            link
        ).strip()

        link = link.rstrip(
            ".,،)]}>\"'"
        )

        match = re.search(
            r"https?://(?:www\.)?ble\.ir/[A-Za-z0-9_]+/\d+",
            link
        )

        if match:

            return match.group(0)

        match = re.search(
            r"https?://(?:www\.)?ble\.ir/c/\d+/\d+",
            link
        )

        if match:

            return match.group(0)

    except Exception:
        pass

    return None


def extract_message_link(
    message
):

    if not message:
        return None

    fields = [
        "link",
        "url",
        "message_link",
        "share_link",
        "permalink"
    ]

    for field in fields:

        value = message.get(
            field
        )

        if isinstance(
            value,
            str
        ):

            link = normalize_ble_link(
                value
            )

            if link:

                return link

    return None


def make_source_link(
    source,
    source_message_id
):

    if not source:
        return None

    username = clean_username(
        source.get(
            "username"
        )
    )

    if not username:
        return None

    if not source_message_id:
        return None

    return (
        f"https://ble.ir/"
        f"{username}/"
        f"{source_message_id}"
    )


# =========================================================
# FORWARD
# =========================================================

def extract_forward(
    message
):

    forward_chat_id = None
    forward_username = None
    forward_message_id = None

    forward_from_chat = message.get(
        "forward_from_chat"
    )

    if forward_from_chat:

        forward_chat_id = (
            forward_from_chat.get(
                "id"
            )
        )

        forward_username = (
            forward_from_chat.get(
                "username"
            )
        )

        forward_message_id = (
            message.get(
                "forward_from_message_id"
            )
        )

    forward_origin = message.get(
        "forward_origin"
    )

    if forward_origin:

        if forward_origin.get(
            "type"
        ) == "channel":

            forward_chat = (
                forward_origin.get(
                    "chat",
                    {}
                )
            )

            if forward_chat:

                forward_chat_id = (
                    forward_chat.get(
                        "id",
                        forward_chat_id
                    )
                )

                forward_username = (
                    forward_chat.get(
                        "username",
                        forward_username
                    )
                )

            forward_message_id = (
                forward_origin.get(
                    "message_id",
                    forward_message_id
                )
            )

    return {
        "chat_id": forward_chat_id,
        "username": clean_username(
            forward_username
        ) if forward_username else None,
        "message_id": forward_message_id
    }


def is_from_source(
    forward
):

    source = get_source()

    if not source:
        return False

    source_id = source.get(
        "channel_id"
    )

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    if (
        source_id
        and forward.get("chat_id")
        and str(source_id)
        == str(forward.get("chat_id"))
    ):

        return True

    if (
        source_username
        and forward.get("username")
        and source_username.lower()
        == forward.get("username").lower()
    ):

        return True

    return False


# =========================================================
# MESSAGE TITLE
# =========================================================

def get_message_title(
    message
):

    if not message:
        return "بدون عنوان"

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

    if len(title) > 120:

        title = (
            title[:117]
            + "..."
        )

    return title


# =========================================================
# DESTINATION RESOLVER
# =========================================================

def complete_destination(
    channel,
    chat
):

    channel = channel or {}
    chat = chat or {}

    chat_id = (
        chat.get("id")
        or channel.get("chat_id")
    )

    username = (
        clean_username(
            chat.get("username")
        )
        or clean_username(
            channel.get("username")
        )
    )

    title = (
        chat.get("title")
        or chat.get("first_name")
        or channel.get("title")
        or username
        or "کانال مقصد"
    )

    # ذخیره اطلاعات جدید
    if channel.get("username"):

        try:

            update_data = {
                "title": title,
                "active": True
            }

            if chat_id:

                update_data["chat_id"] = str(
                    chat_id
                )

            if username:

                update_data["username"] = username

            (
                supabase
                .table("channels")
                .update(update_data)
                .eq(
                    "username",
                    channel.get(
                        "username"
                    )
                )
                .execute()
            )

        except Exception as e:

            print(
                "CHANNEL UPDATE ERROR:",
                e
            )

    return {
        "chat_id": chat_id,
        "username": username,
        "title": title
    }


def resolve_destination_channel(
    chat
):

    if not chat:
        return None

    print(
        "\n========== DESTINATION =========="
    )

    print(
        "RAW CHAT:",
        chat
    )

    chat_id = chat.get(
        "id"
    )

    username = clean_username(
        chat.get(
            "username"
        )
    )

    # 1
    if chat_id:

        channel = get_channel_by_chat_id(
            chat_id
        )

        if channel:

            return complete_destination(
                channel,
                chat
            )

    # 2
    if username:

        channel = get_channel_by_username(
            username
        )

        if channel:

            return complete_destination(
                channel,
                chat
            )

    # 3
    for channel in get_channels():

        saved_id = channel.get(
            "chat_id"
        )

        saved_username = clean_username(
            channel.get(
                "username"
            )
        )

        if (
            chat_id
            and saved_id
            and str(chat_id)
            == str(saved_id)
        ):

            return complete_destination(
                channel,
                chat
            )

        if (
            username
            and saved_username
            and username.lower()
            == saved_username.lower()
        ):

            return complete_destination(
                channel,
                chat
            )

    # 4
    if chat_id:

        fresh_chat = get_chat(
            chat_id
        )

        if fresh_chat:

            fresh_username = clean_username(
                fresh_chat.get(
                    "username"
                )
            )

            if fresh_username:

                channel = get_channel_by_username(
                    fresh_username
                )

                if channel:

                    return complete_destination(
                        channel,
                        fresh_chat
                    )

            channel = get_channel_by_chat_id(
                chat_id
            )

            if channel:

                return complete_destination(
                    channel,
                    fresh_chat
                )

    print(
        "❌ DESTINATION NOT FOUND"
    )

    return None


# =========================================================
# SAVE REPOST
# =========================================================

def save_repost(
    source,
    source_message_id,
    destination,
    destination_message_id,
    message_title
):

    if not source_message_id:
        return False

    if not destination:
        return False

    destination_username = clean_username(
        destination.get(
            "username"
        )
    )

    destination_chat_id = (
        destination.get(
            "chat_id"
        )
    )

    destination_title = (
        destination.get(
            "title"
        )
        or destination_username
        or "کانال مقصد"
    )

    try:

        query = (
            supabase
            .table("reposts")
            .select("id")
            .eq(
                "source_message_id",
                source_message_id
            )
            .eq(
                "source_username",
                clean_username(
                    source.get(
                        "username"
                    )
                )
            )
        )

        if destination_username:

            query = query.eq(
                "destination_username",
                destination_username
            )

        if destination_message_id:

            query = query.eq(
                "destination_message_id",
                destination_message_id
            )

        duplicate = (
            query
            .limit(1)
            .execute()
        )

        if duplicate.data:

            print(
                "DUPLICATE REPOST"
            )

            return False

        data = {
            "source_channel_id":
                source.get(
                    "channel_id"
                ),

            "source_username":
                clean_username(
                    source.get(
                        "username"
                    )
                ),

            "source_message_id":
                source_message_id,

            "destination_channel_id":
                destination_chat_id,

            "destination_username":
                destination_username,

            "destination_message_id":
                destination_message_id,

            "destination_title":
                destination_title,

            "message_title":
                message_title,

            "created_at":
                datetime.now(
                    timezone.utc
                ).isoformat()
        }

        supabase.table(
            "reposts"
        ).insert(
            data
        ).execute()

        print(
            "REPOST SAVED:",
            data
        )

        return True

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            e
        )

        return False


# =========================================================
# ALERT
# =========================================================

def send_repost_alert(
    source,
    destination,
    message_title,
    source_message_id
):

    if OWNER_ID is None:
        return

    destination_title = (
        destination.get(
            "title"
        )
        or "کانال مقصد"
    )

    destination_username = clean_username(
        destination.get(
            "username"
        )
    )

    source_link = make_source_link(
        source,
        source_message_id
    )

    text = (
        "🔔 بازنشر جدید شناسایی شد\n\n"

        "📢 کانال مقصد:\n"
        f"{destination_title}\n"
    )

    if destination_username:

        text += (
            f"🔹 @{destination_username}\n"
        )

    text += (
        "\n"
        "📝 عنوان پیام:\n"
        f"{message_title}\n\n"

        "🕒 زمان:\n"
        f"{now_shamsi()}\n\n"

        "🔗 پست مرجع:\n"
        f"{source_link or 'لینک در دسترس نیست'}"
    )

    send_message(
        OWNER_ID,
        text
    )


# =========================================================
# CHANNEL MESSAGE
# =========================================================

def process_channel_message(
    message
):

    print(
        "\n################################################"
    )

    print(
        "RAW CHANNEL MESSAGE"
    )

    print(
        message
    )

    print(
        "################################################"
    )

    chat = message.get(
        "chat",
        {}
    )

    if not chat:
        return

    destination = resolve_destination_channel(
        chat
    )

    if not destination:
        return

    forward = extract_forward(
        message
    )

    if not forward.get(
        "message_id"
    ):
        return

    if not is_from_source(
        forward
    ):
        return

    source = get_source()

    if not source:
        return

    source_message_id = forward.get(
        "message_id"
    )

    destination_message_id = message.get(
        "message_id"
    )

    message_title = get_message_title(
        message
    )

    saved = save_repost(
        source,
        source_message_id,
        destination,
        destination_message_id,
        message_title
    )

    if saved:

        send_repost_alert(
            source,
            destination,
            message_title,
            source_message_id
        )


# =========================================================
# PRIVATE FORWARD
# =========================================================

def process_private_forward(
    message
):

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    # امنیت
    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    forward = extract_forward(
        message
    )

    if not forward.get(
        "message_id"
    ):

        send_message(
            chat_id,
            "⚠️ این پیام، پست فورواردشده قابل شناسایی نیست."
        )

        return

    if not is_from_source(
        forward
    ):

        send_message(
            chat_id,
            "⚠️ این پست متعلق به کانال مرجع نیست."
        )

        return

    source = get_source()

    if not source:

        send_message(
            chat_id,
            "❌ ابتدا کانال مرجع را با /source تعیین کنید."
        )

        return

    source_message_id = forward.get(
        "message_id"
    )

    source_title = get_message_title(
        message
    )

    real_link = extract_message_link(
        message
    )

    source_link = (
        real_link
        or make_source_link(
            source,
            source_message_id
        )
    )

    save_setting(
        "selected_report_source_message_id",
        source_message_id
    )

    save_setting(
        "selected_report_source_username",
        clean_username(
            source.get(
                "username"
            )
        )
    )

    save_setting(
        "selected_report_source_title",
        source_title
    )

    if source_link:

        save_setting(
            "selected_report_source_link",
            source_link
        )

    send_message(
        chat_id,
        "✅ پست مرجع انتخاب شد.\n\n"
        f"📝 عنوان:\n{source_title}\n\n"
        "🔗 پیوند پیام:\n"
        f"{source_link or 'لینک در دسترس نیست'}\n\n"
        "📊 حالا /report را بزنید."
    )


# =========================================================
# REPORT
# =========================================================

def report(
    chat_id
):

    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    source = get_source()

    if not source:

        send_message(
            chat_id,
            "❌ ابتدا کانال مرجع را تعیین کنید."
        )

        return

    selected_id = get_setting(
        "selected_report_source_message_id"
    )

    if not selected_id:

        send_message(
            chat_id,
            "⚠️ ابتدا پست مرجع را فوروارد کنید."
        )

        return

    try:

        selected_id = int(
            selected_id
        )

    except Exception:

        send_message(
            chat_id,
            "❌ شناسه پست نامعتبر است."
        )

        return

    selected_title = get_setting(
        "selected_report_source_title"
    )

    selected_link = get_setting(
        "selected_report_source_link"
    )

    selected_username = clean_username(
        get_setting(
            "selected_report_source_username"
        )
        or source.get(
            "username"
        )
    )

    if not selected_link:

        selected_link = make_source_link(
            source,
            selected_id
        )

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_message_id",
                selected_id
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(500)
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        send_message(
            chat_id,
            f"❌ خطا در گزارش:\n{e}"
        )

        return

    source_id = source.get(
        "channel_id"
    )

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    filtered = []

    for row in rows:

        same = False

        if (
            source_id
            and row.get(
                "source_channel_id"
            )
            and str(
                source_id
            )
            == str(
                row.get(
                    "source_channel_id"
                )
            )
        ):

            same = True

        if (
            source_username
            and clean_username(
                row.get(
                    "source_username"
                )
            )
            and source_username.lower()
            == clean_username(
                row.get(
                    "source_username"
                )
            ).lower()
        ):

            same = True

        if same:

            filtered.append(
                row
            )

    # -----------------------------------------------------
    # حذف مقصدهای تکراری
    # -----------------------------------------------------

    unique = {}

    for row in filtered:

        key = (
            clean_username(
                row.get(
                    "destination_username"
                )
            )
            or str(
                row.get(
                    "destination_channel_id"
                )
            )
        )

        if key not in unique:

            unique[key] = row

    rows = list(
        unique.values()
    )

    # -----------------------------------------------------
    # HEADER
    # -----------------------------------------------------

    source_title = (
        source.get(
            "title"
        )
        or "کانال مرجع"
    )

    text = (
        "📊 گزارش بازنشر پست انتخاب‌شده\n\n"

        "━━━━━━━━━━━━━━\n\n"

        "🎯 پست مرجع\n\n"

        f"📢 کانال مرجع:\n"
        f"{source_title}\n"
    )

    if selected_username:

        text += (
            f"🔹 @{selected_username}\n"
        )

    text += (
        "\n"
        f"📝 عنوان:\n"
        f"{selected_title or 'بدون عنوان'}\n\n"

        "🔗 پیوند پیام:\n"
        f"{selected_link or 'لینک در دسترس نیست'}\n\n"

        "━━━━━━━━━━━━━━\n\n"
    )

    if not rows:

        text += (
            "❌ برای این پست بازنشری ثبت نشده است."
        )

        send_message(
            chat_id,
            text
        )

        return

    text += (
        f"📢 تعداد کانال‌های بازنشرکننده: "
        f"{len(rows)}\n\n"
    )

    # -----------------------------------------------------
    # DESTINATIONS
    # -----------------------------------------------------

    for index, row in enumerate(
        rows,
        start=1
    ):

        destination_title = (
            row.get(
                "destination_title"
            )
        )

        destination_username = clean_username(
            row.get(
                "destination_username"
            )
        )

        # اگر عنوان داخل repost نبود
        # از channels بگیر
        if not destination_title:

            channel = None

            if destination_username:

                channel = get_channel_by_username(
                    destination_username
                )

            if not channel:

                channel = get_channel_by_chat_id(
                    row.get(
                        "destination_channel_id"
                    )
                )

            if channel:

                destination_title = (
                    channel.get(
                        "title"
                    )
                    or destination_username
                )

            else:

                destination_title = (
                    destination_username
                    or "کانال مقصد نامشخص"
                )

        message_title = (
            row.get(
                "message_title"
            )
            or "بدون عنوان"
        )

        created_at = row.get(
            "created_at"
        )

        text += (
            f"{index}️⃣ "
            f"{destination_title}\n"
        )

        if destination_username:

            text += (
                f"   🔹 @{destination_username}\n"
            )

        text += (
            f"   📝 {message_title}\n"
            f"   🕒 {to_shamsi(created_at)}\n\n"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# LIST CHANNELS
# =========================================================

def list_channels(
    chat_id
):

    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    channels = get_channels()

    if not channels:

        send_message(
            chat_id,
            "📭 هیچ کانال فعالی وجود ندارد."
        )

        return

    text = (
        "📡 کانال‌های تحت مانیتور:\n\n"
    )

    for index, channel in enumerate(
        channels,
        start=1
    ):

        title = (
            channel.get(
                "title"
            )
            or "بدون عنوان"
        )

        username = clean_username(
            channel.get(
                "username"
            )
        )

        text += (
            f"{index}️⃣ {title}\n"
        )

        if username:

            text += (
                f"   🔹 @{username}\n"
            )

        text += "\n"

    send_message(
        chat_id,
        text
    )


# =========================================================
# STATUS
# =========================================================

def status(
    chat_id
):

    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    source = get_source()

    channels = get_channels()

    selected_id = get_setting(
        "selected_report_source_message_id"
    )

    text = (
        "📊 وضعیت ربات\n\n"
    )

    if source:

        text += (
            "🎯 کانال مرجع:\n"
            f"{source.get('title') or 'بدون عنوان'}\n"
        )

        username = clean_username(
            source.get(
                "username"
            )
        )

        if username:

            text += (
                f"🔹 @{username}\n"
            )

        text += "\n"

    else:

        text += (
            "🎯 کانال مرجع:\n"
            "❌ تعیین نشده\n\n"
        )

    text += (
        "📡 کانال‌های مانیتورشده:\n"
        f"{len(channels)} کانال\n\n"
    )

    if selected_id:

        text += (
            "📌 پست انتخاب‌شده:\n"
            f"{get_setting('selected_report_source_title') or 'بدون عنوان'}\n"
            f"🆔 {selected_id}\n"
        )

    else:

        text += (
            "📌 پست انتخاب‌شده:\n"
            "❌ وجود ندارد\n"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# START
# =========================================================

def start_message(
    chat_id
):

    # مهم‌ترین قسمت امنیتی
    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    text = (
        "🤖 ربات پایش بازنشر\n\n"

        "🎯 دستورات اصلی:\n\n"

        "/source @channel\n"
        "تعیین کانال مرجع\n\n"

        "/addchannel @channel\n"
        "افزودن کانال برای مانیتور\n\n"

        "/removechannel @channel\n"
        "حذف کانال از مانیتور\n\n"

        "/listchannels\n"
        "نمایش کانال‌های مانیتورشده\n\n"

        "/report\n"
        "گزارش بازنشر پست انتخاب‌شده\n\n"

        "/status\n"
        "نمایش وضعیت ربات\n\n"
    )

    # فقط مالک
    if is_owner(
        chat_id
    ):

        text += (
            "━━━━━━━━━━━━━━\n\n"

            "👑 مدیریت ادمین‌ها:\n\n"

            "/addadmin @username\n"
            "افزودن ادمین\n\n"

            "/removeadmin @username\n"
            "حذف ادمین\n\n"

            "/listadmins\n"
            "نمایش ادمین‌ها\n"
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
    user=None
):

    text = text.strip()

    # -----------------------------------------------------
    # هر دستور قبل از اجرا
    # -----------------------------------------------------

    if not is_admin(
        chat_id
    ):

        deny_access(
            chat_id
        )

        return

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    if text.startswith(
        "/start"
    ):

        start_message(
            chat_id
        )

        return

    # -----------------------------------------------------
    # ADD ADMIN
    # -----------------------------------------------------

    if text.startswith(
        "/addadmin"
    ):

        if not is_owner(
            chat_id
        ):

            deny_access(
                chat_id
            )

            return

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/addadmin @username"
            )

            return

        username = clean_username(
            parts[1]
        )

        user_chat = find_user(
            username
        )

        if not user_chat:

            send_message(
                chat_id,
                "❌ کاربر پیدا نشد.\n\n"
                "کاربر باید حداقل یک‌بار ربات را Start کرده باشد."
            )

            return

        target_id = user_chat.get(
            "id"
        )

        if is_owner(
            target_id
        ):

            send_message(
                chat_id,
                "⚠️ این کاربر مالک اصلی است."
            )

            return

        ok, msg = add_admin(
            target_id,
            username=user_chat.get(
                "username"
            ),
            first_name=user_chat.get(
                "first_name"
            )
        )

        send_message(
            chat_id,
            (
                "✅ "
                if ok
                else ""
            )
            + msg
        )

        return

    # -----------------------------------------------------
    # REMOVE ADMIN
    # -----------------------------------------------------

    if text.startswith(
        "/removeadmin"
    ):

        if not is_owner(
            chat_id
        ):

            deny_access(
                chat_id
            )

            return

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/removeadmin @username"
            )

            return

        username = clean_username(
            parts[1]
        )

        user_chat = find_user(
            username
        )

        if not user_chat:

            send_message(
                chat_id,
                "❌ کاربر پیدا نشد."
            )

            return

        target_id = user_chat.get(
            "id"
        )

        ok, msg = remove_admin(
            target_id
        )

        send_message(
            chat_id,
            (
                "✅ "
                if ok
                else ""
            )
            + msg
        )

        return

    # -----------------------------------------------------
    # LIST ADMINS
    # -----------------------------------------------------

    if text.startswith(
        "/listadmins"
    ):

        list_admins(
            chat_id
        )

        return

    # -----------------------------------------------------
    # SOURCE
    # -----------------------------------------------------

    if text.startswith(
        "/source"
    ):

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/source @channel"
            )

            return

        username = clean_username(
            parts[1]
        )

        chat = get_chat(
            "@" + username
        )

        if not chat:

            send_message(
                chat_id,
                "❌ کانال پیدا نشد."
            )

            return

        save_source(
            chat
        )

        title = (
            chat.get(
                "title"
            )
            or username
        )

        send_message(
            chat_id,
            "✅ کانال مرجع تعیین شد.\n\n"
            f"🎯 {title}\n"
            f"🔹 @{username}"
        )

        return

    # -----------------------------------------------------
    # ADD CHANNEL
    # -----------------------------------------------------

    if text.startswith(
        "/addchannel"
    ):

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/addchannel @channel"
            )

            return

        ok, msg = add_channel(
            parts[1]
        )

        send_message(
            chat_id,
            (
                "✅ "
                if ok
                else ""
            )
            + msg
        )

        return

    # -----------------------------------------------------
    # REMOVE CHANNEL
    # -----------------------------------------------------

    if text.startswith(
        "/removechannel"
    ):

        parts = text.split()

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/removechannel @channel"
            )

            return

        ok = remove_channel(
            parts[1]
        )

        send_message(
            chat_id,
            (
                "✅ کانال حذف شد."
                if ok
                else "❌ خطا در حذف کانال."
            )
        )

        return

    # -----------------------------------------------------
    # LIST CHANNELS
    # -----------------------------------------------------

    if text.startswith(
        "/listchannels"
    ):

        list_channels(
            chat_id
        )

        return

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    if text.startswith(
        "/report"
    ):

        report(
            chat_id
        )

        return

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if text.startswith(
        "/status"
    ):

        status(
            chat_id
        )

        return


# =========================================================
# UPDATE
# =========================================================

def process_update(
    update
):

    if not update:
        return

    message = update.get(
        "message"
    )

    if not message:
        return

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    if chat_id is None:
        return

    chat_type = chat.get(
        "type"
    )

    print(
        "\n========================================"
    )

    print(
        "UPDATE"
    )

    print(
        "CHAT TYPE:",
        chat_type
    )

    print(
        "CHAT ID:",
        chat_id
    )

    print(
        "========================================"
    )

    # -----------------------------------------------------
    # PRIVATE
    # -----------------------------------------------------

    if chat_type == "private":

        # فقط ادمین
        if not is_admin(
            chat_id
        ):

            # حتی فوروارد هم پردازش نشود
            send_message(
                chat_id,
                "⛔ شما مجاز به استفاده از این ربات نیستید."
            )

            return

        forward = extract_forward(
            message
        )

        if forward.get(
            "message_id"
        ):

            process_private_forward(
                message
            )

            return

        text = message.get(
            "text"
        )

        if text:

            process_command(
                chat_id,
                text,
                chat.get(
                    "username"
                )
            )

        return

    # -----------------------------------------------------
    # CHANNEL
    # -----------------------------------------------------

    if chat_type == "channel":

        process_channel_message(
            message
        )

        return


# =========================================================
# UPDATES
# =========================================================

def get_updates(
    offset=None
):

    data = {
        "timeout": 50
    }

    if offset is not None:

        data["offset"] = offset

    return bale(
        "getUpdates",
        data
    )


# =========================================================
# MAIN
# =========================================================

def main():

    global OWNER_ID

    load_owner()

    print(
        "\n"
        "=========================================="
    )

    print(
        "       BALE REPOST MONITOR BOT"
    )

    print(
        "=========================================="
    )

    print(
        "OWNER:",
        OWNER_ID
    )

    print(
        "==========================================\n"
    )

    # -----------------------------------------------------
    # هشدار امنیتی
    # -----------------------------------------------------

    if OWNER_ID is None:

        print(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            "WARNING:"
        )

        print(
            "owner_id is NOT configured."
        )

        print(
            "Set owner_id manually in bot_settings."
        )

        print(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

    offset = None

    while True:

        try:

            result = get_updates(
                offset
            )

            if not result.get(
                "ok"
            ):

                print(
                    "GET UPDATES FAILED:",
                    result
                )

                time.sleep(5)

                continue

            updates = result.get(
                "result",
                []
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
                        "UPDATE ERROR:",
                        e
                    )

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                e
            )

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
