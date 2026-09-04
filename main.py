import os
import time
import html
import requests
from datetime import datetime

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


# =========================================================
# GLOBAL
# =========================================================

BOT_ID = None
BOT_USERNAME = None

OFFSET = None

ADMIN_CACHE = set()

# جلوگیری از اجرای همزمان چند عملیات
PROCESSING_UPDATES = set()


# =========================================================
# BALE API
# =========================================================

def bale_request(method, data=None, timeout=40):

    url = f"{BALE_API}/{method}"

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=timeout
        )

        response.raise_for_status()

        result = response.json()

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
            e
        )

        return None


# =========================================================
# BOT INFO
# =========================================================

def get_me():

    result = bale_request(
        "getMe",
        {},
        timeout=20
    )

    if not result:
        return None

    return result


def initialize_bot():

    global BOT_ID
    global BOT_USERNAME

    me = get_me()

    if not me:
        raise Exception(
            "Cannot get bot information"
        )

    BOT_ID = str(me.get("id"))

    BOT_USERNAME = me.get("username")

    print(
        "BOT:",
        BOT_ID,
        BOT_USERNAME
    )


# =========================================================
# UPDATES
# =========================================================

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
# BASIC HELPERS
# =========================================================

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

    return html.escape(
        str(value)
    )


def chat_type_allowed(chat):

    if not chat:
        return False

    return chat.get("type") in (
        "group",
        "supergroup",
        "channel"
    )


def get_chat_id(chat):

    if not chat:
        return None

    chat_id = chat.get("id")

    if chat_id is None:
        return None

    return str(chat_id)


def get_chat_title(chat):

    if not chat:
        return ""

    return (
        chat.get("title")
        or chat.get("first_name")
        or chat.get("username")
        or ""
    )


# =========================================================
# BALE MESSAGE LINK
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

    return (
        f"https://ble.ir/"
        f"{username}/"
        f"{chat_id}/"
        f"{message_id}"
    )


# =========================================================
# SEND MESSAGE
# =========================================================

def send_message(
    chat_id,
    text,
    reply_markup=None
):

    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return bale_request(
        "sendMessage",
        data
    )


# =========================================================
# SUPABASE HELPERS
# =========================================================

def get_admins():

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("user_id")
            .execute()
        )

        rows = result.data or []

        return {
            str(row["user_id"])
            for row in rows
            if row.get("user_id") is not None
        }

    except Exception as e:

        print(
            "get_admins ERROR:",
            e
        )

        return set()


def is_admin(user_id):

    if user_id is None:
        return False

    user_id = str(user_id)

    global ADMIN_CACHE

    if not ADMIN_CACHE:
        ADMIN_CACHE = get_admins()

    return user_id in ADMIN_CACHE


def refresh_admin_cache():

    global ADMIN_CACHE

    ADMIN_CACHE = get_admins()


# =========================================================
# OWNER
# =========================================================

def get_owner_id():

    try:

        result = (
            supabase
            .table("bot_settings")
            .select("value")
            .eq("key", "owner_id")
            .limit(1)
            .execute()
        )

        rows = result.data or []

        if rows:
            return str(
                rows[0].get("value")
            )

    except Exception as e:

        print(
            "get_owner_id ERROR:",
            e
        )

    return None


def is_owner(user_id):

    owner_id = get_owner_id()

    if not owner_id:
        return False

    return str(user_id) == str(owner_id)


# =========================================================
# USER
# =========================================================

def save_user(user):

    if not user:
        return

    user_id = user.get("id")

    if user_id is None:
        return

    try:

        data = {
            "user_id": str(user_id),
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name")
        }

        supabase \
            .table("bot_users") \
            .upsert(
                data,
                on_conflict="user_id"
            ) \
            .execute()

    except Exception as e:

        print(
            "save_user ERROR:",
            e
        )


# =========================================================
# CHANNEL DATABASE
# =========================================================

def find_channel_by_chat_id(chat_id):

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

        rows = result.data or []

        if rows:
            return rows[0]

    except Exception as e:

        print(
            "find_channel_by_chat_id ERROR:",
            e
        )

    return None


def find_channel_by_username(username):

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
            .eq("username", username)
            .limit(1)
            .execute()
        )

        rows = result.data or []

        if rows:
            return rows[0]

    except Exception as e:

        print(
            "find_channel_by_username ERROR:",
            e
        )

    return None


