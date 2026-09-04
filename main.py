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

        print("BALE:", method, result)

        return result

    except Exception as e:

        print("BALE ERROR:", method, e)

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
# PERSIAN DATE
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
        gy % 4 == 0 and
        (gy % 100 != 0 or gy % 400 == 0)
    ):
        g_day_no += 1

    g_day_no += gd2

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053

    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)

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


def to_shamsi(dt):

    if not dt:
        return ""

    try:

        if isinstance(dt, str):

            dt = dt.replace("Z", "+00:00")

            dt = datetime.fromisoformat(dt)

        jy, jm, jd = gregorian_to_jalali(
            dt.year,
            dt.month,
            dt.day
        )

        return (
            f"{jy:04d}/{jm:02d}/{jd:02d}"
            f" {dt.hour:02d}:{dt.minute:02d}"
        )

    except Exception as e:

        print("SHAMSI ERROR:", e)

        return str(dt)


def now_shamsi():

    now = datetime.now(timezone.utc)

    iran_time = now + timedelta(hours=3, minutes=30)

    return to_shamsi(iran_time)


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

            return result.data[0]["value"]

    except Exception as e:

        print("GET SETTING ERROR:", e)

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

        print("SAVE SETTING ERROR:", e)

        return False


# =========================================================
# OWNER
# =========================================================

def load_owner():

    global OWNER_ID

    value = get_setting("owner_id")

    if value:

        try:

            OWNER_ID = int(value)

        except Exception:

            OWNER_ID = None

    print("OWNER:", OWNER_ID)


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

    username = str(username).strip()

    username = username.replace(
        "https://ble.ir/",
        ""
    )

    username = username.replace(
        "http://ble.ir/",
        ""
    )

    username = username.replace(
        "www.ble.ir/",
        ""
    )

    username = username.strip("/")

    if username.startswith("@"):

        username = username[1:]

    # اگر لینک کامل فرستاده شده باشد
    if "/" in username:

        username = username.split("/")[0]

    return username


# =========================================================
# BLE LINK
# =========================================================

def normalize_ble_link(link):

    if not link:
        return None

    try:

        link = str(link).strip()

        link = link.rstrip(
            ".,،)]}>\"'"
        )

        # فرمت:
        # https://ble.ir/channel/123

        match = re.search(
            r"https?://(?:www\.)?ble\.ir/[A-Za-z0-9_]+/\d+",
            link
        )

        if match:

            return match.group(0)

        # فرمت:
        # https://ble.ir/c/123456/789

        match = re.search(
            r"https?://(?:www\.)?ble\.ir/c/\d+/\d+",
            link
        )

        if match:

            return match.group(0)

    except Exception as e:

        print(
            "LINK NORMALIZE ERROR:",
            e
        )

    return None


def extract_message_link(message):

    """
    تلاش می‌کند لینک واقعی پیام را
    از اطلاعات دریافتی Bale استخراج کند.
    """

    if not isinstance(message, dict):

        return None

    possible_fields = [
        "link",
        "url",
        "message_link",
        "share_link",
        "permalink"
    ]

    for field in possible_fields:

        value = message.get(field)

        if isinstance(value, str):

            link = normalize_ble_link(value)

            if link:
                return link

    # جستجو در متن و کپشن
    texts = []

    if message.get("text"):

        texts.append(
            str(message.get("text"))
        )

    if message.get("caption"):

        texts.append(
            str(message.get("caption"))
        )

    for text in texts:

        link = normalize_ble_link(text)

        if link:

            return link

    # جستجوی بازگشتی در آبجکت
    def recursive_search(obj):

        if isinstance(obj, dict):

            for key, value in obj.items():

                if isinstance(value, str):

                    link = normalize_ble_link(value)

                    if link:

                        return link

                elif isinstance(
                    value,
                    (dict, list)
                ):

                    result = recursive_search(value)

                    if result:

                        return result

        elif isinstance(obj, list):

            for item in obj:

                result = recursive_search(item)

                if result:

                    return result

        return None

    return recursive_search(message)


