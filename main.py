import os
import time
import hashlib
import requests
from supabase import create_client


# =========================================================
# SETTINGS
# =========================================================

BALE_TOKEN = os.getenv("BALE_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not BALE_TOKEN:
    raise Exception("BALE_TOKEN تنظیم نشده است")

if not SUPABASE_URL:
    raise Exception("SUPABASE_URL تنظیم نشده است")

if not SUPABASE_SECRET_KEY:
    raise Exception("SUPABASE_SECRET_KEY تنظیم نشده است")


BASE_URL = f"https://tapi.bale.ai/bot{BALE_TOKEN}"

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

OWNER_ID = None


# =========================================================
# BALE API
# =========================================================

def bale(method, data=None):

    try:

        if data is None:
            data = {}

        response = requests.post(
            f"{BASE_URL}/{method}",
            json=data,
            timeout=35
        )

        return response.json()

    except Exception as e:

        print("BALE ERROR:", e)

        return {}


def send_message(chat_id, text):

    return bale(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


# =========================================================
# SUPABASE SETTINGS
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

        return None

    except Exception as e:

        print("GET SETTING ERROR:", e)

        return None


def save_setting(key, value):

    try:

        supabase.table("bot_settings").upsert(
            {
                "key": key,
                "value": str(value)
            }
        ).execute()

        return True

    except Exception as e:

        print("SAVE SETTING ERROR:", e)

        return False


# =========================================================
# TARGET POST
# =========================================================

def save_target(
    channel_id=None,
    username=None,
    message_id=None,
    link_channel_id=None
):

    save_setting(
        "target_channel_id",
        channel_id if channel_id is not None else ""
    )

    save_setting(
        "target_username",
        username if username else ""
    )

    save_setting(
        "target_message_id",
        message_id
    )

    # شناسه‌ای که در لینک بله آمده
    save_setting(
        "target_link_channel_id",
        link_channel_id if link_channel_id else ""
    )


def get_target():

    channel_id = get_setting(
        "target_channel_id"
    )

    username = get_setting(
        "target_username"
    )

    message_id = get_setting(
        "target_message_id"
    )

    link_channel_id = get_setting(
        "target_link_channel_id"
    )

    if not message_id:
        return None

    try:
        message_id = int(message_id)
    except:
        return None

    if channel_id:

        try:
            channel_id = int(channel_id)
        except:
            channel_id = None

    if link_channel_id:

        try:
            link_channel_id = int(
                link_channel_id
            )
        except:
            link_channel_id = None

    if username:

        username = (
            username
            .replace("@", "")
            .strip()
            .lower()
        )

    return {
        "channel_id": channel_id,
        "username": username,
        "message_id": message_id,
        "link_channel_id": link_channel_id
    }


# =========================================================
# CHANNELS
# =========================================================

def stable_channel_id(username):

    value = (
        username
        .lower()
        .strip()
        .encode("utf-8")
    )

    return int(
        hashlib.sha256(
            value
        ).hexdigest()[:15],
        16
    )


def get_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("active", True)
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET CHANNELS ERROR:",
            e
        )

        return []


def add_channel(username):

    username = (
        username
        .replace("@", "")
        .strip()
        .lower()
    )

    if not username:

        return False, (
            "نام کانال وارد نشده است."
        )

    channel_id = stable_channel_id(
        username
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
                "کانال دوباره فعال شد."
            )

        supabase.table(
            "channels"
        ).insert(
            {
                "id": channel_id,
                "username": username,
                "title": username,
                "active": True
            }
        ).execute()

        return True, (
            "کانال با موفقیت اضافه شد."
        )

    except Exception as e:

        print(
            "ADD CHANNEL ERROR:",
            e
        )

        return False, str(e)


def remove_channel(username):

    username = (
        username
        .replace("@", "")
        .strip()
        .lower()
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


# =========================================================
# FORWARD INFORMATION
# =========================================================

def extract_forward_info(message):

    forward_chat_id = None
    forward_username = None
    forward_message_id = None

    # -----------------------------------------------------
    # روش قدیمی Bale
    # -----------------------------------------------------

    if message.get(
        "forward_from_chat"
    ):

        chat = message.get(
            "forward_from_chat"
        )

        forward_chat_id = chat.get(
            "id"
        )

        forward_username = chat.get(
            "username"
        )

    if message.get(
        "forward_from_message_id"
    ):

        forward_message_id = message.get(
            "forward_from_message_id"
        )

    # -----------------------------------------------------
    # روش جدید Bale
    # -----------------------------------------------------

    if message.get(
        "forward_origin"
    ):

        origin = message.get(
            "forward_origin"
        )

        if origin.get(
            "type"
        ) == "channel":

            chat = origin.get(
                "chat",
                {}
            )

            forward_chat_id = chat.get(
                "id"
            )

            forward_username = chat.get(
                "username"
            )

            forward_message_id = origin.get(
                "message_id"
            )

    if forward_username:

        forward_username = (
            forward_username
            .replace("@", "")
            .strip()
            .lower()
        )

    return (
        forward_chat_id,
        forward_username,
        forward_message_id
    )


# =========================================================
# ARCHIVE CHANNEL MESSAGE
# =========================================================

def save_channel_message(
    channel_username,
    message,
    forward_chat_id,
    forward_username,
    forward_message_id
):

    try:

        message_id = message.get(
            "message_id"
        )

        text = (
            message.get("text")
            or message.get("caption")
            or ""
        )

        supabase.table(
            "channel_messages"
        ).upsert(
            {
                "channel_username":
                    channel_username,

                "message_id":
                    message_id,

                "text":
                    text,

                "forward_username":
                    forward_username,

                "forward_message_id":
                    forward_message_id
            },
            on_conflict=(
                "channel_username,"
                "message_id"
            )
        ).execute()

        print(
            "ARCHIVED:",
            channel_username,
            message_id,
            "FORWARD:",
            forward_username,
            forward_message_id,
            "FORWARD CHAT ID:",
            forward_chat_id
        )

    except Exception as e:

        print(
            "ARCHIVE ERROR:",
            e
        )


# =========================================================
# ALERTS
# =========================================================

def already_alerted(
    channel_username,
    message_id
):

    try:

        result = (
            supabase
            .table("alerts")
            .select("id")
            .eq(
                "channel_username",
                channel_username
            )
            .eq(
                "message_id",
                message_id
            )
            .limit(1)
            .execute()
        )

        return bool(
            result.data
        )

    except Exception as e:

        print(
            "CHECK ALERT ERROR:",
            e
        )

        return False


def save_alert(
    channel_username,
    message_id,
    target_message_id,
    target_username,
    target_channel_id
):

    try:

        supabase.table(
            "alerts"
        ).upsert(
            {
                "channel_username":
                    channel_username,

                "message_id":
                    message_id,

                "target_message_id":
                    target_message_id,

                "target_username":
                    target_username or "",

                "target_channel_id":
                    target_channel_id
            },
            on_conflict=(
                "channel_username,"
                "message_id"
            )
        ).execute()

        print(
            "ALERT SAVED:",
            channel_username,
            message_id
        )

    except Exception as e:

        print(
            "SAVE ALERT ERROR:",
            e
        )


# =========================================================
# REPORT
# =========================================================

def get_report():

    target = get_target()

    if not target:

        return (
            "❌ هنوز پست هدفی ثبت نشده است."
        )

    target_username = (
        target["username"]
    )

    target_channel_id = (
        target["channel_id"]
    )

    target_link_channel_id = (
        target["link_channel_id"]
    )

    target_message_id = (
        target["message_id"]
    )

    found = []

    # -----------------------------------------------------
    # ALERTS
    # -----------------------------------------------------

    try:

        result = (
            supabase
            .table("alerts")
            .select("*")
            .eq(
                "target_message_id",
                target_message_id
            )
            .execute()
        )

        for row in (
            result.data or []
        ):

            row_username = (
                row.get(
                    "target_username"
                )
                or ""
            ).replace(
                "@",
                ""
            ).lower()

            row_channel_id = (
                row.get(
                    "target_channel_id"
                )
            )

            matched = False

            if (
                target_username
                and row_username
                == target_username.lower()
            ):

                matched = True

            if (
                target_channel_id
                and row_channel_id
                and int(row_channel_id)
                == int(target_channel_id)
            ):

                matched = True

            if matched:

                found.append(
                    {
                        "channel":
                            row.get(
                                "channel_username"
                            ),

                        "message_id":
                            row.get(
                                "message_id"
                            ),

                        "created_at":
                            row.get(
                                "created_at"
                            )
                    }
                )

    except Exception as e:

        print(
            "REPORT ALERT ERROR:",
            e
        )

    # -----------------------------------------------------
    # ARCHIVED MESSAGES
    # -----------------------------------------------------

    try:

        result = (
            supabase
            .table(
                "channel_messages"
            )
            .select("*")
            .execute()
        )

        for row in (
            result.data or []
        ):

            forward_username = (
                row.get(
                    "forward_username"
                )
                or ""
            ).replace(
                "@",
                ""
            ).lower()

            forward_message_id = (
                row.get(
                    "forward_message_id"
                )
            )

            matched = False

            if (
                target_username
                and forward_username
                == target_username.lower()
                and forward_message_id
                == target_message_id
            ):

                matched = True

            if matched:

                item = {
                    "channel":
                        row.get(
                            "channel_username"
                        ),

                    "message_id":
                        row.get(
                            "message_id"
                        ),

                    "created_at":
                        row.get(
                            "created_at"
                        )
                }

                duplicate = False

                for old in found:

                    if (
                        old["channel"]
                        == item["channel"]

                        and

                        old["message_id"]
                        == item["message_id"]
                    ):

                        duplicate = True
                        break

                if not duplicate:

                    found.append(
                        item
                    )

    except Exception as e:

        print(
            "REPORT ARCHIVE ERROR:",
            e
        )

    # -----------------------------------------------------
    # REPORT TEXT
    # -----------------------------------------------------

    text = (
        "📊 گزارش انتشار پست هدف\n\n"
    )

    text += (
        "🎯 پست هدف:\n"
    )

    if target_username:

        text += (
            f"📢 کانال: "
            f"@{target_username}\n"
        )

    if target_link_channel_id:

        text += (
            f"🔢 شناسه داخل لینک: "
            f"{target_link_channel_id}\n"
        )

    elif target_channel_id:

        text += (
            f"🔢 شناسه کانال: "
            f"{target_channel_id}\n"
        )

    text += (
        f"🆔 شماره پیام: "
        f"{target_message_id}\n\n"
    )

    if not found:

        text += (
            "❌ تاکنون بازنشر ثبت‌شده‌ای "
            "پیدا نشد.\n\n"
        )

        text += (
            "⚠️ گزارش بر اساس پیام‌هایی است "
            "که ربات از زمان فعال بودن "
            "آرشیو دریافت کرده است."
        )

        return text

    text += (
        f"✅ تعداد بازنشرها: "
        f"{len(found)}\n\n"
    )

    for i, item in enumerate(
        found,
        1
    ):

        channel = (
            item["channel"]
        )

        message_id = (
            item["message_id"]
        )

        text += (
            f"{i}. @{channel}\n"
            f"   🆔 پیام: {message_id}\n"
        )

        if item.get(
            "created_at"
        ):

            text += (
                f"   🕒 زمان ثبت: "
                f"{item['created_at']}\n"
            )

        text += "\n"

    return text


# =========================================================
# COMMANDS
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

    text = (
        message.get(
            "text",
            ""
        )
        .strip()
    )

    if not text:
        return

    # -----------------------------------------------------
    # مالک ربات
    # -----------------------------------------------------

    if OWNER_ID is None:

        OWNER_ID = chat_id

        print(
            "OWNER ID SET:",
            OWNER_ID
        )

    if chat_id != OWNER_ID:

        return

    # =====================================================
    # START
    # =====================================================

    if text == "/start":

        send_message(
            chat_id,
            "🤖 ربات پایش بازنشر آماده است.\n\n"

            "دستورات:\n\n"

            "/watch لینک پست\n"
            "/report\n"
            "/target\n\n"

            "/addchannel نام_کانال\n"
            "/listchannels\n"
            "/removechannel نام_کانال\n"
            "/status"
        )

        return

    # =====================================================
    # WATCH
    # =====================================================

    if text.startswith(
        "/watch"
    ):

        parts = text.split(
            maxsplit=1
        )

        if len(parts) < 2:

            send_message(
                chat_id,

                "❌ لینک پست را بعد از "
                "/watch وارد کنید.\n\n"

                "مثال:\n"

                "/watch "
                "https://ble.ir/barghsb/"
                "5259067422793579117/"
                "1788443437465"
            )

            return

        original_link = (
            parts[1].strip()
        )

        link = original_link

        # حذف پروتکل
        link = link.replace(
            "https://",
            ""
        )

        link = link.replace(
            "http://",
            ""
        )

        # حذف www
        link = link.replace(
            "www.",
            ""
        )

        # حذف ble.ir
        if link.startswith(
            "ble.ir/"
        ):

            link = link[7:]

        # حذف اسلش ابتدا و انتها
        link = link.strip(
            "/"
        )

        pieces = [
            x.strip()
            for x in link.split("/")
            if x.strip()
        ]

        username = None
        channel_id = None
        link_channel_id = None
        message_id = None

        # =================================================
        # فرمت:
        #
        # ble.ir/barghsb/134
        # =================================================

        if len(pieces) == 2:

            username = (
                pieces[0]
                .replace("@", "")
                .lower()
                .strip()
            )

            try:

                message_id = int(
                    pieces[1]
                )

            except:

                send_message(
                    chat_id,
                    "❌ شماره پیام صحیح نیست."
                )

                return

        # =================================================
        # فرمت:
        #
        # ble.ir/c/6031103884/134
        # =================================================

        elif (
            len(pieces) == 3
            and
            pieces[0].lower()
            == "c"
        ):

            try:

                channel_id = int(
                    pieces[1]
                )

                message_id = int(
                    pieces[2]
                )

            except:

                send_message(
                    chat_id,

                    "❌ شناسه کانال یا "
                    "شماره پیام صحیح نیست."
                )

                return

        # =================================================
        # فرمت واقعی لینک شما:
        #
        # ble.ir/barghsb/
        # 5259067422793579117/
        # 1788443437465
        # =================================================

        elif len(pieces) == 3:

            username = (
                pieces[0]
                .replace("@", "")
                .lower()
                .strip()
            )

            try:

                link_channel_id = int(
                    pieces[1]
                )

                message_id = int(
                    pieces[2]
                )

            except:

                send_message(
                    chat_id,

                    "❌ شناسه کانال یا "
                    "شماره پیام صحیح نیست."
                )

                return

        # =================================================
        # فرمت ناشناخته
        # =================================================

        else:

            send_message(
                chat_id,

                "❌ فرمت لینک پست "
                "قابل تشخیص نیست.\n\n"

                "لینک دریافت‌شده:\n"
                f"{original_link}\n\n"

                "فرمت‌های قابل قبول:\n"

                "1️⃣\n"
                "https://ble.ir/barghsb/134\n\n"

                "2️⃣\n"
                "https://ble.ir/c/6031103884/134\n\n"

                "3️⃣\n"
                "https://ble.ir/barghsb/"
                "5259067422793579117/"
                "1788443437465"
            )

            return

        # =================================================
        # ذخیره هدف
        # =================================================

        save_target(
            channel_id=channel_id,
            username=username,
            message_id=message_id,
            link_channel_id=link_channel_id
        )

        # =================================================
        # پاسخ
        # =================================================

        result = (
            "✅ پست هدف با موفقیت ثبت شد.\n\n"
        )

        if username:

            result += (
                f"📢 کانال: @{username}\n"
            )

        if link_channel_id:

            result += (
                f"🔢 شناسه کانال لینک: "
                f"{link_channel_id}\n"
            )

        if channel_id:

            result += (
                f"🔢 شناسه کانال: "
                f"{channel_id}\n"
            )

        result += (
            f"🆔 شماره پیام: "
            f"{message_id}\n\n"

            "🟢 از این لحظه بازنشرهای "
            "این پست پایش می‌شوند."
        )

        send_message(
            chat_id,
            result
        )

        print(
            "TARGET SAVED:",
            "USERNAME=",
            username,
            "CHANNEL_ID=",
            channel_id,
            "LINK_CHANNEL_ID=",
            link_channel_id,
            "MESSAGE_ID=",
            message_id
        )

        return

    # =====================================================
    # TARGET
    # =====================================================

    if text == "/target":

        target = get_target()

        if not target:

            send_message(
                chat_id,
                "❌ هنوز پست هدف ثبت نشده است."
            )

            return

        result = (
            "🎯 هدف فعلی:\n\n"
        )

        if target["username"]:

            result += (
                f"📢 کانال: "
                f"@{target['username']}\n"
            )

        if target["link_channel_id"]:

            result += (
                f"🔢 شناسه داخل لینک: "
                f"{target['link_channel_id']}\n"
            )

        if target["channel_id"]:

            result += (
                f"🔢 شناسه کانال: "
                f"{target['channel_id']}\n"
            )

        result += (
            f"🆔 شماره پیام: "
            f"{target['message_id']}"
        )

        send_message(
            chat_id,
            result
        )

        return

    # =====================================================
    # REPORT
    # =====================================================

    if text == "/report":

        send_message(
            chat_id,
            get_report()
        )

        return

    # =====================================================
    # ADD CHANNEL
    # =====================================================

    if text.startswith(
        "/addchannel"
    ):

        parts = text.split(
            maxsplit=1
        )

        if len(parts) < 2:

            send_message(
                chat_id,

                "❌ نام کانال را وارد کنید.\n\n"

                "مثال:\n"
                "/addchannel mammalss"
            )

            return

        username = parts[1].strip()

        ok, result = add_channel(
            username
        )

        if ok:

            send_message(
                chat_id,
                "✅ " + result
            )

        else:

            send_message(
                chat_id,
                "❌ " + result
            )

        return

    # =====================================================
    # LIST CHANNELS
    # =====================================================

    if text == "/listchannels":

        channels = get_channels()

        if not channels:

            send_message(
                chat_id,
                "❌ هنوز کانالی ثبت نشده است."
            )

            return

        result = (
            f"📋 کانال‌های فعال "
            f"({len(channels)} مورد):\n\n"
        )

        for i, channel in enumerate(
            channels,
            1
        ):

            result += (
                f"{i}. @{channel['username']}\n"
            )

        send_message(
            chat_id,
            result
        )

        return

    # =====================================================
    # REMOVE CHANNEL
    # =====================================================

    if text.startswith(
        "/removechannel"
    ):

        parts = text.split(
            maxsplit=1
        )

        if len(parts) < 2:

            send_message(
                chat_id,
                "❌ نام کانال را وارد کنید."
            )

            return

        username = parts[1].strip()

        if remove_channel(
            username
        ):

            send_message(
                chat_id,

                f"✅ کانال @{username} "
                "غیرفعال شد."
            )

        else:

            send_message(
                chat_id,
                "❌ خطا در حذف کانال."
            )

        return

    # =====================================================
    # STATUS
    # =====================================================

    if text == "/status":

        channels = get_channels()
        target = get_target()

        result = (
            "🤖 وضعیت ربات\n\n"
        )

        result += (
            f"📡 کانال‌های فعال: "
            f"{len(channels)}\n"
        )

        if target:

            if target["username"]:

                result += (
                    f"🎯 هدف: "
                    f"@{target['username']}/"
                    f"{target['message_id']}\n"
                )

            else:

                result += (
                    f"🎯 هدف: "
                    f"{target['message_id']}\n"
                )

        else:

            result += (
                "🎯 هدف: ثبت نشده\n"
            )

        result += (
            "\n🟢 ربات فعال است."
        )

        send_message(
            chat_id,
            result
        )

        return


# =========================================================
# CHANNEL MESSAGE
# =========================================================

def process_channel_message(message):

    chat = message.get(
        "chat",
        {}
    )

    channel_username = (
        chat.get("username")
        or ""
    ).replace(
        "@",
        ""
    ).lower().strip()

    if not channel_username:

        print(
            "CHANNEL WITHOUT USERNAME"
        )

        return

    # -----------------------------------------------------
    # بررسی کانال‌های مجاز
    # -----------------------------------------------------

    channels = get_channels()

    allowed = False

    for channel in channels:

        saved_username = (
            channel.get(
                "username",
                ""
            )
            .replace("@", "")
            .lower()
            .strip()
        )

        if (
            saved_username
            == channel_username
        ):

            allowed = True

            break

    if not allowed:

        print(
            "IGNORED CHANNEL:",
            channel_username
        )

        return

    message_id = message.get(
        "message_id"
    )

    print(
        "CHANNEL MESSAGE:",
        channel_username,
        message_id
    )

    # -----------------------------------------------------
    # اطلاعات فوروارد
    # -----------------------------------------------------

    (
        forward_chat_id,
        forward_username,
        forward_message_id
    ) = extract_forward_info(
        message
    )

    print(
        "FORWARD:",
        forward_username,
        forward_message_id,
        "CHAT_ID:",
        forward_chat_id
    )

    # -----------------------------------------------------
    # آرشیو
    # -----------------------------------------------------

    save_channel_message(
        channel_username,
        message,
        forward_chat_id,
        forward_username,
        forward_message_id
    )

    # -----------------------------------------------------
    # هدف
    # -----------------------------------------------------

    target = get_target()

    if not target:

        return

    target_username = (
        target["username"]
    )

    target_channel_id = (
        target["channel_id"]
    )

    target_message_id = (
        target["message_id"]
    )

    # =====================================================
    # تطبیق
    # =====================================================

    matched = False

    # -----------------------------------------------------
    # تطبیق username + message_id
    # -----------------------------------------------------

    if (
        target_username
        and forward_username
        and
        forward_username.lower()
        == target_username.lower()
        and
        forward_message_id
        == target_message_id
    ):

        matched = True

    # -----------------------------------------------------
    # تطبیق channel ID + message_id
    # -----------------------------------------------------

    if (
        target_channel_id
        and forward_chat_id
        and
        int(forward_chat_id)
        == int(target_channel_id)
        and
        forward_message_id
        == target_message_id
    ):

        matched = True

    if not matched:

        return

    print(
        "🎯 TARGET FORWARD FOUND!"
    )

    # -----------------------------------------------------
    # جلوگیری از هشدار تکراری
    # -----------------------------------------------------

    if already_alerted(
        channel_username,
        message_id
    ):

        print(
            "ALREADY ALERTED:",
            channel_username,
            message_id
        )

        return

    # -----------------------------------------------------
    # ذخیره هشدار
    # -----------------------------------------------------

    save_alert(
        channel_username=
            channel_username,

        message_id=
            message_id,

        target_message_id=
            target_message_id,

        target_username=
            target_username,

        target_channel_id=
            target_channel_id
    )

    # -----------------------------------------------------
    # لینک پیام بازنشرشده
    # -----------------------------------------------------

    message_link = ""

    if channel_username:

        message_link = (
            "\n🔗 https://ble.ir/"
            f"{channel_username}/"
            f"{message_id}"
        )

    # -----------------------------------------------------
    # متن هشدار
    # -----------------------------------------------------

    alert_text = (
        "🚨 بازنشر پست هدف پیدا شد!\n\n"

        f"📢 کانال: @{channel_username}\n"

        f"🆔 شماره پیام: {message_id}\n"

        f"🎯 پست هدف: {target_message_id}\n"

        f"🕒 زمان ثبت: "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
        f"{message_link}"
    )

    send_message(
        OWNER_ID,
        alert_text
    )


# =========================================================
# PROCESS UPDATE
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
    # PRIVATE
    # -----------------------------------------------------

    if chat_type == "private":

        handle_command(
            message
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
# MAIN LOOP
# =========================================================

def main():

    print(
        "================================"
    )

    print(
        "BALE MONITOR STARTED"
    )

    print(
        "================================"
    )

    offset = 0

    while True:

        try:

            result = bale(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25
                }
            )

            if not result.get(
                "ok"
            ):

                print(
                    "GET UPDATES ERROR:",
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

                    update_id = (
                        update.get(
                            "update_id"
                        )
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
                        "UPDATE PROCESS ERROR:",
                        e
                    )

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                e
            )

            time.sleep(5)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    main()
