import os
import time
import hashlib
import requests
from supabase import create_client


# =========================
# SETTINGS
# =========================

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

OWNER_ID = None
TARGET_POST = None


# =========================
# BALE API
# =========================

def bale(method, data=None):

    try:
        r = requests.post(
            f"{BASE_URL}/{method}",
            json=data or {},
            timeout=60
        )

        return r.json()

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


# =========================
# SETTINGS DATABASE
# =========================

def load_settings():

    global OWNER_ID
    global TARGET_POST

    try:

        result = supabase.table("bot_settings").select("*").execute()

        for row in result.data or []:

            key = row.get("key")
            value = row.get("value")

            if key == "owner_id":
                OWNER_ID = int(value)

            elif key == "target_username":
                if TARGET_POST is None:
                    TARGET_POST = {}

                TARGET_POST["username"] = value

            elif key == "target_message_id":
                if TARGET_POST is None:
                    TARGET_POST = {}

                TARGET_POST["message_id"] = int(value)

    except Exception as e:

        print("LOAD SETTINGS ERROR:", e)


def save_setting(key, value):

    try:

        supabase.table("bot_settings").upsert(
            {
                "key": key,
                "value": str(value)
            },
            on_conflict="key"
        ).execute()

    except Exception as e:

        print("SAVE SETTING ERROR:", e)


def save_target(username, message_id):

    global TARGET_POST

    username = username.replace("@", "").strip()

    TARGET_POST = {
        "username": username,
        "message_id": int(message_id)
    }

    save_setting("target_username", username)
    save_setting("target_message_id", message_id)

    print(
        "TARGET SAVED:",
        username,
        message_id
    )


# =========================
# CHANNELS
# =========================

def stable_channel_id(username):

    h = hashlib.sha256(
        username.encode("utf-8")
    ).hexdigest()

    return int(h[:15], 16)


def add_channel(username):

    username = username.replace("@", "").strip()

    if not username:
        return False

    try:

        existing = (
            supabase
            .table("channels")
            .select("*")
            .eq("username", username)
            .execute()
        )

        if existing.data:
            return True

        channel_id = stable_channel_id(username)

        supabase.table("channels").insert(
            {
                "id": channel_id,
                "username": username,
                "title": username,
                "active": True
            }
        ).execute()

        return True

    except Exception as e:

        print("ADD CHANNEL ERROR:", e)

        return False


def remove_channel(username):

    username = username.replace("@", "").strip()

    try:

        supabase.table("channels").delete().eq(
            "username",
            username
        ).execute()

        return True

    except Exception as e:

        print("REMOVE CHANNEL ERROR:", e)

        return False


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

        print("GET CHANNELS ERROR:", e)

        return []


# =========================
# FORWARD DETECTION
# =========================

def extract_forward_info(message):

    """
    Supports both Bale forward formats:

    1. forward_from_chat
       forward_from_message_id

    2. forward_origin
       chat
       message_id
    """

    forward_username = None
    forward_message_id = None

    # --------------------------------
    # Old / direct fields
    # --------------------------------

    forward_chat = message.get(
        "forward_from_chat"
    )

    if isinstance(forward_chat, dict):

        forward_username = forward_chat.get(
            "username"
        )

    forward_message_id = message.get(
        "forward_from_message_id"
    )

    # --------------------------------
    # New forward_origin format
    # --------------------------------

    if not forward_username or not forward_message_id:

        origin = message.get(
            "forward_origin"
        )

        if isinstance(origin, dict):

            if origin.get("type") == "channel":

                chat = origin.get(
                    "chat",
                    {}
                )

                if isinstance(chat, dict):

                    forward_username = (
                        chat.get("username")
                        or forward_username
                    )

                forward_message_id = (
                    origin.get("message_id")
                    or forward_message_id
                )

    if forward_username:

        forward_username = (
            str(forward_username)
            .replace("@", "")
            .strip()
        )

    if forward_message_id:

        try:
            forward_message_id = int(
                forward_message_id
            )
        except:
            pass

    return (
        forward_username,
        forward_message_id
    )


