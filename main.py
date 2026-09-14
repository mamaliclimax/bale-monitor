import os
import json
import re
import time
import traceback
import requests
import tempfile

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape

from supabase import create_client
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill


# =========================================================
# CONFIG
# =========================================================

BALE_TOKEN = os.environ.get("BALE_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")

# کلید هوش مصنوعی (Gemini) برای پاسخ‌گویی متنی در گروه‌ها.
# اختیاری است: اگر تنظیم نشود، قابلیت پاسخ‌گویی هوشمند در گروه
# غیرفعال می‌ماند ولی بقیه‌ی ربات (بازنشر/گزارش) طبق معمول کار می‌کند.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# حالت جست‌وجوی گوگل (google_search grounding) برای پاسخ‌های AI:
#   auto   (پیش‌فرض) - فقط وقتی سوال شبیه نیاز به اطلاعات به‌روز
#          باشد (خبر/امروز/قیمت/تاریخ/...) ابزار جست‌وجو فعال می‌شود
#   always - همیشه فعال (دقیق‌تر ولی هزینه‌بر‌تر و زودتر به سقف
#            سهمیه‌ی رایگان می‌خورد)
#   off    - همیشه خاموش (ارزان‌ترین حالت، بدون اطلاعات به‌روز)
GEMINI_SEARCH_MODE = os.environ.get("GEMINI_SEARCH_MODE", "auto").strip().lower()

# تعداد تلاش مجدد وقتی Gemini خطای rate limit (429) بدهد، و چند
# ثانیه بین هر تلاش صبر شود.
GEMINI_RETRY_ON_429 = int(os.environ.get("GEMINI_RETRY_ON_429", "1"))
GEMINI_RETRY_DELAY_SECONDS = int(os.environ.get("GEMINI_RETRY_DELAY_SECONDS", "3"))

# 🆘 Groq (پشتیبان/Fallback) - وقتی Gemini با خطا (مثلاً سقف
# سهمیه‌ی رایگان) مواجه شود، به‌جای سکوت یا پیام خطا، سوال را
# با Groq (که سقف رایگان روزانه‌ی خیلی بالاتری دارد) پاسخ می‌دهیم.
# اختیاری است: اگر GROQ_API_KEY تنظیم نشود، فال‌بک غیرفعال می‌ماند
# و رفتار قبلی (پیام خطا) ادامه پیدا می‌کند.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
# اگر GROQ_MODEL تنظیم شود، همیشه اول همان امتحان می‌شود. Groq
# مدل‌هایش را زیاد جابه‌جا/بازنشر می‌کند (چیزی که همین الان هم
# باعث خطای 404 model_not_found شد)، پس یک لیست از مدل‌های
# جایگزین هم داریم که به‌ترتیب امتحان می‌شوند تا یکی جواب بدهد؛
# اولین موردی که کار کند برای دفعات بعد کش می‌شود.
GROQ_MODEL = os.environ.get("GROQ_MODEL")
GROQ_MODEL_CANDIDATES = [
    m for m in [
        GROQ_MODEL,
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3-32b",
        "moonshotai/kimi-k2-instruct",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
    ]
    if m
]
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# اولین مدل Groq که کار کرده (برای جلوگیری از تکرار تست مدل‌های
# غیرفعال در هر درخواست).
GROQ_WORKING_MODEL = {"id": None}

# -----------------------------------------------------------
# 💾 تنظیمات قابل‌تغییر از طریق دستورات ربات (نه فقط env var)
#
# روی دیسک ذخیره می‌شود تا مالک ربات هر وقت خواست (بدون نیاز به
# ری‌دیپلوی یا تغییر env var) بتواند مثلاً مدل متنی Pollinations
# را عوض کند، و این تنظیم بعد از ری‌استارت هم باقی بماند.
# -----------------------------------------------------------
AI_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ai_settings.json"
)
_AI_SETTINGS_CACHE = None


def load_ai_settings():

    global _AI_SETTINGS_CACHE

    if _AI_SETTINGS_CACHE is not None:
        return _AI_SETTINGS_CACHE

    try:

        with open(AI_SETTINGS_FILE, "r", encoding="utf-8") as f:
            _AI_SETTINGS_CACHE = json.load(f)

    except Exception:

        _AI_SETTINGS_CACHE = {}

    return _AI_SETTINGS_CACHE


def save_ai_settings():

    try:

        with open(AI_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                _AI_SETTINGS_CACHE or {},
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            "AI SETTINGS SAVE ERROR:",
            repr(e)
        )


def get_ai_setting(key, default=None):

    return load_ai_settings().get(key, default)


def set_ai_setting(key, value):

    settings = load_ai_settings()
    settings[key] = value
    save_ai_settings()


# 🌸 Pollinations.ai (متن) - رایگان، بدون نیاز به کلید، به‌عنوان
# آخرین لایه‌ی پشتیبان بعد از Gemini و Groq استفاده می‌شود. از
# مدل‌های مختلف (openai، mistral، claude، gemini، deepseek،
# grok و...) پشتیبانی می‌کند؛ مدل پیش‌فرض با دستور /text_model
# توسط مالک ربات قابل‌تغییر است (بدون نیاز به ری‌دیپلوی).
POLLINATIONS_TEXT_URL = "https://text.pollinations.ai/openai"
POLLINATIONS_MODELS_URL = "https://text.pollinations.ai/models"
# کلید sk_ اختیاری (از enter.pollinations.ai) - فقط برای نرخ
# بالاتر/مدل‌های ویژه لازم است، بدونش هم کار می‌کند.
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY")


def get_pollinations_text_model():

    return get_ai_setting(
        "pollinations_text_model",
        os.environ.get("POLLINATIONS_TEXT_MODEL", "openai")
    )

# پاسخ صوتی: علاوه بر متن، یک پیام صوتی (Text-to-Speech) هم
# برای پاسخ ساخته و ارسال می‌شود. با ست کردن AI_VOICE_ENABLED=0
# می‌توان این قابلیت را خاموش کرد (بدون نیاز به تغییر کد).
AI_VOICE_ENABLED = os.environ.get("AI_VOICE_ENABLED", "1") != "0"
# نام صدای Microsoft Edge TTS. لیست صداهای فارسی:
# fa-IR-DilaraNeural (زن) و fa-IR-FaridNeural (مرد)
AI_VOICE_NAME = os.environ.get("AI_VOICE_NAME", "fa-IR-DilaraNeural")

# تبدیل «متن خبر» به صوت با موتور Google AI Studio (Gemini TTS).
# این قابلیت مستقل از AI_VOICE_ENABLED (که برای پاسخ سوالات است)
# با دستور /voice یا /خبر در خصوصی فعال می‌شود و برخلاف پاسخ AI،
# متن ورودی کاربر عیناً (بدون بازنویسی) خوانده می‌شود.
GEMINI_TTS_MODEL = os.environ.get(
    "GEMINI_TTS_MODEL",
    "gemini-3.1-flash-tts-preview"
)
# لیست صداهای آماده‌ی Gemini TTS: Aoede, Puck, Charon, Kore,
# Fenrir, Zephyr, Leda, Orus و... (مدل چندزبانه است و فارسی را
# هم از روی متن ورودی تشخیص می‌دهد).
GEMINI_TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Aoede")
# حداکثر طول متن خبر (کاراکتر) برای جلوگیری از هزینه/خطای زیاد
GEMINI_TTS_MAX_CHARS = int(
    os.environ.get("GEMINI_TTS_MAX_CHARS", "4000")
)

# Cloudflare Workers AI برای ساخت عکس (Flux)
# رایگان روزانه محدود (حدود ۱۰۰–۲۳۰ عکس در روز بسته به تنظیمات)
CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
# مدل پیش‌فرض: سریع و مناسب سطح رایگان
CLOUDFLARE_IMAGE_MODEL = os.environ.get(
    "CLOUDFLARE_IMAGE_MODEL",
    "@cf/black-forest-labs/flux-1-schnell"
)
# تعداد گام‌های دیفیوژن (۴ پیش‌فرض، حداکثر ۸ برای schnell)
CLOUDFLARE_IMAGE_STEPS = int(os.environ.get("CLOUDFLARE_IMAGE_STEPS", "4"))

if not BALE_TOKEN:
    raise Exception("BALE_TOKEN is missing")

if not SUPABASE_URL:
    raise Exception("SUPABASE_URL is missing")

if not SUPABASE_SECRET_KEY:
    raise Exception("SUPABASE_SECRET_KEY is missing")

if not GEMINI_API_KEY:
    print(
        "⚠️ WARNING: GEMINI_API_KEY is missing. "
        "AI text replies are disabled."
    )

if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
    print(
        "⚠️ WARNING: CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN missing. "
        "Cloudflare image generation disabled "
        "(Pollinations fallback still works for /image)."
    )

BALE_API = f"https://tapi.bale.ai/bot{BALE_TOKEN}"
GEMINI_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
GEMINI_TTS_API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_TTS_MODEL}:generateContent"
)
supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

IRAN_TZ = ZoneInfo("Asia/Tehran")


# =========================================================
# MEMORY
# =========================================================

BOT_INFO = None
PENDING_ACTIONS = {}
LAST_UPDATE_ID = None

# وضعیت موقت برای جریان «گزارش مبدأ ↔ مقصد» (دو مرحله‌ای:
# انتخاب مبدأ، سپس انتخاب مقصد از بین کانال‌های فعال).
PAIR_REPORT_STATE = {}

# آپدیت‌هایی که حتماً باید از سرور بله درخواست شوند.
# نکته‌ی مهم: اگر این پارامتر در getUpdates ارسال نشود، برخی
# سرورها (از جمله بله) آپدیت‌های my_chat_member / chat_member
# را که دقیقاً رویداد «اضافه/حذف شدن ربات از کانال یا گروه»
# هستند اصلاً ارسال نمی‌کنند. همین موضوع باعث می‌شد کانال یا
# گروهی که ربات به آن اضافه می‌شود در دیتابیس ثبت نشود و در
# نتیجه در گزارش کانال‌ها و گزارش بازنشر دیده نشود.
ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "callback_query",
    "my_chat_member",
    "chat_member",
    "chat_join_request"
]


# =========================================================
# BASIC HELPERS
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def to_persian_digits(value):
    if value is None:
        return ""

    return str(value).translate(
        str.maketrans(
            "0123456789",
            "۰۱۲۳۴۵۶۷۸۹"
        )
    )


def clean_username(username):
    if not username:
        return None

    username = str(username).strip()

    if username.startswith("@"):
        username = username[1:]

    return username or None


def safe_text(value):
    if value is None:
        return ""

    return str(value)


def html_text(value):
    return escape(
        safe_text(value),
        quote=False
    )


def html_attr(value):
    return escape(
        safe_text(value),
        quote=True
    )


# =========================================================
# MARKDOWN HELPERS
# =========================================================

def markdown_text(value):
    if value is None:
        return ""

    text = str(value)

    replacements = {
        "\\": "\\\\",
        "_": "\\_",
        "*": "\\*",
        "[": "\\[",
        "]": "\\]",
        "(": "\\(",
        ")": "\\)",
        "`": "\\`"
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def markdown_link(label, url, emoji=""):
    if not url:
        return ""

    url = str(url).strip()

    if not url:
        return ""

    return f"{emoji} [{markdown_text(label)}]({url})"


# =========================================================
# JALALI
# =========================================================

def gregorian_to_jalali(gy, gm, gd):

    g_days_in_month = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    ]

    j_days_in_month = [
        31, 31, 31, 31, 31, 31,
        30, 30, 30, 30, 30, 30
    ]

    gy -= 1600
    gm -= 1
    gd -= 1

    g_day_no = (
        365 * gy
        + (gy + 3) // 4
        - (gy + 99) // 100
        + (gy + 399) // 400
    )

    for i in range(gm):
        g_day_no += g_days_in_month[i]

    if gm > 1 and (
        (gy % 4 == 0 and gy % 100 != 0)
        or gy % 400 == 0
    ):
        g_day_no += 1

    g_day_no += gd

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = (
        979
        + 33 * j_np
        + 4 * (j_day_no // 1461)
    )

    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    i = 0

    while (
        i < 11
        and j_day_no >= j_days_in_month[i]
    ):
        j_day_no -= j_days_in_month[i]
        i += 1

    jm = i + 1
    jd = j_day_no + 1

    return jy, jm, jd


def format_iran_datetime(value):

    if not value:
        return "-"

    try:

        if isinstance(value, datetime):
            dt = value

        else:

            value = str(value).strip()

            if value.endswith("Z"):
                value = value[:-1] + "+00:00"

            dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt = dt.astimezone(IRAN_TZ)

        jy, jm, jd = gregorian_to_jalali(
            dt.year,
            dt.month,
            dt.day
        )

        date_text = f"{jy:04d}/{jm:02d}/{jd:02d}"
        time_text = f"{dt.hour:02d}:{dt.minute:02d}"

        return (
            f"{to_persian_digits(date_text)}"
            f" - "
            f"{to_persian_digits(time_text)}"
        )

    except Exception as e:

        print(
            "FORMAT DATETIME ERROR:",
            repr(e)
        )

        return str(value)


def humanize_elapsed_fa(value):

    if not value:
        return "-"

    try:

        if isinstance(value, datetime):
            dt = value

        else:

            value = str(value).strip()

            if value.endswith("Z"):
                value = value[:-1] + "+00:00"

            dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        seconds = int(
            (now - dt).total_seconds()
        )

        if seconds < 0:
            seconds = 0

        if seconds < 60:
            return "چند لحظه پیش"

        minutes = seconds // 60

        if minutes < 60:

            return (
                f"{to_persian_digits(minutes)} "
                "دقیقه پیش"
            )

        hours = minutes // 60

        if hours < 24:

            return (
                f"{to_persian_digits(hours)} "
                "ساعت پیش"
            )

        days = hours // 24

        if days < 30:

            return (
                f"{to_persian_digits(days)} "
                "روز پیش"
            )

        months = days // 30

        if months < 12:

            return (
                f"{to_persian_digits(months)} "
                "ماه پیش"
            )

        years = days // 365

        return (
            f"{to_persian_digits(years)} "
            "سال پیش"
        )

    except Exception as e:

        print(
            "HUMANIZE ELAPSED ERROR:",
            repr(e)
        )

        return "-"


# =========================================================
# BALE API
# =========================================================

def bale_request(
    method,
    data=None,
    timeout=40
):

    url = f"{BALE_API}/{method}"

    try:

        response = requests.post(
            url,
            json=data or {},
            timeout=timeout
        )

        print(
            f"BALE {method}:",
            response.status_code
        )

        try:
            result = response.json()

        except Exception:

            print(
                "BALE RAW:",
                response.text[:3000]
            )

            return None

        if not result.get("ok"):

            print(
                f"BALE {method} ERROR:",
                result
            )

            return None

        return result.get("result")

    except Exception as e:

        print(
            f"BALE {method} EXCEPTION:",
            repr(e)
        )

        return None


# =========================================================
# AI (GEMINI) - پاسخ‌گویی متنی
# =========================================================

# حداکثر طول تاریخچه‌ای که به‌عنوان context نگه می‌داریم
AI_MAX_HISTORY = 6
# حافظه‌ی کوتاه‌مدت هر گفتگو (گروه یا خصوصی):
# { chat_id: [ {"role":..,"text":..}, ... ] }
AI_CHAT_HISTORY = {}

# -----------------------------------------------------------
# 🩹 پاکسازی «ادعای قطع اطلاعات» از تاریخچه
#
# اگر مدل حتی یک‌بار (مثلاً قبل از فعال شدن google_search، یا
# در یک پاسخ استثنایی) جمله‌ای شبیه «اطلاعات من تا فلان تاریخ
# است» بگوید، همان جمله وارد AI_CHAT_HISTORY می‌شود. از آن به
# بعد، در هر سوال جدید، این جمله‌ی خودِ مدل هم به‌عنوان بخشی از
# context به خودش داده می‌شود و مدل تمایل پیدا می‌کند با پاسخ
# قبلی‌اش هم‌راستا بماند و دوباره همان ادعا را تکرار کند (حتی
# با وجود دستور صریح در system prompt). برای همین، پیش از
# استفاده از تاریخچه، هر پاسخ قدیمی مدل که این الگو را دارد حذف
# می‌شود تا این چرخه‌ی تکرار قطع شود.
# -----------------------------------------------------------
AI_CUTOFF_DISCLAIMER_RE = re.compile(
    r"(اطلاعات(\s*و\s*دیتای)?\s*من\s*تا|"
    r"داده(‌|\s)?های\s*من\s*تا|"
    r"دیتای\s*من\s*تا|"
    r"دانش\s*من\s*تا|"
    r"تا\s*این\s*تاریخ\s*اطلاع|"
    r"اطلاع\s*دقیقی\s*ندارم|"
    r"به[‌\s]?روز\s*نیستم|"
    r"training data|knowledge cutoff|"
    r"قطع\s*(اطلاعات|آموزش))",
    re.IGNORECASE
)


def sanitize_ai_history(history):
    """
    از تاریخچه‌ی گفت‌وگو، پاسخ‌های قبلی مدل که ادعای «اطلاعاتم
    تا فلان تاریخه» یا مشابهش را دارند حذف می‌کند (همراه با
    پیام کاربر متناظرش)، تا این جمله دوباره به مدل «یادآوری»
    نشود. پیام‌های کاربر و سایر پاسخ‌های سالم دست‌نخورده باقی
    می‌مانند.
    """

    if not history:
        return history

    cleaned = []

    skip_next_user = False

    for item in history:

        role = item.get("role")
        item_text = item.get("text", "")

        if role == "model" and AI_CUTOFF_DISCLAIMER_RE.search(item_text):
            # این پاسخ مدل را حذف کن؛ چون معمولاً بلافاصله بعد
            # از یک سوال کاربر می‌آید که خودش هم دیگر لازم نیست
            # نگه داشته شود (برای جلوگیری از پیام‌های یتیم).
            continue

        cleaned.append(item)

    return cleaned


AI_PERSONA_PROMPT = (
    "تو یک دستیار هوشمند فارسی‌زبان هستی که داخل پیام‌رسان بله "
    "فعالیت می‌کنی. پاسخ‌هایت را کوتاه، مفید، محاوره‌ای و مودبانه بنویس. "
    "اگر سوال نامفهوم بود، مؤدبانه بپرس منظور دقیق‌تر چیست."
)

AI_SYSTEM_PROMPT = (
    AI_PERSONA_PROMPT + "\n\n"
    "به ابزار جست‌وجوی گوگل (google_search) دسترسی داری. برای هر سوالی "
    "درباره‌ی اخبار، اتفاقات روز، قیمت‌ها، یا هر چیزی که ممکن است بعد از "
    "زمان آموزشت تغییر کرده باشد، حتماً از این ابزار برای گرفتن اطلاعات "
    "به‌روز استفاده کن. هرگز نگو «اطلاعات من تا فلان تاریخ است» یا از "
    "پاسخ به سوالات مربوط به تاریخ امروز/اخبار جدید امتناع نکن؛ در عوض "
    "جست‌وجو کن و بر اساس نتایج جست‌وجو جواب بده."
)


def _today_ir_str():

    now_ir = datetime.now(IRAN_TZ)

    return now_ir.strftime("%Y-%m-%d %H:%M")


def get_ai_system_prompt():
    """
    system prompt (نسخه‌ی Gemini) را با تاریخ و ساعت امروز (به وقت
    ایران) همراه می‌کند تا مدل بداند «امروز» دقیقاً چه تاریخی است و
    به‌جای تکیه به تاریخ قطع آموزش خودش، از google_search برای
    اطلاعات جدید استفاده کند.
    """

    return (
        AI_SYSTEM_PROMPT +
        f"\n\nتاریخ و ساعت فعلی (به وقت ایران): {_today_ir_str()}"
    )


def get_groq_system_prompt():
    """
    system prompt برای Groq (بدون اشاره به google_search، چون این
    ابزار مخصوص Gemini است و Groq چنین ابزاری ندارد).
    """

    return (
        AI_PERSONA_PROMPT +
        f"\n\nتاریخ و ساعت فعلی (به وقت ایران): {_today_ir_str()}"
    )


# لیست مدل‌های واقعاً فعال Groq (از خودِ API گرفته می‌شود، چون
# لیست ثابت بالا ممکن است منسوخ شود - همان‌طور که همین الان هم
# چند مدلش decommissioned از آب درآمدند).
GROQ_MODELS_CACHE = {"ids": None}


def fetch_groq_available_models():
    """
    لیست id مدل‌های واقعاً در دسترس حساب Groq را از
    GET /openai/v1/models می‌گیرد و کش می‌کند (در طول عمر پردازش،
    یک‌بار). در صورت خطا، لیست خالی برمی‌گرداند (نه None) تا
    دوباره امتحان نکنیم.
    """

    if GROQ_MODELS_CACHE["ids"] is not None:
        return GROQ_MODELS_CACHE["ids"]

    ids = []

    if GROQ_API_KEY:

        try:

            response = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                timeout=15
            )

            if response.status_code == 200:

                data = response.json()

                ids = [
                    m.get("id")
                    for m in (data.get("data") or [])
                    if m.get("id")
                ]

            else:

                print(
                    "GROQ MODELS LIST ERROR:",
                    response.status_code,
                    response.text[:300]
                )

        except Exception as e:

            print(
                "GROQ MODELS LIST EXCEPTION:",
                repr(e)
            )

    GROQ_MODELS_CACHE["ids"] = ids

    return ids


def _is_groq_model_level_error(status_code, response_json):
    """
    تشخیص می‌دهد که آیا خطای Groq مربوط به «خودِ این مدل» است
    (پس باید کاندید بعدی را امتحان کرد) یا یک خطای عمومی‌تر است
    (کلید نامعتبر، rate limit خودِ Groq و...) که امتحان مدل‌های
    دیگر هم فایده‌ای ندارد.
    """

    if status_code == 404:
        return True

    error = (response_json or {}).get("error", {})

    error_code = str(error.get("code") or "").lower()
    error_message = str(error.get("message") or "").lower()

    model_error_codes = (
        "model_not_found",
        "model_decommissioned",
        "model_terminated",
        "invalid_model",
    )

    if error_code in model_error_codes:
        return True

    if "model" in error_code and (
        "not found" in error_message or
        "decommission" in error_message or
        "no longer" in error_message
    ):
        return True

    if "decommission" in error_message or "no longer supported" in error_message:
        return True

    return False


def ask_groq(prompt, history=None):
    """
    ارسال یک سوال متنی به Groq (از طریق API سازگار با OpenAI) و
    دریافت پاسخ. این تابع به‌عنوان پشتیبان/Fallback وقتی Gemini
    خطا بدهد (مثلاً سقف سهمیه) استفاده می‌شود. در صورت نبود کلید
    یا بروز خطا، None برمی‌گرداند. Groq ابزار جست‌وجوی گوگل ندارد،
    پس پاسخ‌هایش صرفاً از دانش خودِ مدل است.

    چون Groq مدل‌هایش را مرتب عوض/بازنشسته می‌کند، به‌جای تکیه به
    یک نام مدل ثابت، اول لیست واقعی مدل‌های در دسترس حساب را از
    API می‌گیرد و از بین کاندیدهای شناخته‌شده هر کدام که واقعاً
    موجود باشد را امتحان می‌کند تا یکی جواب بدهد؛ اولین مدل موفق
    برای دفعات بعد کش می‌شود تا هر بار همه را از اول تست نکنیم.
    """

    if not GROQ_API_KEY:
        return None

    if not prompt or not prompt.strip():
        return None

    messages = [
        {"role": "system", "content": get_groq_system_prompt()}
    ]

    for item in (history or []):

        role = "assistant" if item.get("role") == "model" else "user"

        messages.append({
            "role": role,
            "content": item.get("text", "")
        })

    messages.append({
        "role": "user",
        "content": prompt
    })

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}"
    }

    available_ids = fetch_groq_available_models()

    # ترتیب اولویت:
    # ۱. مدلی که قبلاً جواب داده (اگر داریم)
    # ۲. کاندیدهای شناخته‌شده‌ای که واقعاً در لیست حساب موجودند
    # ۳. اگر لیست حساب گرفته شد ولی هیچ‌کدام از کاندیدها توش
    #    نبود، بقیه‌ی مدل‌های متنی آن لیست (به‌جز whisper/tts/guard)
    # ۴. اگر گرفتن لیست حساب هم شکست خورد (خالی بود)، همان
    #    کاندیدهای ثابت را کورکورانه امتحان کن (بهتر از هیچی)
    ordered_models = []

    if GROQ_WORKING_MODEL["id"]:
        ordered_models.append(GROQ_WORKING_MODEL["id"])

    for model_id in GROQ_MODEL_CANDIDATES:

        if model_id in ordered_models:
            continue

        if not available_ids or model_id in available_ids:
            ordered_models.append(model_id)

    if available_ids:

        for model_id in available_ids:

            if model_id in ordered_models:
                continue

            lowered = model_id.lower()

            if any(
                skip in lowered
                for skip in ("whisper", "tts", "guard", "embed")
            ):
                continue

            ordered_models.append(model_id)

    if not ordered_models:
        return None

    for model_id in ordered_models:

        payload = {
            "model": model_id,
            "messages": messages
        }

        try:

            response = requests.post(
                GROQ_API_URL,
                headers=headers,
                json=payload,
                timeout=40
            )

            if response.status_code == 200:

                data = response.json()

                choices = data.get("choices") or []

                if not choices:
                    return None

                answer = (
                    choices[0]
                    .get("message", {})
                    .get("content", "")
                ).strip()

                if answer:
                    GROQ_WORKING_MODEL["id"] = model_id

                return answer or None

            print(
                "GROQ ERROR:",
                model_id,
                response.status_code,
                response.text[:500]
            )

            response_json = {}

            try:
                response_json = response.json()
            except Exception:
                pass

            if _is_groq_model_level_error(response.status_code, response_json):
                # این مدل دیگر وجود ندارد/منسوخ شده؛ کاندید بعدی
                # را امتحان کن.
                continue

            # خطای دیگری بود (rate limit خودِ Groq، کلید نامعتبر و...)
            # - امتحان مدل‌های دیگر فایده‌ای ندارد.
            return None

        except Exception as e:

            print(
                "GROQ EXCEPTION:",
                model_id,
                repr(e)
            )

            traceback.print_exc()

            return None

    return None


