import os
import time
import requests

TOKEN = os.environ.get("BALE_TOKEN")

if not TOKEN:
    raise RuntimeError("BALE_TOKEN is not configured")

API = f"https://tapi.bale.ai/bot{TOKEN}"

OWNER_ID = None

CHANNELS = {}

TARGET_POST = {
    "channel_id": 6031103884,
    "username": "barghsb",
    "message_id": 13
}


def call_api(method, data=None):

    r = requests.post(
        f"{API}/{method}",
        json=data or {},
        timeout=60
    )

    r.raise_for_status()

    result = r.json()

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

        if chat_id != OWNER_ID:
            return

        if text == "/start":

            send_message(
                chat_id,
                "🤖 ربات پایش فعال است.\n\n"
                "پست هدف:\n"
                "@barghsb / 13\n\n"
                "دستورها:\n"
                "/addchannel @username\n"
                "/listchannels\n"
                "/removechannel @username"
            )

        elif text.startswith("/addchannel"):

            parts = text.split()

            if len(parts) != 2:
                send_message(
                    chat_id,
                    "فرمت صحیح:\n/addchannel @username"
                )
                return

            username = parts[1].replace("@", "")

            CHANNELS[username] = True

            send_message(
                chat_id,
                f"✅ @{username} به فهرست پایش اضافه شد.\n"
                f"تعداد کانال‌ها: {len(CHANNELS)}"
            )

        elif text == "/listchannels":

            if not CHANNELS:
                send_message(
                    chat_id,
                    "📭 کانالی ثبت نشده است."
                )
                return

            result = "📡 کانال‌های تحت پایش:\n\n"

            for i, username in enumerate(CHANNELS, 1):
                result += f"{i}. @{username}\n"

            send_message(chat_id, result)

        elif text.startswith("/removechannel"):

            parts = text.split()

            if len(parts) != 2:
                send_message(
                    chat_id,
                    "فرمت صحیح:\n/removechannel @username"
                )
                return

            username = parts[1].replace("@", "")

            if username in CHANNELS:
                del CHANNELS[username]

                send_message(
                    chat_id,
                    f"✅ @{username} حذف شد."
                )
            else:
                send_message(
                    chat_id,
                    "❌ این کانال در فهرست نیست."
                )

        return

    # =========================
    # پست کانال
    # =========================

    if chat_type == "channel":

        username = chat.get("username", "")
        message_id = message.get("message_id")

        # فقط کانال‌های ثبت‌شده را بررسی کن
        if username not in CHANNELS:
            print("CHANNEL NOT MONITORED:", username)
            return

        print(
            "CHECKING:",
            username,
            message_id
        )

        # =========================
        # بررسی Forward
        # =========================

        forward_chat = message.get("forward_from_chat", {})
        forward_message_id = message.get(
            "forward_from_message_id"
        )

        forward_chat_id = forward_chat.get("id")

        target_channel_id = TARGET_POST["channel_id"]
        target_message_id = TARGET_POST["message_id"]

        if (
            forward_chat_id == target_channel_id
            and
            forward_message_id == target_message_id
        ):

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
                f"🆔 پست: {message_id}\n\n"
                "🎯 پست اصلی:\n"
                "@barghsb / 13\n\n"
                f"🔗 {link}"
            )

            print("🚨 MATCH FOUND!")

            if OWNER_ID:
                send_message(
                    OWNER_ID,
                    alert
                )


def main():

    print("==============================")
    print("BALE MONITOR V3")
    print("==============================")

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
