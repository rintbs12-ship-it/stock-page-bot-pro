import os
from dotenv import load_dotenv

load_dotenv()


def _integer_list(value):
    result = []
    for item in value.split(","):
        item = item.strip()
        if item.isdigit():
            result.append(int(item))
    return result


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = _integer_list(os.getenv("ADMIN_IDS", "619658883"))
TELEGRAM_CONTACT = os.getenv("TELEGRAM_CONTACT", "https://t.me/dornthearin")
FACEBOOK_CONTACT = os.getenv("FACEBOOK_CONTACT", "https://web.facebook.com/dorn.thearin.2025/")

DB_PATH = os.getenv("DB_PATH", "database.db")
IMAGE_DIR = os.getenv("IMAGE_DIR", "images/stock")
