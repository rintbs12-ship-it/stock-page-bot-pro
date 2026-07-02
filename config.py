import os
from pathlib import Path
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

RENDER_SQLITE_PATH = "/var/data/database.db"


def is_render_environment(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get("RENDER", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def resolve_db_path(environ=None):
    env = os.environ if environ is None else environ
    if is_render_environment(env):
        return RENDER_SQLITE_PATH
    configured = str(env.get("DB_PATH", "")).strip()
    return configured or str(Path("database.db"))


DB_PATH = resolve_db_path()
IMAGE_DIR = os.getenv("IMAGE_DIR", "images/stock")
