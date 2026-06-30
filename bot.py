import asyncio
import logging
from datetime import datetime

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import BOT_TOKEN
from database.db import (
    add_demo_stock_if_empty,
    add_maintenance_run,
    init_db,
    list_admins,
    verify_database,
)
from handlers.backup import run_due_auto_backup
from handlers.notifications import notification_scheduler
from handlers.scheduler import task_scheduler
from health import start_health_server
from handlers.menu import cancel, start, handle_callback, handle_text, handle_command
from version import PRODUCT_NAME, __version__


LOGGER = logging.getLogger(__name__)


async def handle_error(update, context):
    error = context.error
    reference = datetime.now().strftime("%Y%m%d%H%M%S")
    LOGGER.exception("Unhandled bot error [%s]", reference, exc_info=error)
    details = f"{type(error).__name__}: {str(error)[:500]}"
    try:
        add_maintenance_run("unhandled_error", "failed", f"{reference}: {details}")
    except Exception:
        LOGGER.exception("Could not persist error [%s]", reference)
    message = (
        "⚠️ Something went wrong. Please try again from /start.\n"
        f"Reference: {reference}"
    )
    try:
        if update and getattr(update, "callback_query", None):
            await update.callback_query.message.reply_text(message)
        elif update and getattr(update, "effective_message", None):
            await update.effective_message.reply_text(message)
    except Exception:
        LOGGER.exception("Could not send friendly error message")
    try:
        admins = list_admins()
    except Exception:
        LOGGER.exception("Could not load admins for error %s", reference)
        admins = []
    for admin_id, _ in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🚨 Bot error [{reference}]\n{details}",
            )
        except Exception:
            LOGGER.warning("Could not notify admin %s of error %s", admin_id, reference)


def build_application():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("done", handle_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL
        | (filters.TEXT & ~filters.COMMAND),
        handle_text,
    ))
    app.add_error_handler(handle_error)
    return app


async def run_bot(app):
    health_server = await start_health_server()
    health_port = health_server.sockets[0].getsockname()[1]
    LOGGER.info("Health server listening on 0.0.0.0:%s", health_port)
    try:
        async with app:
            await app.updater.start_polling(allowed_updates=None)
            await app.start()
            notification_task = asyncio.create_task(
                notification_scheduler(app.bot)
            )
            scheduler_task = asyncio.create_task(task_scheduler(app.bot))
            LOGGER.info("%s v%s is running", PRODUCT_NAME, __version__)
            try:
                await asyncio.Event().wait()
            finally:
                notification_task.cancel()
                scheduler_task.cancel()
                try:
                    await notification_task
                except asyncio.CancelledError:
                    pass
                try:
                    await scheduler_task
                except asyncio.CancelledError:
                    pass
                if app.updater.running:
                    await app.updater.stop()
                if app.running:
                    await app.stop()
    finally:
        health_server.close()
        await health_server.wait_closed()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Please create .env from .env.example and add your token.")

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    init_db()
    report = verify_database()
    LOGGER.info(
        "Database verified: integrity=%s, foreign_key_errors=%d",
        report["integrity"], len(report["foreign_key_errors"]),
    )
    add_demo_stock_if_empty()
    try:
        automatic_backup = run_due_auto_backup()
        if automatic_backup:
            LOGGER.info("Auto backup created: %s", automatic_backup.name)
    except (OSError, RuntimeError) as exc:
        LOGGER.warning("Auto backup skipped: %s", exc)
    app = build_application()
    try:
        asyncio.run(run_bot(app))
    except KeyboardInterrupt:
        LOGGER.info("Stock Page Bot stopped")


if __name__ == "__main__":
    main()