# =========================================================
# AUTO REGISTER CHAT
# =========================================================

def auto_register_chat(chat):

    """
    این تابع فقط وظیفه دارد چتی را که واقعاً
    در یک Update از بله دیده‌ایم، داخل DB ثبت کند.

    نکته مهم:
    پیام عادی نباید چتی را که قبلاً توسط ادمین حذف شده
    یا ربات از آن خارج شده دوباره فعال کند.
    """

    if not chat_type_allowed(chat):
        return None

    chat_id = get_chat_id(chat)

    if not chat_id:
        return None

    username = clean_username(
        chat.get("username")
    )

    title = get_chat_title(chat)

    existing = find_channel_by_chat_id(
        chat_id
    )

    # -----------------------------------------------------
    # اگر با chat_id پیدا نشد، username را هم بررسی کن
    # -----------------------------------------------------

    if not existing and username:

        existing = find_channel_by_username(
            username
        )

        # اگر با username پیدا شد ولی chat_id قبلی فرق دارد،
        # رکورد همان کانال را اصلاح می‌کنیم.
        if existing:

            try:

                update_data = {
                    "chat_id": chat_id,
                    "title": title,
                    "username": username
                }

                supabase \
                    .table("channels") \
                    .update(update_data) \
                    .eq(
                        "id",
                        existing["id"]
                    ) \
                    .execute()

                existing.update(
                    update_data
                )

            except Exception as e:

                print(
                    "auto_register_chat UPDATE ERROR:",
                    e
                )

    # -----------------------------------------------------
    # رکورد جدید
    # -----------------------------------------------------

    if not existing:

        data = {
            "chat_id": chat_id,
            "username": username,
            "title": title,
            "active": True,
            "manually_disabled": False,
            "bot_member": True
        }

        try:

            result = (
                supabase
                .table("channels")
                .insert(data)
                .execute()
            )

            rows = result.data or []

            if rows:
                print(
                    "NEW CHAT REGISTERED:",
                    chat_id,
                    title
                )

                return rows[0]

        except Exception as e:

            print(
                "auto_register_chat INSERT ERROR:",
                e
            )

        return None

    # -----------------------------------------------------
    # رکورد موجود
    # -----------------------------------------------------

    manually_disabled = bool(
        existing.get(
            "manually_disabled",
            False
        )
    )

    bot_member = existing.get(
        "bot_member"
    )

    # اگر bot_member قبلاً False بوده،
    # پیام عادی نباید آن را دوباره فعال کند.
    if bot_member is False:

        try:

            update_data = {
                "title": title,
                "username": username
            }

            supabase \
                .table("channels") \
                .update(update_data) \
                .eq(
                    "id",
                    existing["id"]
                ) \
                .execute()

        except Exception as e:

            print(
                "auto_register_chat UPDATE EXISTING ERROR:",
                e
            )

        existing.update({
            "title": title,
            "username": username
        })

        return existing

    # اگر مدیر دستی حذف کرده،
    # پیام عادی حق فعال کردن مجدد را ندارد.
    if manually_disabled:

        try:

            update_data = {
                "title": title,
                "username": username
            }

            supabase \
                .table("channels")
                .update(update_data)
                .eq(
                    "id",
                    existing["id"]
                )
                .execute()

            existing.update(
                update_data
            )

        except Exception as e:

            print(
                "auto_register_chat MANUAL DISABLED ERROR:",
                e
            )

        return existing

    # در حالت عادی اطلاعات چت را به‌روز می‌کنیم.
    try:

        update_data = {
            "title": title,
            "username": username,
            "active": True,
            "bot_member": True
        }

        supabase \
            .table("channels") \
            .update(update_data) \
            .eq(
                "id",
                existing["id"]
            ) \
            .execute()

        existing.update(
            update_data
        )

    except Exception as e:

        print(
            "auto_register_chat NORMAL UPDATE ERROR:",
            e
        )

    return existing


# =========================================================
# ACTIVATE CHAT
# =========================================================