def ask_pollinations_text(prompt, history=None, system_prompt=None, model=None):
    """
    ارسال یک سوال متنی به Pollinations.ai (رایگان، بدون نیاز به
    کلید). به‌عنوان آخرین لایه‌ی پشتیبان بعد از Gemini و Groq
    استفاده می‌شود. مدل پیش‌فرض با get_pollinations_text_model
    تعیین می‌شود (قابل‌تغییر با دستور /text_model). خروجی None
    در صورت خطا.
    """

    if not prompt or not prompt.strip():
        return None

    messages = [
        {
            "role": "system",
            "content": system_prompt or get_groq_system_prompt()
        }
    ]

    for item in (history or []):

        role = "assistant" if item.get("role") == "model" else "user"

        messages.append({
            "role": role,
            "content": item.get("text", "")
        })

    messages.append({
        "role": "user",
        "content": prompt
    })

    headers = {"Content-Type": "application/json"}

    if POLLINATIONS_API_KEY:
        headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

    payload = {
        "model": model or get_pollinations_text_model(),
        "messages": messages
    }

    try:

        response = requests.post(
            POLLINATIONS_TEXT_URL,
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code != 200:

            print(
                "POLLINATIONS TEXT ERROR:",
                response.status_code,
                response.text[:400]
            )

            return None

        data = response.json()

        choices = data.get("choices") or []

        if not choices:
            return None

        answer = (
            choices[0]
            .get("message", {})
            .get("content", "")
        ).strip()

        return answer or None

    except Exception as e:

        print(
            "POLLINATIONS TEXT EXCEPTION:",
            repr(e)
        )

        traceback.print_exc()

        return None


def fetch_pollinations_text_models():
    """
    لیست زنده‌ی مدل‌های متنی Pollinations را برمی‌گرداند (برای
    دستور /text_models). خروجی لیست رشته یا [] در صورت خطا.
    """

    try:

        response = requests.get(
            POLLINATIONS_MODELS_URL,
            timeout=15
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if isinstance(data, list):

            names = []

            for item in data:

                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    names.append(item.get("name") or item.get("id") or "")

            return [n for n in names if n]

        return []

    except Exception as e:

        print(
            "POLLINATIONS MODELS LIST EXCEPTION:",
            repr(e)
        )

        return []



#
# برای جلوگیری از فعال بودن همیشگی google_search (که هم هزینه
# دارد و هم زودتر به سقف سهمیه‌ی رایگان می‌خورد)، فقط وقتی سوال
# شامل کلمات نشان‌دهنده‌ی نیاز به اطلاعات به‌روز باشد، ابزار
# جست‌وجو فعال می‌شود. برای سوالات عادی/عمومی (تعریف، محاسبه،
# گفت‌وگوی معمولی) جست‌وجو انجام نمی‌شود.
# -----------------------------------------------------------
AI_SEARCH_TRIGGER_RE = re.compile(
    r"("
    r"خبر|اخبار|امروز|دیروز|فردا|الان|اکنون|همین\s*الان|"
    r"جدید(ترین)?|تازه(ترین)?|به[‌\s]?روز|آخرین|"
    r"قیمت|نرخ|دلار|یورو|طلا|سکه|بورس|سهام|بازار|تورم|"
    r"هوا(ی)?\s|آب\s*و\s*هوا|پیش‌بینی\s*هوا|"
    r"نتیجه|نتایج|امتحان|کنکور|انتخابات|رای‌گیری|"
    r"رئیس[‌\s]?جمهور|نخست[‌\s]?وزیر|وزیر|رییس|مدیرعامل|"
    r"رویداد|مسابقه|بازی|فوتبال|المپیک|جام\s*جهانی|"
    r"جنگ|تحریم|درگیری|زلزله|بحران|"
    r"چند\s*شنبه|امروز\s*چندمه|تاریخ\s*(امروز|دقیق)|"
    r"سال\s*140\d|سال\s*20\d\d|202\d|203\d"
    r")",
    re.IGNORECASE
)


def prompt_needs_search(prompt):
    """
    تشخیص می‌دهد که آیا متن سوال کاربر به‌احتمال زیاد نیازمند
    اطلاعات به‌روز (و در نتیجه جست‌وجوی گوگل) است یا نه.
    """

    if not prompt:
        return False

    return bool(AI_SEARCH_TRIGGER_RE.search(prompt))


# آخرین خطای Gemini (برای تصمیم‌گیری پیام مناسب به کاربر):
# None یا 429 (rate limit) یا کد دیگر/"exception"
GEMINI_LAST_ERROR = {"status": None}


def ask_gemini(prompt, history=None, use_search=None):
    """
    ارسال یک سوال متنی به Gemini و دریافت پاسخ.
    در صورت نبود کلید یا بروز خطا، None برمی‌گرداند (و
    GEMINI_LAST_ERROR["status"] برای تشخیص نوع خطا ست می‌شود).

    use_search:
        None  -> طبق GEMINI_SEARCH_MODE تصمیم‌گیری خودکار می‌شود
        True  -> جست‌وجوی گوگل حتماً فعال می‌شود
        False -> جست‌وجوی گوگل حتماً غیرفعال می‌شود
    """

    GEMINI_LAST_ERROR["status"] = None

    if not GEMINI_API_KEY:
        return None

    if not prompt or not prompt.strip():
        return None

    if use_search is None:

        if GEMINI_SEARCH_MODE == "always":
            use_search = True
        elif GEMINI_SEARCH_MODE == "off":
            use_search = False
        else:
            use_search = prompt_needs_search(prompt)

    contents = []

    for item in (history or []):

        role = "model" if item.get("role") == "model" else "user"

        contents.append({
            "role": role,
            "parts": [{"text": item.get("text", "")}]
        })

    contents.append({
        "role": "user",
        "parts": [{"text": prompt}]
    })

    payload = {
        "system_instruction": {
            "parts": [{"text": get_ai_system_prompt()}]
        },
        "contents": contents
    }

    if use_search:
        payload["tools"] = [{"google_search": {}}]

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    max_attempts = 1 + max(0, GEMINI_RETRY_ON_429)

    for attempt in range(max_attempts):

        try:

            response = requests.post(
                GEMINI_API_URL,
                headers=headers,
                json=payload,
                timeout=40
            )

            if response.status_code == 200:

                data = response.json()

                candidates = data.get("candidates") or []

                if not candidates:
                    return None

                parts = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [])
                )

                answer = "".join(
                    part.get("text", "") for part in parts
                ).strip()

                return answer or None

            print(
                "GEMINI ERROR:",
                response.status_code,
                response.text[:500]
            )

            GEMINI_LAST_ERROR["status"] = response.status_code

            if response.status_code == 429 and attempt < max_attempts - 1:

                time.sleep(GEMINI_RETRY_DELAY_SECONDS)
                continue

            return None

        except Exception as e:

            print(
                "GEMINI EXCEPTION:",
                repr(e)
            )

            GEMINI_LAST_ERROR["status"] = "exception"

            return None

    return None


def is_bot_mentioned(text, bot_username, message=None):
    """
    تشخیص منشن ربات در متن پیام. هم حالت @username را بررسی
    می‌کند و هم entities رسمی پیام (اگر بله آن‌ها را بفرستد).
    """

    if bot_username:

        if f"@{bot_username}".lower() in (text or "").lower():
            return True

    if isinstance(message, dict):

        entities = message.get("entities") or []

        for entity in entities:

            if not isinstance(entity, dict):
                continue

            if entity.get("type") == "mention":
                return True

    reply_to = (
        message.get("reply_to_message")
        if isinstance(message, dict) else None
    )

    if isinstance(reply_to, dict):

        replied_from = reply_to.get("from") or {}

        bot = get_me()

        if bot and str(replied_from.get("id")) == str(bot.get("id")):
            return True

    return False


def strip_mention(text, bot_username):

    if not bot_username:
        return text.strip()

    return (
        text
        .replace(f"@{bot_username}", "")
        .strip()
    )


def is_ai_question_message(
    message,
    chat_type,
    bot_id,
    bot_username,
    require_mention
):
    """
    تشخیص می‌دهد که آیا این پیام باید توسط هوش مصنوعی پاسخ داده
    شود یا نه. در گروه فقط وقتی ربات منشن/ریپلای شده باشد؛ در
    خصوصی همیشه (مگر دستور یا پیام خالی باشد).
    """

    if not GEMINI_API_KEY:
        return False

    from_user = message.get("from") or {}

    if from_user.get("is_bot"):
        return False

    if str(from_user.get("id")) == str(bot_id):
        return False

    text = (message.get("text") or "").strip()

    if not text:
        return False

    if text.startswith("/"):
        return False

    if require_mention:

        if not is_bot_mentioned(text, bot_username, message):
            return False

    return True


def build_ai_prompt(message, bot_username):
    """
    اگر پیام ریپلای به پیام دیگری باشد، آن را هم به‌عنوان زمینه
    به مدل می‌دهیم تا پاسخ دقیق‌تری بدهد. همچنین منشن ربات از
    متن حذف می‌شود تا وارد سوال نشود.
    """

    text = strip_mention(
        (message.get("text") or "").strip(),
        bot_username
    )

    reply_to = message.get("reply_to_message")

    if isinstance(reply_to, dict):

        quoted = (reply_to.get("text") or "").strip()

        if quoted:

            return (
                f"پیام قبلی: {quoted}\n"
                f"پیام کاربر: {text}"
            )

    return text


def text_to_speech(text, voice=None):
    """
    ساخت فایل صوتی mp3 از روی متن با edge-tts (رایگان، بدون
    نیاز به کلید API، از موتور Microsoft Edge استفاده می‌کند و
    برخلاف gTTS از زبان فارسی هم پشتیبانی می‌کند). در صورت خطا
    یا نبود کتابخانه، None برمی‌گرداند. فایل موقت ساخته‌شده باید
    توسط فراخوان حذف شود.
    """

    if not text or not text.strip():
        return None

    try:

        import asyncio
        import tempfile
        import edge_tts

        tmp = tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
        )

        tmp.close()

        async def _synthesize():

            communicate = edge_tts.Communicate(
                text,
                voice or AI_VOICE_NAME
            )

            await communicate.save(tmp.name)

        asyncio.run(_synthesize())

        return tmp.name

    except ImportError:

        print(
            "⚠️ edge-tts نصب نیست. "
            "برای پاسخ صوتی: pip install edge-tts"
        )

        return None

    except Exception as e:

        print(
            "TTS EXCEPTION:",
            repr(e)
        )

        return None


def send_ai_voice_reply(chat_id, answer, message_id):
    """
    ساخت و ارسال نسخه‌ی صوتی پاسخ. فایل موقت بعد از ارسال حذف
    می‌شود. خطاها فقط لاگ می‌شوند و مانع ارسال پاسخ متنی نمی‌شوند.
    """

    if not AI_VOICE_ENABLED:
        return

    voice_path = None

    try:

        voice_path = text_to_speech(answer)

        if not voice_path:
            return

        send_voice_file(
            chat_id,
            voice_path,
            reply_to_message_id=message_id
        )

    except Exception as e:

        print(
            "AI VOICE REPLY ERROR:",
            repr(e)
        )

        traceback.print_exc()

    finally:

        if voice_path and os.path.exists(voice_path):

            try:
                os.remove(voice_path)
            except Exception:
                pass


def handle_ai_question(
    message,
    chat,
    chat_type,
    bot_id,
    bot_username,
    require_mention
):
    """
    اگر پیام باید توسط هوش مصنوعی پاسخ داده شود (طبق قوانین
    گروه/خصوصی)، با Gemini پاسخ می‌دهد (متن + صوت). خروجی True
    یعنی پیام پردازش شد.
    """

    if not is_ai_question_message(
        message,
        chat_type,
        bot_id,
        bot_username,
        require_mention
    ):
        return False

    chat_id = chat.get("id")
    message_id = message.get("message_id")

    from_user = message.get("from") or {}
    requester_id = from_user.get("id")

    if not is_ai_allowed(requester_id):

        send_message(
            chat_id,
            "⛔ شما به بخش هوش مصنوعی این ربات دسترسی ندارید.",
            reply_to_message_id=message_id
        )

        return True

    prompt = build_ai_prompt(message, bot_username)

    if not prompt:
        return False

    history = sanitize_ai_history(
        AI_CHAT_HISTORY.get(chat_id, [])
    )

    answer = ask_gemini(prompt, history=history)

    if not answer and GROQ_API_KEY:

        # 🆘 Gemini جواب نداد (مثلاً سقف سهمیه) - با Groq تلاش کن
        # تا ربات به‌جای سکوت/پیام خطا، همچنان جواب بدهد.

        print(
            "GEMINI FAILED, FALLING BACK TO GROQ. status:",
            GEMINI_LAST_ERROR.get("status")
        )

        answer = ask_groq(prompt, history=history)

    if not answer:

        # 🌸 آخرین لایه‌ی پشتیبان: Pollinations.ai (رایگان، بدون
        # نیاز به کلید) - اگر Gemini و Groq هم جواب ندادند.

        print(
            "GEMINI+GROQ FAILED, FALLING BACK TO POLLINATIONS TEXT."
        )

        answer = ask_pollinations_text(prompt, history=history)

    if not answer:

        if GEMINI_LAST_ERROR.get("status") == 429:

            send_message(
                chat_id,
                "⏳ الان درخواست‌های هوش مصنوعی زیاد شده و به سقف "
                "مجاز خورده. لطفاً چند لحظه صبر کن و دوباره بپرس.",
                reply_to_message_id=message_id
            )

            return True

        return False

    history = history + [
        {"role": "user", "text": prompt},
        {"role": "model", "text": answer}
    ]

    AI_CHAT_HISTORY[chat_id] = sanitize_ai_history(
        history[-AI_MAX_HISTORY:]
    )

    send_message(
        chat_id,
        html_text(answer),
        reply_to_message_id=message_id
    )

    send_ai_voice_reply(
        chat_id,
        answer,
        message_id
    )

    return True


# =========================================================
# NEWS TO VOICE (Google AI Studio / Gemini TTS)
#
# قابلیت مستقل از چت هوش مصنوعی بالا: کاربر با دستور /voice یا
# /خبر (در خصوصی) متن خبر را می‌فرستد یا فوروارد می‌کند و ربات
# دقیقاً همان متن را (بدون پاسخ‌گویی/بازنویسی توسط AI) با موتور
# Gemini TTS به صوت تبدیل کرده و به‌صورت فایل صوتی زیر همان
# پیام ارسال می‌کند.
# =========================================================

NEWS_VOICE_COMMANDS = ("/voice", "/خبر", "/news")


def get_news_text_from_command(text, bot_username):
    """
    اگر پیام با یکی از دستورات خبر-به-صوت شروع شده باشد، متن
    خبر را استخراج می‌کند (هر چه بعد از دستور آمده). اگر فقط
    خودِ دستور فرستاده شده باشد، رشته‌ی خالی برمی‌گرداند (یعنی
    باید در پیام بعدی از کاربر متن خبر را بگیریم). اگر پیام اصلاً
    با این دستورها شروع نشده، None برمی‌گرداند.
    """

    if not text:
        return None

    stripped = text.strip()

    first_word = stripped.split(" ", 1)[0]
    rest = (
        stripped.split(" ", 1)[1]
        if " " in stripped else ""
    ).strip()

    if bot_username and "@" in first_word:
        first_word = first_word.split("@", 1)[0]

    if first_word.lower() not in NEWS_VOICE_COMMANDS:
        return None

    return rest


def parse_pcm_mime_type(mime_type):
    """
    از مقدار mimeType خروجی Gemini TTS (مثل
    "audio/L16;codec=pcm;rate=24000") نرخ نمونه‌برداری را
    استخراج می‌کند. در صورت نبود، مقدار پیش‌فرض ۲۴۰۰۰ برمی‌گردد.
    """

    sample_rate = 24000

    if mime_type:

        for part in str(mime_type).split(";"):

            part = part.strip()

            if part.lower().startswith("rate="):

                try:
                    sample_rate = int(part.split("=", 1)[1])
                except Exception:
                    pass

    return sample_rate


def gemini_text_to_speech(text, voice=None):
    """
    ساخت فایل صوتی wav از روی متن با Gemini TTS (Google AI
    Studio). برخلاف edge-tts نیاز به کلید GEMINI_API_KEY دارد و
    هزینه‌بر است (طبق تعرفه‌ی گوگل). در صورت نبود کلید یا خطا،
    None برمی‌گرداند. فایل موقت ساخته‌شده باید توسط فراخوان حذف
    شود.
    """

    if not GEMINI_API_KEY:
        return None

    if not text or not text.strip():
        return None

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": text.strip()}]
            }
        ],
        "generation_config": {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {
                        "voice_name": voice or GEMINI_TTS_VOICE
                    }
                }
            }
        }
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    try:

        response = requests.post(
            GEMINI_TTS_API_URL,
            headers=headers,
            json=payload,
            timeout=90
        )

        if response.status_code != 200:

            print(
                "GEMINI TTS ERROR:",
                response.status_code,
                response.text[:500]
            )

            return None

        data = response.json()

        candidates = data.get("candidates") or []

        if not candidates:
            return None

        parts = (
            candidates[0]
            .get("content", {})
            .get("parts", [])
        )

        inline_data = None

        for part in parts:

            inline_data = (
                part.get("inlineData")
                or part.get("inline_data")
            )

            if inline_data:
                break

        if not inline_data:
            return None

        audio_b64 = (
            inline_data.get("data")
        )

        mime_type = (
            inline_data.get("mimeType")
            or inline_data.get("mime_type")
        )

        if not audio_b64:
            return None

        import base64
        import wave

        pcm_bytes = base64.b64decode(audio_b64)
        sample_rate = parse_pcm_mime_type(mime_type)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False
        )

        tmp.close()

        with wave.open(tmp.name, "wb") as wf:

            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)

        return tmp.name

    except Exception as e:

        print(
            "GEMINI TTS EXCEPTION:",
            repr(e)
        )

        traceback.print_exc()

        return None


def process_news_to_voice(chat_id, message_id, news_text):
    """
    گرفتن متن خبر، ساخت صوت با Gemini TTS و ارسال آن به‌عنوان
    فایل صوتی، زیر همان پیام. پیام‌های وضعیت (در حال ساخت/خطا)
    نیز ارسال می‌شوند.
    """

    news_text = (news_text or "").strip()

    if not news_text:

        send_message(
            chat_id,
            "لطفاً متن خبر را بفرست یا پست خبر را Forward کن.\n\n"
            "مثال: <code>/voice متن خبر اینجا</code>\n"
            "یا فقط <code>/voice</code> بفرست و بعد متن/فوروارد "
            "خبر را ارسال کن.",
            reply_to_message_id=message_id
        )

        return

    if not GEMINI_API_KEY:

        send_message(
            chat_id,
            "⚠️ کلید GEMINI_API_KEY تنظیم نشده، این قابلیت غیرفعال است.",
            reply_to_message_id=message_id
        )

        return

    if len(news_text) > GEMINI_TTS_MAX_CHARS:

        send_message(
            chat_id,
            "⚠️ متن خبر خیلی طولانی است "
            f"(حداکثر {to_persian_digits(GEMINI_TTS_MAX_CHARS)} کاراکتر). "
            "لطفاً کوتاه‌ترش کن.",
            reply_to_message_id=message_id
        )

        return

    send_message(
        chat_id,
        "🎙 در حال تبدیل خبر به صوت...",
        reply_to_message_id=message_id
    )

    voice_path = None

    try:

        voice_path = gemini_text_to_speech(news_text)

        if not voice_path:

            send_message(
                chat_id,
                "متاسفانه در ساخت صوت خطایی پیش اومد، دوباره امتحان کن.",
                reply_to_message_id=message_id
            )

            return

        send_voice_file(
            chat_id,
            voice_path,
            reply_to_message_id=message_id
        )

    except Exception as e:

        print(
            "NEWS TO VOICE ERROR:",
            repr(e)
        )

        traceback.print_exc()

    finally:

        if voice_path and os.path.exists(voice_path):

            try:
                os.remove(voice_path)
            except Exception:
                pass


def handle_voice_command(message, chat, bot_username):
    """
    اگر پیام دستور خبر-به-صوت باشد (/voice، /خبر یا /news)، آن
    را مدیریت می‌کند. متن هدف به این ترتیب پیدا می‌شود:
    ۱) متن بعد از خودِ دستور (/voice متن خبر)
    ۲) پیامی که این دستور روی آن ریپلای شده (کاربرد اصلی در
       گروه/کانال: زیر یک پست ریپلای کن و بنویس /voice)
    ۳) (فقط در چت خصوصی) منتظر پیام بعدی کاربر می‌ماند.
    خروجی True یعنی پیام پردازش شد.
    """

    text = (message.get("text") or "").strip()

    news_text = get_news_text_from_command(text, bot_username)

    if news_text is None:
        return False

    chat_id = chat.get("id")
    message_id = message.get("message_id")
    chat_type = chat.get("type")

    from_user = message.get("from") or {}
    requester_id = from_user.get("id")

    if not check_command_access(chat, requester_id, message_id):
        return True

    if not news_text:
        news_text = get_text_from_message_or_reply(message, "") or ""

    if not news_text:

        if chat_type == "private":

            PENDING_ACTIONS[str(chat_id)] = "await_news_voice"

            send_message(
                chat_id,
                "🎙 <b>خبر به صوت</b>\n\n"
                "متن خبر را بفرست یا پست خبر را Forward کن تا "
                "تبدیل به صوت شود.\n\n"
                "برای انصراف /cancel را بفرستید."
            )

        else:

            send_message(
                chat_id,
                "روی پیام موردنظر <b>ریپلای</b> کن و بنویس "
                "<code>/voice</code>، یا متن را بعد از دستور بنویس.",
                reply_to_message_id=message_id
            )

        return True

    process_news_to_voice(chat_id, message_id, news_text)

    return True


# =========================================================
# IMAGE GENERATION
# اولویت: Cloudflare Workers AI (Flux) → در صورت خطا Pollinations
# =========================================================

IMAGE_COMMANDS = ("/image", "/عکس")


def get_image_prompt_from_text(text, bot_username):
    """
    اگر پیام با یکی از دستورات ساخت عکس شروع شده باشد، توضیح
    عکس را استخراج می‌کند. در غیر این صورت None برمی‌گرداند.
    دستور می‌تواند به‌شکل "/image@bot_username توضیح" هم باشد
    (رفتار معمول دستورات در گروه).
    """

    if not text:
        return None

    stripped = text.strip()

    first_word = stripped.split(" ", 1)[0]
    rest = (
        stripped.split(" ", 1)[1]
        if " " in stripped else ""
    ).strip()

    # حذف بخش @bot_username از انتهای دستور، اگر وجود داشته باشد
    if bot_username and "@" in first_word:
        first_word = first_word.split("@", 1)[0]

    if first_word.lower() not in IMAGE_COMMANDS:
        return None

    return rest or None


PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF]")


def translate_prompt_to_english(prompt):
    """
    اگر prompt فارسی/عربی باشد، آن را به انگلیسی ترجمه می‌کند.
    مدل‌های تصویرسازی رایگان (Flux روی Cloudflare/Pollinations)
    عمدتاً روی کپشن‌های انگلیسی آموزش دیده‌اند و فارسی را درست
    نمی‌فهمند؛ برای همین قبل از ساخت عکس، پرامپت فارسی به یک
    توصیف انگلیسی طبیعی تبدیل می‌شود. اگر متن از قبل انگلیسی بود
    یا ترجمه (هم با Gemini هم با Groq) شکست خورد، همان متن اصلی
    بدون تغییر برگردانده می‌شود (بدتر از وضعیت فعلی نمی‌شود).
    """

    if not prompt or not PERSIAN_CHAR_RE.search(prompt):
        return prompt

    instruction = (
        "Translate the following image-generation prompt from "
        "Persian into a natural, vivid English image-generation "
        "prompt. Output ONLY the translated prompt itself - no "
        "quotes, no explanation, no extra text:\n\n" +
        prompt.strip()
    )

    translated = ask_gemini(instruction, use_search=False)

    if not translated and GROQ_API_KEY:
        translated = ask_groq(instruction)

    if not translated:
        return prompt

    translated = translated.strip().strip('"').strip("'").strip()

    return translated or prompt


def generate_cloudflare_image(prompt):
    """
    ساخت عکس با Cloudflare Workers AI (مدل Flux-1-Schnell).
    خروجی مسیر فایل موقت jpg یا None در صورت خطا.
    فایل موقت باید توسط فراخوان حذف شود.
    """

    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        return None

    if not prompt or not prompt.strip():
        return None

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
    )

    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "prompt": prompt.strip(),
        "steps": CLOUDFLARE_IMAGE_STEPS,
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=90
        )

        if response.status_code != 200:

            print(
                "CLOUDFLARE IMAGE ERROR:",
                response.status_code,
                response.text[:600]
            )

            return None

        data = response.json()

        # ساختار پاسخ معمولاً:
        # {"result": {"image": "<base64>"}}  یا  {"image": "<base64>"}
        result = data.get("result") or data
        image_b64 = None

        if isinstance(result, dict):
            image_b64 = result.get("image")
        elif isinstance(result, str):
            image_b64 = result

        if not image_b64:
            # بعضی نسخه‌ها مستقیم binary برمی‌گردانند
            content_type = response.headers.get("Content-Type", "")
            if "image" in content_type:
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".jpg",
                    delete=False
                )
                tmp.write(response.content)
                tmp.close()
                return tmp.name

            print("CLOUDFLARE IMAGE: no image field in response")
            print(str(data)[:400])
            return None

        import base64

        # گاهی data URI کامل می‌آید
        if "," in image_b64 and image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        image_bytes = base64.b64decode(image_b64)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        )
        tmp.write(image_bytes)
        tmp.close()

        return tmp.name

    except Exception as e:

        print(
            "CLOUDFLARE IMAGE EXCEPTION:",
            repr(e)
        )
        traceback.print_exc()
        return None


