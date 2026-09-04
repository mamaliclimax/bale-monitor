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


BASE_URL = f"https://tapi.bale.ai/bot{BALE_TOKEN}"

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)


# =========================================================
# BASIC HELPERS
# =========================================================

def clean_username(username):

    if not username:
        return None

    username = str(username).strip()

    if username.startswith("@"):
        username = username[1:]

    return username.lower()


def safe_text(value):

    if value is None:
        return ""

    return str(value).strip()


# =========================================================
# BALE API
# =========================================================

def bale(method, payload=None, timeout=30):

    url = f"{BASE_URL}/{method}"

    try:

        response = requests.post(
            url,
            json=payload or {},
            timeout=timeout
        )

        if response.status_code != 200:

            print(
                "BALE HTTP ERROR:",
                response.status_code,
                response.text
            )

            return None

        data = response.json()

        if not data.get("ok"):

            print(
                "BALE API ERROR:",
                data
            )

        return data

    except Exception as e:

        print(
            "BALE REQUEST ERROR:",
            e
        )

        return None


def send_message(chat_id, text):

    if not chat_id:
        return None

    return bale(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
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
                },
                on_conflict="key"
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

OWNER_ID = get_setting(
    "owner_id"
)

if OWNER_ID:

    OWNER_ID = str(
        OWNER_ID
    ).strip()

print(
    "OWNER_ID:",
    OWNER_ID
)


def is_owner(user_id):

    if not OWNER_ID:
        return False

    return (
        str(user_id)
        == str(OWNER_ID)
    )


# =========================================================
# BOT USERS
# =========================================================

def save_bot_user(chat):

    if not chat:
        return False

    user_id = chat.get(
        "id"
    )

    if not user_id:
        return False

    username = clean_username(
        chat.get("username")
    )

    first_name = (
        chat.get("first_name")
        or ""
    )

    last_name = (
        chat.get("last_name")
        or ""
    )

    try:

        data = {
            "user_id": str(user_id),
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "active": True,
            "updated_at": datetime.now(
                timezone.utc
            ).isoformat()
        }

        (
            supabase
            .table("bot_users")
            .upsert(
                data,
                on_conflict="user_id"
            )
            .execute()
        )

        print(
            "USER SAVED:",
            data
        )

        return True

    except Exception as e:

        print(
            "SAVE BOT USER ERROR:",
            e
        )

        return False


def get_bot_user_by_id(user_id):

    if not user_id:
        return None

    try:

        result = (
            supabase
            .table("bot_users")
            .select("*")
            .eq(
                "user_id",
                str(user_id)
            )
            .limit(1)
            .execute()
        )

        if result.data:

            return result.data[0]

    except Exception as e:

        print(
            "GET USER BY ID ERROR:",
            e
        )

    return None


def get_bot_user_by_username(username):

    username = clean_username(
        username
    )

    if not username:
        return None

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

            return result.data[0]

    except Exception as e:

        print(
            "GET USER BY USERNAME ERROR:",
            e
        )

    return None


# =========================================================
# ADMIN SYSTEM
# =========================================================

def is_admin(user_id):

    if not user_id:
        return False

    # Owner همیشه دسترسی کامل دارد
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


def add_admin(
    user_id,
    username=None,
    first_name=None
):

    if not user_id:
        return False

    try:

        data = {
            "user_id": str(user_id),
            "username": clean_username(
                username
            ),
            "first_name": (
                first_name
                or ""
            ),
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

        return True

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            e
        )

        return False


def remove_admin(user_id):

    if not user_id:
        return False

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

        return True

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            e
        )

        return False


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
                "created_at"
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


# =========================================================
# ACCESS DENIED
# =========================================================

def deny_access(chat_id):

    send_message(
        chat_id,
        "⛔ شما مجاز به استفاده از این ربات نیستید.\n\n"
        "اگر قصد دریافت User ID خود را دارید، "
        "دستور /myid را ارسال کنید."
    )


# =========================================================
# MY ID
# =========================================================

