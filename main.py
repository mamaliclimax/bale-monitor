import os
import time
import hashlib
import requests
from supabase import create_client


# =========================
# تنظیمات
# =========================

TOKEN = os.environ.get("BALE_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")

MAX_CHANNELS = 100

if not TOKEN:
    raise RuntimeError("BALE_TOKEN is not configured")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is not configured")

if not SUPABASE_SECRET_KEY:
    raise RuntimeError("SUPABASE_SECRET_KEY is not configured")


API = f"https://tapi.bale.ai/bot{TOKEN}"

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)


OWNER_ID = None
TARGET_POST = None


# =========================
# ارتباط با Supabase
# =========================

def stable_id(username):
    """
    برای جدول channels یک شناسه عددی
    ثابت بر اساس نام کانال تولید می‌کند.
    """

    value = hashlib.sha256(
        username.encode("utf-8")
    ).hexdigest()

    return int(value[:15], 16)


def load_settings():

    global OWNER_ID
    global TARGET_POST

    try:

        result = (
            supabase
            .table("bot_settings")
            .select("key,value")
            .execute()
        )

        settings = {}

        for row in result.data or []:
            settings[row["key"]] = row["value"]

        if settings.get("owner_id"):
            OWNER_ID = int(settings["owner_id"])

        print("Settings loaded.")

    except Exception as error:

        print("SETTINGS LOAD ERROR:", error)


def save_setting(key, value):

    try:

        supabase.table("bot_settings").upsert(
            {
                "key": key,
                "value": str(value)
            }
        ).execute()

    except Exception as error:

        print("SETTING SAVE ERROR:", error)


def load_target():

    global TARGET_POST

    try:

        result = (
            supabase
            .table("target_posts")
            .select("*")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )

        rows = result.data or []

        if rows:

            row = rows[0]

            TARGET_POST = {
                "username": row["username"],
                "message_id": int(row["message_id"])
            }

            print(
                "Target loaded:",
                TARGET_POST
            )

        else:

            TARGET_POST = None

    except Exception as error:

        print("TARGET LOAD ERROR:", error)


def save_target(username, message_id):

    global TARGET_POST

    try:

        # فقط آخرین پست هدف نگهداری شود
        supabase.table("target_posts").delete().neq(
            "id",
            0
        ).execute()

        supabase.table("target_posts").insert(
            {
                "channel_id": stable_id(username),
                "username": username,
                "message_id": message_id
            }
        ).execute()

        TARGET_POST = {
            "username": username,
            "message_id": message_id
        }

        print("Target saved.")

    except Exception as error:

        print("TARGET SAVE ERROR:", error)


# =========================
# کانال‌ها
# =========================

def get_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("username")
            .eq("active", True)
            .order("created_at")
            .execute()
        )

        return [
            row["username"]
            for row in (result.data or [])
        ]

    except Exception as error:

        print("CHANNEL LOAD ERROR:", error)

        return []


def add_channel(username):

    try:

        existing = (
            supabase
            .table("channels")
            .select("username")
            .eq("username", username)
            .limit(1)
            .execute()
        )

        if existing.data:

            return False, "exists"

        channels = get_channels()

        if len(channels) >= MAX_CHANNELS:

            return False, "full"

        supabase.table("channels").insert(
            {
                "id": stable_id(username),
                "username": username,
                "active": True
            }
        ).execute()

        return True, "added"

    except Exception as error:

        print("CHANNEL ADD ERROR:", error)

        return False, "error"


def remove_channel(username):

    try:

        result = (
            supabase
            .table("channels")
            .delete()
            .eq("username", username)
            .execute()
        )

        return bool(result.data)

    except Exception as error:

        print("CHANNEL REMOVE ERROR:", error)

        return False


# =========================
# Bale API
# =========================

def call_api(method, data=None):

    response = requests.post(
        f"{API}/{method}",
        json=data or {},
        timeout=60
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):

        raise RuntimeError(result)

    return result.get("result")


def send_message(chat_id, text):

    return call_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


# =========================
# جلوگیری از هشدار تکراری
# =========================