# =========================
# SAVE CHANNEL MESSAGE
# =========================

def save_channel_message(
    channel_username,
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
                "channel_username": channel_username,
                "message_id": message_id,
                "text": text,
                "forward_username": forward_username,
                "forward_message_id": forward_message_id
            },
            on_conflict="channel_username,message_id"
        ).execute()

        print(
            "ARCHIVED:",
            channel_username,
            message_id,
            "FORWARD:",
            forward_username,
            forward_message_id
        )

    except Exception as e:

        print(
            "ARCHIVE ERROR:",
            e
        )


# =========================
# ALERTS
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
            .execute()
        )

        return bool(result.data)

    except Exception as e:

        print(
            "ALERT CHECK ERROR:",
            e
        )

        return False


def save_alert(
    channel_username,
    message_id,
    target_username,
    target_message_id
):

    try:

        supabase.table("alerts").upsert(
            {
                "channel_username": channel_username,
                "message_id": message_id,
                "target_username": target_username,
                "target_message_id": target_message_id
            },
            on_conflict="channel_username,message_id"
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


# =========================
# REPORT
# =========================

def get_report():

    if not TARGET_POST:
        return []

    target_username = (
        TARGET_POST["username"]
    )

    target_message_id = int(
        TARGET_POST["message_id"]
    )

    found = {}

    # --------------------------------
    # Search alerts
    # --------------------------------

    try:

        result = (
            supabase
            .table("alerts")
            .select("*")
            .eq(
                "target_username",
                target_username
            )
            .eq(
                "target_message_id",
                target_message_id
            )
            .order(
                "created_at",
                desc=False
            )
            .execute()
        )

        for row in result.data or []:

            key = (
                row.get("channel_username"),
                row.get("message_id")
            )

            found[key] = row

    except Exception as e:

        print(
            "REPORT ALERT ERROR:",
            e
        )

    # --------------------------------
    # Search archived messages
    # --------------------------------

    try:

        result = (
            supabase
            .table("channel_messages")
            .select("*")
            .eq(
                "forward_username",
                target_username
            )
            .eq(
                "forward_message_id",
                target_message_id
            )
            .order(
                "created_at",
                desc=False
            )
            .execute()
        )

        for row in result.data or []:

            key = (
                row.get("channel_username"),
                row.get("message_id")
            )

            found[key] = row

    except Exception as e:

        print(
            "REPORT ARCHIVE ERROR:",
            e
        )

    return list(found.values())


# =========================
# COMMAND HANDLER
# =========================

def handle_command(message):

    global OWNER_ID

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get("id")

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text.startswith("/"):
        return

    parts = text.split()

    command = parts[0].split("@")[0].lower()

    # --------------------------------
    # START
    # --------------------------------

    if command == "/start":

        if OWNER_ID is None:

            OWNER_ID = chat_id

            save_setting(
                "owner_id",
                chat_id
            )

        send_message(
            chat_id,
            "🤖 ربات پایش بازنشر آماده است.\n\n"
            "دستورها:\n"
            "/watch لینک پست هدف\n"
            "/report گزارش بازنشر\n"
            "/target هدف فعلی\n"
            "/addchannel نام کانال\n"
            "/listchannels فهرست کانال‌ها\n"
            "/removechannel نام کانال\n"
            "/status وضعیت ربات"
        )

        return

    # --------------------------------
    # WATCH
    # --------------------------------

    if command == "/watch":

        if len(parts) < 2:

            send_message(
                chat_id,
                "❌ لینک پست را وارد کن.\n\n"
                "مثال:\n"
                "/watch https://ble.ir/barghsb/25"
            )

            return

        link = parts[1].strip()

        try:

            clean = (
                link
                .replace(
                    "https://ble.ir/",
                    ""
                )
                .replace(
                    "http://ble.ir/",
                    ""
                )
                .strip("/")
            )

            pieces = clean.split("/")

            username = pieces[0]

            message_id = int(
                pieces[1]
            )

            save_target(
                username,
                message_id
            )

            send_message(
                chat_id,
                "✅ پست هدف ثبت شد.\n\n"
                f"🎯 @{username}\n"
                f"🆔 پیام: {message_id}\n\n"
                "حالا پست را در یکی از کانال‌های تحت پایش فوروارد کن و سپس /report را بزن."
            )

        except Exception as e:

            print(
                "WATCH ERROR:",
                e
            )

            send_message(
                chat_id,
                "❌ لینک پست صحیح نیست."
            )

        return

    # --------------------------------
    # TARGET
    # --------------------------------

    if command == "/target":

        if not TARGET_POST:

            send_message(
                chat_id,
                "❌ هنوز پستی برای پایش ثبت نشده."
            )

        else:

            send_message(
                chat_id,
                "🎯 هدف فعلی:\n\n"
                f"@{TARGET_POST['username']}\n"
                f"🆔 پیام: {TARGET_POST['message_id']}"
            )

        return

    # --------------------------------
    # REPORT
    # --------------------------------

    if command == "/report":

        if not TARGET_POST:

            send_message(
                chat_id,
                "❌ ابتدا یک پست با /watch ثبت کن."
            )

            return

        results = get_report()

        target_username = (
            TARGET_POST["username"]
        )

        target_message_id = (
            TARGET_POST["message_id"]
        )

        if not results:

            send_message(
                chat_id,
                "📊 گزارش بازنشر\n\n"
                "🎯 پست هدف:\n"
                f"@{target_username} / {target_message_id}\n\n"
                "❌ هنوز بازنشر این پست در کانال‌های تحت پایش پیدا نشد.\n\n"
                "⚠️ فقط پست‌هایی قابل گزارش هستند که ربات بعد از فعال بودن پایش دریافت کرده باشد."
            )

            return

        report = (
            "📊 گزارش بازنشر\n\n"
            "🎯 پست هدف:\n"
            f"@{target_username} / {target_message_id}\n\n"
            f"✅ تعداد بازنشرهای پیدا شده: {len(results)}\n\n"
        )

        for i, row in enumerate(
            results,
            1
        ):

            channel = (
                row.get("channel_username")
                or "نامشخص"
            )

            message_id = (
                row.get("message_id")
                or "-"
            )

            created_at = (
                row.get("created_at")
                or "-"
            )

            report += (
                f"{i}️⃣ @{channel}\n"
                f"   🆔 پیام: {message_id}\n"
                f"   🕒 زمان ثبت: {created_at}\n\n"
            )

        send_message(
            chat_id,
            report
        )

        return

    # --------------------------------
    # ADD CHANNEL
    # --------------------------------

    if command == "/addchannel":

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/addchannel mammalss"
            )

            return

        username = parts[1]

        if add_channel(username):

            send_message(
                chat_id,
                f"✅ کانال @{username.replace('@','')} اضافه شد."
            )

        else:

            send_message(
                chat_id,
                "❌ اضافه کردن کانال انجام نشد."
            )

        return

    # --------------------------------
    # LIST CHANNELS
    # --------------------------------

    if command == "/listchannels":

        channels = get_channels()

        if not channels:

            send_message(
                chat_id,
                "📭 هنوز کانالی ثبت نشده."
            )

            return

        text_out = (
            "📋 کانال‌های تحت پایش:\n\n"
        )

        for i, channel in enumerate(
            channels,
            1
        ):

            username = (
                channel.get("username")
                or "-"
            )

            text_out += (
                f"{i}. @{username}\n"
            )

        send_message(
            chat_id,
            text_out
        )

        return

    # --------------------------------
    # REMOVE CHANNEL
    # --------------------------------

    if command == "/removechannel":

        if len(parts) < 2:

            send_message(
                chat_id,
                "مثال:\n/removechannel mammalss"
            )

            return

        username = parts[1]

        if remove_channel(username):

            send_message(
                chat_id,
                f"✅ کانال @{username.replace('@','')} حذف شد."
            )

        else:

            send_message(
                chat_id,
                "❌ حذف کانال انجام نشد."
            )

        return

    # --------------------------------
    # STATUS
    # --------------------------------

    if command == "/status":

        channels = get_channels()

        target = "ندارد"

        if TARGET_POST:

            target = (
                f"@{TARGET_POST['username']} / "
                f"{TARGET_POST['message_id']}"
            )

        send_message(
            chat_id,
            "🤖 وضعیت ربات\n\n"
            "🟢 فعال\n"
            f"📡 کانال‌های تحت پایش: {len(channels)}\n"
            f"🎯 هدف: {target}"
        )

        return