def generate_pollinations_image(prompt):
    """
    ساخت عکس از روی متن با Pollinations.ai (رایگان، بدون نیاز
    به کلید API). خروجی مسیر یک فایل موقت jpg است یا None در
    صورت خطا. فایل موقت باید توسط فراخوان حذف شود.
    """

    if not prompt or not prompt.strip():
        return None

    try:

        from urllib.parse import quote

        encoded_prompt = quote(prompt.strip())

        url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width=1024&height=1024&nologo=true&safe=true"
        )

        response = requests.get(url, timeout=90)

        if response.status_code != 200:

            print(
                "POLLINATIONS ERROR:",
                response.status_code,
                response.text[:300]
            )

            return None

        tmp = tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        )

        tmp.write(response.content)
        tmp.close()

        return tmp.name

    except Exception as e:

        print(
            "POLLINATIONS EXCEPTION:",
            repr(e)
        )

        return None


def generate_image(prompt):
    """
    اول Cloudflare Workers AI (Flux) را امتحان می‌کند؛
    اگر کلید نبود یا خطا داد، به Pollinations برمی‌گردد.
    قبل از هر دو، اگر پرامپت فارسی باشد، به انگلیسی ترجمه
    می‌شود (چون هر دو موتور روی کپشن انگلیسی آموزش دیده‌اند).
    """

    prompt = translate_prompt_to_english(prompt)

    image_path = generate_cloudflare_image(prompt)

    if image_path:
        print("✅ IMAGE GENERATED WITH CLOUDFLARE FLUX")
        return image_path

    print("↪️ FALLBACK TO POLLINATIONS")
    return generate_pollinations_image(prompt)



def send_photo_file(
    chat_id,
    file_path,
    caption=None,
    reply_to_message_id=None
):
    """
    ارسال یک فایل عکس با آپلود multipart/form-data به بله.
    """

    url = f"{BALE_API}/sendPhoto"

    data = {
        "chat_id": str(chat_id)
    }

    if caption:
        data["caption"] = caption

    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id

    try:

        with open(file_path, "rb") as f:

            response = requests.post(
                url,
                data=data,
                files={"photo": f},
                timeout=90
            )

        print(
            "BALE sendPhoto:",
            response.status_code
        )

        try:
            result = response.json()

        except Exception:

            print(
                "BALE sendPhoto RAW:",
                response.text[:2000]
            )

            return None

        if not result.get("ok"):

            print(
                "BALE sendPhoto ERROR:",
                result
            )

            return None

        return result.get("result")

    except Exception as e:

        print(
            "BALE sendPhoto EXCEPTION:",
            repr(e)
        )

        return None


def is_image_prompt_safe(prompt):
    """
    بررسی می‌کند که آیا توضیح عکس مناسب و بدون محتوای نامناسب
    (جنسی/خشونت‌آمیز/غیرقانونی و...) است یا نه. از Gemini برای
    این تشخیص استفاده می‌شود. اگر Gemini در دسترس نباشد یا خطا
    بدهد، به‌صورت پیش‌فرض اجازه می‌دهد (فیلتر safe=true خودِ
    Pollinations به‌عنوان لایه‌ی اول همچنان فعال است).
    """

    if not GEMINI_API_KEY:
        return True

    check_prompt = (
        "این توضیح عکس را بررسی کن و فقط با یک کلمه‌ی «SAFE» یا "
        "«UNSAFE» جواب بده (بدون هیچ توضیح اضافه). اگر توضیح شامل "
        "محتوای جنسی/برهنگی، خشونت شدید، آزار کودکان، نفرت‌پراکنی "
        "یا محتوای غیرقانونی باشد UNSAFE بنویس، در غیر این صورت "
        f"SAFE بنویس.\n\nتوضیح عکس: {prompt}"
    )

    try:

        result = ask_gemini(check_prompt)

        if not result:
            return True

        return "unsafe" not in result.strip().lower()

    except Exception as e:

        print(
            "IMAGE MODERATION EXCEPTION:",
            repr(e)
        )

        return True


def check_command_access(chat, requester_id, message_id):
    """
    بررسی دسترسی برای دستورات AI-محور (عکس/خلاصه/بازنویسی/صوت):

    - در چت خصوصی: اگر دسترسی نداشت، پیام رد دسترسی نشان داده
      می‌شود (چون فقط خودِ کاربر آن را می‌بیند).
    - در گروه/سوپرگروه: بررسی is_ai_allowed انجام می‌شود، ولی در
      صورت رد دسترسی، هیچ پیامی فرستاده نمی‌شود (کاملاً بی‌صدا)؛
      این‌طوری اعضای عادی اصلاً متوجه وجود این دستورات نمی‌شوند.
    - در کانال: بله خودش فقط اجازه می‌دهد ادمین‌های همان کانال
      پست بگذارند (و پست‌های کانال اصلاً فیلد «from» ندارند)، پس
      بررسی هویت لازم نیست و همیشه مجاز فرض می‌شود.

    خروجی: True یعنی ادامه بده، False یعنی متوقف شو (خودِ این
    تابع پیام رد دسترسی را در صورت نیاز فرستاده است).
    """

    chat_type = chat.get("type")
    chat_id = chat.get("id")

    if chat_type == "channel":
        return True

    if is_ai_allowed(requester_id):
        return True

    if chat_type == "private":

        send_message(
            chat_id,
            "⛔ شما به بخش هوش مصنوعی این ربات دسترسی ندارید.",
            reply_to_message_id=message_id
        )

    # گروه/سوپرگروه: عمداً هیچ پیامی فرستاده نمی‌شود.
    return False


EDIT_IMAGE_COMMANDS = ("/edit_image", "/ویرایش", "/ویرایش_عکس", "/edit")


def get_bale_file_download_url(file_id):
    """
    با گرفتن file_id یک فایل (مثلاً عکس)، از بله آدرس دانلود
    موقت آن را می‌گیرد. این آدرس شامل توکن ربات است و فقط برای
    مدت کوتاهی (طبق مستندات مشابه تلگرام، حدود ۱ ساعت) معتبر
    می‌ماند. خروجی None در صورت خطا.
    """

    if not file_id:
        return None

    result = bale_request(
        "getFile",
        {"file_id": file_id}
    )

    if not result:
        return None

    file_path = result.get("file_path")

    if not file_path:
        return None

    return f"https://tapi.bale.ai/file/bot{BALE_TOKEN}/{file_path}"


def get_largest_photo_file_id(photo_sizes):
    """
    از لیست اندازه‌های مختلف یک عکس (که بله/تلگرام برمی‌گرداند)،
    file_id بزرگ‌ترین اندازه را برمی‌گرداند.
    """

    if not photo_sizes:
        return None

    try:

        largest = max(
            photo_sizes,
            key=lambda p: (p.get("width", 0) * p.get("height", 0))
        )

        return largest.get("file_id")

    except Exception:

        return photo_sizes[-1].get("file_id")


def get_photo_file_id_from_message_or_reply(message):
    """
    اگر خودِ پیام عکس داشته باشد (مثلاً عکس با کپشن دستور)، یا
    پیامی که روی آن ریپلای شده عکس داشته باشد، file_id آن را
    برمی‌گرداند. در غیر این صورت None.
    """

    photo = message.get("photo")

    if photo:
        return get_largest_photo_file_id(photo)

    reply = message.get("reply_to_message") or {}

    reply_photo = reply.get("photo")

    if reply_photo:
        return get_largest_photo_file_id(reply_photo)

    return None


def get_edit_instruction_from_command(text, bot_username):
    """
    مثل get_news_text_from_command: اگر پیام با یکی از دستورات
    ویرایش عکس شروع شده باشد، توضیح ویرایش (هر چه بعد از دستور
    آمده) را برمی‌گرداند. اگر فقط خودِ دستور بود، رشته‌ی خالی. اگر
    اصلاً با این دستورها شروع نشده، None.
    """

    if not text:
        return None

    stripped = text.strip()

    first_word = stripped.split(" ", 1)[0]
    rest = (
        stripped.split(" ", 1)[1]
        if " " in stripped else ""
    ).strip()

    if bot_username and "@" in first_word:
        first_word = first_word.split("@", 1)[0]

    if first_word.lower() not in EDIT_IMAGE_COMMANDS:
        return None

    return rest


def generate_kontext_edit(image_url, instruction):
    """
    ویرایش یک عکس موجود با مدل kontext در Pollinations.ai، طبق
    یک دستور متنی (مثلاً «این را آبرنگ کن»). قبل از ارسال، اگر
    دستور فارسی باشد به انگلیسی ترجمه می‌شود. خروجی مسیر فایل
    موقت jpg یا None در صورت خطا. فایل موقت باید توسط فراخوان
    حذف شود.
    """

    if not image_url or not instruction or not instruction.strip():
        return None

    instruction = translate_prompt_to_english(instruction)

    try:

        from urllib.parse import quote

        encoded_instruction = quote(instruction.strip())
        encoded_image_url = quote(image_url, safe="")

        url = (
            f"https://image.pollinations.ai/prompt/{encoded_instruction}"
            f"?model=kontext&image={encoded_image_url}"
            f"&width=1024&height=1024&nologo=true&safe=true"
        )

        response = requests.get(url, timeout=120)

        if response.status_code != 200:

            print(
                "KONTEXT EDIT ERROR:",
                response.status_code,
                response.text[:400]
            )

            return None

        content_type = response.headers.get("Content-Type", "")

        if "image" not in content_type:

            print(
                "KONTEXT EDIT: unexpected content-type:",
                content_type,
                response.text[:300]
            )

            return None

        tmp = tempfile.NamedTemporaryFile(
            suffix=".jpg",
            delete=False
        )

        tmp.write(response.content)
        tmp.close()

        return tmp.name

    except Exception as e:

        print(
            "KONTEXT EDIT EXCEPTION:",
            repr(e)
        )

        traceback.print_exc()

        return None


def handle_edit_image_command(message, chat, bot_username):
    """
    اگر پیام دستور ویرایش عکس باشد (/edit_image، /ویرایش،
    /ویرایش_عکس یا /edit)، عکس هدف را (خودِ پیام یا پیام
    ریپلای‌شده) با مدل kontext ویرایش می‌کند. خروجی True یعنی
    پیام پردازش شد.

    ⚠️ نکته‌ی امنیتی: آدرس دانلود عکس از بله شامل توکن ربات است
    و برای گرفتن جواب از Pollinations، این آدرس به سرور آن‌ها
    فرستاده می‌شود. این آدرس کوتاه‌عمر است (حدود ۱ ساعت) ولی
    بازهم یعنی یک سرویس ثالث آن را می‌بیند - ریسک کوچک ولی
    واقعی است.
    """

    text = (message.get("text") or message.get("caption") or "").strip()

    instruction = get_edit_instruction_from_command(text, bot_username)

    if instruction is None:
        return False

    chat_id = chat.get("id")
    message_id = message.get("message_id")

    from_user = message.get("from") or {}
    requester_id = from_user.get("id")

    if not check_command_access(chat, requester_id, message_id):
        return True

    file_id = get_photo_file_id_from_message_or_reply(message)

    if not file_id:

        send_message(
            chat_id,
            "روی یک <b>عکس</b> ریپلای کن و بنویس "
            "<code>/ویرایش توضیح تغییر</code>، یا خودِ عکس را با "
            "همین کپشن بفرست.",
            reply_to_message_id=message_id
        )

        return True

    if not instruction:

        send_message(
            chat_id,
            "بگو چطور می‌خوای عکس ویرایش بشه، مثلاً:\n"
            "<code>/ویرایش این را آبرنگ کن</code>",
            reply_to_message_id=message_id
        )

        return True

    image_url = get_bale_file_download_url(file_id)

    if not image_url:

        send_message(
            chat_id,
            "متاسفانه نتونستم عکس رو از بله بگیرم، دوباره امتحان کن.",
            reply_to_message_id=message_id
        )

        return True

    send_message(
        chat_id,
        "🖌 در حال ویرایش عکس...",
        reply_to_message_id=message_id
    )

    result_path = None

    try:

        result_path = generate_kontext_edit(image_url, instruction)

        if not result_path:

            send_message(
                chat_id,
                "متاسفانه ویرایش عکس انجام نشد، دوباره امتحان کن.",
                reply_to_message_id=message_id
            )

            return True

        send_photo_file(
            chat_id,
            result_path,
            reply_to_message_id=message_id
        )

    finally:

        if result_path and os.path.exists(result_path):

            try:
                os.remove(result_path)
            except Exception:
                pass

    return True


def handle_image_command(message, chat, bot_username):
    """
    اگر پیام دستور ساخت عکس باشد (/image یا /عکس)، عکس را با
    Pollinations.ai می‌سازد و ارسال می‌کند. خروجی True یعنی
    پیام پردازش شد (چه موفق چه ناموفق).
    """

    text = (message.get("text") or "").strip()

    prompt = get_image_prompt_from_text(text, bot_username)

    if prompt is None and text.split(" ", 1)[0].split("@", 1)[0].lower() not in IMAGE_COMMANDS:
        return False

    chat_id = chat.get("id")
    message_id = message.get("message_id")

    from_user = message.get("from") or {}
    requester_id = from_user.get("id")

    if not check_command_access(chat, requester_id, message_id):
        return True

    if not prompt:

        send_message(
            chat_id,
            "لطفاً بعد از دستور، توضیح عکس مورد نظرت را بنویس.\n"
            "مثال: /image یک گربه فضانورد",
            reply_to_message_id=message_id
        )

        return True

    if not is_image_prompt_safe(prompt):

        send_message(
            chat_id,
            "🚫 این درخواست مناسب ساخت عکس نیست. لطفاً توضیح دیگه‌ای بنویس.",
            reply_to_message_id=message_id
        )

        return True

    send_message(
        chat_id,
        "⏳ در حال ساخت عکس...",
        reply_to_message_id=message_id
    )

    image_path = None

    try:

        # اولویت با Cloudflare Flux؛ در صورت خطا → Pollinations
        image_path = generate_image(prompt)

        if not image_path:

            send_message(
                chat_id,
                "متاسفانه در ساخت عکس خطایی پیش اومد، دوباره امتحان کن.",
                reply_to_message_id=message_id
            )

            return True

        send_photo_file(
            chat_id,
            image_path,
            caption=html_text(prompt),
            reply_to_message_id=message_id
        )

    except Exception as e:

        print(
            "IMAGE COMMAND ERROR:",
            repr(e)
        )

        traceback.print_exc()

    finally:

        if image_path and os.path.exists(image_path):

            try:
                os.remove(image_path)
            except Exception:
                pass

    return True


# =========================================================
# TEXT TOOLS: خلاصه + بازنویسی (سه سبک)
# =========================================================

SUMMARY_COMMANDS = ("/خلاصه", "/summary", "/summarize")

# سبک‌های بازنویسی
# کلید = شناسه داخلی ، مقدار = (لیست دستورات/عبارات، system prompt)
REWRITE_STYLES = {
    "default": {
        "commands": ("/بازنویس", "/rewrite"),
        "label": "عادی",
        "system": (
            "متن زیر را به فارسی روان، طبیعی و خوانا بازنویسی کن. "
            "معنا و اطلاعات اصلی را حفظ کن، فقط بیان را بهتر و روان‌تر کن. "
            "هیچ توضیح اضافه‌ای ننویس؛ فقط متن بازنویسی‌شده را برگردان."
        ),
    },
    "pr": {
        "commands": (
            "/بازنویس روابط عمومی",
            "/بازنویس_روابط_عمومی",
            "/بازنویس_pr",
            "/rewrite_pr",
        ),
        "label": "روابط عمومی",
        "system": (
            "متن زیر را به سبک روابط عمومی و رسمی سازمانی بازنویسی کن. "
            "لحن حرفه‌ای، محترمانه، مثبت و مناسب انتشار عمومی باشد. "
            "از اغراق غیرواقعی پرهیز کن و اطلاعات اصلی را حفظ کن. "
            "هیچ توضیح اضافه‌ای ننویس؛ فقط متن بازنویسی‌شده را برگردان."
        ),
    },
    "psycho": {
        "commands": (
            "/بازنویس روان‌شناسانه",
            "/بازنویس روانشناسانه",
            "/بازنویس_روانشناسانه",
            "/بازنویس_روان‌شناسانه",
            "/rewrite_psycho",
        ),
        "label": "روان‌شناسانه (مخاطب عموم)",
        "system": (
            "متن زیر را به زبانی همدلانه، آرام و قابل‌فهم برای مخاطب عموم "
            "بازنویسی کن (سبک روان‌شناسانه و حمایتی). "
            "لحن گرم، بدون قضاوت و مناسب ارتباط مؤثر باشد. "
            "اطلاعات اصلی را حفظ کن و هیچ توضیح اضافه‌ای ننویس؛ "
            "فقط متن بازنویسی‌شده را برگردان."
        ),
    },
}


def _extract_command_and_rest(text, bot_username):
    """اولین کلمه دستور را (با حذف @bot) و بقیه متن را برمی‌گرداند."""
    if not text:
        return None, ""

    stripped = text.strip()
    first = stripped.split(" ", 1)[0]
    rest = stripped.split(" ", 1)[1].strip() if " " in stripped else ""

    if bot_username and "@" in first:
        first = first.split("@", 1)[0]

    return first, rest


def get_text_from_message_or_reply(message, command_rest):
    """
    متن هدف را از بقیه دستور، یا از پیام ریپلای‌شده،
    یا از کپشن/متن فوروارد استخراج می‌کند.
    """
    if command_rest and command_rest.strip():
        return command_rest.strip()

    reply = message.get("reply_to_message") or {}
    if reply:
        t = (reply.get("text") or reply.get("caption") or "").strip()
        if t:
            return t

    # فوروارد مستقیم روی خود پیام
    t = (message.get("text") or message.get("caption") or "").strip()
    # اگر فقط دستور بوده، خالی برگردان
    return None


def ask_groq_with_system(system_prompt, user_text):
    """
    مثل ask_groq ولی با system prompt دلخواه (برای خلاصه/بازنویسی).
    در صورت نبود کلید یا خطا، None برمی‌گرداند.
    """
    if not GROQ_API_KEY:
        return None

    if not user_text or not user_text.strip():
        return None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text.strip()},
    ]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
    }

    available_ids = fetch_groq_available_models()

    ordered_models = []

    if GROQ_WORKING_MODEL["id"]:
        ordered_models.append(GROQ_WORKING_MODEL["id"])

    for model_id in GROQ_MODEL_CANDIDATES:
        if model_id in ordered_models:
            continue
        if not available_ids or model_id in available_ids:
            ordered_models.append(model_id)

    if available_ids:
        for model_id in available_ids:
            if model_id in ordered_models:
                continue
            lowered = model_id.lower()
            if any(
                skip in lowered
                for skip in ("whisper", "tts", "guard", "embed")
            ):
                continue
            ordered_models.append(model_id)

    if not ordered_models:
        return None

    for model_id in ordered_models:
        payload = {
            "model": model_id,
            "messages": messages,
        }

        try:
            response = requests.post(
                GROQ_API_URL,
                headers=headers,
                json=payload,
                timeout=50,
            )

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    return None
                answer = (
                    choices[0]
                    .get("message", {})
                    .get("content", "")
                ).strip()
                if answer:
                    GROQ_WORKING_MODEL["id"] = model_id
                return answer or None

            print(
                "GROQ TEXT-TOOL ERROR:",
                model_id,
                response.status_code,
                response.text[:500],
            )

            response_json = {}
            try:
                response_json = response.json()
            except Exception:
                pass

            if _is_groq_model_level_error(
                response.status_code, response_json
            ):
                continue

            return None

        except Exception as e:
            print(
                "GROQ TEXT-TOOL EXCEPTION:",
                model_id,
                repr(e),
            )
            traceback.print_exc()
            return None

    return None


def ask_gemini_with_system(system_prompt, user_text):
    """
    یک بار Gemini را با system_instruction دلخواه صدا می‌زند
    (بدون تاریخچه چت). برای خلاصه و بازنویسی مناسب است.
    در صورت خطای Gemini (مثلاً سقف سهمیه)، به Groq فال‌بک می‌کند.
    """
    GEMINI_LAST_ERROR["status"] = None

    if not user_text or not user_text.strip():
        return None

    answer = None

    if GEMINI_API_KEY:
        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_text.strip()}]
                }
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }

        max_attempts = 1 + max(0, GEMINI_RETRY_ON_429)

        for attempt in range(max_attempts):
            try:
                response = requests.post(
                    GEMINI_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=50
                )

                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates") or []
                    if not candidates:
                        break

                    parts = (
                        candidates[0]
                        .get("content", {})
                        .get("parts", [])
                    )
                    answer = "".join(
                        p.get("text", "") for p in parts
                    ).strip()
                    if answer:
                        return answer
                    break

                print(
                    "GEMINI TEXT-TOOL ERROR:",
                    response.status_code,
                    response.text[:500]
                )
                GEMINI_LAST_ERROR["status"] = response.status_code

                if (
                    response.status_code == 429
                    and attempt < max_attempts - 1
                ):
                    time.sleep(GEMINI_RETRY_DELAY_SECONDS)
                    continue

                break

            except Exception as e:
                print("GEMINI TEXT-TOOL EXCEPTION:", repr(e))
                traceback.print_exc()
                GEMINI_LAST_ERROR["status"] = "exception"
                break

    # 🆘 فال‌بک به Groq وقتی Gemini جواب نداد
    if not answer and GROQ_API_KEY:
        print(
            "GEMINI TEXT-TOOL FAILED, FALLING BACK TO GROQ. status:",
            GEMINI_LAST_ERROR.get("status"),
        )
        answer = ask_groq_with_system(system_prompt, user_text)

    # 🌸 آخرین لایه‌ی پشتیبان: Pollinations.ai (رایگان)
    if not answer:
        print("GEMINI+GROQ TEXT-TOOL FAILED, FALLING BACK TO POLLINATIONS.")
        answer = ask_pollinations_text(
            user_text,
            system_prompt=system_prompt
        )

    return answer or None


def handle_summary_command(message, chat, bot_username):
    """
    /خلاصه یا /summary
    متن را از ریپلای یا بعد از دستور می‌گیرد و خلاصه می‌کند.
    """
    text = (message.get("text") or "").strip()
    first, rest = _extract_command_and_rest(text, bot_username)

    if not first or first.lower() not in [c.lower() for c in SUMMARY_COMMANDS]:
        # پشتیبانی از حالت «/خلاصه 20» — عدد را نادیده می‌گیریم
        # و فقط خود دستور را چک می‌کنیم
        base = first.lower() if first else ""
        if base not in ("/خلاصه", "/summary", "/summarize"):
            return False

    chat_id = chat.get("id")
    message_id = message.get("message_id")
    from_user = message.get("from") or {}
    requester_id = from_user.get("id")

    if not check_command_access(chat, requester_id, message_id):
        return True

    # اگر rest فقط عدد باشد (مثل /خلاصه 20) آن را متن ندان
    target = rest
    if target and target.strip().isdigit():
        target = ""

    source_text = get_text_from_message_or_reply(message, target)

    if not source_text:
        send_message(
            chat_id,
            "لطفاً متن را بعد از دستور بنویس یا روی پیام موردنظر "
            "<b>ریپلای</b> کن و بگو /خلاصه\n\n"
            "مثال:\n"
            "• ریپلای روی یک پست + <code>/خلاصه</code>\n"
            "• <code>/خلاصه متن طولانی اینجا...</code>",
            reply_to_message_id=message_id
        )
        return True

    if len(source_text) < 20:
        send_message(
            chat_id,
            "متن خیلی کوتاه است؛ برای خلاصه‌سازی به متن بلندتری نیاز دارم.",
            reply_to_message_id=message_id
        )
        return True

    send_message(
        chat_id,
        "⏳ در حال خلاصه‌سازی...",
        reply_to_message_id=message_id
    )

    system = (
        "متن زیر را به فارسی خلاصه کن. "
        "خلاصه باید کوتاه، واضح و شامل نکات اصلی باشد. "
        "از بولت‌پوینت در صورت مناسب بودن استفاده کن. "
        "هیچ مقدمه یا توضیح اضافه‌ای ننویس."
    )

    summary = ask_gemini_with_system(system, source_text)

    if not summary:
        if GEMINI_LAST_ERROR.get("status") == 429 and not GROQ_API_KEY:
            err_msg = (
                "⏳ الان درخواست‌های هوش مصنوعی زیاد شده و به سقف "
                "مجاز خورده. لطفاً چند لحظه صبر کن و دوباره بپرس."
            )
        else:
            err_msg = (
                "متاسفانه در خلاصه‌سازی خطایی پیش آمد. دوباره امتحان کن."
            )
        send_message(
            chat_id,
            err_msg,
            reply_to_message_id=message_id
        )
        return True

    send_message(
        chat_id,
        f"📝 <b>خلاصه:</b>\n\n{html_text(summary)}",
        reply_to_message_id=message_id
    )
    return True


