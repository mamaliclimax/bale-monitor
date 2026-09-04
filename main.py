import os
import time
import requests

from datetime import datetime, timezone

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
# GLOBALS
# =========================================================

OFFSET = None

OWNER_ID = None

SELECTED_SOURCE = {}


# =========================================================
# BASIC HELPERS
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


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

    return str(value).strip()


# =========================================================
# BALE API
# =========================================================

def bale_request(method, data=None):
    url = f"{BALE_API}/{method}"

    try:
        response = requests.post(
            url,
            json=data or {},
            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            print("BALE API ERROR:", method, result)

        return result

    except Exception as e:
        print("BALE REQUEST ERROR:", method, e)
        return {
            "ok": False,
            "description": str(e)
        }


def send_message(chat_id, text):
    if chat_id is None:
        return None

    result = bale_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )

    if result.get("ok"):
        return result.get("result")

    return None


def get_chat(chat_id):
    result = bale_request(
        "getChat",
        {
            "chat_id": chat_id
        }
    )

    if result.get("ok"):
        return result.get("result")

    return None


# =========================================================
# BALE MESSAGE LINK
# =========================================================

def build_bale_message_link(
    username,
    chat_id,
    message_id
):
    """
    لینک صحیح پیام بله

    فرمت:
    https://ble.ir/USERNAME/CHAT_ID/MESSAGE_ID

    نمونه:
    https://ble.ir/bargheiran/3274013777755998022/1788509875302
    """

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
# BOT SETTINGS
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
        print("GET SETTING ERROR:", key, e)

    return None


def set_setting(key, value):
    try:
        data = {
            "key": key,
            "value": str(value)
        }

        (
            supabase
            .table("bot_settings")
            .upsert(
                data,
                on_conflict="key"
            )
            .execute()
        )

        return True

    except Exception as e:
        print("SET SETTING ERROR:", key, e)
        return False


def load_owner():
    global OWNER_ID

    OWNER_ID = get_setting("owner_id")

    if OWNER_ID:
        OWNER_ID = str(OWNER_ID).strip()

    print("OWNER_ID:", OWNER_ID)


def save_selected_source(source):
    global SELECTED_SOURCE

    SELECTED_SOURCE = source or {}

    if source.get("chat_id") is not None:
        set_setting(
            "selected_source_chat_id",
            source["chat_id"]
        )

    if source.get("message_id") is not None:
        set_setting(
            "selected_source_message_id",
            source["message_id"]
        )

    if source.get("username"):
        set_setting(
            "selected_source_username",
            source["username"]
        )

    if source.get("title"):
        set_setting(
            "selected_source_title",
            source["title"]
        )

    if source.get("link"):
        set_setting(
            "selected_source_link",
            source["link"]
        )


def load_selected_source():
    global SELECTED_SOURCE

    chat_id = get_setting(
        "selected_source_chat_id"
    )

    message_id = get_setting(
        "selected_source_message_id"
    )

    username = get_setting(
        "selected_source_username"
    )

    title = get_setting(
        "selected_source_title"
    )

    link = get_setting(
        "selected_source_link"
    )

    if not chat_id or not message_id:
        SELECTED_SOURCE = {}
        return {}

    # اگر لینک قدیمی یا ناقص است،
    # لینک صحیح را دوباره می‌سازیم.
    correct_link = build_bale_message_link(
        username=username,
        chat_id=chat_id,
        message_id=message_id
    )

    SELECTED_SOURCE = {
        "chat_id": chat_id,
        "message_id": message_id,
        "username": username,
        "title": title,
        "link": correct_link or link
    }

    return SELECTED_SOURCE


# =========================================================
# USER TRACKING
# =========================================================

