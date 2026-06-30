import asyncio
import logging
from datetime import datetime
from time import perf_counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, TelegramError

from database.db import (
    add_maintenance_run,
    complete_broadcast,
    create_broadcast,
    get_broadcast,
    get_broadcast_history,
    get_broadcast_recipients,
    get_due_broadcasts,
    get_saved_broadcast_recipients,
    is_admin_user,
    mark_broadcast_sending,
    search_customers,
)


LOGGER = logging.getLogger(__name__)


def notification_center_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📨 Broadcast All Customers",
            callback_data="admin:notify_audience:all",
        )],
        [InlineKeyboardButton(
            "⭐ Broadcast VIP Customers",
            callback_data="admin:notify_audience:vip",
        )],
        [InlineKeyboardButton(
            "📦 Broadcast Customers With Orders",
            callback_data="admin:notify_audience:orders",
        )],
        [InlineKeyboardButton(
            "👥 Broadcast Selected Customers",
            callback_data="admin:notify_selected",
        )],
        [InlineKeyboardButton(
            "🖼 Send Photo Broadcast",
            callback_data="admin:notify_media:photo",
        )],
        [InlineKeyboardButton(
            "🎬 Send Video Broadcast",
            callback_data="admin:notify_media:video",
        )],
        [InlineKeyboardButton(
            "📄 Send Document Broadcast",
            callback_data="admin:notify_media:document",
        )],
        [InlineKeyboardButton(
            "⏰ Schedule Broadcast",
            callback_data="admin:notify_schedule",
        )],
        [InlineKeyboardButton(
            "📜 Broadcast History",
            callback_data="admin:notify_history",
        )],
        [InlineKeyboardButton(
            "📊 Delivery Report",
            callback_data="admin:notify_report",
        )],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin:home")],
    ])


def selected_customers_keyboard(customers, selected):
    selected = set(selected)
    rows = [[InlineKeyboardButton(
        f"{'✅' if customer[1] in selected else '⬜'} "
        f"{customer[2] or customer[1]}",
        callback_data=f"admin:notify_select:{customer[1]}",
    )] for customer in customers]
    rows.extend([
        [InlineKeyboardButton(
            "🔎 Search Customer", callback_data="admin:notify_selected_search"
        )],
        [InlineKeyboardButton(
            f"➡️ Continue ({len(selected)})",
            callback_data="admin:notify_selected_continue",
        )],
        [InlineKeyboardButton(
            "⬅️ Notification Center", callback_data="admin:notify"
        )],
    ])
    return InlineKeyboardMarkup(rows)


def delivery_report_text(broadcast):
    return (
        f"📊 Delivery Report #{broadcast[0]}\n\n"
        f"Total Customers: {broadcast[6]}\n"
        f"Delivered: {broadcast[7]}\n"
        f"Failed: {broadcast[8]}\n"
        f"Blocked: {broadcast[9]}\n"
        f"Duration: {broadcast[10]:.2f}s"
    )


async def execute_broadcast(bot, broadcast_id):
    broadcast = get_broadcast(broadcast_id)
    if not broadcast or not mark_broadcast_sending(broadcast_id):
        return get_broadcast(broadcast_id)
    if broadcast[2] == "selected":
        recipients = get_saved_broadcast_recipients(broadcast_id)
    else:
        recipients = get_broadcast_recipients(broadcast[2])
    success = failed = blocked = 0
    started = perf_counter()
    for telegram_id in recipients:
        try:
            kwargs = {"chat_id": telegram_id}
            if broadcast[4] == "photo":
                await bot.send_photo(
                    **kwargs, photo=broadcast[5],
                    caption=broadcast[3] or None,
                )
            elif broadcast[4] == "video":
                await bot.send_video(
                    **kwargs, video=broadcast[5],
                    caption=broadcast[3] or None,
                )
            elif broadcast[4] == "document":
                await bot.send_document(
                    **kwargs, document=broadcast[5],
                    caption=broadcast[3] or None,
                )
            else:
                await bot.send_message(**kwargs, text=broadcast[3])
            success += 1
        except Forbidden:
            blocked += 1
        except TelegramError:
            failed += 1
    complete_broadcast(
        broadcast_id, len(recipients), success, failed, blocked,
        perf_counter() - started,
    )
    return get_broadcast(broadcast_id)


def _message_content(message):
    if getattr(message, "photo", None):
        return "photo", message.photo[-1].file_id, message.caption or ""
    if getattr(message, "video", None):
        return "video", message.video.file_id, message.caption or ""
    if getattr(message, "document", None):
        return "document", message.document.file_id, message.caption or ""
    text = (getattr(message, "text", "") or "").strip()
    return ("text", "", text) if text else (None, None, None)