def show_my_id(chat_id):

    user = get_bot_user_by_id(
        chat_id
    )

    # اگر به هر دلیل رکورد در DB نبود،
    # خود chat_id را نمایش می‌دهیم.
    if not user:

        send_message(
            chat_id,
            "🆔 اطلاعات حساب شما\n\n"
            f"User ID: {chat_id}\n\n"
            "همین User ID را برای مدیر ربات ارسال کنید."
        )

        return

    username = clean_username(
        user.get("username")
    )

    first_name = (
        user.get("first_name")
        or "بدون نام"
    )

    text = (
        "🆔 اطلاعات حساب شما\n\n"
        f"👤 نام: {first_name}\n"
        f"🆔 User ID: {chat_id}\n"
    )

    if username:

        text += (
            f"🔹 Username: @{username}\n"
        )

    if is_owner(chat_id):

        text += (
            "\n👑 وضعیت: Owner"
        )

    elif is_admin(chat_id):

        text += (
            "\n🛡 وضعیت: Admin"
        )

    else:

        text += (
            "\n👤 وضعیت: کاربر عادی"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# ADD ADMIN
# =========================================================

def command_add_admin(
    chat_id,
    argument
):

    if not is_owner(chat_id):

        deny_access(
            chat_id
        )

        return

    argument = safe_text(
        argument
    )

    if not argument:

        send_message(
            chat_id,
            "❌ User ID یا Username را وارد کنید.\n\n"
            "روش پیشنهادی:\n"
            "/addadmin 123456789\n\n"
            "یا:\n"
            "/addadmin @username"
        )

        return

    target_user = None

    # =====================================================
    # Numeric User ID
    # =====================================================

    if argument.isdigit():

        target_user = get_bot_user_by_id(
            argument
        )

        if not target_user:

            send_message(
                chat_id,
                "❌ این User ID هنوز در ربات ثبت نشده است.\n\n"
                "کاربر موردنظر باید حداقل یک‌بار برای ربات "
                "پیام ارسال کند یا /myid را بزند."
            )

            return

    # =====================================================
    # Username
    # =====================================================

    else:

        username = clean_username(
            argument
        )

        target_user = get_bot_user_by_username(
            username
        )

        if not target_user:

            send_message(
                chat_id,
                "❌ این Username در فهرست کاربران ربات پیدا نشد.\n\n"
                "از کاربر بخواهید ابتدا /myid را برای ربات "
                "ارسال کند و User ID خودش را به شما بدهد.\n\n"
                "سپس استفاده کنید:\n"
                "/addadmin USER_ID"
            )

            return

    target_id = target_user.get(
        "user_id"
    )

    target_username = target_user.get(
        "username"
    )

    target_first_name = (
        target_user.get("first_name")
        or ""
    )

    if is_owner(target_id):

        send_message(
            chat_id,
            "👑 این کاربر Owner ربات است."
        )

        return

    if is_admin(target_id):

        send_message(
            chat_id,
            "ℹ️ این کاربر از قبل Admin است."
        )

        return

    success = add_admin(
        target_id,
        target_username,
        target_first_name
    )

    if not success:

        send_message(
            chat_id,
            "❌ افزودن Admin انجام نشد."
        )

        return

    display_name = (
        target_first_name
        or "بدون نام"
    )

    text = (
        "✅ Admin با موفقیت اضافه شد.\n\n"
        f"👤 نام: {display_name}\n"
        f"🆔 User ID: {target_id}\n"
    )

    if target_username:

        text += (
            f"🔹 Username: @{target_username}\n"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# REMOVE ADMIN
# =========================================================

def command_remove_admin(
    chat_id,
    argument
):

    if not is_owner(chat_id):

        deny_access(
            chat_id
        )

        return

    argument = safe_text(
        argument
    )

    if not argument:

        send_message(
            chat_id,
            "❌ User ID یا Username را وارد کنید.\n\n"
            "مثال:\n"
            "/removeadmin 123456789"
        )

        return

    target_user = None

    if argument.isdigit():

        target_user = get_bot_user_by_id(
            argument
        )

    else:

        target_user = get_bot_user_by_username(
            argument
        )

    if not target_user:

        send_message(
            chat_id,
            "❌ کاربر پیدا نشد."
        )

        return

    target_id = target_user.get(
        "user_id"
    )

    if is_owner(target_id):

        send_message(
            chat_id,
            "⛔ Owner را نمی‌توان حذف کرد."
        )

        return

    if not is_admin(target_id):

        send_message(
            chat_id,
            "ℹ️ این کاربر Admin نیست."
        )

        return

    success = remove_admin(
        target_id
    )

    if not success:

        send_message(
            chat_id,
            "❌ حذف Admin انجام نشد."
        )

        return

    send_message(
        chat_id,
        f"✅ Admin با User ID {target_id} حذف شد."
    )


# =========================================================
# LIST ADMINS
# =========================================================

def command_list_admins(chat_id):

    if not is_owner(chat_id):

        deny_access(
            chat_id
        )

        return

    admins = get_admins()

    text = (
        "🛡 لیست Adminهای فعال\n\n"
    )

    if not admins:

        text += (
            "هیچ Admin فعالی وجود ندارد."
        )

    else:

        for index, admin in enumerate(
            admins,
            start=1
        ):

            user_id = admin.get(
                "user_id",
                "-"
            )

            username = clean_username(
                admin.get("username")
            )

            first_name = (
                admin.get("first_name")
                or "بدون نام"
            )

            text += (
                f"{index}. {first_name}\n"
                f"🆔 {user_id}\n"
            )

            if username:

                text += (
                    f"🔹 @{username}\n"
                )

            text += "\n"

    send_message(
        chat_id,
        text
    )


# =========================================================
# JALALI DATE
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

        g_day_no += (
            g_days_in_month[i]
        )

    if (
        gm > 1
        and (
            (gy + 1600) % 4 == 0
            and (
                (gy + 1600) % 100 != 0
                or (gy + 1600) % 400 == 0
            )
        )
    ):

        g_day_no += 1

    g_day_no += gd

    j_day_no = (
        g_day_no - 79
    )

    j_np = (
        j_day_no // 12053
    )

    j_day_no %= 12053

    jy = (
        979
        + 33 * j_np
        + 4 * (
            j_day_no // 1461
        )
    )

    j_day_no %= 1461

    if j_day_no >= 366:

        jy += (
            (j_day_no - 1)
            // 365
        )

        j_day_no = (
            (j_day_no - 1)
            % 365
        )

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


def format_jalali_datetime(value):

    if not value:
        return "-"

    try:

        dt = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00"
            )
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        iran = timezone(
            timedelta(
                hours=3,
                minutes=30
            )
        )

        dt = dt.astimezone(
            iran
        )

        jy, jm, jd = gregorian_to_jalali(
            dt.year,
            dt.month,
            dt.day
        )

        return (
            f"{jy:04d}/{jm:02d}/{jd:02d} "
            f"{dt.hour:02d}:{dt.minute:02d}"
        )

    except Exception:

        return str(value)


# =========================================================
# CHANNELS
# =========================================================

def get_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .order("id")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET CHANNELS ERROR:",
            e
        )

        return []


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
            .order("id")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET ACTIVE CHANNELS ERROR:",
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
            .limit(1)
            .execute()
        )

        if result.data:

            return result.data[0]

    except Exception as e:

        print(
            "GET CHANNEL USERNAME ERROR:",
            e
        )

    return None