def save_bot_user(chat):
    if not chat:
        return False

    user_id = chat.get("id")

    if not user_id:
        return False

    username = clean_username(
        chat.get("username")
    )

    first_name = chat.get("first_name") or ""
    last_name = chat.get("last_name") or ""

    try:
        data = {
            "user_id": str(user_id),
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "active": True,
            "updated_at": now_iso()
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

        print("USER SAVED:", data)

        return True

    except Exception as e:
        print("SAVE BOT USER ERROR:", e)
        return False


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
        print("IS ADMIN ERROR:", e)
        return False


def deny_access(chat_id):
    send_message(
        chat_id,
        "⛔️ شما دسترسی استفاده از این ربات را ندارید.\n\n"
        "برای دریافت شناسه کاربری خود دستور زیر را ارسال کنید:\n"
        "/myid"
    )


# =========================================================
# MY ID
# =========================================================

def show_my_id(chat_id):
    try:
        result = bale_request(
            "getChat",
            {
                "chat_id": chat_id
            }
        )

        user = {}

        if result.get("ok"):
            user = result.get("result") or {}

        username = clean_username(
            user.get("username")
        )

        admin_status = is_admin(chat_id)

        text = (
            "🆔 اطلاعات کاربری شما\n\n"
            f"User ID:\n{chat_id}\n\n"
            f"Username:\n"
            f"@{username if username else 'ندارد'}\n\n"
            f"وضعیت دسترسی:\n"
            f"{'✅ مدیر ربات' if admin_status else '❌ کاربر عادی'}"
        )

        send_message(
            chat_id,
            text
        )

    except Exception as e:
        print("MY ID ERROR:", e)

        send_message(
            chat_id,
            f"🆔 User ID شما:\n{chat_id}"
        )


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

def find_user_by_username(username):
    username = clean_username(username)

    if not username:
        return None

    try:
        result = (
            supabase
            .table("bot_users")
            .select("*")
            .eq("username", username)
            .eq("active", True)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:
        print("FIND USER ERROR:", e)

    return None


def command_add_admin(chat_id, args):
    if not is_owner(chat_id):
        deny_access(chat_id)
        return

    if not args:
        send_message(
            chat_id,
            "فرمت صحیح:\n"
            "/addadmin USER_ID\n\n"
            "مثال:\n"
            "/addadmin 123456789"
        )
        return

    target = args[0].strip()

    target_user_id = None
    target_username = None
    target_first_name = ""

    if target.startswith("@"):
        user = find_user_by_username(target)

        if not user:
            send_message(
                chat_id,
                "❌ این کاربر قبلاً به ربات پیام نداده است "
                "یا در فهرست کاربران پیدا نشد.\n\n"
                "از کاربر بخواهید ابتدا /myid را ارسال کند."
            )
            return

        target_user_id = user.get("user_id")
        target_username = user.get("username")
        target_first_name = user.get("first_name") or ""

    else:
        target_user_id = target

        try:
            result = (
                supabase
                .table("bot_users")
                .select("*")
                .eq("user_id", str(target_user_id))
                .limit(1)
                .execute()
            )

            if result.data:
                user = result.data[0]
                target_username = user.get("username")
                target_first_name = user.get("first_name") or ""

        except Exception as e:
            print("GET TARGET USER ERROR:", e)

    if not str(target_user_id).isdigit():
        send_message(
            chat_id,
            "❌ شناسه کاربری باید عددی باشد."
        )
        return

    try:
        existing = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq("user_id", str(target_user_id))
            .limit(1)
            .execute()
        )

        if existing.data:
            (
                supabase
                .table("bot_admins")
                .update({
                    "active": True,
                    "username": target_username,
                    "first_name": target_first_name
                })
                .eq("user_id", str(target_user_id))
                .execute()
            )
        else:
            (
                supabase
                .table("bot_admins")
                .insert({
                    "user_id": str(target_user_id),
                    "username": target_username,
                    "first_name": target_first_name,
                    "active": True,
                    "created_at": now_iso()
                })
                .execute()
            )

        send_message(
            chat_id,
            "✅ کاربر با موفقیت به مدیران ربات اضافه شد.\n\n"
            f"User ID: {target_user_id}\n"
            f"Username: "
            f"@{target_username if target_username else 'ندارد'}"
        )

    except Exception as e:
        print("ADD ADMIN ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا در افزودن مدیر:\n{e}"
        )


def command_remove_admin(chat_id, args):
    if not is_owner(chat_id):
        deny_access(chat_id)
        return

    if not args:
        send_message(
            chat_id,
            "فرمت صحیح:\n"
            "/removeadmin USER_ID"
        )
        return

    target_user_id = args[0].strip()

    if not target_user_id.isdigit():
        send_message(
            chat_id,
            "❌ شناسه کاربری باید عددی باشد."
        )
        return

    if is_owner(target_user_id):
        send_message(
            chat_id,
            "❌ مالک ربات را نمی‌توان حذف کرد."
        )
        return

    try:
        result = (
            supabase
            .table("bot_admins")
            .update({
                "active": False
            })
            .eq("user_id", str(target_user_id))
            .execute()
        )

        if result.data:
            send_message(
                chat_id,
                "✅ دسترسی مدیر با موفقیت حذف شد."
            )
        else:
            send_message(
                chat_id,
                "❌ این کاربر مدیر نیست."
            )

    except Exception as e:
        print("REMOVE ADMIN ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا:\n{e}"
        )


def command_list_admins(chat_id):
    if not is_owner(chat_id):
        deny_access(chat_id)
        return

    try:
        result = (
            supabase
            .table("bot_admins")
            .select("*")
            .eq("active", True)
            .order("id")
            .execute()
        )

        lines = [
            "👥 فهرست مدیران ربات",
            ""
        ]

        if OWNER_ID:
            lines.append(
                f"👑 مالک:\n{OWNER_ID}"
            )

        if result.data:
            lines.append("")
            lines.append("🛡 مدیران:")

            for index, admin in enumerate(
                result.data,
                start=1
            ):
                user_id = admin.get("user_id")
                username = clean_username(
                    admin.get("username")
                )
                first_name = admin.get(
                    "first_name"
                ) or ""

                name = first_name

                if username:
                    name += f" (@{username})"

                if not name:
                    name = "بدون نام"

                lines.append(
                    f"{index}. {name}\n"
                    f"   ID: {user_id}"
                )
        else:
            lines.append("")
            lines.append(
                "هیچ مدیر دیگری ثبت نشده است."
            )

        send_message(
            chat_id,
            "\n".join(lines)
        )

    except Exception as e:
        print("LIST ADMINS ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا:\n{e}"
        )


# =========================================================
# CHANNEL MANAGEMENT
# =========================================================

def add_channel(chat_id, username):
    username = clean_username(username)

    if not username:
        send_message(
            chat_id,
            "❌ نام کاربری کانال صحیح نیست."
        )
        return

    channel = get_chat(
        f"@{username}"
    )

    if not channel:
        send_message(
            chat_id,
            "❌ کانال پیدا نشد.\n\n"
            "مطمئن شوید ربات در کانال عضو/مدیر است."
        )
        return

    channel_chat_id = channel.get("id")
    channel_username = clean_username(
        channel.get("username")
    )
    channel_title = (
        channel.get("title")
        or channel.get("first_name")
        or username
    )

    if not channel_chat_id:
        send_message(
            chat_id,
            "❌ شناسه کانال دریافت نشد."
        )
        return

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
            "username": channel_username or username,
            "title": channel_title,
            "active": True
        }

        if existing.data:
            (
                supabase
                .table("channels")
                .update(data)
                .eq(
                    "chat_id",
                    str(channel_chat_id)
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

        send_message(
            chat_id,
            "✅ کانال با موفقیت ثبت شد.\n\n"
            f"📢 {channel_title}\n"
            f"@{channel_username or username}\n"
            f"🆔 {channel_chat_id}"
        )

    except Exception as e:
        print("ADD CHANNEL ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا در ثبت کانال:\n{e}"
        )


def list_channels(chat_id):
    try:
        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("active", True)
            .order("id")
            .limit(100)
            .execute()
        )

        if not result.data:
            send_message(
                chat_id,
                "📢 هیچ کانال فعالی ثبت نشده است."
            )
            return

        lines = [
            "📢 کانال‌های فعال:",
            ""
        ]

        for index, channel in enumerate(
            result.data,
            start=1
        ):
            title = channel.get("title") or "-"
            username = clean_username(
                channel.get("username")
            )
            channel_chat_id = (
                channel.get("chat_id")
                or channel.get("id")
            )

            lines.append(
                f"{index}. {title}\n"
                f"   @{username or '-'}\n"
                f"   ID: {channel_chat_id}"
            )

        send_message(
            chat_id,
            "\n".join(lines)
        )

    except Exception as e:
        print("LIST CHANNEL ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا:\n{e}"
        )


def remove_channel(chat_id, username):
    username = clean_username(username)

    if not username:
        send_message(
            chat_id,
            "فرمت صحیح:\n"
            "/removechannel @channel"
        )
        return

    try:
        result = (
            supabase
            .table("channels")
            .update({
                "active": False
            })
            .eq("username", username)
            .execute()
        )

        if result.data:
            send_message(
                chat_id,
                "✅ کانال غیرفعال شد."
            )
        else:
            send_message(
                chat_id,
                "❌ کانال پیدا نشد."
            )

    except Exception as e:
        print("REMOVE CHANNEL ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا:\n{e}"
        )


# =========================================================
# FORWARD EXTRACTION
# =========================================================

def extract_forward(message):
    result = {
        "chat_id": None,
        "username": None,
        "title": None,
        "message_id": None,
        "link": None
    }

    if not message:
        return result

    # -----------------------------------------------------
    # New forward structure
    # -----------------------------------------------------

    forward_origin = message.get(
        "forward_origin"
    )

    if forward_origin:
        origin_type = forward_origin.get(
            "type"
        )

        if origin_type == "channel":
            source_chat = (
                forward_origin.get("chat")
                or {}
            )

            result["chat_id"] = source_chat.get(
                "id"
            )

            result["username"] = clean_username(
                source_chat.get("username")
            )

            result["title"] = (
                source_chat.get("title")
                or source_chat.get("first_name")
                or result["username"]
            )

            result["message_id"] = (
                forward_origin.get("message_id")
            )

    # -----------------------------------------------------
    # Legacy forward structure
    # -----------------------------------------------------

    if not result["chat_id"]:
        forward_from_chat = message.get(
            "forward_from_chat"
        )

        if forward_from_chat:
            result["chat_id"] = (
                forward_from_chat.get("id")
            )

            result["username"] = clean_username(
                forward_from_chat.get(
                    "username"
                )
            )

            result["title"] = (
                forward_from_chat.get("title")
                or forward_from_chat.get(
                    "first_name"
                )
                or result["username"]
            )

            result["message_id"] = (
                message.get("forward_from_message_id")
            )

    # -----------------------------------------------------
    # Final link
    # -----------------------------------------------------

    result["link"] = build_bale_message_link(
        username=result["username"],
        chat_id=result["chat_id"],
        message_id=result["message_id"]
    )

    print("FORWARD EXTRACTED:", result)

    return result


# =========================================================
# PRIVATE FORWARD
# =========================================================

def process_private_forward(message):
    chat = message.get("chat") or {}
    user_chat_id = chat.get("id")

    forward = extract_forward(
        message
    )

    if not forward.get("message_id"):
        send_message(
            user_chat_id,
            "❌ پیام فورواردشده قابل شناسایی نیست."
        )
        return

    save_selected_source(
        forward
    )

    title = (
        forward.get("title")
        or forward.get("username")
        or "بدون عنوان"
    )

    link = (
        forward.get("link")
        or "لینک قابل ساخت نیست"
    )

    send_message(
        user_chat_id,
        "✅ پیام مرجع با موفقیت انتخاب شد.\n\n"
        f"📢 کانال:\n"
        f"{title}\n\n"
        f"🆔 Channel ID:\n"
        f"{forward.get('chat_id')}\n\n"
        f"📝 Message ID:\n"
        f"{forward.get('message_id')}\n\n"
        f"🔗 لینک پیام:\n"
        f"{link}\n\n"
        "اکنون برای مشاهده گزارش بازنشرها "
        "دستور /report را ارسال کنید."
    )


# =========================================================
# DESTINATION CHANNEL RESOLUTION
# =========================================================

def resolve_destination_channel(chat):
    if not chat:
        return None

    channel_chat_id = chat.get("id")

    username = clean_username(
        chat.get("username")
    )

    # -----------------------------------------------------
    # First: exact chat_id
    # -----------------------------------------------------

    if channel_chat_id is not None:
        try:
            result = (
                supabase
                .table("channels")
                .select("*")
                .eq(
                    "chat_id",
                    str(channel_chat_id)
                )
                .eq("active", True)
                .limit(1)
                .execute()
            )

            if result.data:
                return result.data[0]

        except Exception as e:
            print(
                "RESOLVE CHANNEL BY ID ERROR:",
                e
            )

    # -----------------------------------------------------
    # Second: username
    # -----------------------------------------------------

    if username:
        try:
            result = (
                supabase
                .table("channels")
                .select("*")
                .eq("username", username)
                .eq("active", True)
                .limit(1)
                .execute()
            )

            if result.data:
                channel = result.data[0]

                # اگر chat_id خالی بوده،
                # همین‌جا آن را تکمیل می‌کنیم.
                if (
                    not channel.get("chat_id")
                    and channel_chat_id is not None
                ):
                    (
                        supabase
                        .table("channels")
                        .update({
                            "chat_id": str(
                                channel_chat_id
                            )
                        })
                        .eq(
                            "id",
                            channel.get("id")
                        )
                        .execute()
                    )

                    channel["chat_id"] = str(
                        channel_chat_id
                    )

                return channel

        except Exception as e:
            print(
                "RESOLVE CHANNEL BY USERNAME ERROR:",
                e
            )

    return None


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

    # فقط خط اول
    title = text.splitlines()[0].strip()

    if len(title) > 100:
        title = title[:100] + "..."

    return title


# =========================================================
# SAVE REPOST
# =========================================================

def save_repost(
    source,
    destination,
    destination_message_id,
    message_title
):
    try:
        destination_chat_id = (
            destination.get("chat_id")
            or destination.get("id")
        )

        destination_username = clean_username(
            destination.get("username")
        )

        destination_title = (
            destination.get("title")
            or destination_username
            or "بدون عنوان"
        )

        data = {
            "source_channel_id": str(
                source.get("chat_id")
            ),
            "source_username": clean_username(
                source.get("username")
            ),
            "source_message_id": str(
                source.get("message_id")
            ),
            "destination_channel_id": str(
                destination_chat_id
            ),
            "destination_username":
                destination_username,
            "destination_message_id": str(
                destination_message_id
            ),
            "destination_title":
                destination_title,
            "message_title":
                message_title,
            "created_at": now_iso()
        }

        (
            supabase
            .table("reposts")
            .insert(data)
            .execute()
        )

        print("REPOST SAVED:", data)

        return True

    except Exception as e:
        print("SAVE REPOST ERROR:", e)
        return False


# =========================================================
# PROCESS CHANNEL MESSAGE
# =========================================================

def process_channel_message(message):
    chat = message.get("chat") or {}

    destination = resolve_destination_channel(
        chat
    )

    if not destination:
        return

    source = load_selected_source()

    if not source.get("message_id"):
        return

    message_id = message.get(
        "message_id"
    )

    if not message_id:
        return

    message_title = get_message_title(
        message
    )

    saved = save_repost(
        source=source,
        destination=destination,
        destination_message_id=message_id,
        message_title=message_title
    )

    if not saved:
        return

    # -----------------------------------------------------
    # ارسال هشدار به مدیران
    # -----------------------------------------------------

    destination_chat_id = (
        destination.get("chat_id")
        or destination.get("id")
    )

    destination_username = clean_username(
        destination.get("username")
    )

    destination_title = (
        destination.get("title")
        or destination_username
        or "بدون عنوان"
    )

    destination_link = build_bale_message_link(
        username=destination_username,
        chat_id=destination_chat_id,
        message_id=message_id
    )

    source_link = source.get("link")

    alert = (
        "🔔 بازنشر جدید شناسایی شد\n\n"
        f"📢 کانال مقصد:\n"
        f"{destination_title}\n"
    )

    if destination_username:
        alert += (
            f"@{destination_username}\n"
        )

    alert += (
        "\n"
        f"📝 عنوان پیام:\n"
        f"{message_title}\n\n"
        f"🕐 زمان:\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )

    if source_link:
        alert += (
            f"🔗 پیام مرجع:\n"
            f"{source_link}\n\n"
        )

    if destination_link:
        alert += (
            f"📎 پیام بازنشرشده:\n"
            f"{destination_link}"
        )

    notify_admins(
        alert
    )


# =========================================================
# NOTIFY ADMINS
# =========================================================

def get_admin_ids():
    ids = []

    if OWNER_ID:
        ids.append(
            str(OWNER_ID)
        )

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

            if user_id and str(user_id) not in ids:
                ids.append(
                    str(user_id)
                )

    except Exception as e:
        print("GET ADMIN IDS ERROR:", e)

    return ids


def notify_admins(text):
    for admin_id in get_admin_ids():
        send_message(
            admin_id,
            text
        )


# =========================================================
# REPORT
# =========================================================

def report_reposts(chat_id):
    source = load_selected_source()

    if not source.get("chat_id"):
        send_message(
            chat_id,
            "❌ هنوز هیچ پیام مرجعی انتخاب نشده است.\n\n"
            "ابتدا پیام موردنظر را از کانال فوروارد کنید."
        )
        return

    try:
        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_channel_id",
                str(source.get("chat_id"))
            )
            .eq(
                "source_message_id",
                str(source.get("message_id"))
            )
            .order(
                "created_at",
                desc=True
            )
            .limit(1000)
            .execute()
        )

        rows = result.data or []

        source_title = (
            source.get("title")
            or source.get("username")
            or "پیام مرجع"
        )

        lines = [
            "📊 گزارش بازنشر",
            "",
            f"📌 پیام مرجع:",
            f"{source_title}",
            "",
            f"🆔 Message ID: "
            f"{source.get('message_id')}",
            ""
        ]

        if source.get("link"):
            lines.extend([
                "🔗 لینک پیام مرجع:",
                source["link"],
                ""
            ])

        if not rows:
            lines.append(
                "❌ این پیام تاکنون در هیچ‌یک "
                "از کانال‌های ثبت‌شده بازنشر نشده است."
            )

            send_message(
                chat_id,
                "\n".join(lines)
            )

            return

        lines.append(
            f"✅ تعداد بازنشرها: {len(rows)}"
        )

        lines.append("")

        for index, row in enumerate(
            rows,
            start=1
        ):
            destination_username = clean_username(
                row.get(
                    "destination_username"
                )
            )

            destination_chat_id = row.get(
                "destination_channel_id"
            )

            destination_message_id = row.get(
                "destination_message_id"
            )

            destination_title = (
                row.get(
                    "destination_title"
                )
                or destination_username
                or "بدون عنوان"
            )

            message_title = (
                row.get("message_title")
                or "بدون عنوان"
            )

            created_at = (
                row.get("created_at")
                or "-"
            )

            # -------------------------------------------------
            # مهم:
            # لینک برای رکوردهای قدیمی هم همین‌جا
            # از روی chat_id + message_id ساخته می‌شود.
            # -------------------------------------------------

            link = build_bale_message_link(
                username=destination_username,
                chat_id=destination_chat_id,
                message_id=destination_message_id
            )

            lines.append(
                f"━━━━━━━━━━━━━━\n"
                f"#{index} 📢 {destination_title}\n"
            )

            if destination_username:
                lines.append(
                    f"@{destination_username}"
                )

            lines.extend([
                "",
                f"📝 {message_title}",
                f"🕐 {created_at}"
            ])

            if link:
                lines.extend([
                    "",
                    f"🔗 {link}"
                ])
            else:
                lines.extend([
                    "",
                    "⚠️ لینک پیام قابل ساخت نیست "
                    "(اطلاعات chat_id یا message_id ناقص است)."
                ])

        # بله ممکن است محدودیت طول پیام داشته باشد.
        # گزارش را به قسمت‌های کوچک‌تر تقسیم می‌کنیم.

        full_text = "\n".join(lines)

        chunks = []

        while len(full_text) > 3500:
            cut = full_text.rfind(
                "\n",
                0,
                3500
            )

            if cut <= 0:
                cut = 3500

            chunks.append(
                full_text[:cut]
            )

            full_text = full_text[cut:].lstrip()

        if full_text:
            chunks.append(
                full_text
            )

        for chunk in chunks:
            send_message(
                chat_id,
                chunk
            )

    except Exception as e:
        print("REPORT ERROR:", e)

        send_message(
            chat_id,
            f"❌ خطا در تهیه گزارش:\n{e}"
        )


