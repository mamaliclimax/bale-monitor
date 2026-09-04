import os
import time
import hashlib
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

        print("BALE:", method, result)

        return result

    except Exception as e:

        print("BALE ERROR:", method, e)

        return {
            "ok": False,
            "error": str(e)
        }


# =========================================================
# SEND MESSAGE
# =========================================================

def send_message(chat_id, text):

    return bale(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


# =========================================================
# PERSIAN DATE / TIME
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

    if (
        gm > 1
        and (gy + 1600) % 4 == 0
        and (
            (gy + 1600) % 100 != 0
            or (gy + 1600) % 400 == 0
        )
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

        j_day_no = (
            j_day_no - 1
        ) % 365

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
        return "نامشخص"

    try:

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

        iran_tz = timezone(
            timedelta(
                hours=3,
                minutes=30
            )
        )

        dt = dt.astimezone(
            iran_tz
        )

        jy, jm, jd = (
            gregorian_to_jalali(
                dt.year,
                dt.month,
                dt.day
            )
        )

        return (
            f"{jy:04d}/{jm:02d}/{jd:02d}"
            f" - "
            f"{dt.hour:02d}:"
            f"{dt.minute:02d}:"
            f"{dt.second:02d}"
        )

    except Exception as e:

        print(
            "SHAMSI DATE ERROR:",
            e
        )

        return str(value)


def now_shamsi():

    iran_tz = timezone(
        timedelta(
            hours=3,
            minutes=30
        )
    )

    now = datetime.now(
        timezone.utc
    ).astimezone(
        iran_tz
    )

    jy, jm, jd = (
        gregorian_to_jalali(
            now.year,
            now.month,
            now.day
        )
    )

    return (
        f"{jy:04d}/{jm:02d}/{jd:02d}"
        f" - "
        f"{now.hour:02d}:"
        f"{now.minute:02d}:"
        f"{now.second:02d}"
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

            return result.data[0]["value"]

    except Exception as e:

        print(
            "GET SETTING ERROR:",
            e
        )

    return None


def save_setting(key, value):

    try:

        supabase.table(
            "bot_settings"
        ).upsert(
            {
                "key": key,
                "value": str(value)
            }
        ).execute()

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

        except:

            OWNER_ID = None

    print(
        "OWNER:",
        OWNER_ID
    )


def ensure_owner(chat_id):

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

    return chat_id == OWNER_ID


# =========================================================
# USERNAME CLEANER
# =========================================================

def clean_username(username):

    if not username:

        return ""

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

    return username.lower()


# =========================================================
# EXTRACT BLE MESSAGE LINK
# =========================================================

def extract_ble_link(text):

    if not text:

        return None

    text = str(text)

    patterns = [

        r'https?://(?:www\.)?ble\.ir/[A-Za-z0-9_]+/\d+',

        r'https?://(?:www\.)?ble\.ir/[A-Za-z0-9_]+/\?[^ \n]+',

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            return match.group(
                0
            ).rstrip(
                ".,،)"
            )

    return None


# =========================================================
# GET CHAT
# =========================================================

def get_chat(identifier):

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

    try:

        channel_id_int = (
            int(channel_id)
            if channel_id
            else None
        )

    except:

        channel_id_int = None

    return {

        "username":
            username,

        "id":
            channel_id_int,

        "title":
            title
    }


def set_source(username):

    username = clean_username(
        username
    )

    if not username:

        return (
            False,
            "نام کانال وارد نشده است."
        )

    chat = get_chat(
        "@" + username
    )

    channel_id = None

    title = username

    real_username = username

    if chat:

        channel_id = chat.get(
            "id"
        )

        title = chat.get(
            "title",
            username
        )

        real_username = chat.get(
            "username",
            username
        )

    save_setting(
        "source_username",
        clean_username(
            real_username
        )
    )

    if channel_id is not None:

        save_setting(
            "source_channel_id",
            channel_id
        )

    save_setting(
        "source_title",
        title
    )

    return True, {

        "username":
            clean_username(
                real_username
            ),

        "id":
            channel_id,

        "title":
            title
    }


# =========================================================
# CHANNEL MANAGEMENT
# =========================================================

def channel_hash(username):

    value = hashlib.sha256(
        username.encode(
            "utf-8"
        )
    ).hexdigest()

    return int(
        value[:15],
        16
    )


def add_channel(username):

    username = clean_username(
        username
    )

    if not username:

        return (
            False,
            "نام کانال وارد نشده است."
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

        if existing.data:

            supabase.table(
                "channels"
            ).update(
                {
                    "active": True
                }
            ).eq(
                "username",
                username
            ).execute()

            return True, (
                "کانال قبلاً وجود داشت "
                "و دوباره فعال شد."
            )

    except Exception as e:

        print(
            "CHECK CHANNEL ERROR:",
            e
        )

    try:

        count_result = (
            supabase
            .table("channels")
            .select("username")
            .eq(
                "active",
                True
            )
            .execute()
        )

        count = len(
            count_result.data or []
        )

        if count >= 100:

            return False, (
                "❌ حداکثر ۱۰۰ کانال "
                "قابل پایش است."
            )

    except Exception as e:

        print(
            "COUNT CHANNEL ERROR:",
            e
        )

    try:

        chat = get_chat(
            "@" + username
        )

        real_id = channel_hash(
            username
        )

        title = username

        if chat:

            title = chat.get(
                "title",
                username
            )

        supabase.table(
            "channels"
        ).insert(
            {
                "id": real_id,
                "username": username,
                "title": title,
                "active": True
            }
        ).execute()

        return True, (
            f"✅ کانال @{username} "
            "با موفقیت اضافه شد."
        )

    except Exception as e:

        print(
            "ADD CHANNEL ERROR:",
            e
        )

        return False, str(e)


def remove_channel(username):

    username = clean_username(
        username
    )

    try:

        supabase.table(
            "channels"
        ).update(
            {
                "active": False
            }
        ).eq(
            "username",
            username
        ).execute()

        return True

    except Exception as e:

        print(
            "REMOVE CHANNEL ERROR:",
            e
        )

        return False


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
            .order(
                "username"
            )
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET CHANNELS ERROR:",
            e
        )

        return []


def get_channel_by_username(username):

    username = clean_username(
        username
    )

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
            "GET CHANNEL ERROR:",
            e
        )

    return None


def is_monitored(username):

    if not username:

        return False

    username = clean_username(
        username
    )

    return bool(
        get_channel_by_username(
            username
        )
    )


# =========================================================
# MESSAGE TITLE
# =========================================================

def get_message_title(message):

    value = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    value = str(
        value
    ).strip()

    if not value:

        return "بدون عنوان"

    value = (
        value
        .split("\n")[0]
        .strip()
    )

    if len(value) > 150:

        value = (
            value[:150]
            + "..."
        )

    return value


# =========================================================
# FORWARD DETECTION
# =========================================================

def extract_forward(message):

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

        if (
            forward_origin.get(
                "type"
            )
            == "channel"
        ):

            chat = forward_origin.get(
                "chat",
                {}
            )

            if chat:

                forward_chat_id = (
                    chat.get(
                        "id",
                        forward_chat_id
                    )
                )

                forward_username = (
                    chat.get(
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

        "chat_id":
            forward_chat_id,

        "username":
            (
                clean_username(
                    forward_username
                )
                if forward_username
                else None
            ),

        "message_id":
            forward_message_id
    }


# =========================================================
# SOURCE MATCH
# =========================================================

def is_from_source(forward):

    source = get_source()

    if not source:

        return False

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    source_id = source.get(
        "id"
    )

    forward_username = clean_username(
        forward.get(
            "username"
        )
    )

    forward_id = forward.get(
        "chat_id"
    )

    if (
        source_id
        and forward_id
    ):

        try:

            if int(source_id) == int(
                forward_id
            ):

                return True

        except:

            pass

    if (
        source_username
        and forward_username
    ):

        if (
            source_username
            == forward_username
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

    if not source_message_id:

        return None

    username = clean_username(
        source.get(
            "username"
        )
    )

    if not username:

        return None

    return (
        f"https://ble.ir/"
        f"{username}/"
        f"{source_message_id}"
    )


# =========================================================
# SAVE REPOST
# =========================================================

def save_repost(
    source,
    forward,
    destination
):

    destination_username = (
        clean_username(
            destination.get(
                "username"
            )
        )
    )

    destination_message_id = (
        destination.get(
            "message_id"
        )
    )

    if not destination_username:

        return False

    if not destination_message_id:

        return False

    data = {

        "source_channel_id":
            source.get(
                "id"
            ),

        "source_username":
            clean_username(
                source.get(
                    "username"
                )
            ),

        "source_message_id":
            forward.get(
                "message_id"
            ),

        "destination_channel_id":
            destination.get(
                "chat_id"
            ),

        "destination_username":
            destination_username,

        "destination_message_id":
            destination_message_id,

        "destination_title":
            destination.get(
                "title",
                destination_username
            ),

        "message_title":
            destination.get(
                "message_title",
                "بدون عنوان"
            )
    }

    try:

        existing = (
            supabase
            .table("reposts")
            .select("id")
            .eq(
                "source_username",
                data[
                    "source_username"
                ]
            )
            .eq(
                "source_message_id",
                data[
                    "source_message_id"
                ]
            )
            .eq(
                "destination_username",
                destination_username
            )
            .eq(
                "destination_message_id",
                destination_message_id
            )
            .limit(1)
            .execute()
        )

        if existing.data:

            return False

        supabase.table(
            "reposts"
        ).insert(
            data
        ).execute()

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
    forward,
    destination
):

    if OWNER_ID is None:

        return

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    destination_username = (
        clean_username(
            destination.get(
                "username"
            )
        )
    )

    destination_title = (
        destination.get(
            "title"
        )
        or destination_username
    )

    message_title = (
        destination.get(
            "message_title"
        )
        or "بدون عنوان"
    )

    source_message_id = (
        forward.get(
            "message_id"
        )
    )

    source_link = make_source_link(
        source,
        source_message_id
    )

    text = (
        "🚨 بازنشر جدید شناسایی شد!\n\n"

        f"📢 کانال مقصد:\n"
        f"{destination_title}\n"

        f"🔹 @{destination_username}\n\n"

        f"📝 عنوان پیام:\n"
        f"{message_title}\n\n"

        f"🕒 زمان شناسایی:\n"
        f"{now_shamsi()}"
    )

    if source_link:

        text += (
            "\n\n"
            f"🔗 پست مرجع:\n"
            f"{source_link}"
        )

    send_message(
        OWNER_ID,
        text
    )


# =========================================================
# PRIVATE REPOST
# =========================================================

def save_private_repost(
    source,
    forward,
    destination
):

    data = {

        "source_channel_id":
            source.get(
                "id"
            ),

        "source_username":
            clean_username(
                source.get(
                    "username"
                )
            ),

        "source_message_id":
            forward.get(
                "message_id"
            ),

        "destination_channel_id":
            destination.get(
                "chat_id"
            ),

        "destination_username":
            clean_username(
                destination.get(
                    "username"
                )
            ),

        "destination_message_id":
            None,

        "destination_title":
            destination.get(
                "title",
                destination.get(
                    "username"
                )
            ),

        "message_title":
            destination.get(
                "message_title",
                "بدون عنوان"
            )
    }

    try:

        existing = (
            supabase
            .table("reposts")
            .select("id")
            .eq(
                "source_username",
                data[
                    "source_username"
                ]
            )
            .eq(
                "source_message_id",
                data[
                    "source_message_id"
                ]
            )
            .eq(
                "destination_username",
                data[
                    "destination_username"
                ]
            )
            .limit(1)
            .execute()
        )

        if existing.data:

            return False

        supabase.table(
            "reposts"
        ).insert(
            data
        ).execute()

        return True

    except Exception as e:

        print(
            "SAVE PRIVATE REPOST ERROR:",
            e
        )

        return False


def send_private_repost_alert(
    source,
    forward,
    destination
):

    if OWNER_ID is None:

        return

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    destination_username = (
        clean_username(
            destination.get(
                "username"
            )
        )
    )

    destination_title = (
        destination.get(
            "title"
        )
        or destination_username
    )

    message_title = (
        destination.get(
            "message_title"
        )
        or "بدون عنوان"
    )

    source_message_id = (
        forward.get(
            "message_id"
        )
    )

    source_link = make_source_link(
        source,
        source_message_id
    )

    text = (
        "🚨 بازنشر ثبت شد!\n\n"

        f"📢 کانال مقصد:\n"
        f"{destination_title}\n"

        f"🔹 @{destination_username}\n\n"

        f"📝 عنوان پیام:\n"
        f"{message_title}\n\n"

        f"🕒 زمان ثبت:\n"
        f"{now_shamsi()}"
    )

    if source_link:

        text += (
            "\n\n"
            f"🔗 پست مرجع:\n"
            f"{source_link}"
        )

    send_message(
        OWNER_ID,
        text
    )


# =========================================================
# PRIVATE FORWARDED MESSAGE
# =========================================================

def process_private_forward(message):

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    if OWNER_ID is None:

        return

    if chat_id != OWNER_ID:

        return

    forward = extract_forward(
        message
    )

    if not forward.get(
        "message_id"
    ):

        return

    print(
        "PRIVATE FORWARD:",
        forward
    )

    if not is_from_source(
        forward
    ):

        send_message(
            chat_id,

            "⚠️ این پیام از کانال "
            "مرجع تعیین‌شده نیست."
        )

        return

    source = get_source()

    if not source:

        send_message(
            chat_id,

            "❌ ابتدا کانال مرجع "
            "را تعیین کنید."
        )

        return

    pending_channel = get_setting(
        "pending_private_destination"
    )

    if not pending_channel:

        send_message(
            chat_id,

            "⚠️ کانال مقصد مشخص نشده است.\n\n"

            "ابتدا دستور زیر را بزنید:\n\n"

            "/repost @channel\n\n"

            "سپس همان پیام فورواردشده "
            "از کانال مرجع را ارسال کنید."
        )

        return

    destination_username = (
        clean_username(
            pending_channel
        )
    )

    destination_channel = (
        get_channel_by_username(
            destination_username
        )
    )

    destination_chat = get_chat(
        "@" + destination_username
    )

    destination_title = (
        destination_username
    )

    destination_chat_id = None

    if destination_channel:

        destination_title = (
            destination_channel.get(
                "title",
                destination_username
            )
        )

        destination_chat_id = (
            destination_channel.get(
                "id"
            )
        )

    if destination_chat:

        destination_title = (
            destination_chat.get(
                "title",
                destination_title
            )
        )

        if destination_chat.get(
            "id"
        ):

            destination_chat_id = (
                destination_chat.get(
                    "id"
                )
            )

    message_title = get_message_title(
        message
    )

    destination = {

        "chat_id":
            destination_chat_id,

        "username":
            destination_username,

        "title":
            destination_title,

        "message_id":
            None,

        "message_title":
            message_title
    }

    is_new = save_private_repost(
        source,
        forward,
        destination
    )

    if not is_new:

        send_message(
            chat_id,

            "⚠️ این بازنشر قبلاً "
            "ثبت شده است."
        )

        save_setting(
            "pending_private_destination",
            ""
        )

        return

    send_private_repost_alert(
        source,
        forward,
        destination
    )

    save_setting(
        "pending_private_destination",
        ""

    )


# =========================================================
# REPORT HELPERS
# =========================================================

def source_row_matches(
    row,
    source
):

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    source_id = source.get(
        "id"
    )

    row_username = clean_username(
        row.get(
            "source_username"
        )
    )

    row_id = row.get(
        "source_channel_id"
    )

    if (
        source_username
        and row_username
        and source_username == row_username
    ):

        return True

    if (
        source_id
        and row_id
    ):

        try:

            if int(source_id) == int(
                row_id
            ):

                return True

        except:

            pass

    return False


def get_report_rows():

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .order(
                "created_at",
                desc=True
            )
            .limit(1000)
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET REPORT ROWS ERROR:",
            e
        )

        return []


# =========================================================
# REPORT
# =========================================================

def report():

    source = get_source()

    if not source:

        return (
            "❌ هنوز کانال مرجع "
            "تعیین نشده است."
        )

    rows = get_report_rows()

    source_rows = []

    for row in rows:

        if source_row_matches(
            row,
            source
        ):

            source_rows.append(
                row
            )

    if not source_rows:

        return (
            "📊 گزارش بازنشرها\n\n"

            "برای کانال مرجع فعلی، "
            "هنوز هیچ بازنشری ثبت نشده است."
        )

    # -----------------------------------------------------
    # Group by source message
    # -----------------------------------------------------

    grouped = {}

    for row in source_rows:

        source_message_id = row.get(
            "source_message_id"
        )

        if not source_message_id:

            continue

        key = str(
            source_message_id
        )

        if key not in grouped:

            grouped[key] = []

        grouped[key].append(
            row
        )

    if not grouped:

        return (
            "📊 گزارش بازنشرها\n\n"
            "اطلاعات پست مرجع ناقص است."
        )

    source_username = clean_username(
        source.get(
            "username"
        )
    )

    # -----------------------------------------------------
    # Sort source posts by message ID
    # -----------------------------------------------------

    groups = list(
        grouped.items()
    )

    try:

        groups.sort(
            key=lambda x: int(x[0]),
            reverse=True
        )

    except:

        groups.reverse()

    # -----------------------------------------------------
    # Build report
    # -----------------------------------------------------

    header = (
        "📊 گزارش بازنشرها\n\n"

        f"🎯 کانال مرجع:\n"
        f"@{source_username}\n\n"

        f"📝 تعداد پست‌های مرجع ثبت‌شده: "
        f"{len(groups)}\n"
    )

    messages = []
    current = header

    for source_message_id, rows_for_post in groups:

        source_link = make_source_link(
            source,
            source_message_id
        )

        # Remove duplicate destinations
        unique_rows = []
        seen_destinations = set()

        for row in rows_for_post:

            destination = clean_username(
                row.get(
                    "destination_username"
                )
            )

            if not destination:

                continue

            if destination in seen_destinations:

                continue

            seen_destinations.add(
                destination
            )

            unique_rows.append(
                row
            )

        block = (
            "\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"

            f"📌 پست مرجع\n"
        )

        if source_link:

            block += (
                f"🔗 {source_link}\n"
            )

        block += (
            "\n"
            f"📢 بازنشر شده در "
            f"{len(unique_rows)} کانال:\n\n"
        )

        for index, row in enumerate(
            unique_rows,
            1
        ):

            destination = clean_username(
                row.get(
                    "destination_username"
                )
            )

            destination_title = (
                row.get(
                    "destination_title"
                )
                or (
                    "@"
                    + destination
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

            block += (
                f"{index}️⃣ "
                f"📢 {destination_title}\n"

                f"   🔹 @{destination}\n"

                f"   📝 {message_title}\n"

                f"   🕒 "
                f"{to_shamsi(created_at)}\n\n"
            )

        if len(current) + len(block) > 3500:

            messages.append(
                current
            )

            current = block

        else:

            current += block

    if current.strip():

        messages.append(
            current
        )

    for text in messages:

        send_message(
            OWNER_ID,
            text
        )

    return None


# =========================================================
# STATUS
# =========================================================

def status():

    source = get_source()

    channels = get_channels()

    text = (
        "🤖 وضعیت ربات\n\n"
    )

    if source:

        text += (
            "🎯 کانال مرجع:\n"
            f"@{clean_username(source.get('username'))}\n\n"
        )

        if source.get("title"):

            text += (
                f"📌 عنوان:\n"
                f"{source.get('title')}\n\n"
            )

        if source.get("id"):

            text += (
                f"🆔 شناسه:\n"
                f"{source.get('id')}\n\n"
            )

    else:

        text += (
            "🎯 کانال مرجع:\n"
            "❌ تعیین نشده\n\n"
        )

    text += (
        f"📢 تعداد کانال‌های تحت نظر: "
        f"{len(channels)} / 100\n\n"
    )

    if channels:

        text += "کانال‌ها:\n"

        for i, channel in enumerate(
            channels,
            1
        ):

            channel_title = (
                channel.get(
                    "title"
                )
                or (
                    "@"
                    + channel.get(
                        "username",
                        ""
                    )
                )
            )

            text += (
                f"{i}. "
                f"{channel_title}\n"
            )

    return text


# =========================================================
# COMMAND HANDLER
# =========================================================

def handle_command(message):

    global OWNER_ID

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    text = message.get(
        "text",
        ""
    ).strip()

    if not text.startswith("/"):

        return

    if chat.get(
        "type"
    ) == "private":

        if OWNER_ID is None:

            OWNER_ID = chat_id

            save_setting(
                "owner_id",
                chat_id
            )

        if chat_id != OWNER_ID:

            return

    parts = text.split()

    command = parts[0].lower()

    if "@" in command:

        command = command.split(
            "@"
        )[0]

    args = parts[1:]

    # =====================================================
    # START
    # =====================================================

    if command == "/start":

        send_message(
            chat_id,

            "🤖 ربات پایش بازنشر فعال است.\n\n"

            "دستورها:\n\n"

            "/source @channel\n"
            "🎯 تعیین کانال مرجع\n\n"

            "/addchannel @channel\n"
            "➕ افزودن کانال تحت نظر\n\n"

            "/removechannel @channel\n"
            "➖ حذف کانال از پایش\n\n"

            "/listchannels\n"
            "📢 نمایش کانال‌های تحت نظر\n\n"

            "/repost @channel\n"
            "📝 ثبت بازنشر با فوروارد خصوصی\n\n"

            "/report\n"
            "📊 گزارش بازنشرها بر اساس پست مرجع\n\n"

            "/status\n"
            "⚙️ وضعیت ربات\n\n"

            "حداکثر ۱۰۰ کانال مقصد "
            "قابل پایش است."
        )

        return

    # =====================================================
    # SOURCE
    # =====================================================

    if command == "/source":

        if not args:

            send_message(
                chat_id,

                "❌ نام کانال وارد نشده است.\n\n"

                "مثال:\n"
                "/source @barghsb"
            )

            return

        success, result = set_source(
            args[0]
        )

        if success:

            send_message(
                chat_id,

                "✅ کانال مرجع تعیین شد.\n\n"

                f"🎯 @{result['username']}\n"

                f"📌 {result['title']}\n"

                f"🆔 "
                f"{result['id'] or 'دریافت نشد'}\n\n"

                "از این لحظه بازنشرهای مستقیم "
                "این کانال شناسایی می‌شوند."
            )

        else:

            send_message(
                chat_id,
                "❌ " + str(result)
            )

        return

    # =====================================================
    # ADD CHANNEL
    # =====================================================

    if command == "/addchannel":

        if not args:

            send_message(
                chat_id,

                "❌ نام کانال وارد نشده است.\n\n"

                "مثال:\n"
                "/addchannel @mammalss"
            )

            return

        success, result = add_channel(
            args[0]
        )

        if success:

            send_message(
                chat_id,
                str(result)
            )

        else:

            send_message(
                chat_id,
                "❌ " + str(result)
            )

        return

    # =====================================================
    # REMOVE CHANNEL
    # =====================================================

    if command == "/removechannel":

        if not args:

            send_message(
                chat_id,

                "❌ نام کانال وارد نشده است.\n\n"

                "مثال:\n"
                "/removechannel @mammalss"
            )

            return

        if remove_channel(
            args[0]
        ):

            send_message(
                chat_id,
                "✅ کانال از فهرست پایش حذف شد."
            )

        else:

            send_message(
                chat_id,
                "❌ حذف کانال انجام نشد."
            )

        return

    # =====================================================
    # LIST CHANNELS
    # =====================================================

    if command == "/listchannels":

        channels = get_channels()

        if not channels:

            send_message(
                chat_id,

                "📢 هنوز هیچ کانالی "
                "برای پایش اضافه نشده است."
            )

            return

        text = (
            f"📢 کانال‌های تحت نظر "
            f"({len(channels)}/100):\n\n"
        )

        for i, channel in enumerate(
            channels,
            1
        ):

            channel_title = (
                channel.get(
                    "title"
                )
                or (
                    "@"
                    + channel.get(
                        "username",
                        ""
                    )
                )
            )

            text += (
                f"{i}. "
                f"{channel_title}\n"
            )

        send_message(
            chat_id,
            text
        )

        return

    # =====================================================
    # REPOST
    # =====================================================

    if command == "/repost":

        if not args:

            send_message(
                chat_id,

                "❌ کانال مقصد وارد نشده است.\n\n"

                "مثال:\n"
                "/repost @mammalss\n\n"

                "بعد از آن، پیام فورواردشده "
                "از کانال مرجع را برای ربات ارسال کنید."
            )

            return

        destination = clean_username(
            args[0]
        )

        if not destination:

            send_message(
                chat_id,
                "❌ نام کانال مقصد معتبر نیست."
            )

            return

        # Check whether destination is monitored.
        if not is_monitored(
            destination
        ):

            send_message(
                chat_id,

                "⚠️ این کانال در فهرست "
                "کانال‌های تحت نظر نیست.\n\n"

                f"ابتدا آن را اضافه کنید:\n"
                f"/addchannel @{destination}"
            )

            return

        save_setting(
            "pending_private_destination",
            destination
        )

        send_message(
            chat_id,

            "✅ کانال مقصد ثبت شد:\n\n"

            f"📢 @{destination}\n\n"

            "حالا پیام فورواردشده از کانال "
            "مرجع را برای ربات ارسال کنید."
        )

        return

    # =====================================================
    # REPORT
    # =====================================================

    if command == "/report":

        result = report()

        if result:

            send_message(
                chat_id,
                result
            )

        return

    # =====================================================
    # STATUS
    # =====================================================

    if command == "/status":

        send_message(
            chat_id,
            status()
        )

        return


# =========================================================
# PROCESS CHANNEL MESSAGE
# =========================================================

def process_channel_message(message):

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    username = chat.get(
        "username"
    )

    message_id = message.get(
        "message_id"
    )

    if not username:

        print(
            "CHANNEL WITHOUT USERNAME"
        )

        return

    username = clean_username(
        username
    )

    print(
        "CHANNEL MESSAGE:",
        username,
        message_id
    )

    if not is_monitored(
        username
    ):

        print(
            "NOT MONITORED:",
            username
        )

        return

    forward = extract_forward(
        message
    )

    if not forward.get(
        "message_id"
    ):

        return

    print(
        "FORWARD:",
        forward
    )

    if not is_from_source(
        forward
    ):

        print(
            "NOT FROM SOURCE"
        )

        return

    source = get_source()

    if not source:

        print(
            "SOURCE NOT SET"
        )

        return

    destination_title = (
        chat.get(
            "title"
        )
        or username
    )

    # Prefer title saved in channels table.
    monitored_channel = (
        get_channel_by_username(
            username
        )
    )

    if monitored_channel:

        destination_title = (
            monitored_channel.get(
                "title"
            )
            or destination_title
        )

    message_title = get_message_title(
        message
    )

    destination = {

        "chat_id":
            chat_id,

        "username":
            username,

        "title":
            destination_title,

        "message_id":
            message_id,

        "message_title":
            message_title
    }

    is_new = save_repost(
        source,
        forward,
        destination
    )

    if not is_new:

        print(
            "REPOST ALREADY EXISTS:",
            username,
            message_id
        )

        return

    print(
        "NEW REPOST:",
        username,
        message_id
    )

    send_repost_alert(
        source,
        forward,
        destination
    )


# =========================================================
# UPDATE PROCESSOR
# =========================================================

def process_update(update):

    print(
        "UPDATE:",
        update
    )

    message = update.get(
        "message"
    )

    if not message:

        return

    chat = message.get(
        "chat",
        {}
    )

    chat_type = chat.get(
        "type"
    )

    # -----------------------------------------------------
    # Private
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

        else:

            handle_command(
                message
            )

        return

    # -----------------------------------------------------
    # Channel
    # -----------------------------------------------------

    if chat_type == "channel":

        process_channel_message(
            message
        )

        return


# =========================================================
# POLLING
# =========================================================

def polling():

    offset = 0

    print(
        "BOT STARTED"
    )

    load_owner()

    while True:

        try:

            result = bale(
                "getUpdates",
                {
                    "offset": offset,
                    "limit": 100,
                    "timeout": 30
                }
            )

            if not result.get(
                "ok"
            ):

                print(
                    "GET UPDATES FAILED:",
                    result
                )

                time.sleep(3)

                continue

            updates = result.get(
                "result",
                []
            )

            for update in updates:

                try:

                    process_update(
                        update
                    )

                except Exception as e:

                    print(
                        "UPDATE PROCESS ERROR:",
                        e
                    )

                offset = max(
                    offset,
                    update.get(
                        "update_id",
                        0
                    ) + 1
                )

        except Exception as e:

            print(
                "POLLING ERROR:",
                e
            )

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    polling()
