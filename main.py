import os
import time
import requests

TOKEN = os.getenv("BALE_TOKEN")

if not TOKEN:
    raise RuntimeError("BALE_TOKEN تنظیم نشده است")

API = f"https://tapi.bale.ai/bot{TOKEN}"


def bale(method, data=None):
    url = f"{API}/{method}"

    response = requests.post(
        url,
        json=data or {},
        timeout=40
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(result)

    return result.get("result")


def send_message(chat_id, text):
    return bale(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text
        }
    )


def main():
    print("Bale Monitor started...")

    offset = 0

    while True:
        try:
            updates = bale(
                "getUpdates",
                {
                    "offset": offset,
                    "limit": 100,
                    "timeout": 30
                }
            )

            for update in updates or []:

                offset = update["update_id"] + 1

                message = update.get("message")

                if not message:
                    continue

                chat = message.get("chat", {})
                chat_id = chat.get("id")

                text = message.get("text", "")

                print(
                    "Message:",
                    text,
                    "Chat:",
                    chat_id
                )

                if text == "/start":
                    send_message(
                        chat_id,
                        "🤖 ربات پایش بازنشر آماده است.\n\n"
                        "در نسخه بعدی امکان ثبت کانال‌ها و "
                        "پایش بازنشر پست‌ها اضافه می‌شود."
                    )

        except Exception as e:
            print("ERROR:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
