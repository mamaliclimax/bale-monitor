import os
import time
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
# تنظیمات ربات
# =========================

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

        if (
            settings.get("target_username")
            and
            settings.get("target_message_id")
        ):

            TARGET_POST = {
                "username": settings["target_username"],
                "message_id": int(
                    settings["target_message_id"]
                )
            }

        print("SETTINGS LOADED")
        print("OWNER:", OWNER_ID)
        print("TARGET:", TARGET_POST)

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


# =========================
# پست هدف
# =========================

def save_target(username, message_id):

    global TARGET_POST

    try:

        supabase.table("bot_settings").upsert(
            {
                "key": "target_username",
                "value": username
            }
        ).execute()

        supabase.table("bot_settings").upsert(
            {
                "key": "target_message_id",
                "value": str(message_id)
            }
        ).execute()

        TARGET_POST = {
            "username": username,
            "message_id": message_id
        }

        print("TARGET SAVED:", TARGET_POST)

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

        # ID داخلی ثابت
        channel_id = abs(
            hash(username)
        ) % 900000000000000000

        supabase.table("channels").insert(
            {
                "id": channel_id,
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
# آرشیو پست‌های کانال
# =========================

def save_channel_message(
    username,
    message_id,
    text,
    forward_username,
    forward_message_id
):

    try:

        supabase.table(
            "channel_messages"
        ).upsert(
            {
                "channel_username": username,
                "message_id": message_id,
                "text": text,
                "forward_username": forward_username,
                "forward_message_id": forward_message_id
            },
            on_conflict="channel_username,message_id"
        ).execute()

        print(
            "MESSAGE SAVED:",
            username,
            message_id
        )

    except Exception as error:

        print(
            "MESSAGE SAVE ERROR:",
            error
        )


# =========================
# بررسی گزارش
# =========================

def get_report():

    if not TARGET_POST:
        return "🎯 هنوز پست هدفی ثبت نشده است."

    target_username = TARGET_POST["username"]
    target_message_id = TARGET_POST["message_id"]

    try:

        result = (
            supabase
            .table("channel_messages")
            .select(
                "channel_username,message_id"
            )
            .eq(
                "forward_username",
                target_username
            )
            .eq(
                "forward_message_id",
                target_message_id
            )
            .order("channel_username")
            .execute()
        )

        rows = result.data or []

        if not rows:

            return (
                "📊 گزارش بازنشر\n\n"
                f"🎯 پست هدف:\n"
                f"@{target_username} / "
                f"{target_message_id}\n\n"
                "❌ تاکنون بازنشر این پست "
                "در آرشیو پیدا نشد.\n\n"
                "⚠️ فقط پست‌هایی بررسی می‌شوند "
                "که ربات از زمان فعال بودن پایش "
                "دریافت کرده باشد."
            )


        text = (
            "📊 گزارش بازنشر\n\n"
            f"🎯 پست هدف:\n"
            f"@{target_username} / "
            f"{target_message_id}\n\n"
            f"✅ تعداد بازنشر پیدا شده: "
            f"{len(rows)}\n\n"
        )


        for index, row in enumerate(
            rows,
            1
        ):

            channel = row[
                "channel_username"
            ]

            message_id = row[
                "message_id"
            ]

            link = (
                f"https://ble.ir/"
                f"{channel}/"
                f"{message_id}"
            )

            text += (
                f"{index}. @{channel}\n"
                f"   🆔 پست: {message_id}\n"
                f"   🔗 {link}\n\n"
            )


        return text

    except Exception as error:

        print(
            "REPORT ERROR:",
            error
        )

        return (
            "❌ هنگام تهیه گزارش "
            "خطایی رخ داد."
        )


# =========================
# جلوگیری از هشدار تکراری
# =========================

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

        return bool(result.data)

    except Exception as error:

        print(
            "ALERT CHECK ERROR:",
            error
        )

        return False


def save_alert(
    channel_username,
    message_id,
    target_message_id
):

    try:

        supabase.table("alerts").insert(
            {
                "channel_username":
                    channel_username,

                "message_id":
                    message_id,

                "target_message_id":
                    target_message_id
            }
        ).execute()

        return True

    except Exception as error:

        print(
            "ALERT SAVE ERROR:",
            error
        )

        return False


# =========================
# پردازش پیام
# =========================

def process_update(update):

    global OWNER_ID

    message = update.get("message")

    if not message:
        return

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get("id")
    chat_type = chat.get("type")

    text = (
        message.get("text", "")
        or ""
    )


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

        if chat_id != OWNER_ID:
            return


        # /start

        if text == "/start":

            channels = get_channels()

            target = "تنظیم نشده"

            if TARGET_POST:

                target = (
                    f"@{TARGET_POST['username']} / "
                    f"{TARGET_POST['message_id']}"
                )

            send_message(
                chat_id,

                "🤖 ربات پایش بازنشر فعال است.\n\n"

                f"🎯 پست هدف:\n{target}\n\n"

                f"📡 کانال‌ها: "
                f"{len(channels)} از 100\n\n"

                "دستورات:\n\n"

                "/watch لینک پست\n"
                "🎯 تعیین پست هدف\n\n"

                "/report\n"
                "📊 گزارش بازنشر\n\n"

                "/addchannel @username\n"
                "➕ افزودن کانال\n\n"

                "/listchannels\n"
                "📡 فهرست کانال‌ها\n\n"

                "/removechannel @username\n"
                "➖ حذف کانال\n\n"

                "/target\n"
                "🎯 نمایش پست هدف\n\n"

                "/status\n"
                "📊 وضعیت ربات"
            )

            return


        # /watch

        if text.startswith("/watch"):

            parts = text.split()

            if len(parts) != 2:

                send_message(
                    chat_id,
                    "فرمت صحیح:\n\n"
                    "/watch https://ble.ir/barghsb/25"
                )

                return

            link = parts[1].strip()

            try:

                clean = (
                    link
                    .split("?")[0]
                    .rstrip("/")
                )

                link_parts = clean.split("/")

                username = link_parts[-2]
                message_id = int(
                    link_parts[-1]
                )

                if (
                    "ble.ir"
                    not in clean
                    or not username
                ):
                    raise ValueError()

            except Exception:

                send_message(
                    chat_id,

                    "❌ لینک صحیح نیست.\n\n"
                    "مثال:\n"
                    "/watch https://ble.ir/barghsb/25"
                )

                return


            save_target(
                username,
                message_id
            )


            send_message(
                chat_id,

                "🎯 پست هدف ثبت شد.\n\n"

                f"📢 @{username}\n"
                f"🆔 پست: {message_id}\n\n"

                "حالا می‌توانی /report بزنی."
            )

            return


        # /report

        if text == "/report":

            report = get_report()

            # اگر پیام خیلی طولانی شد،
            # در چند پیام ارسال می‌کنیم.

            if len(report) <= 4000:

                send_message(
                    chat_id,
                    report
                )

            else:

                for i in range(
                    0,
                    len(report),
                    4000
                ):

                    send_message(
                        chat_id,
                        report[i:i+4000]
                    )

            return


        # /target

        if text == "/target":

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
                    f"🆔 پست: "
                    f"{TARGET_POST['message_id']}"
                )

            return


        # /addchannel

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

            success, result = add_channel(
                username
            )

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

                count = len(
                    get_channels()
                )

                send_message(
                    chat_id,

                    f"✅ @{username} اضافه شد.\n\n"
                    f"📊 تعداد: {count} از 100"
                )

            else:

                send_message(
                    chat_id,
                    "❌ خطا در ثبت کانال."
                )

            return


        # /listchannels

        if text == "/listchannels":

            channels = get_channels()

            if not channels:

                send_message(
                    chat_id,
                    "📭 هنوز کانالی ثبت نشده است."
                )

                return

            result = (
                "📡 کانال‌های تحت پایش:\n\n"
            )

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


        # /removechannel

        if text.startswith(
            "/removechannel"
        ):

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


        # /status

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

                "🟢 فعال\n"
                f"📡 کانال‌ها: "
                f"{len(channels)} / 100\n"
                f"🎯 هدف: {target}\n"
                "💾 دیتابیس: Supabase"
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

            return


        # =========================
        # اطلاعات Forward
        # =========================

        forward_chat = message.get(
            "forward_from_chat",
            {}
        )

        forward_username = (
            forward_chat.get("username")
        )

        forward_message_id = (
            message.get(
                "forward_from_message_id"
            )
        )


        # =========================
        # ذخیره در آرشیو
        # =========================

        save_channel_message(
            username,
            message_id,
            text,
            forward_username,
            forward_message_id
        )


        # =========================
        # بررسی هدف فعلی
        # =========================

        if not TARGET_POST:
            return


        target_username = (
            TARGET_POST["username"]
        )

        target_message_id = (
            TARGET_POST["message_id"]
        )


        if (
            forward_message_id
            == target_message_id
            and
            forward_username
            == target_username
        ):

            print(
                "MATCH FOUND:",
                username,
                message_id
            )


            if already_alerted(
                username,
                message_id
            ):

                return


            save_alert(
                username,
                message_id,
                target_message_id
            )


            link = (
                f"https://ble.ir/"
                f"{username}/"
                f"{message_id}"
            )


            alert = (
                "🚨 بازنشر پیدا شد!\n\n"

                f"📢 کانال: @{username}\n"
                f"🆔 پست: {message_id}\n\n"

                "🎯 پست اصلی:\n"
                f"@{target_username} / "
                f"{target_message_id}\n\n"

                f"🔗 {link}"
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
        "BALE MONITOR V6"
    )

    print(
        "=============================="
    )


    load_settings()


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


                process_update(update)


        except Exception as error:

            print(
                "ERROR:",
                error
            )

            time.sleep(5)


if __name__ == "__main__":

    main()