def activate_chat(
    chat,
    clear_manual=True
):

    if not chat_type_allowed(chat):
        return False

    chat_id = get_chat_id(chat)

    if not chat_id:
        return False

    username = clean_username(
        chat.get("username")
    )

    title = get_chat_title(chat)

    existing = find_channel_by_chat_id(
        chat_id
    )

    if not existing and username:

        existing = find_channel_by_username(
            username
        )

    data = {
        "chat_id": chat_id,
        "username": username,
        "title": title,
        "active": True,
        "bot_member": True
    }

    if clear_manual:
        data["manually_disabled"] = False

    try:

        if existing:

            supabase \
                .table("channels") \
                .update(data) \
                .eq(
                    "id",
                    existing["id"]
                ) \
                .execute()

        else:

            supabase \
                .table("channels") \
                .insert(data) \
                .execute()

        print(
            "CHAT ACTIVATED:",
            chat_id,
            title
        )

        return True

    except Exception as e:

        print(
            "activate_chat ERROR:",
            e
        )

        return False


# =========================================================
# DEACTIVATE CHAT
# =========================================================

def deactivate_chat(chat_id):

    if chat_id is None:
        return False

    chat_id = str(chat_id)

    try:

        result = (
            supabase
            .table("channels")
            .select("id")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )

        rows = result.data or []

        if not rows:
            return False

        channel_id = rows[0]["id"]

        supabase \
            .table("channels") \
            .update({
                "active": False,
                "bot_member": False
            }) \
            .eq(
                "id",
                channel_id
            ) \
            .execute()

        print(
            "CHAT DEACTIVATED:",
            chat_id
        )

        return True

    except Exception as e:

        print(
            "deactivate_chat ERROR:",
            e
        )

        return False


# =========================================================
# MANUAL ADD
# =========================================================

def manual_activate_channel(
    chat_id,
    username=None,
    title=None
):

    data = {
        "chat_id": str(chat_id),
        "username": clean_username(username),
        "title": title or "",
        "active": True,
        "manually_disabled": False,
        "bot_member": True
    }

    try:

        existing = find_channel_by_chat_id(
            chat_id
        )

        if existing:

            supabase \
                .table("channels") \
                .update(data) \
                .eq(
                    "id",
                    existing["id"]
                ) \
                .execute()

        else:

            supabase \
                .table("channels") \
                .insert(data) \
                .execute()

        return True

    except Exception as e:

        print(
            "manual_activate_channel ERROR:",
            e
        )

        return False


# =========================================================
# MANUAL REMOVE
# =========================================================

def manual_disable_channel(
    chat_id
):

    if chat_id is None:
        return False

    try:

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

        rows = result.data or []

        if not rows:
            return False

        channel_id = rows[0]["id"]

        supabase \
            .table("channels") \
            .update({
                "active": False,
                "manually_disabled": True
            }) \
            .eq(
                "id",
                channel_id
            ) \
            .execute()

        return True

    except Exception as e:

        print(
            "manual_disable_channel ERROR:",
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
            .order(
                "id",
                desc=False
            )
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "get_channels ERROR:",
            e
        )

        return []


# =========================================================
# SYNC KNOWN CHANNELS
# =========================================================

def sync_channels():

    """
    فقط کانال‌ها/گروه‌هایی که قبلاً در DB ثبت شده‌اند
    قابل بررسی هستند.

    این تابع نمی‌تواند چتی را که هیچ‌وقت Update آن
    دریافت نشده، کشف کند.
    """

    global BOT_ID

    if not BOT_ID:
        initialize_bot()

    channels = get_channels()

    checked = 0
    active = 0
    removed = 0

    for channel in channels:

        chat_id = channel.get("chat_id")

        if not chat_id:
            continue

        checked += 1

        try:

            member = bale_request(
                "getChatMember",
                {
                    "chat_id": chat_id,
                    "user_id": BOT_ID
                },
                timeout=20
            )

            if not member:
                continue

            status = member.get("status")

            print(
                "SYNC:",
                chat_id,
                status
            )

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                if not channel.get(
                    "manually_disabled",
                    False
                ):

                    supabase \
                        .table("channels") \
                        .update({
                            "active": True,
                            "bot_member": True
                        }) \
                        .eq(
                            "id",
                            channel["id"]
                        ) \
                        .execute()

                    active += 1

            elif status in (
                "left",
                "kicked"
            ):

                supabase \
                    .table("channels") \
                    .update({
                        "active": False,
                        "bot_member": False
                    }) \
                    .eq(
                        "id",
                        channel["id"]
                    ) \
                    .execute()

                removed += 1

        except Exception as e:

            print(
                "SYNC CHANNEL ERROR:",
                chat_id,
                e
            )

    return {
        "checked": checked,
        "active": active,
        "removed": removed
    }


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(message):

    if not message:
        return None

    source_chat = (
        message.get("forward_from_chat")
        or message.get("sender_chat")
    )

    if not source_chat:
        return None

    source_chat_id = source_chat.get("id")

    source_username = clean_username(
        source_chat.get("username")
    )

    source_title = (
        source_chat.get("title")
        or source_chat.get("first_name")
        or source_username
        or ""
    )

    source_message_id = (
        message.get("forward_from_message_id")
        or message.get("forwarded_message_id")
        or message.get("forward_message_id")
    )

    source_link = (
        message.get("forward_link")
        or message.get("message_link")
        or message.get("link")
    )

    if not source_link:

        source_link = build_bale_message_link(
            source_username,
            source_chat_id,
            source_message_id
        )

    return {
        "source_chat_id": (
            str(source_chat_id)
            if source_chat_id is not None
            else None
        ),
        "source_username": source_username,
        "source_title": source_title,
        "source_message_id": source_message_id,
        "source_message_link": source_link
    }