def detect_rewrite_style(text, bot_username):
    """
    تشخیص سبک بازنویسی از روی متن دستور.
    برمی‌گرداند: (style_key, rest_text) یا (None, None)
    اول سبک‌های چندکلمه‌ای را چک می‌کند تا با /بازنویس ساده تداخل نکند.
    """
    if not text:
        return None, None

    stripped = text.strip()
    lower = stripped.lower()

    # حذف @bot از اول دستور اگر باشد
    # برای تطبیق دقیق‌تر، اول سبک‌های خاص را امتحان می‌کنیم
    for key in ("pr", "psycho", "default"):
        style = REWRITE_STYLES[key]
        for cmd in style["commands"]:
            cmd_l = cmd.lower()
            # حالت دقیق یا با @bot
            if lower == cmd_l or lower.startswith(cmd_l + " "):
                rest = stripped[len(cmd):].strip()
                # اگر با @bot آمده باشد
                if rest.startswith("@"):
                    # /بازنویس@bot ...
                    parts = rest.split(" ", 1)
                    rest = parts[1].strip() if len(parts) > 1 else ""
                return key, rest

            # حالت /بازنویس@username ...
            if bot_username:
                with_bot = cmd_l + "@" + bot_username.lower()
                if lower == with_bot or lower.startswith(with_bot + " "):
                    rest = stripped[len(cmd) + 1 + len(bot_username):].strip()
                    return key, rest

    return None, None


def handle_rewrite_command(message, chat, bot_username):
    """
    سه سبک بازنویسی:
      /بازنویس
      /بازنویس روابط عمومی
      /بازنویس روان‌شناسانه
    متن از ریپلای یا بعد از دستور گرفته می‌شود.
    """
    text = (message.get("text") or "").strip()
    style_key, rest = detect_rewrite_style(text, bot_username)

    if style_key is None:
        return False

    chat_id = chat.get("id")
    message_id = message.get("message_id")
    from_user = message.get("from") or {}
    requester_id = from_user.get("id")

    if not check_command_access(chat, requester_id, message_id):
        return True

    source_text = get_text_from_message_or_reply(message, rest)

    if not source_text:
        style = REWRITE_STYLES[style_key]
        send_message(
            chat_id,
            f"لطفاً متن را بعد از دستور بنویس یا روی پیام موردنظر "
            f"<b>ریپلای</b> کن.\n\n"
            f"سبک فعلی: <b>{style['label']}</b>\n\n"
            f"مثال‌ها:\n"
            f"• ریپلای + <code>/بازنویس</code>\n"
            f"• ریپلای + <code>/بازنویس روابط عمومی</code>\n"
            f"• ریپلای + <code>/بازنویس روان‌شناسانه</code>\n"
            f"• <code>/بازنویس متن اینجا...</code>",
            reply_to_message_id=message_id
        )
        return True

    if len(source_text) < 5:
        send_message(
            chat_id,
            "متن خیلی کوتاه است.",
            reply_to_message_id=message_id
        )
        return True

    style = REWRITE_STYLES[style_key]

    send_message(
        chat_id,
        f"⏳ در حال بازنویسی ({style['label']})...",
        reply_to_message_id=message_id
    )

    result = ask_gemini_with_system(style["system"], source_text)

    if not result:
        if GEMINI_LAST_ERROR.get("status") == 429 and not GROQ_API_KEY:
            err_msg = (
                "⏳ الان درخواست‌های هوش مصنوعی زیاد شده و به سقف "
                "مجاز خورده. لطفاً چند لحظه صبر کن و دوباره بپرس."
            )
        else:
            err_msg = (
                "متاسفانه در بازنویسی خطایی پیش آمد. دوباره امتحان کن."
            )
        send_message(
            chat_id,
            err_msg,
            reply_to_message_id=message_id
        )
        return True

    send_message(
        chat_id,
        f"✏️ <b>بازنویسی — {style['label']}</b>\n\n{html_text(result)}",
        reply_to_message_id=message_id
    )
    return True


# =========================================================
# BALE METHODS
# =========================================================

def get_me():

    global BOT_INFO

    if BOT_INFO:
        return BOT_INFO

    BOT_INFO = bale_request("getMe")

    if BOT_INFO:

        print("=" * 50)
        print("BOT INFORMATION")
        print(BOT_INFO)
        print("=" * 50)

    return BOT_INFO


def get_chat(chat_id):

    return bale_request(
        "getChat",
        {
            "chat_id": str(chat_id)
        }
    )


def get_chat_member(chat_id, user_id):

    return bale_request(
        "getChatMember",
        {
            "chat_id": str(chat_id),
            "user_id": str(user_id)
        }
    )


def get_chat_members_count(chat_id):

    if chat_id is None:
        return None

    result = bale_request(
        "getChatMembersCount",
        {
            "chat_id": str(chat_id)
        }
    )

    if result is None:
        return None

    if isinstance(result, dict):

        # برخی سرورها ممکن است این متد را به شکل
        # {"count": N} برگردانند؛ برای اطمینان هر دو حالت
        # را پشتیبانی می‌کنیم.
        result = (
            result.get("count")
            or result.get("members_count")
        )

    try:

        return int(result)

    except Exception:

        return None


def forward_message(
    to_chat_id,
    from_chat_id,
    message_id
):

    return bale_request(
        "forwardMessage",
        {
            "chat_id": str(to_chat_id),
            "from_chat_id": str(from_chat_id),
            "message_id": message_id
        }
    )


def send_voice_file(
    chat_id,
    file_path,
    caption=None,
    reply_to_message_id=None
):
    """
    ارسال یک فایل صوتی (mp3) به‌عنوان پیام صوتی/آهنگ. برخلاف
    sendMessage این متد باید multipart/form-data باشد، پس از
    bale_request (که فقط JSON می‌فرستد) استفاده نمی‌کنیم.
    """

    url = f"{BALE_API}/sendAudio"

    data = {
        "chat_id": str(chat_id)
    }

    if caption:
        data["caption"] = caption

    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id

    try:

        with open(file_path, "rb") as f:

            response = requests.post(
                url,
                data=data,
                files={"audio": f},
                timeout=60
            )

        print(
            "BALE sendAudio:",
            response.status_code
        )

        try:
            result = response.json()

        except Exception:

            print(
                "BALE sendAudio RAW:",
                response.text[:2000]
            )

            return None

        if not result.get("ok"):

            print(
                "BALE sendAudio ERROR:",
                result
            )

            return None

        return result.get("result")

    except Exception as e:

        print(
            "BALE sendAudio EXCEPTION:",
            repr(e)
        )

        return None


def send_message(
    chat_id,
    text,
    reply_markup=None,
    parse_mode="HTML",
    reply_to_message_id=None
):

    data = {
        "chat_id": str(chat_id),
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    if parse_mode:
        data["parse_mode"] = parse_mode

    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id

    return bale_request(
        "sendMessage",
        data
    )


def send_markdown_message(
    chat_id,
    text,
    reply_markup=None
):

    return send_message(
        chat_id,
        text,
        reply_markup,
        parse_mode="Markdown"
    )


def answer_callback_query(
    callback_query_id,
    text=None,
    show_alert=False
):

    data = {
        "callback_query_id": str(callback_query_id),
        "show_alert": show_alert
    }

    if text:
        data["text"] = text

    return bale_request(
        "answerCallbackQuery",
        data
    )


def get_updates(offset=None):

    data = {
        "timeout": 30,
        # 🔧 اصلاح اصلی: صراحتاً همه‌ی انواع آپدیت مورد نیاز را
        # درخواست می‌کنیم. بدون این، آپدیت‌های my_chat_member و
        # chat_member (رویداد عضو شدن/خارج شدن ربات از کانال یا
        # گروه) ممکن است اصلاً به سمت ما ارسال نشوند.
        "allowed_updates": ALLOWED_UPDATES
    }

    if offset is not None:
        data["offset"] = offset

    return bale_request(
        "getUpdates",
        data,
        timeout=45
    )


def bale_send_document(
    chat_id,
    file_path,
    caption=None
):

    url = f"{BALE_API}/sendDocument"

    try:

        with open(file_path, "rb") as f:

            files = {
                "document": (
                    os.path.basename(file_path),
                    f
                )
            }

            data = {
                "chat_id": str(chat_id)
            }

            if caption:
                data["caption"] = caption

            response = requests.post(
                url,
                data=data,
                files=files,
                timeout=60
            )

        print(
            "BALE sendDocument:",
            response.status_code
        )

        try:

            result = response.json()

        except Exception:

            print(
                "BALE sendDocument RAW:",
                response.text[:3000]
            )

            return None

        if not result.get("ok"):

            print(
                "BALE sendDocument ERROR:",
                result
            )

            return None

        return result.get("result")

    except Exception as e:

        print(
            "BALE sendDocument EXCEPTION:",
            repr(e)
        )

        return None


# =========================================================
# KEYBOARDS
# =========================================================

def source_report_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "📊 گزارش همین پست",
                    "callback_data": "report_selected_source"
                }
            ]
        ]
    }


def clear_reports_keyboard():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "⚠️ بله، همه گزارش‌ها حذف شود",
                    "callback_data": "confirm_clear_reports"
                }
            ],
            [
                {
                    "text": "❌ انصراف",
                    "callback_data": "cancel_clear_reports"
                }
            ]
        ]
    }


def pair_destination_keyboard(candidates):

    keyboard = []

    for index, row in enumerate(candidates):

        title = (
            row.get("title")
            or row.get("username")
            or row.get("chat_id")
            or "-"
        )

        title = str(title)

        if len(title) > 40:
            title = title[:40] + "…"

        keyboard.append([
            {
                "text": f"🎯 {title}",
                "callback_data": f"pairdst:{index}"
            }
        ])

    keyboard.append([
        {
            "text": "❌ انصراف",
            "callback_data": "cancel_pair_report"
        }
    ])

    return {
        "inline_keyboard": keyboard
    }


# =========================================================
# MESSAGE LINK
# =========================================================

def build_bale_message_link(
    username,
    chat_id,
    message_id
):

    username = clean_username(username)

    if not username:
        return None

    if chat_id is None:
        return None

    if message_id is None:
        return None

    chat_id = str(chat_id).strip()
    message_id = str(message_id).strip()

    if not chat_id or not message_id:
        return None

    return (
        f"https://ble.ir/"
        f"{username}/"
        f"{chat_id}/"
        f"{message_id}"
    )


def resolve_message_link(
    username,
    chat_id,
    message_id
):

    if chat_id is None or message_id is None:
        return None

    username = clean_username(username)

    if username:

        return build_bale_message_link(
            username,
            chat_id,
            message_id
        )

    try:

        chat = get_chat(chat_id)

        if chat:

            username = clean_username(
                chat.get("username")
            )

            if username:

                return build_bale_message_link(
                    username,
                    chat_id,
                    message_id
                )

    except Exception as e:

        print(
            "RESOLVE MESSAGE LINK ERROR:",
            repr(e)
        )

    return None


# =========================================================
# SETTINGS
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
            return result.data[0].get("value")

    except Exception as e:

        print(
            "GET SETTING ERROR:",
            repr(e)
        )

    return None


def set_setting(key, value):

    try:

        existing = (
            supabase
            .table("bot_settings")
            .select("key")
            .eq("key", key)
            .limit(1)
            .execute()
        )

        data = {
            "value": str(value)
        }

        if existing.data:

            (
                supabase
                .table("bot_settings")
                .update(data)
                .eq("key", key)
                .execute()
            )

        else:

            (
                supabase
                .table("bot_settings")
                .insert({
                    "key": key,
                    "value": str(value)
                })
                .execute()
            )

        return True

    except Exception as e:

        print(
            "SET SETTING ERROR:",
            repr(e)
        )

        return False


def delete_setting(key):

    try:

        (
            supabase
            .table("bot_settings")
            .delete()
            .eq("key", key)
            .execute()
        )

        return True

    except Exception as e:

        print(
            "DELETE SETTING ERROR:",
            repr(e)
        )

        return False


# =========================================================
# OWNER / ADMIN
# =========================================================

def get_owner_id():
    return get_setting("owner_id")


def is_owner(user_id):

    owner_id = get_owner_id()

    if not owner_id:
        return False

    return str(user_id) == str(owner_id)


def is_admin(user_id):

    if not user_id:
        return False

    if is_owner(user_id):
        return True

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("active", True)
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as e:

        print(
            "IS ADMIN ERROR:",
            repr(e)
        )

        return False


# =========================================================
# AI ACCESS WHITELIST
#
# دسترسی به چت هوش مصنوعی (متن/عکس/صوت) پیش‌فرض فقط برای
# مدیران است. مدیران می‌توانند کاربران خاصی را هم به این
# لیست اضافه کنند تا فقط همان‌ها بتوانند از هوش مصنوعی
# استفاده کنند، بدون این‌که دسترسی مدیریتی داشته باشند.
# =========================================================

def is_ai_allowed(user_id):

    if not user_id:
        return False

    if is_admin(user_id):
        return True

    try:

        result = (
            supabase
            .table("ai_allowed_users")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("active", True)
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as e:

        print(
            "IS AI ALLOWED ERROR:",
            repr(e)
        )

        return False


def add_ai_allowed_user(user_id):

    user_id = str(user_id).strip()

    if not user_id:
        return False

    try:

        existing = (
            supabase
            .table("ai_allowed_users")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("ai_allowed_users")
                .update({
                    "active": True
                })
                .eq(
                    "id",
                    existing.data[0]["id"]
                )
                .execute()
            )

        else:

            (
                supabase
                .table("ai_allowed_users")
                .insert({
                    "user_id": user_id,
                    "active": True,
                    "created_at": now_iso()
                })
                .execute()
            )

        return True

    except Exception as e:

        print(
            "ADD AI ALLOWED USER ERROR:",
            repr(e)
        )

        return False


def remove_ai_allowed_user(user_id):

    user_id = str(user_id).strip()

    try:

        (
            supabase
            .table("ai_allowed_users")
            .update({
                "active": False
            })
            .eq(
                "user_id",
                user_id
            )
            .execute()
        )

        return True

    except Exception as e:

        print(
            "REMOVE AI ALLOWED USER ERROR:",
            repr(e)
        )

        return False


def list_ai_allowed_users():

    try:

        result = (
            supabase
            .table("ai_allowed_users")
            .select("user_id")
            .eq("active", True)
            .execute()
        )

        return [
            row["user_id"]
            for row in (result.data or [])
        ]

    except Exception as e:

        print(
            "LIST AI ALLOWED USERS ERROR:",
            repr(e)
        )

        return []


# =========================================================
# USERS
# =========================================================

def save_bot_user(user):

    if not user:
        return

    user_id = user.get("id")

    if user_id is None:
        return

    data = {
        "user_id": str(user_id),
        "username": clean_username(
            user.get("username")
        ),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "active": True,
        "updated_at": now_iso()
    }

    try:

        existing = (
            supabase
            .table("bot_users")
            .select("id")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("bot_users")
                .update(data)
                .eq(
                    "id",
                    existing.data[0]["id"]
                )
                .execute()
            )

        else:

            data["created_at"] = now_iso()

            (
                supabase
                .table("bot_users")
                .insert(data)
                .execute()
            )

    except Exception as e:

        print(
            "SAVE USER ERROR:",
            repr(e)
        )


# =========================================================
# CHANNEL DATABASE
# =========================================================

def get_channel_by_chat_id(chat_id):

    if chat_id is None:
        return None

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:

        print(
            "GET CHANNEL BY ID ERROR:",
            repr(e)
        )

    return None


def get_channel_by_username(username):

    username = clean_username(username)

    if not username:
        return None

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("username", username)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:

        print(
            "GET CHANNEL BY USERNAME ERROR:",
            repr(e)
        )

    return None


def update_channel_row(row_id, data):

    try:

        (
            supabase
            .table("channels")
            .update(data)
            .eq("id", row_id)
            .execute()
        )

        return True

    except Exception as e:

        print(
            "UPDATE CHANNEL ERROR:",
            repr(e)
        )

        return False


# =========================================================
# REGISTER CHAT
# =========================================================

def auto_register_chat(chat):

    if not chat:
        return False

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return False

    chat_id = chat.get("id")

    if chat_id is None:
        return False

    chat_id = str(chat_id)

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or username
        or chat_id
    )

    try:

        row = get_channel_by_chat_id(chat_id)

        if row:

            manually_disabled = (
                row.get("manually_disabled") is True
            )

            bot_member = row.get("bot_member")

            if bot_member is None:
                bot_member = True

            data = {
                "chat_id": chat_id,
                "username": username,
                "title": title
            }

            if manually_disabled:

                data["active"] = False

            elif bot_member is False:

                data["active"] = False

            else:

                data["active"] = True

            return update_channel_row(
                row["id"],
                data
            )

        if username:

            row = get_channel_by_username(username)

            if row:

                manually_disabled = (
                    row.get("manually_disabled") is True
                )

                bot_member = row.get("bot_member")

                if bot_member is None:
                    bot_member = True

                data = {
                    "chat_id": chat_id,
                    "username": username,
                    "title": title
                }

                if manually_disabled:

                    data["active"] = False

                elif bot_member is False:

                    data["active"] = False

                else:

                    data["active"] = True

                return update_channel_row(
                    row["id"],
                    data
                )

        (
            supabase
            .table("channels")
            .insert({
                "chat_id": chat_id,
                "username": username,
                "title": title,
                "active": True,
                "manually_disabled": False,
                "bot_member": True
            })
            .execute()
        )

        print(
            "AUTO REGISTERED:",
            chat_id,
            title,
            username
        )

        return True

    except Exception as e:

        print(
            "AUTO REGISTER ERROR:",
            repr(e)
        )

        return False


# =========================================================
# ACTIVATE CHAT
# =========================================================

