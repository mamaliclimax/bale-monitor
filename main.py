import os
import time
import json
import requests

TOKEN = os.environ.get("BALE_TOKEN")

if not TOKEN:
    raise RuntimeError("BALE_TOKEN is not configured")

API = f"https://tapi.bale.ai/bot{TOKEN}"

DATA_FILE = "data.json"
MAX_CHANNELS = 100

OWNER_ID = None

CHANNELS = {}
TARGET_POST = None
ALERTED_POSTS = []


# =========================
# ذخیره و خواندن اطلاعات
# =========================

def load_data():

    global OWNER_ID
    global CHANNELS
    global TARGET_POST
    global ALERTED_POSTS

    if not os.path.exists(DATA_FILE):
        print("No data file. Starting fresh.")
        return

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        OWNER_ID = data.get("owner_id")
        CHANNELS = data.get("channels", {})
        TARGET_POST = data.get("target_post")
        ALERTED_POSTS = data.get("alerted_posts", [])

        print("Data loaded successfully.")

    except Exception as error:

        print("DATA LOAD ERROR:", error)


def save_data():

    data = {
        "owner_id": OWNER_ID,
        "channels": CHANNELS,
        "target_post": TARGET_POST,
        "alerted_posts": ALERTED_POSTS[-1000:]
    }

    try:

        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )

        print("Data saved.")

    except Exception as error:

        print("DATA SAVE ERROR:", error)


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
# پردازش پیام
# =========================

def process_update(update):

    global OWNER_ID
    global TARGET_POST

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
            save_data()

        if chat_id != OWNER_ID:
            return

        # /start
        if text == "/start":

            target_text = "تنظیم نشده"

            if TARGET_POST:

                target_text = (
                    f"@{TARGET_POST['username']} / "
                    f"{TARGET_POST['message_id']}"
                )

            send_message(
                chat_id,
                "🤖 ربات پایش بازنشر فعال است.\n\n"
                f"🎯 پست هدف: {target_text}\n\n"
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
                "نمایش پست هدف"
            )

        # /watch
        elif text.startswith("/watch"):

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

                clean = link.split("?")[0].rstrip("/")

                parts_link = clean.split("/")

                username = parts_link[-2]
                message_id = int(parts_link[-1])

            except Exception:

                send_message(
                    chat_id,
                    "❌ فرمت لینک صحیح نیست.\n\n"
                    "نمونه:\n"
                    "/watch https://ble.ir/barghsb/13"
                )

                return

            TARGET_POST = {
                "username": username,
                "message_id": message_id
            }

            save_data()

            send_message(
                chat_id,
                "🎯 پست هدف ثبت شد.\n\n"
                f"📢 کانال: @{username}\n"
                f"🆔 پست: {message_id}\n\n"
                "از این به بعد بازنشر این پست بررسی می‌شود."
            )

        # /target
        elif text == "/target":

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

        # /addchannel
        elif text.startswith("/addchannel"):

            parts = text.split()

            if len(parts) != 2:

                send_message(
                    chat_id,
                    "فرمت صحیح:\n\n"
                    "/addchannel @username"
                )

                return

            username = parts[1].replace("@", "").strip()

            if len(CHANNELS) >= MAX_CHANNELS:

                send_message(
                    chat_id,
                    "❌ ظرفیت ۱۰۰ کانال تکمیل شده است."
                )

                return

            if username in CHANNELS:

                send_message(
                    chat_id,
                    "⚠️ این کانال قبلاً ثبت شده است."
                )

                return

            CHANNELS[username] = True

            save_data()

            send_message(
                chat_id,
                f"✅ @{username} اضافه شد.\n\n"
                f"📊 تعداد کانال‌ها: "
                f"{len(CHANNELS)} از ۱۰۰"
            )

        # /listchannels
        elif text == "/listchannels":

            if not CHANNELS:

                send_message(
                    chat_id,
                    "📭 هنوز کانالی ثبت نشده است."
                )

                return

            result = "📡 کانال‌های تحت پایش:\n\n"

            for i, username in enumerate(
                CHANNELS.keys(), 1
            ):

                result += f"{i}. @{username}\n"

            send_message(chat_id, result)

        # /removechannel
        elif text.startswith("/removechannel"):

            parts = text.split()

            if len(parts) != 2:

                send_message(
                    chat_id,
                    "فرمت صحیح:\n\n"
                    "/removechannel @username"
                )

                return

            username = parts[1].replace("@", "").strip()

            if username not in CHANNELS:

                send_message(
                    chat_id,
                    "❌ این کانال ثبت نشده است."
                )

                return

            del CHANNELS[username]

            save_data()

            send_message(
                chat_id,
                f"✅ @{username} حذف شد."
            )

        return

    # =========================
    # پست کانال
    # =========================

    if chat_type == "channel":

        username = chat.get("username", "")
        message_id = message.get("message_id")

        if username not in CHANNELS:

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

        # اگر پست هدف نداریم
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

        forward_chat_id = forward_chat.get("id")

        forward_message_id = message.get(
            "forward_from_message_id"
        )

        # =========================
        # تشخیص بازنشر
        # =========================

        target_username = TARGET_POST["username"]
        target_message_id = TARGET_POST["message_id"]

        # فعلاً شناسه کانال اصلی را از username
        # نمی‌توانیم حدس بزنیم.
        #
        # بنابراین اگر Forward از کانال هدف باشد،
        # message_id باید برابر باشد و username
        # مقصد تحت پایش باشد.

        if (
            forward_message_id == target_message_id
            and
            forward_chat.get("username")
            == target_username
        ):

            alert_key = (
                f"{username}:{message_id}"
            )

            if alert_key in ALERTED_POSTS:

                print("DUPLICATE ALERT")

                return

            ALERTED_POSTS.append(alert_key)

            save_data()

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

            print("MATCH FOUND!")

            if OWNER_ID:

                send_message(
                    OWNER_ID,
                    alert
                )


# =========================
# اجرای ربات
# =========================

def main():

    print("==============================")
    print("BALE MONITOR V4")
    print("==============================")

    load_data()

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

                update_id = update.get("update_id")

                if update_id is not None:

                    offset = update_id + 1

                process_update(update)

        except Exception as error:

            print("ERROR:", error)

            time.sleep(5)


if __name__ == "__main__":

    main()