def get_channel_by_chat_id(chat_id):

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
            .limit(1)
            .execute()
        )

        if result.data:

            return result.data[0]

    except Exception as e:

        print(
            "GET CHANNEL CHAT ID ERROR:",
            e
        )

    return None


def add_channel(
    username,
    title=None,
    chat_id=None
):

    username = clean_username(
        username
    )

    if not username:
        return False

    try:

        existing = get_channel_by_username(
            username
        )

        data = {
            "username": username,
            "title": (
                title
                or username
            ),
            "active": True
        }

        if chat_id:

            data["chat_id"] = str(
                chat_id
            )

        if existing:

            (
                supabase
                .table("channels")
                .update(data)
                .eq(
                    "id",
                    existing["id"]
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

        return True

    except Exception as e:

        print(
            "ADD CHANNEL ERROR:",
            e
        )

        return False


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
            "REMOVE CHANNEL ERROR:",
            e
        )

        return False


# =========================================================
# BALE CHAT
# =========================================================

def get_chat(chat_id):

    if not chat_id:
        return None

    result = bale(
        "getChat",
        {
            "chat_id": chat_id
        }
    )

    if not result:
        return None

    if not result.get("ok"):
        return None

    return result.get(
        "result"
    )


def resolve_destination_channel(chat):

    if not chat:
        return None

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

    # =====================================================
    # 1. chat_id
    # =====================================================

    existing = get_channel_by_chat_id(
        chat_id
    )

    if existing:

        return {
            "chat_id": str(
                existing.get("chat_id")
                or chat_id
            ),
            "username": clean_username(
                existing.get("username")
            ),
            "title": (
                existing.get("title")
                or title
            )
        }

    # =====================================================
    # 2. username
    # =====================================================

    if username:

        existing = get_channel_by_username(
            username
        )

        if existing:

            return {
                "chat_id": str(
                    existing.get("chat_id")
                    or chat_id
                ),
                "username": clean_username(
                    existing.get("username")
                ),
                "title": (
                    existing.get("title")
                    or title
                )
            }

    # =====================================================
    # 3. Active channels
    # =====================================================

    for channel in get_active_channels():

        stored_chat_id = str(
            channel.get("chat_id")
            or ""
        )

        stored_username = clean_username(
            channel.get("username")
        )

        if (
            stored_chat_id
            and chat_id
            and stored_chat_id
            == str(chat_id)
        ):

            return {
                "chat_id": str(chat_id),
                "username": stored_username,
                "title": (
                    channel.get("title")
                    or title
                )
            }

        if (
            stored_username
            and username
            and stored_username
            == username
        ):

            return {
                "chat_id": str(
                    channel.get("chat_id")
                    or chat_id
                ),
                "username": stored_username,
                "title": (
                    channel.get("title")
                    or title
                )
            }

    # =====================================================
    # 4. getChat
    # =====================================================

    fetched = get_chat(
        chat_id
    )

    if fetched:

        fetched_username = clean_username(
            fetched.get("username")
        )

        fetched_title = (
            fetched.get("title")
            or fetched_username
            or title
        )

        existing = None

        if fetched_username:

            existing = get_channel_by_username(
                fetched_username
            )

        if existing:

            return {
                "chat_id": str(
                    existing.get("chat_id")
                    or chat_id
                ),
                "username": (
                    clean_username(
                        existing.get("username")
                    )
                    or fetched_username
                ),
                "title": (
                    existing.get("title")
                    or fetched_title
                )
            }

        return {
            "chat_id": str(
                fetched.get("id")
                or chat_id
            ),
            "username": fetched_username,
            "title": fetched_title
        }

    return {
        "chat_id": (
            str(chat_id)
            if chat_id
            else None
        ),
        "username": username,
        "title": title
    }


# =========================================================
# SOURCE MESSAGE
# =========================================================

def save_source_message(
    message_id,
    title=None,
    link=None,
    source_username=None,
    source_chat_id=None
):

    save_setting(
        "selected_source_message_id",
        message_id
    )

    save_setting(
        "selected_source_title",
        title or ""
    )

    save_setting(
        "selected_source_link",
        link or ""
    )

    save_setting(
        "selected_source_username",
        clean_username(
            source_username
        )
        or ""
    )

    if source_chat_id:

        save_setting(
            "selected_source_chat_id",
            source_chat_id
        )


def get_selected_source():

    return {
        "message_id": get_setting(
            "selected_source_message_id"
        ),
        "title": get_setting(
            "selected_source_title"
        ),
        "link": get_setting(
            "selected_source_link"
        ),
        "username": get_setting(
            "selected_source_username"
        ),
        "chat_id": get_setting(
            "selected_source_chat_id"
        )
    }


# =========================================================
# BALE LINK
# =========================================================

def normalize_bale_link(
    username,
    message_id
):

    username = clean_username(
        username
    )

    if not username:
        return None

    if not message_id:
        return None

    return (
        f"https://ble.ir/"
        f"{username}/"
        f"{message_id}"
    )


def extract_message_link(message):

    if not message:
        return None

    entities = (
        message.get(
            "entities"
        )
        or []
    )

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    for entity in entities:

        if (
            entity.get("type")
            == "text_link"
        ):

            url = entity.get(
                "url"
            )

            if url:

                return url

    urls = re.findall(
        r'https?://[^\s]+',
        text
    )

    for url in urls:

        if (
            "ble.ir" in url
            or "bale.ai" in url
        ):

            return url.rstrip(
                ".,،؛"
            )

    return None


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(message):

    result = {
        "message_id": None,
        "username": None,
        "title": None,
        "link": None,
        "chat_id": None
    }

    if not message:
        return result

    # =====================================================
    # New forward structure
    # =====================================================

    origin = message.get(
        "forward_origin"
    )

    if origin:

        origin_type = origin.get(
            "type"
        )

        if origin_type == "channel":

            result["message_id"] = (
                origin.get(
                    "message_id"
                )
            )

            chat = (
                origin.get("chat")
                or {}
            )

            result["chat_id"] = (
                chat.get("id")
            )

            result["username"] = clean_username(
                chat.get("username")
            )

            result["title"] = (
                chat.get("title")
                or result["username"]
            )

    # =====================================================
    # Old forward structure
    # =====================================================

    if not result["message_id"]:

        forward_from_chat = message.get(
            "forward_from_chat"
        )

        if forward_from_chat:

            result["chat_id"] = (
                forward_from_chat.get(
                    "id"
                )
            )

            result["username"] = clean_username(
                forward_from_chat.get(
                    "username"
                )
            )

            result["title"] = (
                forward_from_chat.get(
                    "title"
                )
                or result["username"]
            )

            result["message_id"] = (
                message.get(
                    "forward_from_message_id"
                )
            )

    # =====================================================
    # Link
    # =====================================================

    if (
        result["username"]
        and result["message_id"]
    ):

        result["link"] = normalize_bale_link(
            result["username"],
            result["message_id"]
        )

    return result


# =========================================================
# PRIVATE FORWARD
# =========================================================

def process_private_forward(message):

    chat = (
        message.get("chat")
        or {}
    )

    chat_id = chat.get(
        "id"
    )

    if not is_admin(chat_id):

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
            "❌ پست فورواردشده معتبر نیست.\n\n"
            "لطفاً پست موردنظر را مستقیماً "
            "از کانال برای ربات Forward کنید."
        )

        return

    source_username = clean_username(
        forward.get("username")
    )

    source_title = (
        forward.get("title")
        or source_username
        or "کانال مرجع"
    )

    source_message_id = forward.get(
        "message_id"
    )

    source_link = forward.get(
        "link"
    )

    source_chat_id = forward.get(
        "chat_id"
    )

    save_source_message(
        message_id=source_message_id,
        title=source_title,
        link=source_link,
        source_username=source_username,
        source_chat_id=source_chat_id
    )

    text = (
        "✅ پست مرجع با موفقیت انتخاب شد.\n\n"
        f"📢 کانال: {source_title}\n"
        f"🆔 Message ID: {source_message_id}\n"
    )

    if source_username:

        text += (
            f"🔹 @{source_username}\n"
        )

    if source_link:

        text += (
            f"🔗 {source_link}\n"
        )

    text += (
        "\nحالا دستور /report را ارسال کنید "
        "تا بازنشرهای همین پست نمایش داده شود."
    )

    send_message(
        chat_id,
        text
    )


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

            "source_channel_id": (
                str(source_channel_id)
                if source_channel_id
                else None
            ),

            "source_username": clean_username(
                source_username
            ),

            "source_message_id": str(
                source_message_id
            ),

            "destination_channel_id": (
                str(destination_channel_id)
                if destination_channel_id
                else None
            ),

            "destination_username": clean_username(
                destination_username
            ),

            "destination_message_id": str(
                destination_message_id
            ),

            "destination_title": (
                destination_title
                or destination_username
                or str(destination_channel_id)
            ),

            "message_title": (
                message_title
                or ""
            ),

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

        return True

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            e
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

    text = text.strip()

    if not text:

        return "بدون عنوان"

    first_line = (
        text.split(
            "\n",
            1
        )[0]
        .strip()
    )

    if len(first_line) > 120:

        first_line = (
            first_line[:117]
            + "..."
        )

    return first_line


