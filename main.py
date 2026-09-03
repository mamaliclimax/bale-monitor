import os
import time
import requests

TOKEN = os.environ.get("BALE_TOKEN")

if not TOKEN:
    raise RuntimeError("BALE_TOKEN is not configured")

API = f"https://tapi.bale.ai/bot{TOKEN}"

# شناسه کاربر صاحب ربات
OWNER_ID = None

# حداکثر تعداد کانال‌ها
MAX_CHANNELS = 100

# فهرست کانال‌های تحت پایش
CHANNELS = {}


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

    print("UPDATE:")
    print(update)

    message = update.get("message")

    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type")

    text = message.get("text", "") or ""

    # -------------------------
    # پیام خصوصی با ربات
    # -------------------------

    if chat_type == "private":

        if OWNER_ID is None:
            OWNER_ID = chat_id
            print("OWNER_ID:", OWNER_ID)

        if chat_id != OWNER_ID:
            return

        if text == "/start":

            send_message(
                chat_id,
                "🤖 ربات پایش بازنشر فعال است.\n\n"
                "دستورات:\n\n"
                "/addchannel\n"
                "افزودن کانال\n\n"
                "/listchannels\n"
                "نمایش کانال‌ها\n\n"
                "/removechannel\n"
                "حذف کانال"
            )

        elif text == "/listchannels":

            if not CHANNELS:
                send_message(
                    chat_id,
                    "📭 هنوز هیچ کانالی برای پایش ثبت نشده است."
                )
                return

            result = "📡 کانال‌های تحت پایش:\n\n"

            for number, (channel_id, channel) in enumerate(
                CHANNELS.items(), 1
            ):

                result += (
                    f"{number}. {channel['title']}\n"
                    f"@{channel['username']}\n\n"
                )

            send_message(chat_id, result)

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

            # فعلاً کانال را با نام کاربری ثبت می‌کنیم

            channel_key = username

            if channel_key in CHANNELS:

                send_message(
                    chat_id,
                    "⚠️ این کانال قبلاً اضافه شده است."
                )

                return

            CHANNELS[channel_key] = {
                "title": username,
                "username": username
            }

            send_message(
                chat_id,
                f"✅ کانال @{username} به فهرست پایش اضافه شد.\n\n"
                f"تعداد کانال‌ها: {len(CHANNELS)} از ۱۰۰"
            )

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
                    "❌ این کانال در فهرست پایش نیست."
                )

                return

            del CHANNELS[username]

            send_message(
                chat_id,
                f"✅ کانال @{username} حذف شد."
            )

        else:

            send_message(
                chat_id,
                "دستور نامعتبر است.\n\n"
                "برای مشاهده دستورات /start را بفرستید."
            )

        return

    # -------------------------
    # دریافت پست کانال
    # -------------------------

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
    print("BALE MONITOR V1")
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