# =========================
# CHANNEL MESSAGE PROCESSOR
# =========================

def process_channel_message(message):

    chat = message.get(
        "chat",
        {}
    )

    if chat.get("type") != "channel":
        return

    channel_username = (
        chat.get("username")
    )

    if not channel_username:
        return

    channel_username = (
        channel_username
        .replace("@", "")
        .strip()
    )

    message_id = message.get(
        "message_id"
    )

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    (
        forward_username,
        forward_message_id
    ) = extract_forward_info(
        message
    )

    print(
        "CHANNEL MESSAGE:",
        channel_username,
        message_id
    )

    print(
        "FORWARD:",
        forward_username,
        forward_message_id
    )

    # --------------------------------
    # Archive
    # --------------------------------

    save_channel_message(
        channel_username,
        message_id,
        text,
        forward_username,
        forward_message_id
    )

    # --------------------------------
    # Target check
    # --------------------------------

    if not TARGET_POST:
        return

    target_username = (
        TARGET_POST["username"]
    )

    target_message_id = int(
        TARGET_POST["message_id"]
    )

    if (
        forward_username == target_username
        and
        forward_message_id == target_message_id
    ):

        print(
            "🎯 TARGET FORWARD FOUND!"
        )

        if not already_alerted(
            channel_username,
            message_id
        ):

            save_alert(
                channel_username,
                message_id,
                target_username,
                target_message_id
            )

            if OWNER_ID:

                send_message(
                    OWNER_ID,
                    "🚨 بازنشر پست هدف پیدا شد!\n\n"
                    f"🎯 @{target_username} / {target_message_id}\n\n"
                    f"📢 کانال: @{channel_username}\n"
                    f"🆔 پیام: {message_id}\n\n"
                    f"🔗 https://ble.ir/{channel_username}/{message_id}"
                )


# =========================
# UPDATE PROCESSOR
# =========================

def process_update(update):

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

    if chat_type in (
        "private",
        "group",
        "supergroup"
    ):

        handle_command(
            message
        )

    elif chat_type == "channel":

        process_channel_message(
            message
        )


# =========================
# MAIN LOOP
# =========================

def main():

    print(
        "================================="
    )

    print(
        "BALE MONITOR V7 STARTED"
    )

    print(
        "================================="
    )

    load_settings()

    offset = None

    while True:

        try:

            data = bale(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 50
                }
            )

            if not data.get("ok"):

                print(
                    "GET UPDATES ERROR:",
                    data
                )

                time.sleep(5)

                continue

            updates = (
                data.get("result")
                or []
            )

            for update in updates:

                print(
                    "UPDATE:",
                    update
                )

                offset = (
                    update["update_id"] + 1
                )

                process_update(
                    update
                )

        except Exception as e:

            print(
                "MAIN ERROR:",
                e
            )

            time.sleep(5)


if __name__ == "__main__":

    main()