# =========================================================
# SELECTED SOURCE
# =========================================================

def set_selected_source(
    user_id,
    source
):

    if not source:
        return False

    data = {
        "user_id": str(user_id),
        "selected_source_channel_id":
            source.get("source_chat_id"),
        "selected_source_message_id":
            source.get("source_message_id"),
        "selected_source_username":
            source.get("source_username"),
        "selected_source_title":
            source.get("source_title"),
        "selected_source_message_link":
            source.get("source_message_link")
    }

    try:

        supabase \
            .table("bot_users") \
            .upsert(
                data,
                on_conflict="user_id"
            ) \
            .execute()

        return True

    except Exception as e:

        print(
            "set_selected_source ERROR:",
            e
        )

        return False


def get_selected_source(user_id):

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

        rows = result.data or []

        if not rows:
            return None

        row = rows[0]

        source_chat_id = row.get(
            "selected_source_channel_id"
        )

        source_message_id = row.get(
            "selected_source_message_id"
        )

        source_username = clean_username(
            row.get(
                "selected_source_username"
            )
        )

        source_link = row.get(
            "selected_source_message_link"
        )

        if not source_link:

            source_link = build_bale_message_link(
                source_username,
                source_chat_id,
                source_message_id
            )

        return {
            "source_chat_id":
                source_chat_id,
            "source_message_id":
                source_message_id,
            "source_username":
                source_username,
            "source_title":
                row.get(
                    "selected_source_title"
                ),
            "source_message_link":
                source_link
        }

    except Exception as e:

        print(
            "get_selected_source ERROR:",
            e
        )

        return None


# =========================================================
# DUPLICATE CHECK
# =========================================================

def repost_exists(
    source_channel_id,
    source_message_id,
    destination_channel_id
):

    if not source_channel_id:
        return False

    if not source_message_id:
        return False

    if not destination_channel_id:
        return False

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
            "repost_exists ERROR:",
            e
        )

        return False


# =========================================================
# SAVE REPOST
# =========================================================

def save_repost(
    source_channel_id,
    source_message_id,
    destination_channel_id,
    source_message_link=None,
    destination_message_id=None
):

    data = {
        "source_channel_id":
            str(source_channel_id)
            if source_channel_id is not None
            else None,

        "source_message_id":
            str(source_message_id)
            if source_message_id is not None
            else None,

        "destination_channel_id":
            str(destination_channel_id)
            if destination_channel_id is not None
            else None,

        "source_message_link":
            source_message_link,

        "destination_message_id":
            str(destination_message_id)
            if destination_message_id is not None
            else None
    }

    try:

        supabase \
            .table("reposts") \
            .insert(data) \
            .execute()

        return True

    except Exception as e:

        print(
            "save_repost ERROR:",
            e
        )

        return False


# =========================================================
# MEMBERSHIP UPDATE
# =========================================================