# =========================================================
# CHANNEL MESSAGE
# =========================================================

def process_channel_message(message):

    if not message:
        return

    chat = (
        message.get("chat")
        or {}
    )

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

    message_id = message.get(
        "message_id"
    )

    if not message_id:
        return

    # =====================================================
    # Check active channel
    # =====================================================

    active_channels = get_active_channels()

    matched_channel = None

    for channel in active_channels:

        stored_chat_id = str(
            channel.get("chat_id")
            or ""
        )

        stored_username = clean_username(
            channel.get("username")
        )

        if (
            stored_chat_id
            and chat_id
            and stored_chat_id
            == str(chat_id)
        ):

            matched_channel = channel

            break

        if (
            stored_username
            and username
            and stored_username
            == username
        ):

            matched_channel = channel

            break

    if not matched_channel:

        return

    # =====================================================
    # Source
    # =====================================================

    source = get_selected_source()

    source_message_id = source.get(
        "message_id"
    )

    source_username = clean_username(
        source.get("username")
    )

    source_chat_id = source.get(
        "chat_id"
    )

    if not source_message_id:

        return

    # =====================================================
    # Forward
    # =====================================================

    forward = extract_forward(
        message
    )

    forwarded_message_id = (
        forward.get("message_id")
    )

    forwarded_username = clean_username(
        forward.get("username")
    )

    forwarded_chat_id = forward.get(
        "chat_id"
    )

    is_repost = False

    # =====================================================
    # Exact Message ID
    # =====================================================

    if (
        forwarded_message_id
        and str(forwarded_message_id)
        == str(source_message_id)
    ):

        # اگر username منبع مشخص است
        if source_username:

            if (
                forwarded_username
                == source_username
            ):

                is_repost = True

        # اگر chat_id منبع مشخص است
        elif source_chat_id:

            if (
                forwarded_chat_id
                and str(forwarded_chat_id)
                == str(source_chat_id)
            ):

                is_repost = True

        else:

            is_repost = True

    if not is_repost:

        return

    # =====================================================
    # Destination
    # =====================================================

    destination = resolve_destination_channel(
        chat
    )

    if not destination:

        destination = {
            "chat_id": chat_id,
            "username": username,
            "title": title
        }

    destination_chat_id = destination.get(
        "chat_id"
    )

    destination_username = clean_username(
        destination.get("username")
    )

    destination_title = (
        destination.get("title")
        or title
        or destination_username
        or str(destination_chat_id)
    )

    message_title = get_message_title(
        message
    )

    # =====================================================
    # Save
    # =====================================================

    saved = save_repost(
        source_channel_id=source_chat_id,
        source_username=source_username,
        source_message_id=source_message_id,
        destination_channel_id=destination_chat_id,
        destination_username=destination_username,
        destination_message_id=message_id,
        destination_title=destination_title,
        message_title=message_title
    )

    if not saved:

        return

    # =====================================================
    # Alert
    # =====================================================

    alert = (
        "🔔 بازنشر جدید شناسایی شد\n\n"
        f"📢 کانال مقصد: {destination_title}\n"
    )

    if destination_username:

        alert += (
            f"🔹 @{destination_username}\n"
        )

    alert += (
        f"📝 عنوان: {message_title}\n"
        f"🆔 Message ID: {message_id}\n"
        f"🕐 زمان: "
        f"{format_jalali_datetime(datetime.now(timezone.utc).isoformat())}\n"
    )

    if source.get("link"):

        alert += (
            "\n🔗 پست مرجع:\n"
            f"{source.get('link')}\n"
        )

    # =====================================================
    # Send to Owner
    # =====================================================

    recipients = []

    if OWNER_ID:

        recipients.append(
            str(OWNER_ID)
        )

    # =====================================================
    # Send to Admins
    # =====================================================

    for admin in get_admins():

        admin_id = admin.get(
            "user_id"
        )

        if (
            admin_id
            and str(admin_id)
            not in recipients
        ):

            recipients.append(
                str(admin_id)
            )

    for recipient in recipients:

        send_message(
            recipient,
            alert
        )


