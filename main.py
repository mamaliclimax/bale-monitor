import os
import time
import re
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
        30, 30, 30, 30, 30, 29
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


def set_owner(chat_id):

    global OWNER_ID

    if OWNER_ID is None:

        OWNER_ID = chat_id

        save_setting(
            "owner_id",
            chat_id
        )

        print(
            "NEW OWNER:",
            OWNER_ID
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

    if username.startswith("c/"):

        return None

    if "/" in username:

        username = username.split(
            "/"
        )[0]

    return username or None


# =========================================================
# BLE LINK
# =========================================================

def normalize_ble_link(link):

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

    except Exception as e:

        print(
            "LINK ERROR:",
            e
        )

    return None


def extract_message_link(message):

    if not isinstance(
        message,
        dict
    ):

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

    texts = []

    if message.get("text"):

        texts.append(
            str(
                message.get("text")
            )
        )

    if message.get("caption"):

        texts.append(
            str(
                message.get("caption")
            )
        )

    for text in texts:

        link = normalize_ble_link(
            text
        )

        if link:

            return link

    return None


# =========================================================
# CHAT
# =========================================================

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

            chat = result.get(
                "result"
            )

            print(
                "GET CHAT SUCCESS:",
                chat
            )

            return chat

        print(
            "GET CHAT FAILED:",
            result
        )

    except Exception as e:

        print(
            "GET CHAT ERROR:",
            e
        )

    return None


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


def save_source(chat):

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
        or chat.get(
            "first_name"
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
# CHANNEL ID
# =========================================================

def channel_db_id(username):

    return hashlib_sha256(
        username.lower()
    )[:32]


def hashlib_sha256(text):

    import hashlib

    return hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()


# =========================================================
# ADD CHANNEL
# =========================================================

def add_channel(username):

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

        # -------------------------------------------------
        # کانال قبلاً وجود دارد
        # -------------------------------------------------

        if existing.data:

            chat = get_chat(
                "@" + username
            )

            update_data = {
                "active": True
            }

            if chat:

                if chat.get("id"):

                    update_data["chat_id"] = str(
                        chat.get("id")
                    )

                if chat.get("title"):

                    update_data["title"] = (
                        chat.get("title")
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
                "کانال دوباره فعال شد."
            )

        # -------------------------------------------------
        # محدودیت
        # -------------------------------------------------

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

        # -------------------------------------------------
        # دریافت اطلاعات کانال
        # -------------------------------------------------

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

        # -------------------------------------------------
        # ذخیره
        # -------------------------------------------------

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

        print(
            "CHANNEL SAVED:",
            data
        )

        return (
            True,
            f"کانال «{title}» با موفقیت اضافه شد."
        )

    except Exception as e:

        print(
            "ADD CHANNEL ERROR:",
            e
        )

        return (
            False,
            f"❌ خطا در افزودن کانال:\n{e}"
        )


# =========================================================
# REMOVE CHANNEL
# =========================================================

def remove_channel(username):

    username = clean_username(
        username
    )

    if not username:

        return False

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
            "REMOVE ERROR:",
            e
        )

        return False


# =========================================================
# GET CHANNELS
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


# =========================================================
# FIND CHANNEL BY USERNAME
# =========================================================

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


# =========================================================
# FIND CHANNEL BY CHAT ID
# =========================================================

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


# =========================================================
# FIND DESTINATION CHANNEL
# =========================================================

def resolve_destination_channel(
    chat
):

    if not chat:

        return None

    print(
        "\n========================================"
    )

    print(
        "RESOLVING DESTINATION CHANNEL"
    )

    print(
        "RAW CHAT:"
    )

    print(
        chat
    )

    print(
        "========================================"
    )

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
        or chat.get(
            "first_name"
        )
    )

    print(
        "CHAT ID:",
        chat_id
    )

    print(
        "CHAT USERNAME:",
        username
    )

    print(
        "CHAT TITLE:",
        title
    )

    # -----------------------------------------------------
    # روش اول: chat_id
    # -----------------------------------------------------

    if chat_id:

        channel = get_channel_by_chat_id(
            chat_id
        )

        if channel:

            print(
                "FOUND BY CHAT ID:",
                channel
            )

            return complete_destination(
                channel,
                chat
            )

    # -----------------------------------------------------
    # روش دوم: username
    # -----------------------------------------------------

    if username:

        channel = get_channel_by_username(
            username
        )

        if channel:

            print(
                "FOUND BY USERNAME:",
                channel
            )

            return complete_destination(
                channel,
                chat
            )

    # -----------------------------------------------------
    # روش سوم: مقایسه دستی
    # -----------------------------------------------------

    channels = get_channels()

    for channel in channels:

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
            and str(saved_id)
            == str(chat_id)
        ):

            print(
                "FOUND MANUALLY BY CHAT ID:",
                channel
            )

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

            print(
                "FOUND MANUALLY BY USERNAME:",
                channel
            )

            return complete_destination(
                channel,
                chat
            )

    # -----------------------------------------------------
    # روش چهارم:
    # getChat مستقیم
    # -----------------------------------------------------

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

            fresh_title = (
                fresh_chat.get(
                    "title"
                )
                or fresh_chat.get(
                    "first_name"
                )
            )

            print(
                "FRESH CHAT:",
                fresh_chat
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

            # اگر کانال در DB با username نبود
            # اما chat_id آن برابر بود
            channel = get_channel_by_chat_id(
                chat_id
            )

            if channel:

                return complete_destination(
                    channel,
                    fresh_chat
                )

    # -----------------------------------------------------
    # هیچ تطبیقی پیدا نشد
    # -----------------------------------------------------

    print(
        "\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    )

    print(
        "DESTINATION CHANNEL NOT RESOLVED"
    )

    print(
        "RAW CHAT:",
        chat
    )

    print(
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
    )

    return None


# =========================================================
# COMPLETE DESTINATION
# =========================================================

def complete_destination(
    channel,
    chat
):

    if channel is None:

        channel = {}

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

    # -----------------------------------------------------
    # اگر عنوان پیدا شد، DB را هم به‌روز کن
    # -----------------------------------------------------

    if channel.get("username"):

        update_data = {}

        if chat_id:

            update_data["chat_id"] = str(
                chat_id
            )

        if username:

            update_data["username"] = username

        if title:

            update_data["title"] = title

        if update_data:

            try:

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
                    "UPDATE CHANNEL INFO ERROR:",
                    e
                )

    result = {
        "id": chat_id,
        "chat_id": chat_id,
        "username": username,
        "title": title
    }

    print(
        "\nDESTINATION FINAL:"
    )

    print(
        result
    )

    return result


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(
    message
):

    forward_chat_id = None
    forward_username = None
    forward_message_id = None

    # -----------------------------------------------------
    # قدیمی
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # جدید
    # -----------------------------------------------------

    forward_origin = message.get(
        "forward_origin"
    )

    if forward_origin:

        if (
            forward_origin.get(
                "type"
            )
            == "channel"
        ):

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

    result = {
        "chat_id": forward_chat_id,
        "username": (
            clean_username(
                forward_username
            )
            if forward_username
            else None
        ),
        "message_id": forward_message_id
    }

    print(
        "EXTRACTED FORWARD:",
        result
    )

    return result


# =========================================================
# SOURCE CHECK
# =========================================================

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

    forward_id = forward.get(
        "chat_id"
    )

    forward_username = clean_username(
        forward.get(
            "username"
        )
    )

    if (
        source_id
        and forward_id
        and str(source_id)
        == str(forward_id)
    ):

        return True

    if (
        source_username
        and forward_username
        and source_username.lower()
        == forward_username.lower()
    ):

        return True

    return False


# =========================================================
# SOURCE LINK
# =========================================================

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
# MESSAGE TITLE
# =========================================================

def get_message_title(
    message
):

    if not message:

        return "بدون عنوان"

    text = (
        message.get(
            "text"
        )
        or message.get(
            "caption"
        )
        or ""
    )

    text = str(
        text
    ).strip()

    if not text:

        return "بدون عنوان"

    first_line = (
        text.splitlines()[0]
        .strip()
    )

    if len(first_line) > 120:

        first_line = (
            first_line[:117]
            + "..."
        )

    return first_line


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
        or destination.get(
            "id"
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

        result = (
            supabase
            .table("reposts")
            .insert(data)
            .execute()
        )

        print(
            "========================================"
        )

        print(
            "REPOST SAVED:"
        )

        print(
            data
        )

        print(
            "SUPABASE RESULT:",
            result.data
        )

        print(
            "========================================"
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
# PROCESS CHANNEL MESSAGE
# =========================================================

def process_channel_message(
    message
):

    print(
        "\n\n"
        "################################################"
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

        print(
            "NO DESTINATION CHAT"
        )

        return

    # -----------------------------------------------------
    # مقصد
    # -----------------------------------------------------

    destination = resolve_destination_channel(
        chat
    )

    if not destination:

        print(
            "❌ DESTINATION CHANNEL NOT FOUND"
        )

        return

    # -----------------------------------------------------
    # فوروارد
    # -----------------------------------------------------

    forward = extract_forward(
        message
    )

    if not forward.get(
        "message_id"
    ):

        print(
            "MESSAGE IS NOT A FORWARD"
        )

        return

    # -----------------------------------------------------
    # بررسی مرجع
    # -----------------------------------------------------

    if not is_from_source(
        forward
    ):

        print(
            "FORWARD IS NOT FROM SOURCE"
        )

        return

    source = get_source()

    if not source:

        print(
            "SOURCE NOT CONFIGURED"
        )

        return

    source_message_id = (
        forward.get(
            "message_id"
        )
    )

    destination_message_id = (
        message.get(
            "message_id"
        )
    )

    message_title = get_message_title(
        message
    )

    # -----------------------------------------------------
    # ذخیره
    # -----------------------------------------------------

    saved = save_repost(
        source=source,
        source_message_id=source_message_id,
        destination=destination,
        destination_message_id=destination_message_id,
        message_title=message_title
    )

    if saved:

        send_repost_alert(
            source=source,
            destination=destination,
            message_title=message_title,
            source_message_id=source_message_id
        )

    print(
        "CHANNEL MESSAGE PROCESS FINISHED"
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

    if OWNER_ID is None:

        return

    if str(chat_id) != str(
        OWNER_ID
    ):

        return

    forward = extract_forward(
        message
    )

    if not forward.get(
        "message_id"
    ):

        send_message(
            chat_id,
            "⚠️ پست فورواردشده قابل شناسایی نیست."
        )

        return

    if not is_from_source(
        forward
    ):

        send_message(
            chat_id,
            "⚠️ این پست متعلق به کانال مرجع تعیین‌شده نیست."
        )

        return

    source = get_source()

    if not source:

        send_message(
            chat_id,
            "❌ ابتدا کانال مرجع را با /source تعیین کنید."
        )

        return

    source_message_id = (
        forward.get(
            "message_id"
        )
    )

    # عنوان
    source_title = get_message_title(
        message
    )

    # لینک واقعی
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

    # ذخیره
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

    text = (
        "✅ پست مرجع انتخاب شد.\n\n"

        "🎯 پست مرجع\n\n"

        f"📝 عنوان:\n"
        f"{source_title}\n\n"

        "🔗 پیوند پیام:\n"
        f"{source_link or 'لینک در دسترس نیست'}\n\n"

        "📊 حالا /report را بزنید.\n\n"

        "گزارش فقط مربوط به همین پست خواهد بود."
    )

    send_message(
        chat_id,
        text
    )


# =========================================================
# REPORT
# =========================================================

def report(
    chat_id
):

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
            "⚠️ ابتدا پست مرجع را برای ربات فوروارد کنید."
        )

        return

    try:

        selected_id = int(
            selected_id
        )

    except Exception:

        send_message(
            chat_id,
            "❌ شناسه پست مرجع نامعتبر است."
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

    # -----------------------------------------------------
    # دریافت بازنشرهای همان پست
    # -----------------------------------------------------

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

        print(
            "REPORT ERROR:",
            e
        )

        send_message(
            chat_id,
            f"❌ خطا در گزارش:\n{e}"
        )

        return

    # -----------------------------------------------------
    # فیلتر کانال مرجع
    # -----------------------------------------------------

    source_id = source.get(
        "channel_id"
    )

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    filtered_rows = []

    for row in rows:

        row_source_id = row.get(
            "source_channel_id"
        )

        row_source_username = clean_username(
            row.get(
                "source_username"
            )
        )

        same_source = False

        if (
            source_id
            and row_source_id
            and str(source_id)
            == str(row_source_id)
        ):

            same_source = True

        if (
            source_username
            and row_source_username
            and source_username.lower()
            == row_source_username.lower()
        ):

            same_source = True

        if same_source:

            filtered_rows.append(
                row
            )

    # -----------------------------------------------------
    # حذف تکراری‌ها
    # -----------------------------------------------------

    unique_rows = {}

    for row in filtered_rows:

        username = clean_username(
            row.get(
                "destination_username"
            )
        )

        destination_id = row.get(
            "destination_channel_id"
        )

        title = (
            row.get(
                "destination_title"
            )
            or ""
        )

        key = (
            username
            or str(
                destination_id
            )
            or title
        )

        if key not in unique_rows:

            unique_rows[key] = row

    rows = list(
        unique_rows.values()
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

        "━━━━━━━━━━━━━━\n"

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

    # -----------------------------------------------------
    # بدون بازنشر
    # -----------------------------------------------------

    if not rows:

        text += (
            "❌ برای این پست، "
            "هیچ بازنشر ثبت‌شده‌ای پیدا نشد."
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
    # کانال‌های مقصد
    # -----------------------------------------------------

    for index, row in enumerate(
        rows,
        start=1
    ):

        destination_title = (
            row.get(
                "destination_title"
            )
            or "کانال مقصد نامشخص"
        )

        destination_username = clean_username(
            row.get(
                "destination_username"
            )
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

        shamsi_time = to_shamsi(
            created_at
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
            f"   🕒 {shamsi_time}\n\n"
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

        selected_title = get_setting(
            "selected_report_source_title"
        )

        text += (
            "📌 پست انتخاب‌شده:\n"
            f"📝 {selected_title or 'بدون عنوان'}\n"
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

    text = (
        "🤖 ربات پایش بازنشر\n\n"

        "🎯 دستورات:\n\n"

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

        "━━━━━━━━━━━━━━\n\n"

        "📌 برای گزارش:\n\n"

        "۱️⃣ پست موردنظر را از کانال مرجع "
        "برای ربات فوروارد کنید.\n\n"

        "۲️⃣ ربات عنوان و شناسه همان پست "
        "را ذخیره می‌کند.\n\n"

        "۳️⃣ /report را بزنید.\n\n"

        "۴️⃣ فقط بازنشرهای همان پست "
        "نمایش داده می‌شوند."
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
    text
):

    text = text.strip()

    if text.startswith(
        "/start"
    ):

        start_message(
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

        if not username:

            send_message(
                chat_id,
                "❌ نام کانال معتبر نیست."
            )

            return

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
    # ADD
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
    # REMOVE
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
    # LIST
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
# UPDATE PROCESSOR
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

    # -----------------------------------------------------
    # OWNER
    # -----------------------------------------------------

    set_owner(
        chat_id
    )

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
        "CHAT:",
        chat
    )

    print(
        "MESSAGE ID:",
        message.get(
            "message_id"
        )
    )

    print(
        "========================================\n"
    )

    # -----------------------------------------------------
    # PRIVATE
    # -----------------------------------------------------

    if chat_type == "private":

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
                text
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
# GET UPDATES
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
        "      BALE REPOST MONITOR BOT"
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