# =========================================================
# BALE CHAT
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

            return result.get("result")

    except Exception as e:

        print(
            "GET CHAT ERROR:",
            e
        )

    return None


# =========================================================
# SOURCE CHANNEL
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

    chat_id = chat.get("id")

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or chat.get("first_name")
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
# CHANNEL TABLE
# =========================================================

def channel_db_id(username):

    return hashlib.sha256(
        username.lower().encode(
            "utf-8"
        )
    ).hexdigest()[:32]


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
            .eq("username", username)
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("channels")
                .update(
                    {
                        "active": True
                    }
                )
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

        active = (
            supabase
            .table("channels")
            .select("id")
            .eq("active", True)
            .execute()
        )

        if len(active.data or []) >= 100:

            return (
                False,
                "❌ حداکثر ۱۰۰ کانال قابل مانیتور است."
            )

        chat = get_chat(
            "@" + username
        )

        title = username

        chat_id = None

        if chat:

            title = (
                chat.get("title")
                or username
            )

            chat_id = chat.get("id")

        data = {
            "id": channel_db_id(
                username
            ),
            "username": username,
            "title": title,
            "active": True
        }

        if chat_id:

            data["id"] = channel_db_id(
                username
            )

        (
            supabase
            .table("channels")
            .insert(data)
            .execute()
        )

        return (
            True,
            "کانال با موفقیت اضافه شد."
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


def remove_channel(username):

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


def get_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("active", True)
            .order(
                "title"
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


def get_channel_by_username(username):

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
            "GET CHANNEL ERROR:",
            e
        )

    return None


def is_monitored(forward):

    username = clean_username(
        forward.get("username")
    )

    chat_id = forward.get(
        "chat_id"
    )

    if username:

        channel = get_channel_by_username(
            username
        )

        if channel:

            return channel

    channels = get_channels()

    for channel in channels:

        if (
            chat_id
            and str(channel.get("chat_id")) == str(chat_id)
        ):

            return channel

        if (
            username
            and clean_username(
                channel.get("username")
            ) == username
        ):

            return channel

    return None


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(message):

    forward_chat_id = None
    forward_username = None
    forward_message_id = None

    # روش قدیمی Bale API
    forward_from_chat = message.get(
        "forward_from_chat"
    )

    if forward_from_chat:

        forward_chat_id = (
            forward_from_chat.get("id")
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

    # روش جدید
    forward_origin = message.get(
        "forward_origin"
    )

    if forward_origin:

        if (
            forward_origin.get("type")
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


# =========================================================
# SOURCE CHECK
# =========================================================

def is_from_source(forward):

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

def get_message_title(message):

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    text = str(text).strip()

    if not text:

        return "بدون عنوان"

    # اولین خط به عنوان عنوان
    first_line = (
        text.splitlines()[0].strip()
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
        destination.get("username")
    )

    if not destination_username:
        return False

    try:

        # جلوگیری از ثبت تکراری
        duplicate = (
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
                    source.get("username")
                )
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

        if duplicate.data:

            print(
                "DUPLICATE REPOST"
            )

            return False

        data = {
            "source_channel_id": source.get(
                "channel_id"
            ),
            "source_username": clean_username(
                source.get(
                    "username"
                )
            ),
            "source_message_id": source_message_id,

            "destination_channel_id": destination.get(
                "id"
            ),
            "destination_username": destination_username,
            "destination_message_id": destination_message_id,
            "destination_title": destination.get(
                "title"
            ),

            "message_title": message_title,

            "created_at": datetime.now(
                timezone.utc
            ).isoformat()
        }

        (
            supabase
            .table("reposts")
            .insert(data)
            .execute()
        )

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
# REPOST ALERT
# =========================================================

def send_repost_alert(
    source,
    destination,
    message_title,
    destination_message_id,
    source_message_id
):

    if OWNER_ID is None:

        return

    source_link = make_source_link(
        source,
        source_message_id
    )

    destination_username = clean_username(
        destination.get(
            "username"
        )
    )

    text = (
        "🔔 بازنشر جدید شناسایی شد\n\n"

        f"📢 کانال مقصد:\n"
        f"{destination.get('title') or 'بدون عنوان'}\n"
        f"🔹 @{destination_username}\n\n"

        f"📝 عنوان پیام:\n"
        f"{message_title}\n\n"

        f"🕒 زمان:\n"
        f"{now_shamsi()}\n\n"

        f"🔗 پست مرجع:\n"
        f"{source_link or 'لینک در دسترس نیست'}"
    )

    send_message(
        OWNER_ID,
        text
    )


# =========================================================
# PROCESS CHANNEL MESSAGE
# =========================================================

def process_channel_message(message):

    chat = message.get(
        "chat",
        {}
    )

    destination_username = clean_username(
        chat.get(
            "username"
        )
    )

    if not destination_username:

        return

    destination = get_channel_by_username(
        destination_username
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
            destination_message_id=destination_message_id,
            source_message_id=source_message_id
        )


# =========================================================
# PRIVATE FORWARDED SOURCE POST
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

    if str(chat_id) != str(OWNER_ID):

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

    print(
        "PRIVATE SOURCE FORWARD:",
        forward
    )

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
            "❌ ابتدا کانال مرجع را تعیین کنید."
        )

        return

    source_message_id = forward.get(
        "message_id"
    )

    # -----------------------------------------------------
    # عنوان پست مرجع
    # -----------------------------------------------------

    source_title = get_message_title(
        message
    )

    # -----------------------------------------------------
    # تلاش برای دریافت لینک واقعی پیام
    # -----------------------------------------------------

    real_link = extract_message_link(
        message
    )

    # اگر لینک واقعی داخل اطلاعات فوروارد نبود،
    # لینک استاندارد ساخته می‌شود.
    source_link = (
        real_link
        or make_source_link(
            source,
            source_message_id
        )
    )

    # -----------------------------------------------------
    # ذخیره پست انتخاب شده
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # پاسخ به کاربر
    # -----------------------------------------------------

    text = (
        "✅ پست مرجع دریافت و انتخاب شد.\n\n"

        "🎯 پست مرجع:\n"
        f"📝 عنوان: {source_title}\n\n"

        "🔗 پیوند پیام:\n"
        f"{source_link or 'لینک در دسترس نیست'}\n\n"

        "حالا /report را بزنید تا فقط "
        "بازنشرهای همین پست بررسی شود."
    )

    send_message(
        chat_id,
        text
    )


# =========================================================
# REPORT SELECTED SOURCE POST
# =========================================================

def report(chat_id):

    source = get_source()

    if not source:

        send_message(
            chat_id,
            "❌ ابتدا کانال مرجع را با /source تعیین کنید."
        )

        return

    selected_id = get_setting(
        "selected_report_source_message_id"
    )

    if not selected_id:

        send_message(
            chat_id,
            "⚠️ ابتدا پست مرجع را در همین چت برای ربات فوروارد کنید."
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

    # اگر لینک ذخیره نشده بود
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

        print(
            "REPORT ERROR:",
            e
        )

        send_message(
            chat_id,
            f"❌ خطا در دریافت گزارش:\n{e}"
        )

        return

    # -----------------------------------------------------
    # فقط بازنشرهای مربوط به کانال مرجع فعلی
    # -----------------------------------------------------

    filtered_rows = []

    source_id = source.get(
        "channel_id"
    )

    source_username = clean_username(
        source.get(
            "username"
        )
    )

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
    # حذف بازنشرهای تکراری یک کانال
    # -----------------------------------------------------

    unique_rows = {}

    for row in filtered_rows:

        username = clean_username(
            row.get(
                "destination_username"
            )
        )

        key = (
            username
            or str(
                row.get(
                    "destination_channel_id"
                )
            )
        )

        if key not in unique_rows:

            unique_rows[key] = row

    rows = list(
        unique_rows.values()
    )

    # -----------------------------------------------------
    # REPORT HEADER
    # -----------------------------------------------------

    text = (
        "📊 گزارش بازنشر پست انتخاب‌شده\n\n"

        "🎯 پست مرجع\n"

        f"📝 عنوان: "
        f"{selected_title or 'بدون عنوان'}\n\n"

        "🔗 پیوند پیام:\n"
        f"{selected_link or 'لینک در دسترس نیست'}\n\n"
    )

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
            or "بدون عنوان"
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

def list_channels(chat_id):

    channels = get_channels()

    if not channels:

        send_message(
            chat_id,
            "📭 هیچ کانال فعالی برای مانیتور وجود ندارد."
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
            f"   🔹 @{username}\n\n"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# STATUS
# =========================================================

def status(chat_id):

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
            f"📝 {source.get('title') or 'بدون عنوان'}\n"
            f"🔹 @{clean_username(source.get('username'))}\n\n"
        )

    else:

        text += (
            "🎯 کانال مرجع:\n"
            "❌ تعیین نشده\n\n"
        )

    text += (
        "📡 تعداد کانال‌های مانیتورشده:\n"
        f"{len(channels)} کانال\n\n"
    )

    if selected_id:

        selected_title = get_setting(
            "selected_report_source_title"
        )

        text += (
            "📌 پست انتخاب‌شده برای گزارش:\n"
            f"📝 {selected_title or 'بدون عنوان'}\n"
            f"🆔 {selected_id}\n"
        )

    else:

        text += (
            "📌 پست انتخاب‌شده:\n"
            "❌ هنوز پستی فوروارد نشده\n"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# HELP
# =========================================================

def start_message(chat_id):

    text = (
        "🤖 ربات پایش بازنشر\n\n"

        "دستورات:\n\n"

        "🎯 /source @channel\n"
        "تعیین کانال مرجع\n\n"

        "➕ /addchannel @channel\n"
        "افزودن کانال برای مانیتور\n\n"

        "➖ /removechannel @channel\n"
        "حذف کانال از مانیتور\n\n"

        "📋 /listchannels\n"
        "نمایش کانال‌های مانیتورشده\n\n"

        "📊 /report\n"
        "گزارش بازنشر پست مرجع انتخاب‌شده\n\n"

        "ℹ️ /status\n"
        "نمایش وضعیت ربات\n\n"

        "━━━━━━━━━━━━━━\n\n"

        "📌 روش استفاده از گزارش:\n\n"

        "1️⃣ پست موردنظر را از کانال مرجع "
        "برای ربات فوروارد کنید.\n\n"

        "2️⃣ ربات همان پست را به عنوان "
        "«پست مرجع» انتخاب می‌کند.\n\n"

        "3️⃣ سپس /report را بزنید.\n\n"

        "4️⃣ ربات فقط بازنشرهای همان پست "
        "را از کانال‌های تحت مانیتور نمایش می‌دهد."
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

        if save_source(
            chat
        ):

            send_message(
                chat_id,
                "✅ کانال مرجع با موفقیت تعیین شد.\n\n"
                f"🎯 {chat.get('title') or username}\n"
                f"🔹 @{username}"
            )

        return

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
            ("✅ " if ok else "")
            + msg
        )

        return

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

    if text.startswith(
        "/listchannels"
    ):

        list_channels(
            chat_id
        )

        return

    if text.startswith(
        "/report"
    ):

        report(
            chat_id
        )

        return

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

    # -----------------------------------------------------
    # PRIVATE CHAT
    # -----------------------------------------------------

    chat_type = chat.get(
        "type"
    )

    if chat_type == "private":

        # اگر پیام فوروارد شده باشد
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

        # دستورات
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
    # CHANNEL MESSAGE
    # -----------------------------------------------------

    if chat_type == "channel":

        process_channel_message(
            message
        )

        return


# =========================================================
# POLLING
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
# MAIN LOOP
# =========================================================

def main():

    global OWNER_ID

    load_owner()

    print(
        "================================="
    )

    print(
        "BALE REPOST BOT STARTED"
    )

    print(
        "OWNER:",
        OWNER_ID
    )

    print(
        "================================="
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