# =========================================================
# STATUS
# =========================================================

def command_status(chat_id):
    source = load_selected_source()

    try:
        channels = (
            supabase
            .table("channels")
            .select("id")
            .eq("active", True)
            .execute()
        )

        channel_count = len(
            channels.data or []
        )

    except Exception:
        channel_count = 0

    source_text = "❌ انتخاب نشده"

    if source.get("message_id"):
        source_text = (
            f"✅ {source.get('title') or '-'}\n"
            f"Message ID: "
            f"{source.get('message_id')}"
        )

    text = (
        "📊 وضعیت ربات\n\n"
        f"📢 تعداد کانال‌های فعال: "
        f"{channel_count}\n\n"
        f"📌 پیام مرجع:\n"
        f"{source_text}\n\n"
        f"👤 وضعیت شما:\n"
        f"{'مدیر' if is_admin(chat_id) else 'کاربر عادی'}"
    )

    send_message(
        chat_id,
        text
    )


# =========================================================
# START / MENU
# =========================================================

def start_message(chat_id):
    if not is_admin(chat_id):
        send_message(
            chat_id,
            "سلام 👋\n\n"
            "شما دسترسی مدیریتی به این ربات ندارید.\n\n"
            "برای مشاهده شناسه کاربری خود:\n"
            "/myid"
        )
        return

    text = (
        "🤖 ربات پایش بازنشر بله\n\n"
        "📌 ابتدا یک پیام از کانال مرجع را "
        "به صورت Forward برای ربات ارسال کنید.\n\n"
        "سپس:\n\n"
        "/report\n"
        "گزارش بازنشر همان پیام را نمایش می‌دهد.\n\n"
        "/channels\n"
        "فهرست کانال‌ها\n\n"
        "/addchannel @channel\n"
        "افزودن کانال\n\n"
        "/removechannel @channel\n"
        "حذف کانال\n\n"
        "/status\n"
        "وضعیت ربات\n\n"
        "/myid\n"
        "شناسه کاربری"
    )

    if is_owner(chat_id):
        text += (
            "\n\n"
            "👑 مدیریت مدیران:\n\n"
            "/addadmin USER_ID\n"
            "افزودن مدیر\n\n"
            "/removeadmin USER_ID\n"
            "حذف مدیر\n\n"
            "/admins\n"
            "فهرست مدیران"
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

    args = parts[1:]

    # -----------------------------------------------------
    # /myid باید قبل از بررسی admin باشد
    # -----------------------------------------------------

    if command == "/myid":
        show_my_id(
            chat_id
        )
        return

    # -----------------------------------------------------
    # تمام دستورات دیگر فقط برای مدیر
    # -----------------------------------------------------

    if not is_admin(chat_id):
        deny_access(chat_id)
        return

    if command in (
        "/start",
        "/help"
    ):
        start_message(
            chat_id
        )
        return

    if command == "/report":
        report_reposts(
            chat_id
        )
        return

    if command == "/channels":
        list_channels(
            chat_id
        )
        return

    if command == "/addchannel":
        if not args:
            send_message(
                chat_id,
                "فرمت صحیح:\n"
                "/addchannel @channel"
            )
            return

        add_channel(
            chat_id,
            args[0]
        )
        return

    if command == "/removechannel":
        if not args:
            send_message(
                chat_id,
                "فرمت صحیح:\n"
                "/removechannel @channel"
            )
            return

        remove_channel(
            chat_id,
            args[0]
        )
        return

    if command == "/status":
        command_status(
            chat_id
        )
        return

    if command == "/addadmin":
        command_add_admin(
            chat_id,
            args
        )
        return

    if command == "/removeadmin":
        command_remove_admin(
            chat_id,
            args
        )
        return

    if command in (
        "/admins",
        "/listadmins"
    ):
        command_list_admins(
            chat_id
        )
        return

    send_message(
        chat_id,
        "❓ دستور ناشناخته است.\n\n"
        "برای مشاهده راهنما /start را ارسال کنید."
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

    chat = message.get(
        "chat"
    ) or {}

    chat_id = chat.get(
        "id"
    )

    if chat_id is None:
        return

    # ذخیره تمام کاربرانی که با ربات تعامل دارند
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

        text = message.get(
            "text"
        ) or ""

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

        # /myid برای همه آزاد است
        if first_command == "/myid":
            show_my_id(
                chat_id
            )
            return

        # بررسی Forward
        forward = extract_forward(
            message
        )

        if forward.get("message_id"):

            if not is_admin(chat_id):
                deny_access(
                    chat_id
                )
                return

            process_private_forward(
                message
            )
            return

        # سایر دستورات
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
# GET UPDATES
# =========================================================

def get_updates(offset=None):
    data = {
        "timeout": 30,
        "allowed_updates": [
            "message"
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
    global OFFSET

    load_owner()
    load_selected_source()

    print("=" * 60)
    print("BALE REPOST MONITOR STARTED")
    print("OWNER_ID:", OWNER_ID)
    print("SELECTED_SOURCE:", SELECTED_SOURCE)
    print("=" * 60)

    while True:

        try:
            result = get_updates(
                OFFSET
            )

            if not result.get("ok"):
                print(
                    "GET UPDATES FAILED:",
                    result
                )

                time.sleep(3)
                continue

            updates = (
                result.get("result")
                or []
            )

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

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