async def handle_notification_callback(query, context):
    if not is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ Admin only")
        return True
    data = query.data
    if data == "admin:notify":
        context.user_data.clear()
        await query.edit_message_text(
            "📢 Notification Center",
            reply_markup=notification_center_menu(),
        )
        return True
    if data.startswith("admin:notify_audience:"):
        audience = data.rsplit(":", 1)[1]
        if audience not in {"all", "vip", "orders"}:
            await query.message.reply_text("Invalid audience.")
            return True
        context.user_data.clear()
        context.user_data.update({
            "notify_mode": "content",
            "notify_audience": audience,
        })
        await query.edit_message_text(
            "📨 Send text, photo, video, or document to broadcast."
        )
        return True
    if data.startswith("admin:notify_media:"):
        media_type = data.rsplit(":", 1)[1]
        if media_type not in {"photo", "video", "document"}:
            await query.message.reply_text("Invalid media type.")
            return True
        context.user_data.clear()
        context.user_data.update({
            "notify_mode": "content",
            "notify_audience": "all",
            "notify_media": media_type,
        })
        await query.edit_message_text(
            f"Send the {media_type} with an optional caption."
        )
        return True
    if data == "admin:notify_selected":
        context.user_data.clear()
        context.user_data["notify_selected"] = []
        await query.edit_message_text(
            "👥 Selected Customers\n\nSearch and select recipients.",
            reply_markup=selected_customers_keyboard(
                [], context.user_data["notify_selected"]
            ),
        )
        return True
    if data == "admin:notify_selected_search":
        context.user_data["notify_mode"] = "selected_search"
        await query.edit_message_text(
            "🔎 Send Telegram ID or username."
        )
        return True
    if data.startswith("admin:notify_select:"):
        try:
            telegram_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid customer.")
            return True
        selected = set(context.user_data.get("notify_selected", []))
        if telegram_id in selected:
            selected.remove(telegram_id)
        else:
            selected.add(telegram_id)
        context.user_data["notify_selected"] = list(selected)
        await query.edit_message_text(
            "👥 Selected Customers",
            reply_markup=selected_customers_keyboard([], selected),
        )
        return True
    if data == "admin:notify_selected_continue":
        if not context.user_data.get("notify_selected"):
            await query.message.reply_text("Select at least one customer.")
            return True
        context.user_data["notify_mode"] = "content"
        context.user_data["notify_audience"] = "selected"
        await query.edit_message_text(
            "📨 Send text, photo, video, or document to broadcast."
        )
        return True
    if data == "admin:notify_schedule":
        context.user_data.clear()
        context.user_data.update({
            "notify_mode": "content",
            "notify_audience": "all",
            "notify_schedule": True,
        })
        await query.edit_message_text(
            "⏰ Send the broadcast content first."
        )
        return True
    if data == "admin:notify_history":
        history = get_broadcast_history()
        lines = ["📜 Broadcast History", ""]
        lines.extend(
            f"#{row[0]} · {row[2]} · {row[4]} · {row[12]}\n"
            f"{row[13]}"
            for row in history
        )
        await query.edit_message_text(
            "\n\n".join(lines) if history else "📜 No broadcast history.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Notification Center", callback_data="admin:notify"
                )
            ]]),
        )
        return True
    if data == "admin:notify_report":
        history = get_broadcast_history(1)
        text = (
            delivery_report_text(history[0])
            if history else "📊 No delivery report available."
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⬅️ Notification Center", callback_data="admin:notify"
                )
            ]]),
        )
        return True
    return False


async def handle_notification_message(update, context):
    mode = context.user_data.get("notify_mode")
    if not mode:
        return False
    if not is_admin_user(update.effective_user.id):
        context.user_data.clear()
        await update.message.reply_text("⛔ Admin only")
        return True
    if mode == "selected_search":
        value = (update.message.text or "").strip()
        search_type = "telegram" if value.isdigit() else "username"
        customers = search_customers(search_type, value)
        context.user_data.pop("notify_mode", None)
        await update.message.reply_text(
            f"🔎 Results: {len(customers)}",
            reply_markup=selected_customers_keyboard(
                customers, context.user_data.get("notify_selected", [])
            ),
        )
        return True
    if mode == "schedule_time":
        value = (update.message.text or "").strip()
        try:
            scheduled = datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text(
                "Use date and time format: YYYY-MM-DD HH:MM"
            )
            return True
        if scheduled <= datetime.now():
            await update.message.reply_text("Schedule time must be in the future.")
            return True
        content = context.user_data["notify_content"]
        broadcast_id = create_broadcast(
            update.effective_user.id,
            context.user_data["notify_audience"],
            content["message"],
            content["media_type"],
            content["file_id"],
            scheduled.strftime("%Y-%m-%d %H:%M:%S"),
            context.user_data.get("notify_selected"),
        )
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Broadcast #{broadcast_id} scheduled for "
            f"{scheduled:%Y-%m-%d %H:%M}."
        )
        return True
    media_type, file_id, message = _message_content(update.message)
    if not media_type:
        await update.message.reply_text("Send valid broadcast content.")
        return True
    expected_media = context.user_data.get("notify_media")
    if expected_media and media_type != expected_media:
        await update.message.reply_text(f"Please send a {expected_media}.")
        return True
    if context.user_data.get("notify_schedule"):
        context.user_data["notify_content"] = {
            "media_type": media_type,
            "file_id": file_id,
            "message": message,
        }
        context.user_data["notify_mode"] = "schedule_time"
        await update.message.reply_text(
            "⏰ Send date and time: YYYY-MM-DD HH:MM"
        )
        return True
    broadcast_id = create_broadcast(
        update.effective_user.id,
        context.user_data.get("notify_audience", "all"),
        message,
        media_type,
        file_id,
        selected_ids=context.user_data.get("notify_selected"),
    )
    context.user_data.clear()
    result = await execute_broadcast(context.bot, broadcast_id)
    await update.message.reply_text(delivery_report_text(result))
    return True


async def process_due_broadcasts(bot, now=None):
    results = []
    for broadcast in get_due_broadcasts(now):
        results.append(await execute_broadcast(bot, broadcast[0]))
    return results


async def notification_scheduler(bot, interval=30):
    while True:
        try:
            await process_due_broadcasts(bot)
        except Exception as exc:
            LOGGER.exception("Scheduled broadcast cycle failed")
            try:
                add_maintenance_run("broadcast_scheduler", "failed", str(exc)[:500])
            except Exception:
                LOGGER.exception("Could not persist broadcast scheduler failure")
        await asyncio.sleep(interval)
