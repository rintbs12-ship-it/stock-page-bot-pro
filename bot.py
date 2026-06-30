import asyncio
import logging

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import BOT_TOKEN
from database.db import init_db, add_demo_stock_if_empty
from handlers.backup import run_due_auto_backup
from handlers.menu import cancel, start, handle_callback, handle_text, handle_command
from version import PRODUCT_NAME, __version__


LOGGER = logging.getLogger(__name__)


async def handle_error(update, context):
    LOGGER.exception("Unhandled bot error", exc_info=context.error)
    message = "⚠️ Something went wrong. Please try again from /start."
    try:
        if update and getattr(update, "callback_query", None):
            await update.callback_query.message.reply_text(message)
        elif update and getattr(update, "effective_message", None):
            await update.effective_message.reply_text(message)
    except Exception:
        LOGGER.exception("Could not send friendly error message")


def build_application():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", handle_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.ALL | (filters.TEXT & ~filters.COMMAND),
        handle_text,
    ))
    app.add_error_handler(handle_error)
    return app


async def run_bot(app):
    async with app:
        await app.updater.start_polling(allowed_updates=None)
        await app.start()
        print(f"{PRODUCT_NAME} v{__version__} is running...")
        try:
            await asyncio.Event().wait()
        finally:
            if app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Please create .env from .env.example and add your token.")

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    init_db()
    add_demo_stock_if_empty()
    try:
        automatic_backup = run_due_auto_backup()
        if automatic_backup:
            print(f"Auto backup created: {automatic_backup.name}")
    except (OSError, RuntimeError) as exc:
        # A backup filesystem problem must not prevent customer features
        # from starting. The Admin can retry from Backup Manager.
        print(f"Auto backup skipped: {exc}")
    app = build_application()
    try:
        asyncio.run(run_bot(app))
    except KeyboardInterrupt:
        print("Stock Page Bot stopped.")


if __name__ == "__main__":
    main()