# =========================================================
# REPORT
# =========================================================

def report_reposts(chat_id):

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    source = get_selected_source()

    source_message_id = source.get(
        "message_id"
    )

    if not source_message_id:

        send_message(
            chat_id,
            "❌ هنوز هیچ پست مرجعی انتخاب نشده است.\n\n"
            "ابتدا پست مرجع را برای ربات Forward کنید."
        )

        return

    source_title = (
        source.get("title")
        or source.get("username")
        or "پست مرجع"
    )

    text = (
        "📊 گزارش بازنشر\n\n"
        "━━━━━━━━━━━━━━\n"
        f"📌 پست مرجع: {source_title}\n"
        f"🆔 Message ID: {source_message_id}\n"
    )

    if source.get("username"):

        text += (
            f"🔹 @{clean_username(source.get('username'))}\n"
        )

    if source.get("link"):

        text += (
            f"🔗 {source.get('link')}\n"
        )

    text += (
        "━━━━━━━━━━━━━━\n\n"
    )

    try:

        query = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_message_id",
                str(source_message_id)
            )
        )

        # اگر source chat id مشخص است
        if source.get("chat_id"):

            query = query.eq(
                "source_channel_id",
                str(source.get("chat_id"))
            )

        result = (
            query
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        reposts = result.data or []

    except Exception as e:

        print(
            "REPORT ERROR:",
            e
        )

        send_message(
            chat_id,
            "❌ دریافت گزارش با خطا مواجه شد."
        )

        return

    if not reposts:

        text += (
            "📭 تاکنون بازنشر ثبت‌شده‌ای "
            "برای این پست وجود ندارد."
        )

        send_message(
            chat_id,
            text
        )

        return

    text += (
        f"🔢 تعداد بازنشر: "
        f"{len(reposts)}\n\n"
    )

    for index, repost in enumerate(
        reposts,
        start=1
    ):

        destination_title = (
            repost.get(
                "destination_title"
            )
            or ""
        )

        destination_username = clean_username(
            repost.get(
                "destination_username"
            )
        )

        destination_chat_id = repost.get(
            "destination_channel_id"
        )

        # =================================================
        # Resolve old records
        # =================================================

        if not destination_title:

            channel = None

            if destination_chat_id:

                channel = get_channel_by_chat_id(
                    destination_chat_id
                )

            if (
                not channel
                and destination_username
            ):

                channel = get_channel_by_username(
                    destination_username
                )

            if channel:

                destination_title = (
                    channel.get("title")
                    or destination_username
                    or str(destination_chat_id)
                )

        if not destination_title:

            destination_title = (
                destination_username
                or str(destination_chat_id)
                or "نامشخص"
            )

        message_title = (
            repost.get(
                "message_title"
            )
            or "بدون عنوان"
        )

        destination_message_id = (
            repost.get(
                "destination_message_id"
            )
        )

        created_at = format_jalali_datetime(
            repost.get(
                "created_at"
            )
        )

        text += (
            f"#{index} "
            f"📢 {destination_title}\n"
        )

        if destination_username:

            text += (
                f"🔹 @{destination_username}\n"
            )

        text += (
            f"📝 {message_title}\n"
            f"🆔 {destination_message_id}\n"
            f"🕐 {created_at}\n"
        )

        if (
            destination_username
            and destination_message_id
        ):

            link = normalize_bale_link(
                destination_username,
                destination_message_id
            )

            if link:

                text += (
                    f"🔗 {link}\n"
                )

        text += "\n"

    send_message(
        chat_id,
        text
    )


# =========================================================
# LIST CHANNELS
# =========================================================

def list_channels(chat_id):

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    channels = get_active_channels()

    text = (
        "📡 کانال‌های تحت مانیتور\n\n"
    )

    if not channels:

        text += (
            "هیچ کانال فعالی ثبت نشده است."
        )

    else:

        for index, channel in enumerate(
            channels,
            start=1
        ):

            title = (
                channel.get("title")
                or channel.get("username")
                or "بدون عنوان"
            )

            username = clean_username(
                channel.get("username")
            )

            text += (
                f"{index}. 📢 {title}\n"
            )

            if username:

                text += (
                    f"   🔹 @{username}\n"
                )

            if channel.get("chat_id"):

                text += (
                    f"   🆔 {channel.get('chat_id')}\n"
                )

            text += "\n"

    send_message(
        chat_id,
        text
    )


# =========================================================
# ADD CHANNEL
# =========================================================

def command_add_channel(
    chat_id,
    argument
):

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    username = clean_username(
        argument
    )

    if not username:

        send_message(
            chat_id,
            "❌ Username کانال را وارد کنید.\n\n"
            "مثال:\n"
            "/addchannel @example"
        )

        return

    channel_chat = get_chat(
        f"@{username}"
    )

    title = username
    channel_id = None

    if channel_chat:

        title = (
            channel_chat.get("title")
            or username
        )

        channel_id = channel_chat.get(
            "id"
        )

    success = add_channel(
        username=username,
        title=title,
        chat_id=channel_id
    )

    if not success:

        send_message(
            chat_id,
            "❌ افزودن کانال انجام نشد."
        )

        return

    text = (
        "✅ کانال با موفقیت اضافه شد.\n\n"
        f"📢 {title}\n"
        f"🔹 @{username}\n"
    )

    if channel_id:

        text += (
            f"🆔 {channel_id}\n"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# REMOVE CHANNEL
# =========================================================

def command_remove_channel(
    chat_id,
    argument
):

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    username = clean_username(
        argument
    )

    if not username:

        send_message(
            chat_id,
            "❌ Username کانال را وارد کنید.\n\n"
            "مثال:\n"
            "/removechannel @example"
        )

        return

    success = remove_channel(
        username
    )

    if not success:

        send_message(
            chat_id,
            "❌ حذف کانال انجام نشد."
        )

        return

    send_message(
        chat_id,
        f"✅ کانال @{username} از مانیتور خارج شد."
    )


# =========================================================
# SOURCE COMMAND
# =========================================================

def command_source(
    chat_id,
    argument
):

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    username = clean_username(
        argument
    )

    if not username:

        send_message(
            chat_id,
            "❌ Username کانال مرجع را وارد کنید.\n\n"
            "مثال:\n"
            "/source @example"
        )

        return

    channel = get_channel_by_username(
        username
    )

    title = username
    channel_id = None

    if channel:

        title = (
            channel.get("title")
            or username
        )

        channel_id = channel.get(
            "chat_id"
        )

    else:

        channel_chat = get_chat(
            f"@{username}"
        )

        if channel_chat:

            title = (
                channel_chat.get("title")
                or username
            )

            channel_id = channel_chat.get(
                "id"
            )

    save_setting(
        "source_channel_username",
        username
    )

    if channel_id:

        save_setting(
            "source_channel_id",
            channel_id
        )

    send_message(
        chat_id,
        "✅ کانال مرجع تعیین شد.\n\n"
        f"📢 {title}\n"
        f"🔹 @{username}\n\n"
        "اکنون پست موردنظر را از همین کانال "
        "برای ربات Forward کنید."
    )


# =========================================================
# STATUS
# =========================================================

def status_command(chat_id):

    if not is_admin(chat_id):

        deny_access(
            chat_id
        )

        return

    channels = get_active_channels()

    source = get_selected_source()

    admins = get_admins()

    text = (
        "🤖 وضعیت ربات\n\n"
        "━━━━━━━━━━━━━━\n"
        f"📡 کانال‌های فعال: {len(channels)}\n"
        f"🛡 Adminها: {len(admins)}\n"
    )

    if OWNER_ID:

        text += (
            "👑 Owner: تنظیم شده\n"
        )

    else:

        text += (
            "⚠️ Owner: تنظیم نشده\n"
        )

    text += (
        "\n━━━━━━━━━━━━━━\n"
    )

    if source.get("message_id"):

        text += (
            "\n📌 پست مرجع فعلی:\n"
            f"🆔 {source.get('message_id')}\n"
        )

        if source.get("title"):

            text += (
                f"📢 {source.get('title')}\n"
            )

        if source.get("link"):

            text += (
                f"🔗 {source.get('link')}\n"
            )

    else:

        text += (
            "\n📌 پست مرجع: انتخاب نشده"
        )

    send_message(
        chat_id,
        text
    )


# =========================================================
# START
# =========================================================

def start_message(chat_id):

    # =====================================================
    # User عادی هیچ منوی مدیریتی نمی‌گیرد
    # =====================================================

    if not is_admin(chat_id):

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

        "/myid\n"
        "نمایش User ID\n"
    )

    # =====================================================
    # Owner
    # =====================================================

    if is_owner(chat_id):

        text += (
            "\n━━━━━━━━━━━━━━\n\n"

            "👑 مدیریت Adminها:\n\n"

            "/addadmin 123456789\n"
            "افزودن Admin با User ID\n\n"

            "/addadmin @username\n"
            "افزودن Admin با Username\n\n"

            "/removeadmin 123456789\n"
            "حذف Admin\n\n"

            "/listadmins\n"
            "نمایش Adminها\n"
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

    text = text.strip()

    parts = text.split()

    if not parts:
        return

    command = parts[0].lower()

    if "@" in command:

        command = command.split(
            "@",
            1
        )[0]

    argument = ""

    if len(parts) > 1:

        argument = " ".join(
            parts[1:]
        ).strip()

    # =====================================================
    # /myid
    #
    # این دستور برای همه آزاد است
    # =====================================================

    if command == "/myid":

        show_my_id(
            chat_id
        )

        return

    # =====================================================
    # امنیت
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

        start_message(
            chat_id
        )

        return

    # =====================================================
    # SOURCE
    # =====================================================

    if command == "/source":

        command_source(
            chat_id,
            argument
        )

        return

    # =====================================================
    # ADD CHANNEL
    # =====================================================

    if command == "/addchannel":

        command_add_channel(
            chat_id,
            argument
        )

        return

    # =====================================================
    # REMOVE CHANNEL
    # =====================================================

    if command == "/removechannel":

        command_remove_channel(
            chat_id,
            argument
        )

        return

    # =====================================================
    # LIST CHANNELS
    # =====================================================

    if command == "/listchannels":

        list_channels(
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
    # STATUS
    # =====================================================

    if command == "/status":

        status_command(
            chat_id
        )

        return

    # =====================================================
    # ADD ADMIN
    # =====================================================

    if command == "/addadmin":

        command_add_admin(
            chat_id,
            argument
        )

        return

    # =====================================================
    # REMOVE ADMIN
    # =====================================================

    if command == "/removeadmin":

        command_remove_admin(
            chat_id,
            argument
        )

        return

    # =====================================================
    # LIST ADMINS
    # =====================================================

    if command == "/listadmins":

        command_list_admins(
            chat_id
        )

        return

    # =====================================================
    # UNKNOWN
    # =====================================================

    send_message(
        chat_id,
        "❓ دستور ناشناخته است.\n\n"
        "برای مشاهده دستورات:\n"
        "/start"
    )


# =========================================================
# UPDATE PROCESSOR
# =========================================================

def process_update(update):

    if not update:
        return

    message = update.get(
        "message"
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

    if chat_id is None:
        return

    # =====================================================
    # مهم:
    # هر کاربری که با ربات تعامل می‌کند ثبت می‌شود
    # =====================================================

    save_bot_user(
        chat
    )

    chat_type = chat.get(
        "type"
    )

    # =====================================================
    # PRIVATE
    # =====================================================

    if chat_type == "private":

        text = (
            message.get("text")
            or ""
        )

        # =================================================
        # /myid برای همه کاربران
        #
        # این قسمت باید قبل از is_admin باشد
        # =================================================

        first_command = ""

        if text.strip():

            first_command = (
                text
                .strip()
                .split()[0]
                .lower()
            )

            if "@" in first_command:

                first_command = (
                    first_command
                    .split("@", 1)[0]
                )

        if first_command == "/myid":

            show_my_id(
                chat_id
            )

            return

        # =================================================
        # بعد از /myid:
        # فقط Admin / Owner
        # =================================================

        if not is_admin(chat_id):

            deny_access(
                chat_id
            )

            return

        # =================================================
        # Forward
        # =================================================

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

        # =================================================
        # Commands
        # =================================================

        if text:

            process_command(
                chat_id,
                text,
                chat.get("username")
            )

        return

    # =====================================================
    # CHANNEL
    # =====================================================

    if chat_type == "channel":

        process_channel_message(
            message
        )

        return


# =========================================================
# POLLING
# =========================================================

def run_polling():

    print(
        "=========================================="
    )

    print(
        "BALE REPOST MONITOR STARTED"
    )

    print(
        "OWNER_ID:",
        OWNER_ID
    )

    print(
        "=========================================="
    )

    offset = None

    while True:

        try:

            payload = {
                "timeout": 50
            }

            if offset is not None:

                payload["offset"] = offset

            result = bale(
                "getUpdates",
                payload,
                timeout=60
            )

            if not result:

                time.sleep(2)

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
                        "PROCESS UPDATE ERROR:",
                        e
                    )

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "POLLING ERROR:",
                e
            )

            time.sleep(5)


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    run_polling()
