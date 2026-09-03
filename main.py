import os
import time
import requests

TOKEN = os.environ.get("BALE_TOKEN")

if not TOKEN:
    raise RuntimeError("BALE_TOKEN is not configured")

API = f"https://tapi.bale.ai/bot{TOKEN}"


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
    print("UPDATE:")
    print(update)

    message = update.get("message")

    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    text = message.get("text", "")

    # پاسخ به /start
    if text == "/start":
        send_message(
            chat_id,
            "🤖 ربات پایش بازنشر فعال است.\n\n"
            "نسخه آزمایشی با موفقیت اجرا شد."
        )


def main():
    print("================================")
    print("BALE MONITOR STARTED")
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
