import os
import time
import re
import requests

TOKEN = os.environ.get("BALE_TOKEN")

if not TOKEN:
    raise RuntimeError("BALE_TOKEN is not configured")

API = f"https://tapi.bale.ai/bot{TOKEN}"

OWNER_ID = None
MAX_CHANNELS = 100

CHANNELS = {}
TARGET_POST = None


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
            print("OWNER_ID:", OWNER_ID)

        if chat_id != OWNER_ID:
            return

        # -------------------------
        # START
        # -------------------------

        if text == "/start":

            send_message(
                chat_id,
                "🤖 ربات پایش بازنشر فعال است.\n\n"
                "دستورات:\n\n"
                "/addchannel @username\n"
                "افزودن کانال\n\n"
                "/listchannels\n"
                "نمایش کانال‌ها\n\n"
                "/removechannel @username\n"
                "حذف کانال\n\n"
                "/watch لینک_پست\n"
                "انتخاب پست هدف\n\n"
                "/target\n"
                "نمایش پست هدف"
            )

        # -------------------------
        # ADD CHANNEL
        # -------------------------

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
                    "⚠️ این کانال قبلاً اضافه شده است."
                )

                return

            CHANNELS[username] = {
                "title": username,
                "username": username
            }

            send_message(
                chat_id,
                f"✅ کانال @{username} اضافه شد.\n\n"
                f"تعداد کانال‌ها: {len(CHANNELS)} از ۱۰۰"
            )

        # -------------------------
        # LIST CHANNELS
        # -------------------------

        elif text == "/listchannels":

            if not CHANNELS:

                send_message(
                    chat_id,
                    "📭 هنوز هیچ کانالی ثبت نشده است."
                )

                return

            result = "📡 کانال‌های تحت پایش:\n\n"

            for number, (username, channel) in enumerate(
                CHANNELS.items(), 1
            ):

                result += (
                    f"{number}. @{username}\n"
                )

            send_message(chat_id, result)

        # -------------------------
        # REMOVE CHANNEL
        # -------------------------

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
                    "❌ این کانال در فهرست نیست."
                )

                return

            del CHANNELS[username]

            send_message(
                chat_id,
                f"✅ کانال @{username} حذف شد."
            )

        # -------------------------
        # WATCH
        # -------------------------

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

            # تشخیص لینک بله
            match = re.search(
                r"ble\.ir/([^/]+)/(\d+)",
                link
            )

            if not match:

                send_message(
                    chat_id,
                    "❌ لینک معتبر بله پیدا نشد.\n\n"
                    "نمونه:\n"
                    "/watch https://ble.ir/barghsb/13"
                )

                return

            username = match.group(1)
            message_id = int(match.group(2))

            TARGET_POST = {
                "username": username,
                "message_id": message_id,
                "link": link
            }

            send_message(
                chat_id,
                "🎯 پست هدف ثبت شد.\n\n"
                f"کانال: @{username}\n"
                f"شماره پست: {message_id}\n\n"
                "حالا آماده مقایسه بازنشرها هستیم."
            )

        # -------------------------
        # TARGET
        # -------------------------

        elif text == "/target":

            if TARGET_POST is None:

                send_message(
                    chat_id,
                    "🎯 هنوز پست هدفی ثبت نشده است."
                )

            else:

                send_message(
                    chat_id,
                    "🎯 پست هدف فعلی:\n\n"
                    f"کانال: @{TARGET_POST['username']}\n"
                    f"شماره پست: {TARGET_POST['message_id']}\n"
                    f"لینک:\n{TARGET_POST['link']}"
                )

        else:

            send_message(
                chat_id,
                "دستور نامعتبر است.\n\n"
                "برای مشاهده دستورات /start را بفرستید."
            )

        return

    # =========================
    # پست کانال
    # =========================

    if chat_type == "channel":

        channel_id = chat.get("id")
        channel_title = chat.get("title", "")
        username = chat.get("username", "")
        message_id = message.get("message_id")

        print(
            "CHANNEL POST:",
            channel_id,
            channel_title,
            username,
            message_id
        )


def main():

    print("================================")
    print("BALE MONITOR V2")
    print("================================")

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
