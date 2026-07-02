import asyncio
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)
from config import BOT_TOKEN, DB_PATH, is_render_environment
from database.db import (
    add_demo_stock_if_empty,
    add_maintenance_run,
    database_backend,
    database_startup_diagnostics,
    init_db,
    is_admin_user,
    is_telegram_user_blocked,
    list_admins,
    track_telegram_user,
    verify_database,
)
from handlers.backup import run_due_auto_backup
from handlers.notifications import notification_scheduler
from handlers.scheduler import task_scheduler
from health import start_health_server
from khmer_bot import KhmerExtBot
from keyboards.buttons import start_reply_keyboard
from handlers.menu import cancel, start, handle_callback, handle_text, handle_command
from version import PRODUCT_NAME, __version__


LOGGER = logging.getLogger(__name__)
HEALTH_SERVER_KEY = "health_server"
BACKGROUND_TASKS_KEY = "background_tasks"
BLOCKED_USER_MESSAGE = (
    "❌ គណនីរបស់អ្នកត្រូវបានផ្អាកពីការប្រើប្រាស់ Bot នេះ។\n"
    "សូមទាក់ទង Admin ប្រសិនបើអ្នកគិតថាជាកំហុស។"
)


async def track_and_guard_user(update: Update, context):
    user = update.effective_user
    if not user:
        return
    admin = is_admin_user(user.id)
    try:
        track_telegram_user(
            user.id,
            getattr(user, "username", "") or "",
            getattr(user, "first_name", "") or "",
            getattr(user, "last_name", "") or "",
            getattr(user, "language_code", "") or "",
            is_admin=admin,
            count_message=update.message is not None,
        )
    except Exception:
        LOGGER.exception("Could not track Telegram user %s", user.id)
    if admin or not is_telegram_user_blocked(user.id):
        return
    LOGGER.info("Blocked Telegram user update stopped: user_id=%s", user.id)
    if update.callback_query:
        await update.callback_query.answer(BLOCKED_USER_MESSAGE, show_alert=True)
        await update.callback_query.message.reply_text(BLOCKED_USER_MESSAGE)
    elif update.effective_message:
        await update.effective_message.reply_text(BLOCKED_USER_MESSAGE)
    raise ApplicationHandlerStop


async def global_start(update: Update, context):
    user = update.effective_user
    if user:
        try:
            track_telegram_user(
                user.id,
                getattr(user, "username", "") or "",
                getattr(user, "first_name", "") or "",
                getattr(user, "last_name", "") or "",
                getattr(user, "language_code", "") or "",
                is_admin=is_admin_user(user.id),
                count_message=True,
            )
        except Exception:
            LOGGER.exception(
                "Could not track /start user %s", user.id
            )
    await start(update, context)
    raise ApplicationHandlerStop


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
            await update.callback_query.message.reply_text(
                message, reply_markup=start_reply_keyboard()
            )
        elif update and getattr(update, "effective_message", None):
            await update.effective_message.reply_text(
                message, reply_markup=start_reply_keyboard()
            )
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


def _log_background_task_result(task):
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        LOGGER.exception("Background task %s stopped unexpectedly", task.get_name())


async def post_init(app):
    tasks = [
        asyncio.create_task(
            notification_scheduler(app.bot),
            name="notification_scheduler",
        ),
        asyncio.create_task(
            task_scheduler(app.bot),
            name="task_scheduler",
        ),
    ]
    for task in tasks:
        task.add_done_callback(_log_background_task_result)
    app.bot_data[BACKGROUND_TASKS_KEY] = tasks
    LOGGER.info("%s v%s startup completed", PRODUCT_NAME, __version__)


async def _close_health_server(app):
    health_server = app.bot_data.pop(HEALTH_SERVER_KEY, None)
    if health_server is not None:
        health_server.close()
        await health_server.wait_closed()


async def post_shutdown(app):
    tasks = app.bot_data.pop(BACKGROUND_TASKS_KEY, [])
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    await _close_health_server(app)
    LOGGER.info("%s shutdown completed", PRODUCT_NAME)


def build_application():
    telegram_bot = KhmerExtBot(token=BOT_TOKEN)
    app = (
        Application.builder()
        .bot(telegram_bot)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", global_start), group=-100)
    app.add_handler(TypeHandler(Update, track_and_guard_user), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(
            r"^\s*(?:✅\ufe0f?\s*)?/(?:done|រួចរាល់)(?:@\w+)?\s*$"
        ),
        handle_command,
    ))
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


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty. Please create .env from .env.example and add your token.")

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    sqlite_file_existed = (
        database_backend() == "sqlite"
        and Path(DB_PATH).is_file()
    )
    init_db()
    diagnostics = database_startup_diagnostics()
    LOGGER.info(
        "Database startup: backend=%s path=%s existed_before_startup=%s "
        "exists_now=%s counts=%s",
        diagnostics["backend"],
        diagnostics["path"] or "(DATABASE_URL)",
        sqlite_file_existed if diagnostics["backend"] == "sqlite" else "n/a",
        diagnostics["exists"],
        diagnostics["counts"],
    )
    report = verify_database()
    LOGGER.info(
        "Database verified: integrity=%s, foreign_key_errors=%d",
        report["integrity"], len(report["foreign_key_errors"]),
    )
    if (
        diagnostics["backend"] == "sqlite"
        and not is_render_environment()
        and not sqlite_file_existed
    ):
        add_demo_stock_if_empty()
    try:
        automatic_backup = run_due_auto_backup()
        if automatic_backup:
            LOGGER.info("Auto backup created: %s", automatic_backup.name)
    except (OSError, RuntimeError) as exc:
        LOGGER.warning("Auto backup skipped: %s", exc)
    app = build_application()
    try:
        # Python 3.14 no longer creates a MainThread event loop implicitly.
        # PTB 22.3's synchronous run_polling() expects a current, non-running
        # loop and remains the sole owner of the application polling lifecycle.
        with asyncio.Runner() as runner:
            runner.get_loop()
            health_server = runner.run(start_health_server())
            app.bot_data[HEALTH_SERVER_KEY] = health_server
            health_port = health_server.sockets[0].getsockname()[1]
            LOGGER.info("Health server listening on 0.0.0.0:%s", health_port)
            try:
                app.run_polling(
                    allowed_updates=Update.ALL_TYPES,
                    bootstrap_retries=-1,
                    close_loop=False,
                )
            finally:
                runner.run(_close_health_server(app))
    except KeyboardInterrupt:
        LOGGER.info("Stock Page Bot stopped")
    except Exception:
        LOGGER.exception("Fatal bot process error")
        raise


if __name__ == "__main__":
    main()