def handle_bot_membership_update(update):

    """
    برخی نسخه‌ها/کتابخانه‌های بله ممکن است اطلاعات
    تغییر عضویت را با کلیدهای membership ارسال کنند.

    این تابع چند ساختار احتمالی را بررسی می‌کند.
    """

    chat_member_update = (
        update.get("my_chat_member")
        or update.get("chat_member")
        or update.get("bot_chat_member")
    )

    if not chat_member_update:
        return False

    chat = chat_member_update.get(
        "chat"
    )

    new_member = chat_member_update.get(
        "new_chat_member"
    )

    if not chat or not new_member:
        return False

    if not chat_type_allowed(chat):
        return False

    user = new_member.get(
        "user"
    ) or new_member

    user_id = user.get("id")

    if BOT_ID and str(user_id) != str(BOT_ID):
        return False

    status = new_member.get(
        "status"
    )

    print(
        "MEMBERSHIP EVENT:",
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

        return True

    if status in (
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

def handle_group_service_message(
    message
):

    if not message:
        return False

    chat = message.get("chat")

    if not chat:
        return False

    # -----------------------------------------------------
    # ربات به گروه اضافه شده
    # -----------------------------------------------------

    new_members = (
        message.get(
            "new_chat_members"
        )
        or []
    )

    for member in new_members:

        member_id = member.get(
            "id"
        )

        if BOT_ID and str(member_id) == str(BOT_ID):

            print(
                "BOT ADDED TO CHAT:",
                chat.get("id"),
                chat.get("title")
            )

            activate_chat(
                chat,
                clear_manual=True
            )

            return True

    # -----------------------------------------------------
    # ربات از گروه حذف شده
    # -----------------------------------------------------

    left_member = message.get(
        "left_chat_member"
    )

    if left_member:

        left_id = left_member.get(
            "id"
        )

        if BOT_ID and str(left_id) == str(BOT_ID):

            print(
                "BOT REMOVED FROM CHAT:",
                chat.get("id"),
                chat.get("title")
            )

            deactivate_chat(
                chat.get("id")
            )

            return True

    return False


# =========================================================
# PRIVATE MESSAGE
# =========================================================

def process_private_message(
    message
):

    user = message.get(
        "from"
    )

    if user:
        save_user(user)

    user_id = (
        user.get("id")
        if user
        else message.get("chat", {}).get("id")
    )

    if user_id is None:
        return

    text = (
        message.get("text")
        or ""
    ).strip()

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    if text == "/start":

        send_message(
            user_id,
            (
                "سلام 👋\n\n"
                "به ربات مدیریت بازنشر خوش آمدید.\n\n"
                "از منوی زیر استفاده کنید."
            ),
            get_main_keyboard(
                user_id
            )
        )

        return

    # -----------------------------------------------------
    # MY ID
    # -----------------------------------------------------

    if text == "/myid":

        send_message(
            user_id,
            f"🆔 شناسه شما:\n<code>{user_id}</code>"
        )

        return

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    if text == "/report":

        send_report(
            user_id
        )

        return

    # -----------------------------------------------------
    # CHANNELS
    # -----------------------------------------------------

    if text == "/channels":

        send_channels(
            user_id
        )

        return

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if text == "/status":

        send_status(
            user_id
        )

        return

    # -----------------------------------------------------
    # SYNC
    # -----------------------------------------------------

    if text == "/syncchannels":

        if not is_admin(user_id):

            send_message(
                user_id,
                "⛔ شما دسترسی لازم را ندارید."
            )

            return

        result = sync_channels()

        send_message(
            user_id,
            (
                "🔄 همگام‌سازی انجام شد.\n\n"
                f"بررسی‌شده: {result['checked']}\n"
                f"فعال: {result['active']}\n"
                f"خارج‌شده: {result['removed']}"
            )
        )

        return

    # -----------------------------------------------------
    # ADMINS
    # -----------------------------------------------------

    if text == "/admins":

        if not is_owner(user_id):

            send_message(
                user_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return

        send_admins(
            user_id
        )

        return

    # -----------------------------------------------------
    # FORWARDED SOURCE
    # -----------------------------------------------------

    source = extract_forward(
        message
    )

    if source:

        if set_selected_source(
            user_id,
            source
        ):

            link = (
                source.get(
                    "source_message_link"
                )
            )

            if link:

                send_message(
                    user_id,
                    (
                        "✅ پست مبدأ انتخاب شد.\n\n"
                        f"🔵 <a href=\"{html.escape(link, quote=True)}\">"
                        "مشاهده پست مبدأ"
                        "</a>"
                    )
                )

            else:

                send_message(
                    user_id,
                    (
                        "✅ پست مبدأ انتخاب شد.\n\n"
                        "⚠️ لینک مستقیم این پست از اطلاعات "
                        "ارسال‌شده توسط بله قابل استخراج نبود."
                    )
                )

        return

    # -----------------------------------------------------
    # KEYBOARD
    # -----------------------------------------------------

    if text == "📡 کانال‌ها و گروه‌ها":

        send_channels(
            user_id
        )

        return

    if text == "📊 گزارش بازنشر":

        send_report(
            user_id
        )

        return

    if text == "📈 وضعیت ربات":

        send_status(
            user_id
        )

        return

    if text == "🔄 همگام‌سازی":

        if not is_admin(user_id):

            send_message(
                user_id,
                "⛔ دسترسی ندارید."
            )

            return

        result = sync_channels()

        send_message(
            user_id,
            (
                "🔄 همگام‌سازی انجام شد.\n\n"
                f"تعداد بررسی‌شده: "
                f"{result['checked']}\n"
                f"فعال: {result['active']}\n"
                f"غیرفعال‌شده: "
                f"{result['removed']}"
            )
        )

        return

    if text == "🆔 شناسه من":

        send_message(
            user_id,
            f"🆔 شناسه شما:\n<code>{user_id}</code>"
        )

        return

    if text == "❓ راهنما":

        send_help(
            user_id
        )

        return

    if text == "➕ افزودن مقصد":

        send_message(
            user_id,
            (
                "➕ برای افزودن مقصد، ربات را به "
                "گروه یا کانال موردنظر اضافه کنید.\n\n"
                "بعد از دریافت اولین Update، مقصد "
                "به‌صورت خودکار شناسایی می‌شود."
            )
        )

        return

    if text == "➖ حذف مقصد":

        send_message(
            user_id,
            (
                "➖ برای حذف مقصد باید شناسه chat آن "
                "را ارسال کنید.\n\n"
                "مثال:\n"
                "/removechannel 123456789"
            )
        )

        return


# =========================================================
# MAIN CHANNEL MESSAGE
# =========================================================

def process_channel_message(
    message
):

    chat = message.get(
        "chat"
    )

    if not chat:
        return

    if not chat_type_allowed(chat):
        return

    # -----------------------------------------------------
    # اول چت را ثبت/به‌روز می‌کنیم
    # -----------------------------------------------------

    channel = auto_register_chat(
        chat
    )

    if not channel:
        return

    # -----------------------------------------------------
    # بررسی وضعیت
    # -----------------------------------------------------

    if channel.get(
        "manually_disabled",
        False
    ):

        print(
            "SKIP MANUALLY DISABLED:",
            chat.get("id")
        )

        return

    if channel.get(
        "bot_member"
    ) is False:

        print(
            "SKIP BOT NOT MEMBER:",
            chat.get("id")
        )

        return

    if channel.get(
        "active"
    ) is not True:

        return

    # -----------------------------------------------------
    # فعلاً فقط مقصدهایی که در DB فعال هستند
    # -----------------------------------------------------

    source_message = (
        message
    )

    # -----------------------------------------------------
    # ارسال پیام از کانال مقصد
    # -----------------------------------------------------
    #
    # این بخش بر اساس ساختار قبلی ربات شماست:
    # مقصدی که پیام از آن دریافت شده، خودش را به عنوان
    # مقصد در نظر می‌گیرد.
    #
    # برای انتخاب source از bot_users استفاده می‌کنیم.
    #

    source = None

    # چون پیام کانال خودش منبع بازنشر نیست،
    # بازنشر از source انتخاب‌شده انجام می‌شود.
    #
    # این قسمت در صورت استفاده از forward/copy باید
    # با منطق قبلی شما هماهنگ شود.

    return


# =========================================================
# CHANNEL LIST
# =========================================================

def send_channels(
    user_id
):

    if not is_admin(user_id):

        send_message(
            user_id,
            "⛔ دسترسی ندارید."
        )

        return

    channels = get_channels()

    if not channels:

        send_message(
            user_id,
            (
                "📡 هیچ کانال یا گروهی ثبت نشده است.\n\n"
                "ربات را به یک گروه یا کانال اضافه کنید."
            )
        )

        return

    lines = [
        "📡 <b>کانال‌ها و گروه‌ها</b>",
        ""
    ]

    for index, channel in enumerate(
        channels,
        start=1
    ):

        title = safe_text(
            channel.get("title")
            or "بدون نام"
        )

        username = clean_username(
            channel.get("username")
        )

        chat_id = channel.get(
            "chat_id"
        )

        active = channel.get(
            "active"
        )

        bot_member = channel.get(
            "bot_member"
        )

        manually_disabled = channel.get(
            "manually_disabled"
        )

        if active and bot_member:
            status = "🟢 فعال"

        elif manually_disabled:
            status = "🟡 حذف دستی"

        elif bot_member is False:
            status = "🔴 ربات خارج شده"

        else:
            status = "⚪ غیرفعال"

        lines.append(
            f"{index}. {title}"
        )

        if username:
            lines.append(
                f"   @{safe_text(username)}"
            )

        lines.append(
            f"   🆔 <code>{safe_text(chat_id)}</code>"
        )

        lines.append(
            f"   وضعیت: {status}"
        )

        lines.append("")

    send_message(
        user_id,
        "\n".join(lines)
    )


# =========================================================
# STATUS
# =========================================================

def send_status(
    user_id
):

    if not is_admin(user_id):

        send_message(
            user_id,
            "⛔ دسترسی ندارید."
        )

        return

    channels = get_channels()

    total = len(channels)

    active = sum(
        1
        for c in channels
        if c.get("active")
        and c.get("bot_member")
    )

    inactive = total - active

    admins = get_admins()

    send_message(
        user_id,
        (
            "📈 <b>وضعیت ربات</b>\n\n"
            f"🤖 Bot ID: "
            f"<code>{safe_text(BOT_ID)}</code>\n\n"
            f"📡 کل مقصدها: {total}\n"
            f"🟢 فعال: {active}\n"
            f"🔴 غیرفعال: {inactive}\n"
            f"👤 مدیران: {len(admins)}"
        )
    )


# =========================================================
# REPORT
# =========================================================

def send_report(
    user_id
):

    if not is_admin(user_id):

        send_message(
            user_id,
            "⛔ دسترسی ندارید."
        )

        return

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .order(
                "id",
                desc=True
            )
            .limit(20)
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        print(
            "send_report ERROR:",
            e
        )

        send_message(
            user_id,
            "❌ دریافت گزارش با خطا مواجه شد."
        )

        return

    if not rows:

        send_message(
            user_id,
            "📊 هنوز بازنشری ثبت نشده است."
        )

        return

    lines = [
        "📊 <b>آخرین بازنشرها</b>",
        ""
    ]

    for row in rows:

        source_link = row.get(
            "source_message_link"
        )

        source_channel = row.get(
            "source_channel_id"
        )

        source_message = row.get(
            "source_message_id"
        )

        destination = row.get(
            "destination_channel_id"
        )

        lines.append(
            "━━━━━━━━━━━━━━"
        )

        lines.append(
            f"🔵 مبدأ: "
            f"<code>{safe_text(source_channel)}</code>"
        )

        lines.append(
            f"📝 پیام: "
            f"<code>{safe_text(source_message)}</code>"
        )

        if source_link:

            lines.append(
                f'🔵 <a href="{html.escape(source_link, quote=True)}">'
                "مشاهده پست مبدأ"
                "</a>"
            )

        else:

            lines.append(
                "🔵 مشاهده پست مبدأ: لینک موجود نیست"
            )

        lines.append(
            f"📡 مقصد: "
            f"<code>{safe_text(destination)}</code>"
        )

    send_message(
        user_id,
        "\n".join(lines)
    )


# =========================================================
# HELP
# =========================================================

def send_help(
    user_id
):

    text = (
        "❓ <b>راهنمای ربات</b>\n\n"
        "📡 کانال‌ها و گروه‌ها:\n"
        "مشاهده مقصدهای ثبت‌شده.\n\n"
        "➕ افزودن مقصد:\n"
        "ربات را به گروه یا کانال اضافه کنید.\n\n"
        "➖ حذف مقصد:\n"
        "مقصد را از فهرست فعال خارج می‌کند.\n\n"
        "🔄 همگام‌سازی:\n"
        "وضعیت عضویت ربات در مقصدهای ثبت‌شده را بررسی می‌کند.\n\n"
        "📊 گزارش بازنشر:\n"
        "آخرین بازنشرهای ثبت‌شده را نمایش می‌دهد."
    )

    send_message(
        user_id,
        text
    )


# =========================================================
# ADMIN LIST
# =========================================================

def send_admins(
    user_id
):

    admins = get_admins()

    if not admins:

        send_message(
            user_id,
            "👤 هیچ مدیری ثبت نشده است."
        )

        return

    lines = [
        "⚙️ <b>مدیران ربات</b>",
        ""
    ]

    for admin in admins:

        lines.append(
            f"👤 <code>{safe_text(admin)}</code>"
        )

    send_message(
        user_id,
        "\n".join(lines)
    )


# =========================================================
# KEYBOARD
# =========================================================

def get_main_keyboard(
    user_id
):

    if is_owner(user_id):

        keyboard = [
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
                    "text": "🔄 همگام‌سازی"
                },
                {
                    "text": "📈 وضعیت ربات"
                }
            ],
            [
                {
                    "text": "⚙️ مدیریت مدیران"
                },
                {
                    "text": "❓ راهنما"
                }
            ]
        ]

    elif is_admin(user_id):

        keyboard = [
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
                    "text": "🔄 همگام‌سازی"
                },
                {
                    "text": "📈 وضعیت ربات"
                }
            ],
            [
                {
                    "text": "❓ راهنما"
                }
            ]
        ]

    else:

        keyboard = [
            [
                {
                    "text": "🆔 شناسه من"
                },
                {
                    "text": "❓ راهنما"
                }
            ]
        ]

    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


