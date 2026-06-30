import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "619658883").split(",") if x.strip()]
TELEGRAM_CONTACT = os.getenv("TELEGRAM_CONTACT", "https://t.me/dornthearin")
FACEBOOK_CONTACT = os.getenv("FACEBOOK_CONTACT", "https://web.facebook.com/dorn.thearin.2025/")

DB_PATH = "database.db"
IMAGE_DIR = "images/stock"