def already_alerted(channel_username, message_id):

    try:

        result = (
            supabase
            .table("alerts")
            .select("id")
            .eq("channel_username", channel_username)
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as error:

        print("ALERT CHECK ERROR:", error)

        return False


def save_alert(
    channel_username,
    message_id,
    target_message_id
):

    try:

        supabase.table("alerts").insert(
            {
                "channel_username": channel_username,
                "message_id": message_id,
                "target_message_id": target_message_id
            }
        ).execute()

        return True

    except Exception as error:

        print("ALERT SAVE ERROR:", error)

        return False


# =========================
# پردازش پیام
# =========================

def process_update(update):

    global OWNER_ID

    print("UPDATE:")
    print(update)

    message = update.get("message")

    if not message:
        return

    chat = message.get("chat", {})

    chat_id = chat.get("id")
    chat_type = chat.get("type")

    text = message.get("text", "") or ""


    # =========================
    # پیام خصوصی
    # =========================

    if chat_type == "private":

        if OWNER_ID is None:

            OWNER_ID = chat_id

            save_setting(
                "owner_id",
                OWNER_ID
            )

            print(
                "OWNER REGISTERED:",
                OWNER_ID
            )

        if chat_id != OWNER_ID:
            return


        # =========================
        # /start
        # =========================

        if text == "/start":

            channels = get_channels()

            if TARGET_POST:

                target_text = (
                    f"@{TARGET_POST['username']} / "
                    f"{TARGET_POST['message_id']}"
                )

            else:

                target_text = "تنظیم نشده"


            send_message(
                chat_id,

                "🤖 ربات پایش بازنشر فعال است.\n\n"

                f"🎯 پست هدف:\n"
                f"{target_text}\n\n"

                f"📡 تعداد کانال‌های تحت پایش: "
                f"{len(channels)} از {MAX_CHANNELS}\n\n"

                "دستورات:\n\n"

                "/watch لینک پست\n"
                "تعیین پست هدف\n\n"

                "/addchannel @username\n"
                "افزودن کانال\n\n"

                "/listchannels\n"
                "فهرست کانال‌ها\n\n"

                "/removechannel @username\n"
                "حذف کانال\n\n"

                "/target\n"
                "نمایش پست هدف\n\n"

                "/status\n"
                "وضعیت ربات"
            )

            return


        # =========================
        # /watch
        # =========================

        if text.startswith("/watch"):

            parts = text.split()

            if len(parts) != 2:

                send_message(
                    chat_id,

                    "فرمت صحیح:\n\n"
                    "/watch https://ble.ir/barghsb/13"
                )

                return

            link = parts[1].strip()

            if "ble.ir/" not in link:

                send_message(
                    chat_id,
                    "❌ لینک بله معتبر نیست."
                )

                return

            try:

                clean = (
                    link
                    .split("?")[0]
                    .rstrip("/")
                )

                link_parts = clean.split("/")

                username = link_parts[-2]
                message_id = int(link_parts[-1])

            except Exception:

                send_message(
                    chat_id,

                    "❌ فرمت لینک صحیح نیست.\n\n"
                    "نمونه:\n"
                    "/watch https://ble.ir/barghsb/13"
                )

                return


            save_target(
                username,
                message_id
            )


            send_message(
                chat_id,

                "🎯 پست هدف ثبت شد.\n\n"

                f"📢 کانال: @{username}\n"
                f"🆔 پست: {message_id}\n\n"

                "از این به بعد بازنشر این پست بررسی می‌شود."
            )

            return


        # =========================
        # /target
        # =========================

        if text == "/target":

            load_target()

            if not TARGET_POST:

                send_message(
                    chat_id,
                    "🎯 هنوز پست هدفی ثبت نشده است."
                )

            else:

                send_message(
                    chat_id,

                    "🎯 پست هدف فعلی:\n\n"

                    f"📢 @{TARGET_POST['username']}\n"
                    f"🆔 پست: {TARGET_POST['message_id']}"
                )

            return


        # =========================
        # /addchannel
        # =========================

        if text.startswith("/addchannel"):

            parts = text.split()

            if len(parts) != 2:

                send_message(
                    chat_id,

                    "فرمت صحیح:\n\n"
                    "/addchannel @username"
                )

                return

            username = (
                parts[1]
                .replace("@", "")
                .strip()
            )

            success, result = add_channel(username)

            if result == "exists":

                send_message(
                    chat_id,
                    "⚠️ این کانال قبلاً ثبت شده است."
                )

            elif result == "full":

                send_message(
                    chat_id,
                    "❌ ظرفیت ۱۰۰ کانال تکمیل شده است."
                )

            elif success:

                count = len(get_channels())

                send_message(
                    chat_id,

                    f"✅ @{username} اضافه شد.\n\n"
                    f"📊 تعداد کانال‌ها: "
                    f"{count} از {MAX_CHANNELS}"
                )

            else:

                send_message(
                    chat_id,
                    "❌ هنگام ثبت کانال خطایی رخ داد."
                )

            return


        # =========================
        # /listchannels
        # =========================

        if text == "/listchannels":

            channels = get_channels()

            if not channels:

                send_message(
                    chat_id,
                    "📭 هنوز کانالی ثبت نشده است."
                )

                return


            result = "📡 کانال‌های تحت پایش:\n\n"

            for i, username in enumerate(
                channels,
                1
            ):

                result += (
                    f"{i}. @{username}\n"
                )


            send_message(
                chat_id,
                result
            )

            return


        # =========================
        # /removechannel
        # =========================

        if text.startswith("/removechannel"):

            parts = text.split()

            if len(parts) != 2:

                send_message(
                    chat_id,

                    "فرمت صحیح:\n\n"
                    "/removechannel @username"
                )

                return

            username = (
                parts[1]
                .replace("@", "")
                .strip()
            )

            if remove_channel(username):

                send_message(
                    chat_id,

                    f"✅ @{username} حذف شد."
                )

            else:

                send_message(
                    chat_id,

                    "❌ این کانال ثبت نشده است."
                )

            return


        # =========================
        # /status
        # =========================

        if text == "/status":

            channels = get_channels()

            target = "تنظیم نشده"

            if TARGET_POST:

                target = (
                    f"@{TARGET_POST['username']} / "
                    f"{TARGET_POST['message_id']}"
                )


            send_message(
                chat_id,

                "📊 وضعیت ربات\n\n"

                "🟢 ربات فعال است\n"
                f"📡 کانال‌ها: {len(channels)} / 100\n"
                f"🎯 هدف: {target}\n"
                "💾 ذخیره‌سازی: Supabase"
            )

            return

        return


    # =========================
    # پست کانال
    # =========================

    if chat_type == "channel":

        username = chat.get(
            "username",
            ""
        )

        message_id = message.get(
            "message_id"
        )


        channels = get_channels()

        if username not in channels:

            print(
                "CHANNEL NOT MONITORED:",
                username
            )

            return


        print(
            "CHECKING CHANNEL:",
            username,
            message_id
        )


        if not TARGET_POST:

            print("NO TARGET POST")

            return


        # =========================
        # اطلاعات Forward
        # =========================

        forward_chat = message.get(
            "forward_from_chat",
            {}
        )

        forward_message_id = message.get(
            "forward_from_message_id"
        )


        # =========================
        # هدف
        # =========================

        target_username = (
            TARGET_POST["username"]
        )

        target_message_id = (
            TARGET_POST["message_id"]
        )


        # =========================
        # تشخیص بازنشر مستقیم
        # =========================

        if (
            forward_message_id
            == target_message_id
            and
            forward_chat.get("username")
            == target_username
        ):

            print("MATCH FOUND!")


            # جلوگیری از هشدار تکراری

            if already_alerted(
                username,
                message_id
            ):

                print(
                    "DUPLICATE ALERT"
                )

                return


            save_alert(
                username,
                message_id,
                target_message_id
            )


            link = ""

            if username:

                link = (
                    f"https://ble.ir/"
                    f"{username}/"
                    f"{message_id}"
                )


            alert = (
                "🚨 بازنشر پیدا شد!\n\n"

                f"📢 کانال: @{username}\n"
                f"🆔 شماره پست: {message_id}\n\n"

                "🎯 پست اصلی:\n"
                f"@{target_username} / "
                f"{target_message_id}\n\n"

                f"🔗 {link}"
            )


            print(
                "SENDING ALERT"
            )


            if OWNER_ID:

                send_message(
                    OWNER_ID,
                    alert
                )


# =========================
# اجرای ربات
# =========================

def main():

    print(
        "=============================="
    )

    print(
        "BALE MONITOR V5 - SUPABASE"
    )

    print(
        "=============================="
    )


    load_settings()
    load_target()


    offset = 0


    while True:

        try:

            updates = call_api(
                "getUpdates",
                {
                    "offset": offset,
                    "limit": 100,
                    "timeout": 30
                }
            )


            for update in updates or []:

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


        except Exception as error:

            print(
                "ERROR:",
                error
            )

            time.sleep(5)


if __name__ == "__main__":

    main()