# =========================================================
# UPDATE PROCESSOR
# =========================================================

def process_update(
    update
):

    if not update:
        return

    print(
        "\n" +
        "=" * 70
    )

    print(
        "NEW UPDATE:",
        update.get("update_id")
    )

    print(
        "UPDATE KEYS:",
        list(update.keys())
    )

    print(
        "=" * 70
    )

    # -----------------------------------------------------
    # 1. membership update
    # -----------------------------------------------------

    try:

        handled = handle_bot_membership_update(
            update
        )

        if handled:
            return

    except Exception as e:

        print(
            "MEMBERSHIP HANDLER ERROR:",
            e
        )

    # -----------------------------------------------------
    # 2. message
    # -----------------------------------------------------

    message = update.get(
        "message"
    )

    # -----------------------------------------------------
    # 3. channel post
    # -----------------------------------------------------

    channel_post = update.get(
        "channel_post"
    )

    # اگر channel_post وجود داشت
    # آن را مثل message پردازش می‌کنیم.
    if channel_post:

        message = channel_post

    if not message:
        return

    chat = message.get(
        "chat"
    )

    if not chat:
        return

    # -----------------------------------------------------
    # 4. گروه
    # -----------------------------------------------------

    if chat.get("type") in (
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
                e
            )

    # -----------------------------------------------------
    # 5. PRIVATE
    # -----------------------------------------------------

    if chat.get("type") == "private":

        process_private_message(
            message
        )

        return

    # -----------------------------------------------------
    # 6. GROUP / SUPERGROUP / CHANNEL
    # -----------------------------------------------------

    if chat.get("type") in (
        "group",
        "supergroup",
        "channel"
    ):

        process_channel_message(
            message
        )


# =========================================================
# MAIN LOOP
# =========================================================

def run():

    global OFFSET

    initialize_bot()

    refresh_admin_cache()

    print(
        "======================================"
    )

    print(
        "BALE REPOST BOT STARTED"
    )

    print(
        "BOT ID:",
        BOT_ID
    )

    print(
        "BOT USERNAME:",
        BOT_USERNAME
    )

    print(
        "======================================"
    )

    while True:

        try:

            updates = get_updates(
                OFFSET
            )

            if not updates:
                continue

            for update in updates:

                update_id = update.get(
                    "update_id"
                )

                if update_id is not None:

                    OFFSET = (
                        int(update_id) + 1
                    )

                try:

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
                "MAIN LOOP ERROR:",
                e
            )

            time.sleep(3)


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    run()