def activate_chat(
    chat,
    clear_manual=True
):

    if not chat:
        return False

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return False

    chat_id = chat.get("id")

    if chat_id is None:
        return False

    chat_id = str(chat_id)

    username = clean_username(
        chat.get("username")
    )

    title = (
        chat.get("title")
        or username
        or chat_id
    )

    try:

        row = get_channel_by_chat_id(chat_id)

        data = {
            "chat_id": chat_id,
            "username": username,
            "title": title,
            "active": True,
            "bot_member": True
        }

        if clear_manual:
            data["manually_disabled"] = False

        if row:

            return update_channel_row(
                row["id"],
                data
            )

        data["manually_disabled"] = False

        (
            supabase
            .table("channels")
            .insert(data)
            .execute()
        )

        print(
            "ACTIVATED NEW CHAT:",
            chat_id,
            title
        )

        return True

    except Exception as e:

        print(
            "ACTIVATE CHAT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# DEACTIVATE CHAT
# =========================================================

def deactivate_chat(chat_id):

    if chat_id is None:
        return False

    try:

        row = get_channel_by_chat_id(chat_id)

        if not row:
            return False

        return update_channel_row(
            row["id"],
            {
                "active": False,
                "bot_member": False
            }
        )

    except Exception as e:

        print(
            "DEACTIVATE CHAT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# MANUAL ADD
# =========================================================

def manual_add_channel(identifier):

    if not identifier:

        return (
            False,
            "❌ شناسه یا نام کاربری مقصد وارد نشده است."
        )

    identifier = str(identifier).strip()

    try:

        chat = get_chat(identifier)

        if not chat:

            return (
                False,
                "❌ مقصد پیدا نشد.\n\n"
                "مطمئن شوید ربات در مقصد عضو است "
                "و شناسه یا نام کاربری درست است."
            )

        chat_type = chat.get("type")

        if chat_type not in (
            "group",
            "supergroup",
            "channel"
        ):

            return (
                False,
                "❌ این مقصد گروه یا کانال نیست."
            )

        ok = activate_chat(
            chat,
            clear_manual=True
        )

        if not ok:

            return (
                False,
                "❌ ثبت مقصد در پایگاه داده ناموفق بود."
            )

        title = (
            chat.get("title")
            or chat.get("username")
            or chat.get("id")
        )

        return (
            True,
            "✅ <b>مقصد فعال شد</b>\n\n"
            f"📡 {html_text(title)}\n"
            f"🆔 <code>{html_text(chat.get('id'))}</code>"
        )

    except Exception as e:

        print(
            "MANUAL ADD ERROR:",
            repr(e)
        )

        return (
            False,
            "❌ هنگام افزودن مقصد خطایی رخ داد."
        )


# =========================================================
# MANUAL REMOVE
# =========================================================

def manual_remove_channel(identifier):

    if not identifier:

        return (
            False,
            "❌ شناسه مقصد وارد نشده است."
        )

    identifier = str(identifier).strip()

    try:

        row = None

        if identifier.lstrip("-").isdigit():

            row = get_channel_by_chat_id(identifier)

        else:

            row = get_channel_by_username(identifier)

        if not row:

            return (
                False,
                "❌ این مقصد در لیست ربات پیدا نشد."
            )

        ok = update_channel_row(
            row["id"],
            {
                "active": False,
                "manually_disabled": True
            }
        )

        if not ok:

            return (
                False,
                "❌ حذف مقصد ناموفق بود."
            )

        return (
            True,
            "✅ <b>مقصد حذف شد</b>\n\n"
            f"📡 {html_text(row.get('title') or row.get('username') or row.get('chat_id'))}"
        )

    except Exception as e:

        print(
            "MANUAL REMOVE ERROR:",
            repr(e)
        )

        return (
            False,
            "❌ هنگام حذف مقصد خطایی رخ داد."
        )


# =========================================================
# SYNC
# =========================================================

def sync_channels():

    bot = get_me()

    if not bot:

        return {
            "checked": 0,
            "active": 0,
            "removed": 0,
            "errors": 1
        }

    bot_id = bot.get("id")

    if bot_id is None:

        return {
            "checked": 0,
            "active": 0,
            "removed": 0,
            "errors": 1
        }

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        print(
            "SYNC FETCH ERROR:",
            repr(e)
        )

        return {
            "checked": 0,
            "active": 0,
            "removed": 0,
            "errors": 1
        }

    checked = 0
    active = 0
    removed = 0
    errors = 0

    for row in rows:

        chat_id = row.get("chat_id")

        if not chat_id:
            continue

        checked += 1

        try:

            member = get_chat_member(
                chat_id,
                bot_id
            )

            if not member:

                # 🔧 خطای getChatMember نباید باعث شود کانال را
                # از گزارش‌گیری خارج کنیم. ممکن است کانال خصوصی
                # باشد یا API بله وضعیت عضویت را برنگرداند؛ اما اگر
                # channel_post واقعاً به ربات برسد، باید ثبت شود.
                errors += 1
                print(
                    "⚠️ SYNC MEMBERSHIP UNKNOWN - KEEP CHANNEL:",
                    chat_id
                )
                continue

            status = str(
                member.get("status", "")
            ).lower()

            print(
                "SYNC:",
                chat_id,
                status
            )

            if status in (
                "left",
                "kicked"
            ):

                # وضعیت عضویت برای مدیریت لیست نگه داشته می‌شود،
                # اما رکوردهای قبلی reposts هرگز حذف/فیلتر نمی‌شوند.
                update_channel_row(
                    row["id"],
                    {
                        "active": False,
                        "bot_member": False
                    }
                )

                removed += 1
                continue

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                data = {
                    "bot_member": True
                }

                if row.get("manually_disabled") is not True:

                    data["active"] = True
                    active += 1

                update_channel_row(
                    row["id"],
                    data
                )

            time.sleep(0.15)

        except Exception as e:

            errors += 1

            print(
                "SYNC CHAT ERROR:",
                chat_id,
                repr(e)
            )

    return {
        "checked": checked,
        "active": active,
        "removed": removed,
        "errors": errors
    }


# =========================================================
# CHANNEL LIST
# =========================================================

def get_active_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .eq("active", True)
            .order("title")
            .execute()
        )

        rows = result.data or []

        valid = []

        for row in rows:

            if row.get("manually_disabled") is True:
                continue

            if row.get("bot_member") is False:
                continue

            valid.append(row)

        return valid

    except Exception as e:

        print(
            "GET ACTIVE CHANNELS ERROR:",
            repr(e)
        )

        return []


def get_all_channels():

    try:

        result = (
            supabase
            .table("channels")
            .select("*")
            .order("title")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET ALL CHANNELS ERROR:",
            repr(e)
        )

        return []


# =========================================================
# BROADCAST (بازنشر گسترده)
# =========================================================

def broadcast_message_to_channels(
    from_chat_id,
    message_id
):

    channels = get_active_channels()

    success = []
    failed = []

    for row in channels:

        dest_chat_id = row.get(
            "chat_id"
        )

        if not dest_chat_id:
            continue

        try:

            result = forward_message(
                dest_chat_id,
                from_chat_id,
                message_id
            )

            if result:

                success.append(row)

                print(
                    "✅ BROADCAST OK:",
                    dest_chat_id
                )

            else:

                failed.append(row)

                print(
                    "❌ BROADCAST FAILED:",
                    dest_chat_id
                )

            # برای جلوگیری از rate-limit سرور بله
            time.sleep(0.25)

        except Exception as e:

            failed.append(row)

            print(
                "BROADCAST EXCEPTION:",
                dest_chat_id,
                repr(e)
            )

    return {
        "total": len(channels),
        "success": success,
        "failed": failed
    }


# =========================================================
# SOURCE EXTRACTION
# =========================================================

def extract_forward(message):

    if not message:
        return None

    print(
        "🔎 CHECK FORWARD MESSAGE:"
    )

    print(
        "MESSAGE KEYS:",
        list(message.keys())
    )

    forward_origin = message.get(
        "forward_origin"
    )

    forward_chat = None

    possible_forward_chat = (
        message.get("forward_from_chat")
        or message.get("forward_chat")
    )

    if isinstance(
        possible_forward_chat,
        dict
    ):
        forward_chat = possible_forward_chat

    if not forward_chat and isinstance(
        forward_origin,
        dict
    ):

        forward_chat = (
            forward_origin.get("chat")
            or forward_origin.get("sender_chat")
        )

    if not forward_chat:

        sender_chat = message.get(
            "sender_chat"
        )

        if (
            isinstance(sender_chat, dict)
            and (
                forward_origin
                or message.get("forward_from_message_id")
                or message.get("forwarded_message_id")
                or message.get("forward_message_id")
            )
        ):

            forward_chat = sender_chat

    if not forward_chat:

        print(
            "❌ FORWARD CHAT NOT FOUND"
        )

        return None

    source_chat_id = (
        forward_chat.get("id")
    )

    source_username = clean_username(
        forward_chat.get("username")
    )

    source_title = (
        forward_chat.get("title")
        or forward_chat.get("first_name")
        or source_username
        or source_chat_id
    )

    source_message_id = (
        message.get("forward_from_message_id")
        or message.get("forwarded_message_id")
        or message.get("forward_message_id")
    )

    if not source_message_id:

        if isinstance(
            forward_origin,
            dict
        ):

            source_message_id = (
                forward_origin.get("message_id")
                or forward_origin.get(
                    "forward_from_message_id"
                )
            )

    if not source_message_id:

        origin_message = (
            forward_origin.get("message")
            if isinstance(
                forward_origin,
                dict
            )
            else None
        )

        if isinstance(
            origin_message,
            dict
        ):

            source_message_id = (
                origin_message.get("message_id")
            )

    if source_chat_id is None:

        print(
            "❌ SOURCE CHAT ID NOT FOUND"
        )

        return None

    if source_message_id is None:

        print(
            "❌ SOURCE MESSAGE ID NOT FOUND"
        )

        return None

    source_link = (
        message.get("forward_link")
        or message.get("message_link")
        or message.get("link")
        or ""
    )

    if not source_link:

        source_link = resolve_message_link(
            source_username,
            source_chat_id,
            source_message_id
        )

    source = {
        "channel_id": str(source_chat_id),
        "message_id": str(source_message_id),
        "username": source_username,
        "title": source_title,
        "message_link": source_link
    }

    print(
        "✅ FORWARD DETECTED:"
    )

    print(
        "SOURCE CHAT:",
        source["channel_id"]
    )

    print(
        "SOURCE MESSAGE:",
        source["message_id"]
    )

    print(
        "SOURCE USERNAME:",
        source["username"]
    )

    print(
        "SOURCE TITLE:",
        source["title"]
    )

    print(
        "SOURCE LINK:",
        source["message_link"]
    )

    return source


# =========================================================
# ADMIN SOURCE DATABASE
# =========================================================

def set_selected_source(
    source,
    admin_user_id
):

    if not source:
        return False

    if not admin_user_id:
        return False

    admin_user_id = str(admin_user_id)

    data = {
        "admin_user_id": admin_user_id,
        "source_channel_id": str(
            source.get("channel_id") or ""
        ),
        "source_message_id": str(
            source.get("message_id") or ""
        ),
        "source_username": (
            source.get("username") or ""
        ),
        "source_title": (
            source.get("title") or ""
        ),
        "source_message_link": (
            source.get("message_link") or ""
        ),
        "updated_at": now_iso()
    }

    try:

        existing = (
            supabase
            .table("admin_sources")
            .select("admin_user_id")
            .eq(
                "admin_user_id",
                admin_user_id
            )
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("admin_sources")
                .update(data)
                .eq(
                    "admin_user_id",
                    admin_user_id
                )
                .execute()
            )

        else:

            data["created_at"] = now_iso()

            (
                supabase
                .table("admin_sources")
                .insert(data)
                .execute()
            )

        text = (
            "✅ <b>پست مبدأ انتخاب شد</b>\n\n"
            f"📡 کانال: "
            f"{html_text(source.get('title') or '-')}\n"
            f"🆔 شناسه کانال: "
            f"<code>{html_text(source.get('channel_id') or '-')}</code>\n"
            f"📝 شناسه پست: "
            f"<code>{html_text(source.get('message_id') or '-')}</code>"
        )

        send_message(
            admin_user_id,
            text,
            source_report_keyboard()
        )

        if source.get("message_link"):

            link_text = markdown_link(
                "مشاهده پست مبدأ",
                source.get("message_link"),
                "🔵"
            )

            send_markdown_message(
                admin_user_id,
                link_text
            )

        # ---------------------------------------------------
        # 🔧 بلافاصله گزارش کامل همین پست را هم می‌فرستیم؛
        # چون بازنشرها دیگر مستقل از زمان انتخاب source ذخیره
        # می‌شوند، این گزارش شامل بازنشرهایی هم می‌شود که قبل
        # از این انتخاب در کانال‌ها/گروه‌های فعال ثبت شده بودند.
        # ---------------------------------------------------

        try:

            send_markdown_message(
                admin_user_id,
                generate_report_markdown(
                    admin_user_id
                ),
                main_keyboard(
                    admin_user_id
                )
            )

        except Exception as report_error:

            print(
                "AUTO REPORT AFTER SELECT ERROR:",
                repr(report_error)
            )

        return True

    except Exception as e:

        print(
            "SET ADMIN SOURCE ERROR:",
            repr(e)
        )

        send_message(
            admin_user_id,
            "❌ ذخیره پست مبدأ ناموفق بود."
        )

        return False


def get_selected_source(admin_user_id):

    if not admin_user_id:
        return {}

    try:

        result = (
            supabase
            .table("admin_sources")
            .select("*")
            .eq(
                "admin_user_id",
                str(admin_user_id)
            )
            .limit(1)
            .execute()
        )

        if not result.data:
            return {}

        row = result.data[0]

        return {
            "admin_user_id": str(
                row.get("admin_user_id")
            ),
            "channel_id": row.get(
                "source_channel_id"
            ),
            "message_id": row.get(
                "source_message_id"
            ),
            "username": row.get(
                "source_username"
            ),
            "title": row.get(
                "source_title"
            ),
            "message_link": row.get(
                "source_message_link"
            )
        }

    except Exception as e:

        print(
            "GET SELECTED SOURCE ERROR:",
            repr(e)
        )

        return {}


def get_all_selected_sources():

    try:

        result = (
            supabase
            .table("admin_sources")
            .select("*")
            .execute()
        )

        rows = result.data or []

        sources = []

        for row in rows:

            admin_user_id = row.get(
                "admin_user_id"
            )

            channel_id = row.get(
                "source_channel_id"
            )

            message_id = row.get(
                "source_message_id"
            )

            if not admin_user_id:
                continue

            if not channel_id:
                continue

            if not message_id:
                continue

            sources.append({
                "admin_user_id": str(
                    admin_user_id
                ),
                "channel_id": str(
                    channel_id
                ),
                "message_id": str(
                    message_id
                ),
                "username": row.get(
                    "source_username"
                ),
                "title": row.get(
                    "source_title"
                ),
                "message_link": row.get(
                    "source_message_link"
                )
            })

        return sources

    except Exception as e:

        print(
            "GET ALL SELECTED SOURCES ERROR:",
            repr(e)
        )

        return []


# =========================================================
# FORWARD MATCHING
# =========================================================

def message_matches_source(
    message,
    source
):

    if not message:
        return False

    if not source:
        return False

    source_channel_id = source.get(
        "channel_id"
    )

    source_message_id = source.get(
        "message_id"
    )

    if not source_channel_id:
        return False

    if not source_message_id:
        return False

    forwarded = extract_forward(
        message
    )

    if not forwarded:

        print(
            "⏭ DESTINATION MESSAGE IS NOT A FORWARD"
        )

        return False

    destination_source_chat_id = (
        forwarded.get("channel_id")
    )

    destination_source_message_id = (
        forwarded.get("message_id")
    )

    matched = (
        str(destination_source_chat_id)
        == str(source_channel_id)
        and
        str(destination_source_message_id)
        == str(source_message_id)
    )

    if matched:

        print(
            "✅ SOURCE MATCHED!"
        )

        print(
            "SOURCE:",
            source_channel_id,
            source_message_id
        )

        print(
            "FORWARD:",
            destination_source_chat_id,
            destination_source_message_id
        )

        return True

    print(
        "❌ SOURCE NOT MATCHED"
    )

    print(
        "SELECTED SOURCE:",
        source_channel_id,
        source_message_id
    )

    print(
        "FORWARDED SOURCE:",
        destination_source_chat_id,
        destination_source_message_id
    )

    return False


# =========================================================
# REPOST DATABASE
# =========================================================

def repost_exists(
    source_channel_id,
    source_message_id,
    destination_channel_id
):

    try:

        result = (
            supabase
            .table("reposts")
            .select("id")
            .eq(
                "source_channel_id",
                str(source_channel_id)
            )
            .eq(
                "source_message_id",
                str(source_message_id)
            )
            .eq(
                "destination_channel_id",
                str(destination_channel_id)
            )
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception as e:

        print(
            "REPOST EXISTS ERROR:",
            repr(e)
        )

        return False


def save_repost(
    source,
    destination,
    destination_message_id,
    message_title="",
    message=None
):

    try:

        destination_username = clean_username(
            destination.get("username")
        )

        destination_link = resolve_message_link(
            destination_username,
            destination.get("id"),
            destination_message_id
        )

        views = extract_message_views(
            message
        )

        data = {
            "source_channel_id": source.get(
                "channel_id"
            ),
            "source_username": source.get(
                "username"
            ),
            "source_message_id": source.get(
                "message_id"
            ),
            "source_message_link": source.get(
                "message_link"
            ),
            "destination_channel_id": str(
                destination.get("id")
            ),
            "destination_username": destination_username,
            "destination_message_id": str(
                destination_message_id
            ),
            "destination_title": (
                destination.get("title")
                or destination.get("username")
                or destination.get("id")
            ),
            "message_title": message_title or "",
            "created_at": now_iso()
        }

        if destination_link:

            data[
                "destination_message_link"
            ] = destination_link

        # 🧪 آزمایشی: فقط اگر واقعاً عددی برای ویو پیدا شد
        # اضافه می‌شود. چون ممکن است ستون "views" در جدول
        # reposts وجود نداشته باشد، این فیلد جزو موارد
        # fallback-پذیر در ادامه است.
        if views is not None:

            data["views"] = views

        if repost_exists(
            source.get("channel_id"),
            source.get("message_id"),
            destination.get("id")
        ):

            print(
                "⚠️ REPOST ALREADY EXISTS"
            )

            return False

        # -------------------------------------------------
        # تلاش با تمام فیلدها؛ در صورت خطا، فیلدهای احتمالاً
        # ناموجود در جدول (destination_message_link و سپس
        # views) به‌ترتیب حذف و دوباره تلاش می‌شود.
        # -------------------------------------------------

        attempt_data = dict(data)

        for attempt in range(3):

            try:

                result = (
                    supabase
                    .table("reposts")
                    .insert(attempt_data)
                    .execute()
                )

                return bool(result.data)

            except Exception as insert_error:

                print(
                    "SAVE REPOST INSERT ERROR "
                    f"(attempt {attempt + 1}):",
                    repr(insert_error)
                )

                if "destination_message_link" in attempt_data:

                    attempt_data.pop(
                        "destination_message_link",
                        None
                    )

                    continue

                if "views" in attempt_data:

                    attempt_data.pop(
                        "views",
                        None
                    )

                    continue

                raise

        return False

    except Exception as e:

        print(
            "SAVE REPOST ERROR:",
            repr(e)
        )

        return False


# =========================================================
# MESSAGE TITLE
# =========================================================

def get_message_title(message):

    if not message:
        return "بدون عنوان"

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    text = str(text).strip()

    if not text:
        return "بدون عنوان"

    title = text.splitlines()[0].strip()

    if len(title) > 100:
        title = title[:100] + "…"

    return title


def extract_message_views(message):

    # 🧪 حالت آزمایشی: مستندات رسمی بله فیلد "views" را در
    # شیء Message تعریف نکرده‌اند، اما اگر روزی این فیلد
    # (یا مشابهش) به‌صورت مستندنشده در payload پیام موجود
    # باشد، اینجا آن را می‌گیریم. اگر هیچ‌کدام وجود نداشته
    # باشد، فقط None برمی‌گردد و هیچ خطایی رخ نمی‌دهد.

    if not message:
        return None

    for key in (
        "views",
        "view_count",
        "views_count",
        "seen_count"
    ):

        value = message.get(key)

        if value is None:
            continue

        try:

            return int(value)

        except Exception:

            continue

    return None


def update_repost_views(source_channel_id, source_message_id, destination_channel_id, message):
    """در صورت وجود ویو در payload، رکورد بازنشر قبلی را به‌روزرسانی می‌کند."""
    views = extract_message_views(message)
    if views is None:
        return False
    try:
        result = (
            supabase.table("reposts").update({"views": views})
            .eq("source_channel_id", str(source_channel_id))
            .eq("source_message_id", str(source_message_id))
            .eq("destination_channel_id", str(destination_channel_id))
            .execute()
        )
        print("👁 REPOST VIEWS UPDATED:", source_channel_id, source_message_id, destination_channel_id, views)
        return bool(result.data)
    except Exception as e:
        print("UPDATE REPOST VIEWS ERROR:", repr(e))
        return False


# =========================================================
# ADMIN IDS
# =========================================================

def get_admin_ids():

    ids = []

    owner_id = get_owner_id()

    if owner_id:
        ids.append(str(owner_id))

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("user_id")
            .eq("active", True)
            .execute()
        )

        for row in result.data or []:

            user_id = row.get("user_id")

            if user_id:

                user_id = str(user_id)

                if user_id not in ids:
                    ids.append(user_id)

    except Exception as e:

        print(
            "GET ADMIN IDS ERROR:",
            repr(e)
        )

    return ids


# =========================================================
# REPOST ALERT
# =========================================================

def send_repost_alert(
    admin_user_id,
    source,
    destination,
    message,
    destination_message_id
):

    if not admin_user_id:
        return

    admin_user_id = str(
        admin_user_id
    )

    destination_username = clean_username(
        destination.get("username")
    )

    destination_chat_id = destination.get("id")

    destination_link = resolve_message_link(
        destination_username,
        destination_chat_id,
        destination_message_id
    )

    source_link = source.get(
        "message_link"
    )

    if not source_link:

        source_link = resolve_message_link(
            source.get("username"),
            source.get("channel_id"),
            source.get("message_id")
        )

    title = get_message_title(
        message
    )

    live_views = extract_message_views(message)

    text = (
        "🔔 <b>بازنشر جدید شناسایی شد</b>\n\n"
        f"📡 <b>مقصد:</b> "
        f"{html_text(destination.get('title') or '-')}"
    )

    if destination_username:

        text += (
            f"\n🔖 <b>نام کاربری:</b> "
            f"@{html_text(destination_username)}"
        )

    text += (
        f"\n📝 <b>عنوان:</b> "
        f"{html_text(title)}\n"
        f"🕐 <b>زمان:</b> "
        f"{format_iran_datetime(now_iso())}"
    )

    if live_views is not None:
        text += (
            f"\n👁 <b>ویو:</b> "
            f"{to_persian_digits(live_views)}"
        )

    # فقط همان مدیر
    send_message(
        admin_user_id,
        text
    )

    if source_link:

        send_markdown_message(
            admin_user_id,
            markdown_link(
                "مشاهده پست مبدأ",
                source_link,
                "🔵"
            )
        )

    if destination_link:

        send_markdown_message(
            admin_user_id,
            markdown_link(
                "مشاهده پست مقصد",
                destination_link,
                "🟢"
            )
        )

    else:

        send_message(
            admin_user_id,
            "🟢 ⚠️ لینک مستقیم پست مقصد در دسترس نیست."
        )


# =========================================================
# PROCESS CHANNEL/GROUP MESSAGE
# =========================================================

def process_channel_message(message):

    if not message:
        return

    chat = message.get("chat")

    if not chat:
        return

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return

    chat_id = chat.get("id")

    if chat_id is None:
        return

    destination_message_id = message.get(
        "message_id"
    )

    if destination_message_id is None:
        return

    print(
        "\n"
        "📡 DESTINATION MESSAGE RECEIVED"
    )

    print(
        "DESTINATION CHAT:",
        chat_id
    )

    print(
        "DESTINATION TYPE:",
        chat_type
    )

    print(
        "DESTINATION MESSAGE:",
        destination_message_id
    )

    # -----------------------------------------------------
    # هر پیام دریافتی از یک کانال/گروه، خودش دلیلی است بر اینکه
    # ربات هنوز عضو آن است. اگر مقصد قبلاً ثبت نشده یا به هر
    # دلیلی active/bot_member آن نادرست شده، اینجا آن را
    # خودکار به‌روزرسانی می‌کنیم تا از دست رفتن ثبت کانال‌ها
    # (که باعث گزارش‌گیری نشدن می‌شد) جلوگیری شود.
    # -----------------------------------------------------

    auto_register_chat(chat)

    row = get_channel_by_chat_id(
        chat_id
    )

    if not row:

        print(
            "⏭ DESTINATION NOT REGISTERED:",
            chat_id
        )

        return

    # -----------------------------------------------------
    # 🔧 اصلاح مهم: ثبت بازنشر نباید به وضعیت active / bot_member
    # / manually_disabled وابسته باشد.
    # اگر بله یک channel_post را به ربات تحویل داده باشد، همان
    # آپدیت معتبر است و باید بازنشر ثبت شود؛ حتی اگر کانال خصوصی
    # باشد یا ربات ادمین نباشد. وضعیت عضویت فقط برای مدیریت لیست
    # کانال‌هاست و نباید باعث حذف رکورد بازنشر شود.
    # -----------------------------------------------------

    print(
        "✅ PROCESSING RECEIVED CHANNEL POST WITHOUT MEMBERSHIP GATE:",
        chat_id
    )

    # -----------------------------------------------------
    # مقصد
    # -----------------------------------------------------

    destination = {
        "id": str(chat_id),
        "username": chat.get("username"),
        "title": (
            chat.get("title")
            or chat.get("username")
            or chat_id
        )
    }

    title = get_message_title(
        message
    )

    # -----------------------------------------------------
    # بررسی Forward
    #
    # 🔧 نکته‌ی مهم: منبع (source) این پست از روی خودِ Forward
    # استخراج می‌شود، نه از روی «پست مبدأ انتخابی» یک مدیر خاص.
    # به همین دلیل ثبت بازنشر کاملاً مستقل از اینکه در همان
    # لحظه کسی این پست را به‌عنوان مبدأ انتخاب کرده باشد یا نه
    # انجام می‌شود. این کار باعث می‌شود وقتی یک مدیر بعداً همین
    # پست را در خصوصی برای ربات Forward می‌کند، تمام بازنشرهای
    # قبلی آن (چه قبل چه بعد از انتخاب) در گزارش دیده شوند و
    # گزارش هر بار از صفر شروع نشود.
    # -----------------------------------------------------

    forwarded = extract_forward(
        message
    )

    if not forwarded:

        print(
            "⏭ MESSAGE IS NOT A FORWARD"
        )

        # ---------------------------------------------------
        # 🤖 اگر این یک فوروارد نبود، شاید یک دستور (عکس/خلاصه/
        # بازنویسی/صوت) یا یک سوال معمولی از طرف یکی از اعضای
        # گروه باشد.
        #
        # 🔧 کانال هم اینجا بررسی می‌شود (نه فقط گروه/سوپرگروه):
        # چون در کانال فقط ادمین‌های همان کانال می‌توانند پست
        # بگذارند، هر post که به دستِ ربات برسد خودبه‌خود از طرف
        # یک ادمین است - نیازی به بررسی جداگانه‌ی هویت نیست. برای
        # همین دستورات (مثلاً ریپلای روی یک پست + /voice) اینجا
        # هم فعال می‌شوند، ولی پاسخ‌گویی آزاد با منشن (که به شناسه‌ی
        # فرستنده نیاز دارد و در کانال اصلاً وجود ندارد) فقط برای
        # گروه/سوپرگروه باقی می‌ماند.
        # ---------------------------------------------------

        if chat_type in ("group", "supergroup", "channel"):

            try:

                bot = get_me()
                bot_id = bot.get("id") if bot else None
                bot_username = bot.get("username") if bot else None

                # 🖼 دستور ساخت عکس (/image یا /عکس)
                if handle_image_command(
                    message,
                    chat,
                    bot_username
                ):
                    return

                if handle_summary_command(
                    message,
                    chat,
                    bot_username
                ):
                    return

                if handle_rewrite_command(
                    message,
                    chat,
                    bot_username
                ):
                    return

                # 🎙 خبر به صوت (/voice، /خبر یا /news) - معمولاً با
                # ریپلای روی یک پست استفاده می‌شود.
                if handle_voice_command(
                    message,
                    chat,
                    bot_username
                ):
                    return

                # 🖌 ویرایش عکس (/ویرایش یا /edit_image) - با ریپلای
                # روی یک عکس استفاده می‌شود.
                if handle_edit_image_command(
                    message,
                    chat,
                    bot_username
                ):
                    return

                if chat_type in ("group", "supergroup"):

                    handle_ai_question(
                        message,
                        chat,
                        chat_type,
                        bot_id,
                        bot_username,
                        require_mention=True
                    )

            except Exception as e:

                print(
                    "AI GROUP REPLY ERROR:",
                    repr(e)
                )

                traceback.print_exc()

        return

    source = forwarded

    print(
        "FORWARDED SOURCE:",
        source.get("channel_id"),
        source.get("message_id")
    )

    # -----------------------------------------------------
    # ذخیره‌ی بازنشر (مستقل از انتخاب مدیر)
    # -----------------------------------------------------

    already_exists = repost_exists(
        source.get("channel_id"),
        source.get("message_id"),
        str(chat_id)
    )

    if already_exists:

        print(
            "⏭ REPOST ALREADY EXISTS:",
            source.get("channel_id"),
            source.get("message_id"),
            chat_id
        )

        # اگر payload ویو داشته باشد، رکورد قبلی را هم به‌روزرسانی کن.
        update_repost_views(
            source.get("channel_id"),
            source.get("message_id"),
            str(chat_id),
            message
        )

        # بازنشر تکراری دوباره اعلان نمی‌شود.
        return

    saved = save_repost(
        source,
        destination,
        destination_message_id,
        title,
        message
    )

    if not saved:

        print(
            "❌ REPOST WAS NOT SAVED:",
            source.get("channel_id"),
            source.get("message_id"),
            chat_id
        )

        return

    print("=" * 60)
    print("✅ REPOST SAVED")
    print(
        "SOURCE:",
        source.get("channel_id"),
        source.get("message_id")
    )
    print(
        "DESTINATION:",
        chat_id,
        destination_message_id
    )
    print("=" * 60)

    # -----------------------------------------------------
    # اگر مدیری همین لحظه دقیقاً همین source را به‌عنوان مبدأ
    # انتخاب کرده باشد، فوراً به او اعلان لحظه‌ای می‌فرستیم.
    # (اگر هنوز کسی این source را انتخاب نکرده باشد، بازنشر
    # همچنان ذخیره شده و بعداً که مدیر آن پست را Forward کند
    # در گزارش کامل نمایش داده می‌شود.)
    # -----------------------------------------------------

    selected_sources = get_all_selected_sources()

    forwarded_channel_id = str(
        source.get("channel_id")
    )

    forwarded_message_id = str(
        source.get("message_id")
    )

    for admin_source in selected_sources:

        source_channel_id = str(
            admin_source.get("channel_id")
        )

        source_message_id = str(
            admin_source.get("message_id")
        )

        matched = (
            forwarded_channel_id
            == source_channel_id
            and
            forwarded_message_id
            == source_message_id
        )

        if not matched:
            continue

        admin_user_id = admin_source.get(
            "admin_user_id"
        )

        if not admin_user_id:
            continue

        print(
            "🎯 LIVE ALERT TO ADMIN:",
            admin_user_id
        )

        send_repost_alert(
            admin_user_id,
            admin_source,
            destination,
            message,
            destination_message_id
        )


# =========================================================
# MEMBERSHIP UPDATE
# =========================================================

def handle_bot_membership_update(update):

    bot = get_me()

    if not bot:
        return False

    bot_id = str(
        bot.get("id")
    )

    my_chat_member = update.get(
        "my_chat_member"
    )

    if my_chat_member:

        print(
            "🔥 FOUND my_chat_member"
        )

        print(
            my_chat_member
        )

        chat = my_chat_member.get(
            "chat"
        )

        new_member = (
            my_chat_member.get(
                "new_chat_member"
            )
            or {}
        )

        user = (
            new_member.get("user")
            or {}
        )

        if (
            chat
            and str(user.get("id"))
            == bot_id
        ):

            status = str(
                new_member.get("status", "")
            ).lower()

            print(
                "BOT MEMBERSHIP:",
                chat.get("id"),
                status
            )

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                activate_chat(
                    chat,
                    clear_manual=True
                )

            elif status in (
                "left",
                "kicked"
            ):

                deactivate_chat(
                    chat.get("id")
                )

            return True

    chat_member = update.get(
        "chat_member"
    )

    if chat_member:

        print(
            "🔥 FOUND chat_member"
        )

        print(
            chat_member
        )

        chat = chat_member.get(
            "chat"
        )

        new_member = (
            chat_member.get(
                "new_chat_member"
            )
            or {}
        )

        user = (
            new_member.get("user")
            or {}
        )

        if (
            chat
            and str(user.get("id"))
            == bot_id
        ):

            status = str(
                new_member.get("status", "")
            ).lower()

            print(
                "BOT CHAT MEMBER:",
                chat.get("id"),
                status
            )

            if status in (
                "member",
                "administrator",
                "creator",
                "restricted"
            ):

                activate_chat(
                    chat,
                    clear_manual=True
                )

            elif status in (
                "left",
                "kicked"
            ):

                deactivate_chat(
                    chat.get("id")
                )

            return True

    return False


# =========================================================
# GROUP SERVICE MESSAGE
# =========================================================

def handle_group_service_message(message):

    if not message:
        return False

    chat = message.get("chat")

    if not chat:
        return False

    chat_type = chat.get("type")

    # 🔧 نکته‌ی مهم درباره‌ی بله: برخلاف رفتار معمول تلگرام،
    # بله رویداد «اضافه/حذف شدن ربات» را برای کانال‌ها هم از
    # طریق همین پیام سرویسی (new_chat_members / left_chat_member)
    # می‌فرستد، نه صرفاً از طریق my_chat_member. پس باید نوع
    # "channel" را هم اینجا پوشش بدهیم، وگرنه ربات هیچ‌وقت
    # از اضافه/حذف شدنش در کانال باخبر نمی‌شود.
    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return False

    bot = get_me()

    if not bot:
        return False

    bot_id = str(
        bot.get("id")
    )

    # -----------------------------------------------------
    # BOT ADDED
    # -----------------------------------------------------

    new_members = (
        message.get("new_chat_members")
        or []
    )

    if isinstance(
        new_members,
        dict
    ):

        new_members = [
            new_members
        ]

    for member in new_members:

        if not isinstance(
            member,
            dict
        ):
            continue

        member_id = member.get("id")

        user_obj = member.get(
            "user"
        )

        if isinstance(
            user_obj,
            dict
        ):

            member_id = (
                user_obj.get("id")
                or member_id
            )

        if str(member_id) == bot_id:

            print("=" * 50)
            print("🔥 BOT ADDED TO GROUP")
            print("CHAT:", chat)
            print("=" * 50)

            activate_chat(
                chat,
                clear_manual=True
            )

            return True

    # -----------------------------------------------------
    # BOT REMOVED
    # -----------------------------------------------------

    left_member = message.get(
        "left_chat_member"
    )

    if left_member:

        member_id = None

        if isinstance(
            left_member,
            dict
        ):

            member_id = left_member.get(
                "id"
            )

            user_obj = left_member.get(
                "user"
            )

            if isinstance(
                user_obj,
                dict
            ):

                member_id = (
                    user_obj.get("id")
                    or member_id
                )

        if str(member_id) == bot_id:

            print("=" * 50)
            print("🔴 BOT REMOVED FROM GROUP")
            print("CHAT:", chat)
            print("=" * 50)

            deactivate_chat(
                chat.get("id")
            )

            return True

    return False


# =========================================================
# REPORT DATA
# =========================================================

def get_reposts_for_selected_source(
    admin_user_id
):

    source = get_selected_source(
        admin_user_id
    )

    if not source.get("channel_id"):
        return source, []

    if not source.get("message_id"):
        return source, []

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_channel_id",
                str(source.get("channel_id"))
            )
            .eq(
                "source_message_id",
                str(source.get("message_id"))
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        rows = result.data or []

    except Exception as e:

        print(
            "GET REPOSTS ERROR:",
            repr(e)
        )

        return source, []

    # -----------------------------------------------------
    # 🔧 اصلاح مهم گزارش:
    # گزارش باید تمام بازنشرهای ثبت‌شده را نشان دهد.
    # قبلاً فقط مقصدهای active نمایش داده می‌شدند؛ بنابراین اگر
    # کانال خصوصی بود، bot_member اشتباه ثبت شده بود، یا sync آن
    # را inactive کرده بود، رکورد واقعی از گزارش حذف می‌شد.
    # -----------------------------------------------------

    print(
        "📊 REPORT ROWS FOUND:",
        len(rows),
        "FOR SOURCE:",
        source.get("channel_id"),
        source.get("message_id")
    )

    return source, rows


# =========================================================
# PAIR REPORT (گزارش مبدأ ↔ مقصد)
# =========================================================

def resolve_pair_source_from_message(message):

    forwarded = extract_forward(
        message
    )

    if forwarded:

        return {
            "channel_id": str(
                forwarded.get("channel_id")
            ),
            "username": forwarded.get(
                "username"
            ),
            "title": forwarded.get(
                "title"
            )
        }

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:
        return None

    chat = get_chat(text)

    if not chat:
        return None

    chat_type = chat.get("type")

    if chat_type not in (
        "group",
        "supergroup",
        "channel"
    ):
        return None

    return {
        "channel_id": str(
            chat.get("id")
        ),
        "username": clean_username(
            chat.get("username")
        ),
        "title": (
            chat.get("title")
            or chat.get("username")
            or chat.get("id")
        )
    }


def resolve_pair_destination_from_identifier(identifier):

    if not identifier:
        return None

    identifier = str(identifier).strip()

    if not identifier:
        return None

    row = None

    if identifier.lstrip("-").isdigit():

        row = get_channel_by_chat_id(
            identifier
        )

    else:

        row = get_channel_by_username(
            identifier
        )

    return row


def get_reposts_for_source_destination(
    source_channel_id,
    destination_channel_id
):

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .eq(
                "source_channel_id",
                str(source_channel_id)
            )
            .eq(
                "destination_channel_id",
                str(destination_channel_id)
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET PAIR REPOSTS ERROR:",
            repr(e)
        )

        return []


def generate_pair_report(
    source,
    destination_row
):

    destination_chat_id = destination_row.get(
        "chat_id"
    )

    rows = get_reposts_for_source_destination(
        source.get("channel_id"),
        destination_chat_id
    )

    destination_title = (
        destination_row.get("title")
        or destination_row.get("username")
        or destination_row.get("chat_id")
        or "-"
    )

    members_count = get_chat_members_count(
        destination_chat_id
    )

    text = (
        "📍 <b>گزارش مبدأ ↔ مقصد</b>\n\n"
        f"📡 <b>مبدأ:</b> "
        f"{html_text(source.get('title') or '-')}\n"
        f"🎯 <b>مقصد:</b> "
        f"{html_text(destination_title)}\n"
    )

    if members_count is not None:

        text += (
            f"👥 <b>اعضای مقصد:</b> "
            f"{to_persian_digits(members_count)}\n"
        )

    text += (
        f"\n📈 <b>تعداد کل بازنشرها:</b> "
        f"{to_persian_digits(len(rows))}\n"
    )

    if not rows:

        text += (
            "\n"
            "ℹ️ هنوز هیچ بازنشری بین این مبدأ "
            "و مقصد ثبت نشده است."
        )

        return text

    total_views = sum(
        int(row.get("views") or 0)
        for row in rows
        if str(row.get("views") or "").isdigit()
    )

    if total_views > 0:

        text += (
            f"👁 <b>مجموع ویوهای ثبت‌شده:</b> "
            f"{to_persian_digits(total_views)}\n"
        )

    text += "\n"

    for index, row in enumerate(
        rows,
        start=1
    ):

        message_title = (
            row.get("message_title")
            or "بدون عنوان"
        )

        created_at_raw = row.get(
            "created_at"
        )

        created_at = format_iran_datetime(
            created_at_raw
        )

        elapsed = humanize_elapsed_fa(
            created_at_raw
        )

        destination_link = (
            row.get(
                "destination_message_link"
            )
            or ""
        )

        views_count = row.get(
            "views"
        )

        text += (
            f"<b>{to_persian_digits(index)}.</b> "
            f"📝 {html_text(message_title)}\n"
            f"   🕐 {html_text(created_at)} "
            f"({html_text(elapsed)})\n"
        )

        if views_count is not None:

            text += (
                f"   👁 ویو: "
                f"{to_persian_digits(views_count)}\n"
            )

        if destination_link:

            text += (
                f"   🟢 <code>"
                f"{html_text(destination_link)}"
                f"</code>\n"
            )

        text += "\n"

    return text


# =========================================================
# EXCEL EXPORT
# =========================================================

def build_reposts_excel(
    rows,
    sheet_title="گزارش بازنشر"
):

    wb = openpyxl.Workbook()

    ws = wb.active

    ws.title = (
        sheet_title[:31]
        if sheet_title
        else "گزارش"
    )

    ws.sheet_view.rightToLeft = True

    headers = [
        "ردیف",
        "مبدأ",
        "شناسه پست مبدأ",
        "مقصد",
        "نام‌کاربری مقصد",
        "عنوان پست",
        "تعداد ویو",
        "تاریخ (شمسی)",
        "چه مدت پیش",
        "لینک مقصد"
    ]

    header_font = Font(
        name="Arial",
        bold=True,
        color="FFFFFF"
    )

    header_fill = PatternFill(
        start_color="2F5597",
        end_color="2F5597",
        fill_type="solid"
    )

    body_font = Font(
        name="Arial"
    )

    center_align = Alignment(
        horizontal="center",
        vertical="center",
        wrap_text=True
    )

    for col_index, header in enumerate(
        headers,
        start=1
    ):

        cell = ws.cell(
            row=1,
            column=col_index,
            value=header
        )

        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    for row_index, row in enumerate(
        rows,
        start=2
    ):

        created_at_raw = row.get(
            "created_at"
        )

        views_value = row.get(
            "views"
        )

        source_label = (
            row.get("source_username")
            or row.get("source_channel_id")
            or "-"
        )

        destination_label = (
            row.get("destination_title")
            or row.get("destination_username")
            or row.get("destination_channel_id")
            or "-"
        )

        values = [
            row_index - 1,
            source_label,
            row.get("source_message_id") or "-",
            destination_label,
            row.get("destination_username") or "-",
            row.get("message_title") or "بدون عنوان",
            (
                views_value
                if views_value is not None
                else "-"
            ),
            format_iran_datetime(
                created_at_raw
            ),
            humanize_elapsed_fa(
                created_at_raw
            ),
            row.get(
                "destination_message_link"
            ) or "-"
        ]

        for col_index, value in enumerate(
            values,
            start=1
        ):

            cell = ws.cell(
                row=row_index,
                column=col_index,
                value=value
            )

            cell.font = body_font
            cell.alignment = center_align

    column_widths = [
        6, 22, 16, 24, 18, 32, 10, 18, 14, 42
    ]

    for col_index, width in enumerate(
        column_widths,
        start=1
    ):

        col_letter = ws.cell(
            row=1,
            column=col_index
        ).column_letter

        ws.column_dimensions[
            col_letter
        ].width = width

    ws.freeze_panes = "A2"

    tmp_dir = tempfile.gettempdir()

    file_name = (
        f"repost_report_{int(time.time())}.xlsx"
    )

    file_path = os.path.join(
        tmp_dir,
        file_name
    )

    wb.save(file_path)

    return file_path


def get_all_reposts():

    try:

        result = (
            supabase
            .table("reposts")
            .select("*")
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "GET ALL REPOSTS ERROR:",
            repr(e)
        )

        return []


# =========================================================
# REPORT MARKDOWN
# =========================================================

def generate_report_markdown(
    admin_user_id
):

    source, rows = get_reposts_for_selected_source(
        admin_user_id
    )

    if not source.get("channel_id"):

        return (
            "📊 *گزارش بازنشر*\n\n"
            "⚠️ هنوز پست مبدأ انتخاب نشده است.\n\n"
            "یک پست را از کانال مبدأ برای ربات "
            "Forward کنید."
        )

    source_message_id = str(
        source.get("message_id")
    )

    source_link = source.get(
        "message_link"
    )

    if not source_link:

        source_link = resolve_message_link(
            source.get("username"),
            source.get("channel_id"),
            source.get("message_id")
        )

        if source_link:

            try:

                (
                    supabase
                    .table("admin_sources")
                    .update({
                        "source_message_link": source_link,
                        "updated_at": now_iso()
                    })
                    .eq(
                        "admin_user_id",
                        str(admin_user_id)
                    )
                    .execute()
                )

            except Exception as e:

                print(
                    "UPDATE SOURCE LINK ERROR:",
                    repr(e)
                )

    text = (
        "📊 *گزارش همین پست*\n\n"
        f"📡 *مبدأ:* "
        f"{markdown_text(source.get('title') or '-')}\n"
        f"🆔 *شناسه پست:* "
        f"`{markdown_text(source_message_id)}`\n"
    )

    if source_link:

        text += (
            "\n"
            + markdown_link(
                "مشاهده پست مبدأ",
                source_link,
                "🔵"
            )
            + "\n"
        )

    else:

        text += (
            "\n"
            "🔵 ⚠️ لینک پست مبدأ در دسترس نیست.\n"
        )

    text += (
        f"\n📈 *تعداد بازنشر فعال:* "
        f"{to_persian_digits(len(rows))}\n"
    )

    if not rows:

        text += (
            "\n"
            "ℹ️ هنوز بازنشری از این پست "
            "در مقصدهای فعال ثبت نشده است.\n\n"
            "💡 توجه: ربات فقط بازنشرهایی را ثبت می‌کند "
            "که بعد از انتخاب پست مبدأ دریافت شوند."
        )

        return text

    text += "\n"

    for index, row in enumerate(
        rows,
        start=1
    ):

        destination_title = (
            row.get("destination_title")
            or "-"
        )

        destination_username = clean_username(
            row.get("destination_username")
        )

        destination_chat_id = row.get(
            "destination_channel_id"
        )

        destination_message_id = row.get(
            "destination_message_id"
        )

        destination_link = (
            row.get(
                "destination_message_link"
            )
            or ""
        )

        if not destination_link:

            destination_link = resolve_message_link(
                destination_username,
                destination_chat_id,
                destination_message_id
            )

        message_title = (
            row.get("message_title")
            or "بدون عنوان"
        )

        created_at_raw = row.get(
            "created_at"
        )

        created_at = format_iran_datetime(
            created_at_raw
        )

        elapsed = humanize_elapsed_fa(
            created_at_raw
        )

        members_count = get_chat_members_count(
            destination_chat_id
        )

        views_count = row.get(
            "views"
        )

        text += (
            f"*{to_persian_digits(index)}.* "
            f"📡 {markdown_text(destination_title)}\n"
        )

        if destination_username:

            text += (
                f"   🔖 @{markdown_text(destination_username)}\n"
            )

        if members_count is not None:

            text += (
                f"   👥 اعضا: "
                f"{to_persian_digits(members_count)}\n"
            )

        if views_count is not None:

            text += (
                f"   👁 ویو: "
                f"{to_persian_digits(views_count)}\n"
            )

        text += (
            f"   📝 {markdown_text(message_title)}\n"
            f"   🕐 {markdown_text(created_at)} "
            f"\\({markdown_text(elapsed)}\\)\n"
        )

        if destination_link:

            text += (
                "   "
                + markdown_link(
                    "مشاهده پست مقصد",
                    destination_link,
                    "🟢"
                )
                + "\n"
            )

        else:

            text += (
                "   "
                "🟢 ⚠️ لینک مستقیم مقصد در دسترس نیست.\n"
            )

        text += "\n"

    return text


# =========================================================
# REPORT HTML
# =========================================================

def generate_report(
    admin_user_id
):

    source, rows = get_reposts_for_selected_source(
        admin_user_id
    )

    if not source.get("channel_id"):

        return (
            "📊 <b>گزارش بازنشر</b>\n\n"
            "⚠️ هنوز پست مبدأ انتخاب نشده است.\n\n"
            "یک پست را از کانال مبدأ برای ربات "
            "Forward کنید."
        )

    source_message_id = str(
        source.get("message_id")
    )

    source_link = source.get(
        "message_link"
    )

    if not source_link:

        source_link = resolve_message_link(
            source.get("username"),
            source.get("channel_id"),
            source.get("message_id")
        )

        if source_link:

            try:

                (
                    supabase
                    .table("admin_sources")
                    .update({
                        "source_message_link": source_link,
                        "updated_at": now_iso()
                    })
                    .eq(
                        "admin_user_id",
                        str(admin_user_id)
                    )
                    .execute()
                )

            except Exception as e:

                print(
                    "UPDATE SOURCE LINK ERROR:",
                    repr(e)
                )

    text = (
        "📊 <b>گزارش همین پست</b>\n\n"
        f"📡 <b>مبدأ:</b> "
        f"{html_text(source.get('title') or '-')}\n"
        f"🆔 <b>شناسه پست:</b> "
        f"<code>{html_text(source_message_id)}</code>\n"
    )

    if source_link:

        text += (
            "\n"
            f"🔵 <b>مشاهده پست مبدأ:</b>\n"
            f"<code>{html_text(source_link)}</code>\n"
        )

    else:

        text += (
            "\n"
            "🔵 ⚠️ لینک پست مبدأ در دسترس نیست.\n"
        )

    text += (
        f"\n📈 <b>تعداد بازنشر فعال:</b> "
        f"{to_persian_digits(len(rows))}\n"
    )

    total_views = sum(
        int(row.get("views") or 0)
        for row in rows
        if str(row.get("views") or "").isdigit()
    )
    if total_views > 0:
        text += (
            f"👁 <b>مجموع ویو ثبت‌شده:</b> "
            f"{to_persian_digits(total_views)}\n"
        )

    if not rows:

        return text + (
            "\n"
            "ℹ️ هنوز بازنشری از این پست "
            "در مقصدهای فعال ثبت نشده است.\n\n"
            "💡 ربات فقط بازنشرهایی را ثبت می‌کند "
            "که بعد از انتخاب پست مبدأ دریافت شوند."
        )

    text += "\n"

    for index, row in enumerate(
        rows,
        start=1
    ):

        destination_title = (
            row.get("destination_title")
            or "-"
        )

        destination_username = clean_username(
            row.get("destination_username")
        )

        destination_chat_id = row.get(
            "destination_channel_id"
        )

        destination_message_id = row.get(
            "destination_message_id"
        )

        destination_link = (
            row.get(
                "destination_message_link"
            )
            or ""
        )

        if not destination_link:

            destination_link = resolve_message_link(
                destination_username,
                destination_chat_id,
                destination_message_id
            )

        message_title = (
            row.get("message_title")
            or "بدون عنوان"
        )

        created_at_raw = row.get(
            "created_at"
        )

        created_at = format_iran_datetime(
            created_at_raw
        )

        elapsed = humanize_elapsed_fa(
            created_at_raw
        )

        members_count = get_chat_members_count(
            destination_chat_id
        )

        views_count = row.get(
            "views"
        )

        text += (
            f"<b>{to_persian_digits(index)}.</b> "
            f"📡 {html_text(destination_title)}\n"
        )

        if destination_username:

            text += (
                f"   🔖 @{html_text(destination_username)}\n"
            )

        if members_count is not None:

            text += (
                f"   👥 <b>اعضا:</b> "
                f"{to_persian_digits(members_count)}\n"
            )

        if views_count is not None:

            text += (
                f"   👁 <b>ویو:</b> "
                f"{to_persian_digits(views_count)}\n"
            )

        text += (
            f"   📝 {html_text(message_title)}\n"
            f"   🕐 {html_text(created_at)} "
            f"({html_text(elapsed)})\n"
        )

        if destination_link:

            text += (
                f"   🟢 <b>مشاهده پست مقصد:</b>\n"
                f"   <code>{html_text(destination_link)}</code>\n"
            )

        else:

            text += (
                "   🟢 ⚠️ لینک مستقیم مقصد در دسترس نیست.\n"
            )

        text += "\n"

    return text


# =========================================================
# DELETE REPORTS
# =========================================================

def get_reposts_count():

    try:

        result = (
            supabase
            .table("reposts")
            .select("id")
            .execute()
        )

        return len(
            result.data or []
        )

    except Exception as e:

        print(
            "GET REPOST COUNT ERROR:",
            repr(e)
        )

        return None


def delete_all_reports():

    try:

        count = get_reposts_count()

        if count is None:
            return False, 0

        if count == 0:
            return True, 0

        (
            supabase
            .table("reposts")
            .delete()
            .gt("id", 0)
            .execute()
        )

        print(
            "ALL REPORTS DELETED:",
            count
        )

        return True, count

    except Exception as e:

        print(
            "DELETE ALL REPORTS ERROR:",
            repr(e)
        )

        return False, 0


# =========================================================
# CHANNEL LIST
# =========================================================

def generate_channels_list():

    rows = get_active_channels()

    text = (
        "📡 <b>کانال‌ها و گروه‌های فعال</b>\n\n"
    )

    if not rows:

        return (
            text
            + "⚠️ هنوز مقصد فعالی ثبت نشده است.\n\n"
            "ربات را به مقصد اضافه کنید "
            "یا از گزینه «➕ افزودن مقصد» استفاده کنید."
        )

    text += (
        f"تعداد مقصدهای فعال: "
        f"<b>{to_persian_digits(len(rows))}</b>\n\n"
    )

    for index, row in enumerate(
        rows,
        start=1
    ):

        title = (
            row.get("title")
            or row.get("username")
            or row.get("chat_id")
            or "-"
        )

        username = clean_username(
            row.get("username")
        )

        chat_id = row.get(
            "chat_id"
        )

        text += (
            f"<b>{to_persian_digits(index)}.</b> "
            f"📡 {html_text(title)}\n"
        )

        if username:

            text += (
                f"   🔖 @{html_text(username)}\n"
            )

        text += (
            f"   🆔 <code>"
            f"{html_text(chat_id or '-')}"
            f"</code>\n\n"
        )

    return text


# =========================================================
# STATUS
# =========================================================

def generate_status(
    user_id
):

    active = get_active_channels()
    all_channels = get_all_channels()
    source = get_selected_source(
        user_id
    )
    admins = get_admin_ids()
    bot = get_me()

    bot_name = (
        bot.get("first_name")
        if bot
        else "-"
    )

    return (
        "📈 <b>وضعیت ربات</b>\n\n"
        f"🤖 ربات: <b>{html_text(bot_name)}</b>\n"
        f"📡 مقصدهای فعال: "
        f"<b>{to_persian_digits(len(active))}</b>\n"
        f"🗂 کل مقصدهای ثبت‌شده: "
        f"<b>{to_persian_digits(len(all_channels))}</b>\n"
        f"👥 مدیران: "
        f"<b>{to_persian_digits(len(admins))}</b>\n\n"
        f"📌 مبدأ فعلی شما: "
        f"<b>{html_text(source.get('title') or 'انتخاب نشده')}</b>"
    )


# =========================================================
# MAIN KEYBOARD
# =========================================================

def main_keyboard(user_id):

    if is_owner(user_id):

        keyboard = [
            [
                {"text": "📊 گزارش بازنشر"},
                {"text": "📡 کانال‌ها و گروه‌ها"}
            ],
            [
                {"text": "➕ افزودن مقصد"},
                {"text": "➖ حذف مقصد"}
            ],
            [
                {"text": "🔄 همگام‌سازی"},
                {"text": "📈 وضعیت ربات"}
            ],
            [
                {"text": "📣 بازنشر گسترده"},
                {"text": "📍 گزارش مبدأ و مقصد"}
            ],
            [
                {"text": "📥 خروجی اکسل"},
                {"text": "📥 اکسل کل گزارش‌ها"}
            ],
            [
                {"text": "🗑️ پاک کردن کلیه گزارش‌ها"}
            ],
            [
                {"text": "⚙️ مدیریت مدیران"},
                {"text": "❓ راهنما"}
            ]
        ]

    elif is_admin(user_id):

        keyboard = [
            [
                {"text": "📊 گزارش بازنشر"},
                {"text": "📡 کانال‌ها و گروه‌ها"}
            ],
            [
                {"text": "➕ افزودن مقصد"},
                {"text": "➖ حذف مقصد"}
            ],
            [
                {"text": "🔄 همگام‌سازی"},
                {"text": "📈 وضعیت ربات"}
            ],
            [
                {"text": "📣 بازنشر گسترده"},
                {"text": "📍 گزارش مبدأ و مقصد"}
            ],
            [
                {"text": "📥 خروجی اکسل"}
            ],
            [
                {"text": "❓ راهنما"}
            ]
        ]

    else:

        keyboard = [
            [
                {"text": "🆔 شناسه من"},
                {"text": "❓ راهنما"}
            ]
        ]

    return {
        "keyboard": keyboard,
        "resize_keyboard": True
    }


def admin_keyboard():

    return {
        "keyboard": [
            [
                {"text": "👥 مدیران ربات"},
                {"text": "➕ افزودن مدیر"}
            ],
            [
                {"text": "➖ حذف مدیر"}
            ],
            [
                {"text": "🏠 منوی اصلی"}
            ]
        ],
        "resize_keyboard": True
    }


# =========================================================
# START
# =========================================================

def send_start(chat_id, user_id):

    if is_owner(user_id):

        text = (
            "👋 <b>سلام مدیر ارشد</b>\n\n"
            "به پنل مدیریت ربات بازنشر خوش آمدید.\n\n"
            "از منوی زیر می‌توانید مقصدها، "
            "گزارش‌ها و مدیران ربات را مدیریت کنید."
        )

    elif is_admin(user_id):

        text = (
            "👋 <b>سلام مدیر</b>\n\n"
            "به پنل مدیریت ربات خوش آمدید.\n\n"
            "می‌توانید گزارش بازنشر را ببینید، "
            "مقصدها را مدیریت کنید و وضعیت ربات "
            "را بررسی نمایید."
        )

    else:

        text = (
            "👋 <b>سلام!</b>\n\n"
            "به ربات بازنشر خوش آمدید.\n\n"
            "برای مشاهده شناسه کاربری خود "
            "از گزینه «🆔 شناسه من» استفاده کنید."
        )

    send_message(
        chat_id,
        text,
        main_keyboard(user_id)
    )


# =========================================================
# HELP
# =========================================================

def send_help(chat_id, user_id):

    ai_section = (
        "\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🤖 <b>بخش هوش مصنوعی</b>\n"
        "(فقط برای مدیران و کاربرانی که دسترسی گرفته‌اند - "
        "هم در خصوصی، هم با ریپلای زیر پست در گروه/کانال)\n\n"
        "🔹 <b>گفت‌وگوی آزاد</b>\n"
        "در خصوصی مستقیم پیام بده؛ در گروه باید ربات را "
        "@mention کنی.\n\n"
        "🔹 <b>خبر به صوت</b>\n"
        "<code>/voice</code> یا <code>/خبر</code> یا "
        "<code>/news</code>\n"
        "روی یک پست ریپلای کن و دستور را بفرست، یا متن را "
        "بعد از دستور بنویس؛ ربات آن را با صدا برایت می‌فرستد.\n\n"
        "🔹 <b>ساخت عکس</b>\n"
        "<code>/image</code> یا <code>/عکس</code> "
        "+ توضیح عکس موردنظر\n\n"
        "🔹 <b>ویرایش عکس</b>\n"
        "<code>/ویرایش</code> یا <code>/edit_image</code>\n"
        "روی یک عکس ریپلای کن و بنویس چطور تغییرش بدی (مثلاً "
        "«این را آبرنگ کن»)، یا خودِ عکس را با همین کپشن بفرست.\n\n"
        "🔹 <b>خلاصه‌سازی</b>\n"
        "<code>/خلاصه</code> یا <code>/summary</code>\n"
        "روی متن بلند ریپلای کن، یا متن را بعد از دستور بنویس.\n\n"
        "🔹 <b>بازنویسی متن</b>\n"
        "<code>/بازنویس</code> — بازنویسی عادی و روان\n"
        "<code>/بازنویس روابط عمومی</code> — لحن رسمی/سازمانی\n"
        "<code>/بازنویس روان‌شناسانه</code> — لحن همدلانه/حمایتی\n\n"
        "🔹 <b>پاک کردن حافظه‌ی گفت‌وگو</b>\n"
        "<code>/reset_ai</code> یا <code>/پاک_حافظه</code>\n"
        "اگر ربات جواب‌های عجیب/تکراری می‌داد، این را بزن.\n\n"
        "🔒 <i>نکته: در گروه/کانال، اگر کاربری دسترسی نداشته "
        "باشد، ربات کاملاً سکوت می‌کند تا این قابلیت‌ها برای "
        "اعضای عادی دیده نشود.</i>"
    )

    ai_access_section = (
        "\n\n"
        "━━━━━━━━━━━━━━━\n"
        "👤 <b>مدیریت دسترسی هوش مصنوعی</b>\n\n"
        "🔹 <b>دادن دسترسی</b>\n"
        "<code>/allow_ai USER_ID</code>\n\n"
        "🔹 <b>گرفتن دسترسی</b>\n"
        "<code>/disallow_ai USER_ID</code>\n\n"
        "🔹 <b>لیست کاربران مجاز</b>\n"
        "<code>/ai_users</code>\n\n"
        "برای گرفتن USER_ID یه نفر، بگو با ربات در خصوصی "
        "پیام بده و روی دکمه‌ی «🆔 شناسه من» بزنه."
    )

    owner_section = (
        "\n\n"
        "━━━━━━━━━━━━━━━\n"
        "👑 <b>مخصوص مالک ربات</b>\n\n"
        "🔹 <b>لیست مدیران</b>\n"
        "<code>/admins</code>\n\n"
        "🔹 <b>افزودن مدیر</b>\n"
        "<code>/addadmin USER_ID</code>\n\n"
        "🔹 <b>حذف مدیر</b>\n"
        "<code>/removeadmin USER_ID</code>\n\n"
        "🔹 <b>حذف کامل همه‌ی گزارش‌ها</b>\n"
        "<code>/clearreports</code>\n"
        "⚠️ غیرقابل‌بازگشت است.\n\n"
        "🔹 <b>مدل متنی پشتیبان (Pollinations)</b>\n"
        "<code>/text_model اسم_مدل</code> برای تغییر\n"
        "<code>/text_models</code> برای دیدن لیست مدل‌ها\n"
        "این مدل فقط وقتی استفاده می‌شه که Gemini و Groq هر دو "
        "جواب ندن (آخرین لایه‌ی پشتیبان، رایگان)."
    )

    if is_owner(user_id):

        text = (
            "❓ <b>راهنمای ربات (مالک)</b>\n\n"
            "🔹 <b>انتخاب پست مبدأ</b>\n"
            "یک پست را از کانال مبدأ به صورت "
            "Forward برای ربات ارسال کنید.\n\n"
            "🔹 <b>گزارش همین پست</b>\n"
            "بعد از ارسال پست مبدأ، دکمه "
            "«📊 گزارش همین پست» زیر پیام ظاهر می‌شود.\n\n"
            "🔹 <b>ثبت بازنشر</b>\n"
            "بعد از انتخاب پست مبدأ، اگر همان پست "
            "در یکی از مقصدهای فعال Forward شود، "
            "ربات آن را ثبت و گزارش می‌کند.\n\n"
            "🔹 <b>استقلال مدیران</b>\n"
            "هر مدیر می‌تواند پست مبدأ مخصوص خودش "
            "را انتخاب کند و گزارش او مستقل از سایر مدیران است.\n\n"
            "🔹 <b>افزودن مقصد</b>\n"
            "<code>/addchannel @username</code>\n\n"
            "🔹 <b>حذف مقصد</b>\n"
            "<code>/removechannel @username</code>\n\n"
            "🔹 <b>گزارش کلی</b>\n"
            "از «📊 گزارش بازنشر» استفاده کنید.\n\n"
            "🔹 <b>همگام‌سازی</b>\n"
            "برای بررسی مقصدهای ثبت‌شده از گزینه "
            "«🔄 همگام‌سازی» استفاده کنید.\n\n"
            "🔹 <b>بازنشر گسترده</b>\n"
            "با «📣 بازنشر گسترده» و سپس Forward کردن "
            "یک پست، همان پست به‌صورت خودکار به تمام "
            "مقصدهای فعال ارسال می‌شود (نیاز به ادمین "
            "بودن ربات در آن مقصد دارد).\n\n"
            "🔹 <b>گزارش مبدأ و مقصد</b>\n"
            "با «📍 گزارش مبدأ و مقصد»، یک کانال مبدأ و "
            "یک مقصد مشخص انتخاب می‌کنید و تعداد کل "
            "بازنشرهای انجام‌شده بین آن دو را می‌بینید.\n\n"
            "🔹 <b>خروجی اکسل</b>\n"
            "با «📥 خروجی اکسل»، گزارش مبدأ انتخابی‌تان "
            "به‌صورت فایل Excel ارسال می‌شود. با "
            "«📥 اکسل کل گزارش‌ها» می‌توانید خروجی کامل "
            "تمام بازنشرهای ثبت‌شده را هم دریافت کنید.\n\n"
            "🔹 <b>شناسه من</b>\n"
            "<code>/myid</code>"
            + ai_section
            + ai_access_section
            + owner_section
        )

    elif is_admin(user_id):

        text = (
            "❓ <b>راهنمای ربات</b>\n\n"
            "🔹 <b>انتخاب پست مبدأ</b>\n"
            "یک پست را از کانال مبدأ به صورت "
            "Forward برای ربات ارسال کنید.\n\n"
            "🔹 <b>گزارش همین پست</b>\n"
            "بعد از ارسال پست مبدأ، دکمه "
            "«📊 گزارش همین پست» زیر پیام ظاهر می‌شود.\n\n"
            "🔹 <b>ثبت بازنشر</b>\n"
            "بعد از انتخاب پست مبدأ، اگر همان پست "
            "در یکی از مقصدهای فعال Forward شود، "
            "ربات آن را ثبت و گزارش می‌کند.\n\n"
            "🔹 <b>استقلال مدیران</b>\n"
            "هر مدیر می‌تواند پست مبدأ مخصوص خودش "
            "را انتخاب کند و گزارش او مستقل از سایر مدیران است.\n\n"
            "🔹 <b>افزودن مقصد</b>\n"
            "<code>/addchannel @username</code>\n\n"
            "🔹 <b>حذف مقصد</b>\n"
            "<code>/removechannel @username</code>\n\n"
            "🔹 <b>گزارش کلی</b>\n"
            "از «📊 گزارش بازنشر» استفاده کنید.\n\n"
            "🔹 <b>پاک کردن گزارش‌ها</b>\n"
            "فقط مالک ربات می‌تواند گزارش‌ها را حذف کند.\n\n"
            "🔹 <b>همگام‌سازی</b>\n"
            "برای بررسی مقصدهای ثبت‌شده از گزینه "
            "«🔄 همگام‌سازی» استفاده کنید.\n\n"
            "🔹 <b>بازنشر گسترده</b>\n"
            "با «📣 بازنشر گسترده» و سپس Forward کردن "
            "یک پست، همان پست به‌صورت خودکار به تمام "
            "مقصدهای فعال ارسال می‌شود (نیاز به ادمین "
            "بودن ربات در آن مقصد دارد).\n\n"
            "🔹 <b>گزارش مبدأ و مقصد</b>\n"
            "با «📍 گزارش مبدأ و مقصد»، یک کانال مبدأ و "
            "یک مقصد مشخص انتخاب می‌کنید و تعداد کل "
            "بازنشرهای انجام‌شده بین آن دو را می‌بینید.\n\n"
            "🔹 <b>خروجی اکسل</b>\n"
            "با «📥 خروجی اکسل»، گزارش مبدأ انتخابی‌تان "
            "به‌صورت فایل Excel ارسال می‌شود. مالک ربات "
            "با «📥 اکسل کل گزارش‌ها» می‌تواند خروجی کامل "
            "تمام بازنشرهای ثبت‌شده را هم دریافت کند.\n\n"
            "🔹 <b>شناسه من</b>\n"
            "<code>/myid</code>"
            + ai_section
            + ai_access_section
        )

    else:

        text = (
            "❓ <b>راهنما</b>\n\n"
            "🆔 برای مشاهده شناسه کاربری:\n"
            "<code>/myid</code>\n\n"
            "برای دسترسی به بخش هوش مصنوعی (گفت‌وگو، ساخت "
            "عکس، خبر به صوت، خلاصه‌سازی و بازنویسی متن)، "
            "باید یکی از مدیران ربات دسترسی‌ت را فعال کند."
        )

    send_message(
        chat_id,
        text,
        main_keyboard(user_id)
    )


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

def list_admins():

    try:

        result = (
            supabase
            .table("bot_admins")
            .select("*")
            .eq("active", True)
            .order("created_at")
            .execute()
        )

        return result.data or []

    except Exception as e:

        print(
            "LIST ADMINS ERROR:",
            repr(e)
        )

        return []


def generate_admins():

    rows = list_admins()

    text = (
        "👥 <b>مدیران ربات</b>\n\n"
    )

    owner_id = get_owner_id()

    text += (
        "👑 مالک:\n"
        f"<code>{html_text(owner_id or '-')}</code>\n\n"
    )

    if not rows:

        text += "هنوز مدیر دیگری ثبت نشده است."

        return text

    for index, row in enumerate(
        rows,
        start=1
    ):

        name = (
            row.get("first_name")
            or row.get("username")
            or row.get("user_id")
        )

        username = clean_username(
            row.get("username")
        )

        text += (
            f"{to_persian_digits(index)}. "
            f"👤 {html_text(name)}"
        )

        if username:

            text += (
                f" (@{html_text(username)})"
            )

        text += (
            f"\n   🆔 "
            f"<code>{html_text(row.get('user_id'))}</code>\n\n"
        )

    return text


def add_admin(user_id):

    user_id = str(user_id).strip()

    if not user_id:
        return False

    try:

        existing = (
            supabase
            .table("bot_admins")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if existing.data:

            (
                supabase
                .table("bot_admins")
                .update({
                    "active": True
                })
                .eq(
                    "id",
                    existing.data[0]["id"]
                )
                .execute()
            )

        else:

            (
                supabase
                .table("bot_admins")
                .insert({
                    "user_id": user_id,
                    "active": True,
                    "created_at": now_iso()
                })
                .execute()
            )

        return True

    except Exception as e:

        print(
            "ADD ADMIN ERROR:",
            repr(e)
        )

        return False


def remove_admin(user_id):

    user_id = str(user_id).strip()

    try:

        (
            supabase
            .table("bot_admins")
            .update({
                "active": False
            })
            .eq(
                "user_id",
                user_id
            )
            .execute()
        )

        return True

    except Exception as e:

        print(
            "REMOVE ADMIN ERROR:",
            repr(e)
        )

        return False


# =========================================================
# COMMAND HANDLER
# =========================================================

def handle_command(
    message,
    chat_id,
    user
):

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text:
        return False

    parts = text.split()

    if not parts:
        return False

    command = parts[0].lower()

    user_id = (
        user.get("id")
        if user
        else None
    )

    if command.startswith("/start"):

        send_start(
            chat_id,
            user_id
        )

        return True

    if command.startswith("/myid"):

        send_message(
            chat_id,
            "🆔 <b>شناسه کاربری شما:</b>\n\n"
            f"<code>{html_text(user_id)}</code>"
        )

        return True

    if command.startswith("/cancel"):

        PENDING_ACTIONS.pop(
            str(chat_id),
            None
        )

        PAIR_REPORT_STATE.pop(
            str(chat_id),
            None
        )

        send_message(
            chat_id,
            "❌ عملیات لغو شد.",
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/reset_ai") or command.startswith("/پاک_حافظه"):

        if not is_ai_allowed(user_id):

            send_message(
                chat_id,
                "⛔ شما به بخش هوش مصنوعی این ربات دسترسی ندارید."
            )

            return True

        AI_CHAT_HISTORY.pop(chat_id, None)

        send_message(
            chat_id,
            "🧹 حافظه‌ی گفت‌وگوی هوش مصنوعی این چت پاک شد.\n\n"
            "اگر ربات جمله‌ی «اطلاعاتم تا فلان تاریخه» را تکرار "
            "می‌کرد، از این به بعد نباید دوباره تکرار شود.",
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/text_models"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ این دستور فقط برای مالک ربات است."
            )

            return True

        models = fetch_pollinations_text_models()
        current = get_pollinations_text_model()

        if not models:

            send_message(
                chat_id,
                "نتونستم لیست مدل‌ها رو از Pollinations بگیرم، "
                "بعداً امتحان کن."
            )

            return True

        models_text = "، ".join(
            f"<code>{html_text(m)}</code>" for m in models[:60]
        )

        send_message(
            chat_id,
            f"🌸 <b>مدل‌های متنی Pollinations</b> "
            f"(فعلی: <code>{html_text(current)}</code>):\n\n"
            f"{models_text}\n\n"
            "برای تغییر: <code>/text_model اسم_مدل</code>"
        )

        return True

    if command.startswith("/text_model"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ این دستور فقط برای مالک ربات است."
            )

            return True

        rest_parts = text.strip().split(" ", 1)
        new_model = rest_parts[1].strip() if len(rest_parts) > 1 else ""

        if not new_model:

            current = get_pollinations_text_model()

            send_message(
                chat_id,
                f"مدل متنی فعلی Pollinations: "
                f"<code>{html_text(current)}</code>\n\n"
                "برای تغییر: <code>/text_model اسم_مدل</code>\n"
                "برای دیدن لیست مدل‌ها: <code>/text_models</code>"
            )

            return True

        set_ai_setting("pollinations_text_model", new_model)

        send_message(
            chat_id,
            f"✅ مدل متنی پیش‌فرض Pollinations به "
            f"<code>{html_text(new_model)}</code> تغییر کرد.\n\n"
            "نکته: این لایه فقط وقتی استفاده می‌شه که Gemini و "
            "Groq هر دو جواب ندن (لایه‌ی سوم پشتیبان)."
        )

        return True

    if not is_admin(user_id):

        send_message(
            chat_id,
            "⛔ شما دسترسی مدیریتی ندارید."
        )

        return True

    if command.startswith("/allow_ai"):

        parts = text.split(" ", 1)

        if len(parts) < 2 or not parts[1].strip():

            send_message(
                chat_id,
                "❗ فرمت درست: /allow_ai USER_ID\n\n"
                "برای پیدا کردن شناسه‌ی کاربر، از او بخواه در "
                "خصوصی به ربات پیام بده و روی دکمه‌ی "
                "«🆔 شناسه من» بزنه."
            )

            return True

        target_id = parts[1].strip()

        if add_ai_allowed_user(target_id):

            send_message(
                chat_id,
                f"✅ دسترسی هوش مصنوعی برای کاربر "
                f"<code>{html_text(target_id)}</code> فعال شد."
            )

        else:

            send_message(
                chat_id,
                "❌ عملیات ناموفق بود."
            )

        return True

    if command.startswith("/disallow_ai"):

        parts = text.split(" ", 1)

        if len(parts) < 2 or not parts[1].strip():

            send_message(
                chat_id,
                "❗ فرمت درست: /disallow_ai USER_ID"
            )

            return True

        target_id = parts[1].strip()

        if remove_ai_allowed_user(target_id):

            send_message(
                chat_id,
                f"✅ دسترسی هوش مصنوعی برای کاربر "
                f"<code>{html_text(target_id)}</code> غیرفعال شد."
            )

        else:

            send_message(
                chat_id,
                "❌ عملیات ناموفق بود."
            )

        return True

    if command.startswith("/ai_users"):

        allowed = list_ai_allowed_users()

        if not allowed:

            send_message(
                chat_id,
                "📋 در حال حاضر (به‌جز مدیران) هیچ کاربری به "
                "هوش مصنوعی دسترسی ندارد.\n\n"
                "برای افزودن: /allow_ai USER_ID"
            )

        else:

            lines = "\n".join(
                f"• <code>{html_text(uid)}</code>"
                for uid in allowed
            )

            send_message(
                chat_id,
                "📋 <b>کاربران مجاز هوش مصنوعی:</b>\n\n"
                f"{lines}"
            )

        return True

    if command.startswith("/report"):

        send_markdown_message(
            chat_id,
            generate_report_markdown(
                user_id
            ),
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/channels"):

        send_message(
            chat_id,
            generate_channels_list(),
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/status"):

        send_message(
            chat_id,
            generate_status(
                user_id
            ),
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/clearreports"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات می‌تواند "
                "همه گزارش‌ها را حذف کند."
            )

            return True

        send_message(
            chat_id,
            "⚠️ <b>حذف کلیه گزارش‌ها</b>\n\n"
            "تمام گزارش‌های بازنشر قبلی حذف می‌شوند.\n\n"
            "این عملیات قابل بازگشت نیست.",
            clear_reports_keyboard()
        )

        return True

    if command.startswith("/addchannel"):

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "add_channel"

            send_message(
                chat_id,
                "➕ <b>افزودن مقصد</b>\n\n"
                "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
                "مثال:\n"
                "<code>@example</code>\n\n"
                "یا:\n"
                "<code>-100123456789</code>\n\n"
                "برای انصراف /cancel را بفرستید."
            )

        else:

            ok, result_text = manual_add_channel(
                parts[1]
            )

            send_message(
                chat_id,
                result_text,
                main_keyboard(user_id)
            )

        return True

    if command.startswith("/removechannel"):

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "remove_channel"

            send_message(
                chat_id,
                "➖ <b>حذف مقصد</b>\n\n"
                "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
                "برای انصراف /cancel را بفرستید."
            )

        else:

            ok, result_text = manual_remove_channel(
                parts[1]
            )

            send_message(
                chat_id,
                result_text,
                main_keyboard(user_id)
            )

        return True

    if command.startswith("/syncchannels"):

        send_message(
            chat_id,
            "⏳ در حال بررسی وضعیت مقصدهای ثبت‌شده..."
        )

        result = sync_channels()

        text = (
            "🔄 <b>همگام‌سازی انجام شد</b>\n\n"
            f"🔍 بررسی‌شده: "
            f"{to_persian_digits(result['checked'])}\n"
            f"🟢 فعال: "
            f"{to_persian_digits(result['active'])}\n"
            f"🔴 خارج‌شده: "
            f"{to_persian_digits(result['removed'])}\n"
            f"⚠️ خطا: "
            f"{to_persian_digits(result['errors'])}"
        )

        send_message(
            chat_id,
            text,
            main_keyboard(user_id)
        )

        return True

    if command.startswith("/admins"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return True

        send_message(
            chat_id,
            generate_admins(),
            admin_keyboard()
        )

        return True

    if command.startswith("/addadmin"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return True

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "add_admin"

            send_message(
                chat_id,
                "➕ <b>افزودن مدیر</b>\n\n"
                "شناسه عددی کاربر را ارسال کنید."
            )

        else:

            if add_admin(parts[1]):

                send_message(
                    chat_id,
                    "✅ مدیر با موفقیت اضافه شد.",
                    admin_keyboard()
                )

            else:

                send_message(
                    chat_id,
                    "❌ افزودن مدیر ناموفق بود.",
                    admin_keyboard()
                )

        return True

    if command.startswith("/removeadmin"):

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات دسترسی دارد."
            )

            return True

        if len(parts) < 2:

            PENDING_ACTIONS[
                str(chat_id)
            ] = "remove_admin"

            send_message(
                chat_id,
                "➖ <b>حذف مدیر</b>\n\n"
                "شناسه عددی مدیر را ارسال کنید."
            )

        else:

            if remove_admin(parts[1]):

                send_message(
                    chat_id,
                    "✅ مدیر حذف شد.",
                    admin_keyboard()
                )

            else:

                send_message(
                    chat_id,
                    "❌ حذف مدیر ناموفق بود.",
                    admin_keyboard()
                )

        return True

    return False


# =========================================================
# BUTTON HANDLER
# =========================================================

ADMIN_ONLY_BUTTON_TEXTS = {
    "📊 گزارش بازنشر",
    "📡 کانال‌ها و گروه‌ها",
    "➕ افزودن مقصد",
    "➖ حذف مقصد",
    "📣 بازنشر گسترده",
    "🔄 همگام‌سازی",
    "📈 وضعیت ربات",
    "🗑️ پاک کردن کلیه گزارش‌ها",
    "⚙️ مدیریت مدیران",
    "👥 مدیران ربات",
    "➕ افزودن مدیر",
    "➖ حذف مدیر",
}


def handle_button(
    message,
    chat_id,
    user
):

    text = (
        message.get("text")
        or ""
    ).strip()

    user_id = (
        user.get("id")
        if user
        else None
    )

    if text == "🆔 شناسه من":

        send_message(
            chat_id,
            "🆔 <b>شناسه کاربری شما:</b>\n\n"
            f"<code>{html_text(user_id)}</code>"
        )

        return True

    if text == "❓ راهنما":

        send_help(
            chat_id,
            user_id
        )

        return True

    # ⚠️ این بررسی فقط برای دکمه‌های مخصوص مدیریت اعمال می‌شود؛
    # پیام‌های آزاد کاربران عادی (که ممکن است سوال برای هوش
    # مصنوعی باشند) نباید اینجا مسدود شوند.
    if (
        text in ADMIN_ONLY_BUTTON_TEXTS
        and not is_admin(user_id)
    ):

        send_message(
            chat_id,
            "⛔ دسترسی شما محدود است."
        )

        return True

    if text == "📊 گزارش بازنشر":

        send_markdown_message(
            chat_id,
            generate_report_markdown(
                user_id
            ),
            main_keyboard(user_id)
        )

        return True

    if text == "📡 کانال‌ها و گروه‌ها":

        send_message(
            chat_id,
            generate_channels_list(),
            main_keyboard(user_id)
        )

        return True

    if text == "➕ افزودن مقصد":

        PENDING_ACTIONS[
            str(chat_id)
        ] = "add_channel"

        send_message(
            chat_id,
            "➕ <b>افزودن مقصد</b>\n\n"
            "نام کاربری مقصد با @ یا شناسه عددی را "
            "ارسال کنید.\n\n"
            "برای انصراف /cancel را بفرستید."
        )

        return True

    if text == "➖ حذف مقصد":

        PENDING_ACTIONS[
            str(chat_id)
        ] = "remove_channel"

        send_message(
            chat_id,
            "➖ <b>حذف مقصد</b>\n\n"
            "نام کاربری یا شناسه مقصد را ارسال کنید.\n\n"
            "برای انصراف /cancel را بفرستید."
        )

        return True

    if text == "📣 بازنشر گسترده":

        active_count = len(
            get_active_channels()
        )

        PENDING_ACTIONS[
            str(chat_id)
        ] = "broadcast_forward"

        send_message(
            chat_id,
            "📣 <b>بازنشر گسترده</b>\n\n"
            "پستی که می‌خواهید ارسال شود را برای من "
            "Forward کنید (یا مستقیم بفرستید).\n\n"
            f"این پست به تمام "
            f"<b>{to_persian_digits(active_count)}</b> "
            "مقصد فعال ارسال خواهد شد.\n\n"
            "⚠️ توجه: ربات باید در آن مقصد عضو/ادمین "
            "باشد و اجازه ارسال پیام داشته باشد، وگرنه "
            "برای همان مقصد ناموفق گزارش می‌شود.\n\n"
            "برای انصراف /cancel را بفرستید."
        )

        return True

    if text == "📍 گزارش مبدأ و مقصد":

        key = str(chat_id)

        PENDING_ACTIONS[key] = "pair_report_source"

        PAIR_REPORT_STATE.pop(
            key,
            None
        )

        send_message(
            chat_id,
            "📍 <b>گزارش مبدأ و مقصد</b>\n\n"
            "یک پست از کانال مبدأ مدنظر را برای من "
            "Forward کنید؛ یا نام کاربری/شناسه‌ی آن "
            "کانال را مستقیم بفرستید.\n\n"
            "برای انصراف /cancel را بفرستید."
        )

        return True

    if text == "📥 خروجی اکسل":

        source, rows = get_reposts_for_selected_source(
            user_id
        )

        if not source.get("channel_id"):

            send_message(
                chat_id,
                "⚠️ ابتدا باید یک پست مبدأ انتخاب کنید "
                "(آن را برای من Forward کنید)، سپس دوباره "
                "«📥 خروجی اکسل» را بزنید."
            )

            return True

        if not rows:

            send_message(
                chat_id,
                "ℹ️ هنوز هیچ بازنشری برای این مبدأ "
                "ثبت نشده تا خروجی اکسل بگیریم."
            )

            return True

        send_message(
            chat_id,
            "⏳ در حال ساخت فایل اکسل..."
        )

        file_path = None

        try:

            file_path = build_reposts_excel(
                rows,
                sheet_title=(
                    source.get("title")
                    or "گزارش بازنشر"
                )
            )

            bale_send_document(
                chat_id,
                file_path,
                caption=(
                    "📊 گزارش بازنشر — "
                    f"{source.get('title') or '-'}"
                )
            )

        except Exception as e:

            print(
                "EXCEL EXPORT ERROR:",
                repr(e)
            )

            send_message(
                chat_id,
                "❌ ساخت فایل اکسل با خطا مواجه شد."
            )

        finally:

            if file_path and os.path.exists(file_path):

                try:

                    os.remove(file_path)

                except Exception:

                    pass

        return True

    if text == "📥 اکسل کل گزارش‌ها":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات به این بخش دسترسی دارد."
            )

            return True

        rows = get_all_reposts()

        if not rows:

            send_message(
                chat_id,
                "ℹ️ هنوز هیچ بازنشری در دیتابیس ثبت نشده است."
            )

            return True

        send_message(
            chat_id,
            "⏳ در حال ساخت فایل اکسل کل گزارش‌ها..."
        )

        file_path = None

        try:

            file_path = build_reposts_excel(
                rows,
                sheet_title="کل گزارش‌ها"
            )

            bale_send_document(
                chat_id,
                file_path,
                caption=(
                    "📊 خروجی کامل تمام بازنشرهای ثبت‌شده"
                )
            )

        except Exception as e:

            print(
                "EXCEL EXPORT ALL ERROR:",
                repr(e)
            )

            send_message(
                chat_id,
                "❌ ساخت فایل اکسل با خطا مواجه شد."
            )

        finally:

            if file_path and os.path.exists(file_path):

                try:

                    os.remove(file_path)

                except Exception:

                    pass

        return True

    if text == "🔄 همگام‌سازی":

        send_message(
            chat_id,
            "⏳ در حال بررسی وضعیت مقصدهای ثبت‌شده..."
        )

        result = sync_channels()

        send_message(
            chat_id,
            "🔄 <b>همگام‌سازی انجام شد</b>\n\n"
            f"🔍 بررسی‌شده: "
            f"{to_persian_digits(result['checked'])}\n"
            f"🟢 فعال: "
            f"{to_persian_digits(result['active'])}\n"
            f"🔴 خارج‌شده: "
            f"{to_persian_digits(result['removed'])}\n"
            f"⚠️ خطا: "
            f"{to_persian_digits(result['errors'])}",
            main_keyboard(user_id)
        )

        return True

    if text == "📈 وضعیت ربات":

        send_message(
            chat_id,
            generate_status(
                user_id
            ),
            main_keyboard(user_id)
        )

        return True

    if text == "🗑️ پاک کردن کلیه گزارش‌ها":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات می‌تواند "
                "همه گزارش‌ها را حذف کند."
            )

            return True

        send_message(
            chat_id,
            "⚠️ <b>حذف کلیه گزارش‌ها</b>\n\n"
            "تمام گزارش‌های بازنشر قبلی حذف خواهند شد.\n\n"
            "❗ این عملیات قابل بازگشت نیست.\n\n"
            "آیا مطمئن هستید؟",
            clear_reports_keyboard()
        )

        return True

    if text == "⚙️ مدیریت مدیران":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ فقط مالک ربات به مدیریت مدیران دسترسی دارد."
            )

            return True

        send_message(
            chat_id,
            "⚙️ <b>مدیریت مدیران</b>\n\n"
            "از منوی زیر استفاده کنید.",
            admin_keyboard()
        )

        return True

    if text == "👥 مدیران ربات":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        send_message(
            chat_id,
            generate_admins(),
            admin_keyboard()
        )

        return True

    if text == "➕ افزودن مدیر":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS[
            str(chat_id)
        ] = "add_admin"

        send_message(
            chat_id,
            "➕ <b>افزودن مدیر</b>\n\n"
            "شناسه عددی کاربر را ارسال کنید."
        )

        return True

    if text == "➖ حذف مدیر":

        if not is_owner(user_id):

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS[
            str(chat_id)
        ] = "remove_admin"

        send_message(
            chat_id,
            "➖ <b>حذف مدیر</b>\n\n"
            "شناسه عددی مدیر را ارسال کنید."
        )

        return True

    if text == "🏠 منوی اصلی":

        send_start(
            chat_id,
            user_id
        )

        return True

    return False


# =========================================================
# CALLBACK QUERY
# =========================================================

def process_callback_query(callback_query):

    if not callback_query:
        return

    callback_id = callback_query.get(
        "id"
    )

    data = (
        callback_query.get("data")
        or ""
    )

    from_user = (
        callback_query.get("from")
        or {}
    )

    user_id = from_user.get(
        "id"
    )

    message = (
        callback_query.get("message")
        or {}
    )

    chat = (
        message.get("chat")
        or {}
    )

    chat_id = chat.get(
        "id"
    )

    if callback_id:

        try:

            answer_callback_query(
                callback_id
            )

        except Exception as e:

            print(
                "CALLBACK ANSWER ERROR:",
                repr(e)
            )

    # -----------------------------------------------------
    # REPORT
    # -----------------------------------------------------

    if data == "report_selected_source":

        if not is_admin(user_id):

            if callback_id:

                answer_callback_query(
                    callback_id,
                    "⛔ شما دسترسی مدیریتی ندارید.",
                    True
                )

            return

        if chat_id is None:
            return

        send_markdown_message(
            chat_id,
            generate_report_markdown(
                user_id
            ),
            main_keyboard(user_id)
        )

        return

    # -----------------------------------------------------
    # CONFIRM DELETE
    # -----------------------------------------------------

    if data == "confirm_clear_reports":

        if not is_owner(user_id):

            if callback_id:

                answer_callback_query(
                    callback_id,
                    "⛔ فقط مالک ربات اجازه دارد.",
                    True
                )

            return

        ok, count = delete_all_reports()

        if ok:

            if count:

                text = (
                    "✅ <b>گزارش‌ها پاک شدند.</b>\n\n"
                    f"🗑 تعداد گزارش‌های حذف‌شده: "
                    f"<b>{to_persian_digits(count)}</b>\n\n"
                    "گزارش‌های جدید دوباره ثبت خواهند شد."
                )

            else:

                text = (
                    "ℹ️ <b>گزارشی برای حذف وجود نداشت.</b>"
                )

        else:

            text = (
                "❌ <b>حذف گزارش‌ها ناموفق بود.</b>\n\n"
                "لطفاً لاگ ربات را بررسی کنید."
            )

        send_message(
            chat_id,
            text,
            main_keyboard(user_id)
        )

        return

    # -----------------------------------------------------
    # CANCEL DELETE
    # -----------------------------------------------------

    if data == "cancel_clear_reports":

        if not is_owner(user_id):
            return

        send_message(
            chat_id,
            "❌ عملیات حذف گزارش‌ها لغو شد.",
            main_keyboard(user_id)
        )

        return

    # -----------------------------------------------------
    # انتخاب مقصد در جریان «گزارش مبدأ و مقصد»
    # -----------------------------------------------------

    if data == "cancel_pair_report":

        if not is_admin(user_id):

            if callback_id:

                answer_callback_query(
                    callback_id,
                    "⛔ شما دسترسی مدیریتی ندارید.",
                    True
                )

            return

        key = str(chat_id)

        PENDING_ACTIONS.pop(
            key,
            None
        )

        PAIR_REPORT_STATE.pop(
            key,
            None
        )

        send_message(
            chat_id,
            "❌ گزارش مبدأ و مقصد لغو شد.",
            main_keyboard(user_id)
        )

        return

    if data.startswith("pairdst:"):

        if not is_admin(user_id):

            if callback_id:

                answer_callback_query(
                    callback_id,
                    "⛔ شما دسترسی مدیریتی ندارید.",
                    True
                )

            return

        key = str(chat_id)

        state = PAIR_REPORT_STATE.get(
            key
        )

        if not state:

            send_message(
                chat_id,
                "❌ این درخواست منقضی شده؛ "
                "لطفاً دوباره از منو شروع کنید.",
                main_keyboard(user_id)
            )

            return

        try:

            idx = int(
                data.split(":", 1)[1]
            )

        except Exception:

            idx = -1

        candidates = state.get(
            "candidates"
        ) or []

        if idx < 0 or idx >= len(candidates):

            send_message(
                chat_id,
                "❌ گزینه‌ی نامعتبر."
            )

            return

        destination_row = candidates[idx]

        source = state.get("source")

        PENDING_ACTIONS.pop(
            key,
            None
        )

        PAIR_REPORT_STATE.pop(
            key,
            None
        )

        if not source:

            send_message(
                chat_id,
                "❌ مبدأ گم شده؛ لطفاً دوباره شروع کنید.",
                main_keyboard(user_id)
            )

            return

        send_message(
            chat_id,
            generate_pair_report(
                source,
                destination_row
            ),
            main_keyboard(user_id)
        )

        return


# =========================================================
# PENDING ACTION
# =========================================================

def handle_broadcast_forward(
    message,
    chat_id,
    user_id
):

    key = str(
        chat_id
    )

    message_id = message.get(
        "message_id"
    )

    if message_id is None:

        send_message(
            chat_id,
            "❌ پیام قابل شناسایی نبود. "
            "لطفاً دوباره تلاش کنید یا "
            "/cancel را بفرستید."
        )

        return True

    PENDING_ACTIONS.pop(
        key,
        None
    )

    active_channels = get_active_channels()

    if not active_channels:

        send_message(
            chat_id,
            "⚠️ هیچ مقصد فعالی برای ارسال وجود ندارد.",
            main_keyboard(user_id)
        )

        return True

    send_message(
        chat_id,
        "⏳ در حال ارسال پست به تمام مقصدهای فعال..."
    )

    result = broadcast_message_to_channels(
        chat_id,
        message_id
    )

    success_count = len(
        result["success"]
    )

    failed_count = len(
        result["failed"]
    )

    text = (
        "📣 <b>نتیجه بازنشر گسترده</b>\n\n"
        f"📊 کل مقصدهای فعال: "
        f"{to_persian_digits(result['total'])}\n"
        f"✅ ارسال موفق: "
        f"{to_persian_digits(success_count)}\n"
        f"❌ ارسال ناموفق: "
        f"{to_persian_digits(failed_count)}\n"
    )

    if result["failed"]:

        text += (
            "\n"
            "🔻 <b>مقصدهای ناموفق:</b>\n"
        )

        for row in result["failed"][:25]:

            title = (
                row.get("title")
                or row.get("username")
                or row.get("chat_id")
                or "-"
            )

            text += (
                f"• {html_text(title)}\n"
            )

        if failed_count > 25:

            text += (
                f"... و "
                f"{to_persian_digits(failed_count - 25)} "
                "مورد دیگر\n"
            )

        text += (
            "\n"
            "💡 معمولاً دلیل ناموفق بودن این است که "
            "ربات در آن مقصد ادمین نیست یا اجازه‌ی "
            "ارسال پیام ندارد."
        )

    send_message(
        chat_id,
        text,
        main_keyboard(user_id)
    )

    return True


def handle_pending_action(
    message,
    chat_id,
    user
):

    key = str(
        chat_id
    )

    action = PENDING_ACTIONS.get(
        key
    )

    if not action:
        return False

    user_id = (
        user.get("id")
        if user
        else None
    )

    text = (
        message.get("text")
        or ""
    ).strip()

    if text.lower() in (
        "/cancel",
        "لغو",
        "انصراف"
    ):

        PENDING_ACTIONS.pop(
            key,
            None
        )

        PAIR_REPORT_STATE.pop(
            key,
            None
        )

        send_message(
            chat_id,
            "❌ عملیات لغو شد.",
            main_keyboard(user_id)
        )

        return True

    # -----------------------------------------------------
    # بازنشر گسترده
    #
    # این حالت ممکن است روی پیام‌های غیرمتنی (عکس/ویدیو/...)
    # هم اتفاق بیفتد، پس نباید به وجود text وابسته باشد.
    # -----------------------------------------------------

    if action == "broadcast_forward":

        return handle_broadcast_forward(
            message,
            chat_id,
            user_id
        )

    # -----------------------------------------------------
    # خبر به صوت - منتظر متن/فوروارد خبر
    #
    # ممکن است پیام فوروارد شده باشد (بدون تایپ مستقیم)، پس
    # مستقیماً از message.get("text") می‌خوانیم که در پیام‌های
    # فوروارد شده هم همان متن اصلی را دارد.
    # -----------------------------------------------------

    if action == "await_news_voice":

        news_text = (message.get("text") or "").strip()

        if not news_text:

            send_message(
                chat_id,
                "❌ متنی پیدا نشد. لطفاً متن خبر را بفرست یا "
                "پست خبر را Forward کن.\n\n"
                "برای انصراف /cancel را بفرستید."
            )

            return True

        PENDING_ACTIONS.pop(key, None)

        process_news_to_voice(
            chat_id,
            message.get("message_id"),
            news_text
        )

        return True

    # -----------------------------------------------------
    # گزارش مبدأ و مقصد - مرحله‌ی اول: شناسایی مبدأ
    #
    # ممکن است با Forward یک پست (بدون متن) انجام شود، پس
    # این هم نباید به وجود text وابسته باشد.
    # -----------------------------------------------------

    if action == "pair_report_source":

        source = resolve_pair_source_from_message(
            message
        )

        if not source or not source.get("channel_id"):

            send_message(
                chat_id,
                "❌ کانال مبدأ شناسایی نشد.\n\n"
                "یک پست از همان کانال را Forward کنید "
                "یا نام کاربری/شناسه‌ی آن را بفرستید.\n\n"
                "برای انصراف /cancel را بفرستید."
            )

            return True

        active_channels = get_active_channels()

        if not active_channels:

            PENDING_ACTIONS.pop(
                key,
                None
            )

            send_message(
                chat_id,
                "⚠️ هیچ مقصد فعالی برای انتخاب وجود ندارد.",
                main_keyboard(user_id)
            )

            return True

        candidates = active_channels[:25]

        PAIR_REPORT_STATE[key] = {
            "source": source,
            "candidates": candidates
        }

        PENDING_ACTIONS[key] = "pair_report_destination"

        extra_note = ""

        if len(active_channels) > len(candidates):

            extra_note = (
                "\n\nℹ️ چون تعداد مقصدها زیاد است، فقط "
                f"{to_persian_digits(len(candidates))} "
                "مورد اول نشان داده شده. برای مقصدهای "
                "دیگر، نام کاربری یا شناسه‌شان را مستقیم "
                "بفرستید."
            )

        send_message(
            chat_id,
            "✅ مبدأ شناسایی شد:\n"
            f"📡 {html_text(source.get('title') or '-')}\n\n"
            "حالا مقصد را از لیست زیر انتخاب کنید، یا "
            "نام کاربری/شناسه‌ی آن را مستقیم بفرستید."
            + extra_note,
            pair_destination_keyboard(
                candidates
            )
        )

        return True

    # -----------------------------------------------------
    # گزارش مبدأ و مقصد - مرحله‌ی دوم: شناسایی مقصد
    # (فقط ورودی متنی؛ انتخاب از کیبورد از طریق callback
    # در process_callback_query انجام می‌شود)
    # -----------------------------------------------------

    if action == "pair_report_destination":

        if not text:
            return True

        destination_row = resolve_pair_destination_from_identifier(
            text
        )

        if not destination_row:

            send_message(
                chat_id,
                "❌ این مقصد در لیست ربات پیدا نشد.\n\n"
                "دوباره تلاش کنید یا از دکمه‌های بالا "
                "استفاده کنید، یا /cancel را بفرستید."
            )

            return True

        state = PAIR_REPORT_STATE.get(
            key,
            {}
        )

        source = state.get("source")

        PENDING_ACTIONS.pop(
            key,
            None
        )

        PAIR_REPORT_STATE.pop(
            key,
            None
        )

        if not source:

            send_message(
                chat_id,
                "❌ مبدأ گم شده؛ لطفاً دوباره شروع کنید.",
                main_keyboard(user_id)
            )

            return True

        send_message(
            chat_id,
            generate_pair_report(
                source,
                destination_row
            ),
            main_keyboard(user_id)
        )

        return True

    if not text:
        return False

    if action == "add_channel":

        PENDING_ACTIONS.pop(
            key,
            None
        )

        ok, result_text = manual_add_channel(
            text
        )

        send_message(
            chat_id,
            result_text,
            main_keyboard(user_id)
        )

        return True

    if action == "remove_channel":

        PENDING_ACTIONS.pop(
            key,
            None
        )

        ok, result_text = manual_remove_channel(
            text
        )

        send_message(
            chat_id,
            result_text,
            main_keyboard(user_id)
        )

        return True

    if action == "add_admin":

        if not is_owner(user_id):

            PENDING_ACTIONS.pop(
                key,
                None
            )

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS.pop(
            key,
            None
        )

        if add_admin(text):

            send_message(
                chat_id,
                "✅ مدیر با موفقیت اضافه شد.",
                admin_keyboard()
            )

        else:

            send_message(
                chat_id,
                "❌ افزودن مدیر ناموفق بود.",
                admin_keyboard()
            )

        return True

    if action == "remove_admin":

        if not is_owner(user_id):

            PENDING_ACTIONS.pop(
                key,
                None
            )

            send_message(
                chat_id,
                "⛔ دسترسی غیرمجاز."
            )

            return True

        PENDING_ACTIONS.pop(
            key,
            None
        )

        if remove_admin(text):

            send_message(
                chat_id,
                "✅ مدیر حذف شد.",
                admin_keyboard()
            )

        else:

            send_message(
                chat_id,
                "❌ حذف مدیر ناموفق بود.",
                admin_keyboard()
            )

        return True

    return False


# =========================================================
# PRIVATE MESSAGE
# =========================================================

def process_private_message(message):

    if not message:
        return

    chat = message.get(
        "chat"
    )

    user = (
        message.get("from")
        or {}
    )

    if not chat:
        return

    chat_id = chat.get(
        "id"
    )

    if chat_id is None:
        return

    save_bot_user(
        user
    )

    user_id = user.get(
        "id"
    )

    text = (
        message.get("text")
        or ""
    ).strip()

    # -----------------------------------------------------
    # VOICE COMMAND (خبر به صوت: /voice، /خبر یا /news)
    #
    # 🔧 این بررسی باید قبل از handle_command باشد: handle_command
    # هر دستور ناشناخته را برای کاربران غیرمدیر (حتی اگر در
    # ai_allowed_users باشند، مثل /image) رد می‌کند. /voice هم
    # باید طبق همان منطق «دسترسی هوش مصنوعی» (نه صرفاً مدیر)
    # کنترل شود، پس پیش از دستورات مدیریتی بررسی می‌شود.
    # -----------------------------------------------------

    if text.startswith("/"):

        try:

            bot = get_me()
            bot_username = bot.get("username") if bot else None

        except Exception:

            bot_username = None

        if handle_voice_command(
            message,
            chat,
            bot_username
        ):
            return

    # -----------------------------------------------------
    # EDIT IMAGE COMMAND (/ویرایش یا /edit_image)
    #
    # ممکن است این دستور به‌صورت کپشن روی خودِ عکس بیاید (که در
    # این صورت message["text"] خالی است و caption باید بررسی
    # شود)، پس شرط شروع این بخش وسیع‌تر از فقط text.startswith
    # است.
    # -----------------------------------------------------

    caption = (message.get("caption") or "").strip()

    if text.startswith("/") or caption.startswith("/"):

        try:

            bot = get_me()
            bot_username = bot.get("username") if bot else None

        except Exception:

            bot_username = None

        if handle_edit_image_command(
            message,
            chat,
            bot_username
        ):
            return

    # -----------------------------------------------------
    # COMMAND
    # -----------------------------------------------------

    if text.startswith("/"):

        if handle_command(
            message,
            chat_id,
            user
        ):
            return

    # -----------------------------------------------------
    # IMAGE COMMAND (/image یا /عکس)
    # -----------------------------------------------------

    if text.startswith("/"):

        try:

            bot = get_me()
            bot_username = bot.get("username") if bot else None

        except Exception:

            bot_username = None

        if handle_image_command(
            message,
            chat,
            bot_username
        ):
            return

        if handle_summary_command(
            message,
            chat,
            bot_username
        ):
            return

        if handle_rewrite_command(
            message,
            chat,
            bot_username
        ):
            return

    # -----------------------------------------------------
    # PENDING
    # -----------------------------------------------------

    if handle_pending_action(
        message,
        chat_id,
        user
    ):
        return

    # -----------------------------------------------------
    # BUTTON
    # -----------------------------------------------------

    if text:

        if handle_button(
            message,
            chat_id,
            user
        ):
            return

    # -----------------------------------------------------
    # FORWARD SOURCE
    # -----------------------------------------------------

    source = extract_forward(
        message
    )

    if source:

        if not is_admin(user_id):

            send_message(
                chat_id,
                "⛔ فقط مدیران می‌توانند "
                "پست مبدأ انتخاب کنند."
            )

            return

        set_selected_source(
            source,
            user_id
        )

        return

    # -----------------------------------------------------
    # 🤖 پاسخ‌گویی هوشمند (Gemini) در خصوصی
    #
    # اگر هیچ‌کدام از موارد بالا (دستور/دکمه/فوروارد مبدأ) این
    # پیام را مدیریت نکردند، آن را به‌عنوان یک سوال معمولی به
    # هوش مصنوعی می‌دهیم. در خصوصی نیازی به منشن کردن ربات نیست.
    # -----------------------------------------------------

    try:

        bot = get_me()
        bot_id = bot.get("id") if bot else None
        bot_username = bot.get("username") if bot else None

        handle_ai_question(
            message,
            chat,
            "private",
            bot_id,
            bot_username,
            require_mention=False
        )

    except Exception as e:

        print(
            "AI PRIVATE REPLY ERROR:",
            repr(e)
        )

        traceback.print_exc()


# =========================================================
# DEBUG UPDATE
# =========================================================

def print_update_debug(update):

    print("\n")
    print("=" * 100)
    print("🔥🔥🔥 NEW BALE UPDATE 🔥🔥🔥")
    print("=" * 100)

    print(
        "UPDATE ID:",
        update.get("update_id")
    )

    print(
        "UPDATE KEYS:",
        list(update.keys())
    )

    print("-" * 100)

    if "message" in update:

        print("MESSAGE:")
        print(
            update["message"]
        )

    if "channel_post" in update:

        print("CHANNEL POST:")
        print(
            update["channel_post"]
        )

    if "callback_query" in update:

        print("CALLBACK QUERY:")
        print(
            update["callback_query"]
        )

    if "my_chat_member" in update:

        print("MY CHAT MEMBER:")
        print(
            update["my_chat_member"]
        )

    if "chat_member" in update:

        print("CHAT MEMBER:")
        print(
            update["chat_member"]
        )

    if "chat_join_request" in update:

        print("CHAT JOIN REQUEST:")
        print(
            update["chat_join_request"]
        )

    print("=" * 100)
    print("🔥 END UPDATE")
    print("=" * 100)
    print("\n")


# =========================================================
# PROCESS UPDATE
# =========================================================

def process_update(update):

    print_update_debug(
        update
    )

    # -----------------------------------------------------
    # CALLBACK
    # -----------------------------------------------------

    callback_query = update.get(
        "callback_query"
    )

    if callback_query:

        try:

            process_callback_query(
                callback_query
            )

        except Exception as e:

            print(
                "CALLBACK PROCESS ERROR:",
                repr(e)
            )

            traceback.print_exc()

        return

    # -----------------------------------------------------
    # MEMBERSHIP
    # -----------------------------------------------------

    try:

        if handle_bot_membership_update(
            update
        ):
            return

    except Exception as e:

        print(
            "MEMBERSHIP UPDATE ERROR:",
            repr(e)
        )

        traceback.print_exc()

    # -----------------------------------------------------
    # MESSAGE
    # -----------------------------------------------------

    message = update.get(
        "message"
    )

    if not message:

        message = update.get(
            "channel_post"
        )

    if not message:
        return

    chat = message.get(
        "chat"
    )

    if not chat:
        return

    chat_type = chat.get(
        "type"
    )

    # -----------------------------------------------------
    # GROUP / CHANNEL SERVICE
    #
    # 🔧 بله برای کانال‌ها هم new_chat_members/left_chat_member
    # می‌فرستد، پس "channel" هم باید اینجا بررسی شود.
    # -----------------------------------------------------

    if chat_type in (
        "group",
        "supergroup",
        "channel"
    ):

        try:

            if handle_group_service_message(
                message
            ):
                return

        except Exception as e:

            print(
                "GROUP SERVICE ERROR:",
                repr(e)
            )

            traceback.print_exc()

    # -----------------------------------------------------
    # PRIVATE
    # -----------------------------------------------------

    if chat_type == "private":

        process_private_message(
            message
        )

        return

    # -----------------------------------------------------
    # GROUP / CHANNEL
    # -----------------------------------------------------

    if chat_type in (
        "group",
        "supergroup",
        "channel"
    ):

        process_channel_message(
            message
        )


# =========================================================
# INITIALIZE
# =========================================================

def initialize():

    print(
        "\n"
        "======================================"
    )

    print(
        "🚀 BALE REPOST BOT STARTING..."
    )

    print(
        "======================================"
    )

    bot = get_me()

    if not bot:

        raise Exception(
            "Bot authentication failed"
        )

    print(
        "BOT ID:",
        bot.get("id")
    )

    print(
        "BOT USERNAME:",
        bot.get("username")
    )

    owner_id = get_owner_id()

    if not owner_id:

        print(
            "⚠️ WARNING: owner_id is not configured."
        )

        print(
            "Set bot_settings.owner_id in Supabase."
        )

    else:

        print(
            "OWNER ID:",
            owner_id
        )

    print(
        "======================================"
    )

    print(
        "BOT IS READY"
    )

    print(
        "======================================"
    )


# =========================================================
# MAIN LOOP
# =========================================================

def main():

    global LAST_UPDATE_ID

    initialize()

    offset = None

    while True:

        try:

            updates = get_updates(
                offset
            )

            if updates is None:

                time.sleep(2)

                continue

            if not updates:
                continue

            print(
                f"📥 RECEIVED {len(updates)} UPDATE(S)"
            )

            for update in updates:

                try:

                    update_id = update.get(
                        "update_id"
                    )

                    if update_id is not None:

                        LAST_UPDATE_ID = update_id

                        offset = (
                            int(update_id) + 1
                        )

                    process_update(
                        update
                    )

                except Exception as e:

                    print(
                        "❌ PROCESS UPDATE ERROR:",
                        repr(e)
                    )

                    traceback.print_exc()

        except KeyboardInterrupt:

            print(
                "🛑 BOT STOPPED"
            )

            break

        except Exception as e:

            print(
                "❌ MAIN LOOP ERROR:",
                repr(e)
            )

            traceback.print_exc()

            time.sleep(5)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
