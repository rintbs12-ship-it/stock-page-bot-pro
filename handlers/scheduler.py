import asyncio
import calendar
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from config import DB_PATH
from database.db import (
    add_audit_log,
    add_maintenance_run,
    cancel_scheduled_job,
    connect,
    create_scheduled_job,
    get_due_scheduled_jobs,
    get_maintenance_runs,
    get_setting,
    list_admins,
    list_scheduled_jobs,
    set_setting,
    update_scheduled_job_run,
)
from handlers.analytics import get_analytics_data
from handlers.audit import admin_display_name
from handlers.backup import (
    BACKUP_DIR,
    get_backup_retention,
    prune_backups,
    run_due_auto_backup,
)


REMINDER_TYPES = {
    "pending_payment": "Pending Payment Reminder",
    "pending_order": "Pending Order Reminder",
    "customer_followup": "Customer Follow-up Reminder",
}
RECURRENCES = {"one_time", "daily", "weekly", "monthly"}


def scheduler_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 Auto Backup Scheduler", callback_data="admin:backup_auto")],
        [InlineKeyboardButton("📢 Scheduled Announcements", callback_data="admin:scheduler:announcements")],
        [InlineKeyboardButton("🔔 Reminder Manager", callback_data="admin:scheduler:reminders")],
        [InlineKeyboardButton("🧹 Maintenance", callback_data="admin:scheduler:maintenance")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def scheduled_announcements_menu(jobs):
    rows = [[InlineKeyboardButton(
        f"❌ #{job[0]} {job[3][:28]}",
        callback_data=f"admin:scheduler:cancel:{job[0]}:announcements",
    )] for job in jobs]
    rows.extend([
        [InlineKeyboardButton("➕ Schedule Announcement", callback_data="admin:scheduler:announcement_new")],
        [InlineKeyboardButton("⬅ Scheduler", callback_data="admin:scheduler")],
    ])
    return InlineKeyboardMarkup(rows)


def reminder_manager_menu(jobs):
    rows = [
        [InlineKeyboardButton(
            "💳 Pending Payment", callback_data="admin:scheduler:reminder_new:pending_payment"
        )],
        [InlineKeyboardButton(
            "📦 Pending Order", callback_data="admin:scheduler:reminder_new:pending_order"
        )],
        [InlineKeyboardButton(
            "🤝 Customer Follow-up", callback_data="admin:scheduler:reminder_new:customer_followup"
        )],
        [InlineKeyboardButton(
            "✍ Custom Reminder", callback_data="admin:scheduler:reminder_custom"
        )],
    ]
    rows.extend([[
        InlineKeyboardButton(
            f"❌ #{job[0]} {job[3][:25]}",
            callback_data=f"admin:scheduler:cancel:{job[0]}:reminders",
        )
    ] for job in jobs])
    rows.append([InlineKeyboardButton("⬅ Scheduler", callback_data="admin:scheduler")])
    return InlineKeyboardMarkup(rows)


def maintenance_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Auto Cleanup", callback_data="admin:scheduler:maint:cleanup")],
        [
            InlineKeyboardButton("⚡ Optimize", callback_data="admin:scheduler:maint:optimize"),
            InlineKeyboardButton("🗜 Vacuum", callback_data="admin:scheduler:maint:vacuum"),
        ],
        [
            InlineKeyboardButton("📊 Refresh Analytics", callback_data="admin:scheduler:maint:analytics"),
            InlineKeyboardButton("❤️ Health Check", callback_data="admin:scheduler:maint:health"),
        ],
        [InlineKeyboardButton("▶ Run Daily Maintenance", callback_data="admin:scheduler:maint:daily")],
        [InlineKeyboardButton("📜 Maintenance History", callback_data="admin:scheduler:maint:history")],
        [InlineKeyboardButton("⬅ Scheduler", callback_data="admin:scheduler")],
    ])


def _advance_time(current, recurrence):
    if recurrence == "daily":
        return current + timedelta(days=1)
    if recurrence == "weekly":
        return current + timedelta(days=7)
    if recurrence == "monthly":
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)
    return None


def _parse_schedule(text):
    parts = [part.strip() for part in text.rsplit("|", 1)]
    if len(parts) != 2 or parts[1] not in RECURRENCES:
        raise ValueError("Invalid schedule")
    run_at = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
    return run_at.strftime("%Y-%m-%d %H:%M:%S"), parts[1]


async def _send_many(bot, recipients, message):
    success = 0
    failed = 0
    for recipient in recipients:
        try:
            await bot.send_message(chat_id=recipient, text=message)
            success += 1
        except TelegramError:
            failed += 1
    return success, failed


def _customer_ids(clause="", params=()):
    con = connect()
    rows = con.execute(
        "SELECT telegram_id FROM customer_profiles WHERE is_banned=0 "
        + clause, params
    ).fetchall()
    con.close()
    return [row[0] for row in rows]


async def _execute_job(bot, job):
    job_id, admin_id, job_type, title, payload, recurrence, next_run = job[:7]
    if job_type == "announcement":
        recipients = _customer_ids()
        success, failed = await _send_many(
            bot, recipients, f"📢 {payload.get('message', title)}"
        )
        return f"sent={success}, failed={failed}"
    if job_type == "pending_payment":
        con = connect()
        rows = con.execute("""
            SELECT DISTINCT customer_id, order_id FROM orders
            WHERE status IN (
                'waiting_payment', 'waiting_receipt', 'waiting_admin_confirm'
            )
        """).fetchall()
        con.close()
        success = failed = 0
        for customer_id, order_id in rows:
            sent, missed = await _send_many(
                bot, [customer_id],
                f"🔔 Payment reminder for Order #{order_id}.\n"
                "Please complete payment or upload your receipt.",
            )
            success += sent
            failed += missed
        return f"sent={success}, failed={failed}"
    if job_type == "pending_order":
        con = connect()
        count = con.execute("""
            SELECT COUNT(*) FROM orders
            WHERE status NOT IN ('completed', 'cancelled')
        """).fetchone()[0]
        con.close()
        admins = [row[0] for row in list_admins()]
        success, failed = await _send_many(
            bot, admins, f"🔔 Pending order reminder: {count} active order(s)."
        )
        return f"sent={success}, failed={failed}, orders={count}"
    if job_type == "customer_followup":
        recipients = _customer_ids(
            "AND telegram_id IN ("
            "SELECT customer_id FROM orders WHERE status='completed' "
            "AND completed_at<=datetime('now', 'localtime', '-7 days'))"
        )
        success, failed = await _send_many(
            bot, recipients,
            payload.get("message") or
            "🤝 Thank you for your order. Reply if you need any further help.",
        )
        return f"sent={success}, failed={failed}"
    target_id = int(payload["target_id"])
    success, failed = await _send_many(bot, [target_id], payload["message"])
    return f"sent={success}, failed={failed}"


async def process_due_jobs(bot, now=None):
    now = now or datetime.now()
    results = []
    for job in get_due_scheduled_jobs(now):
        try:
            details = await _execute_job(bot, job)
            recurrence = job[5]
            next_time = _advance_time(
                datetime.fromisoformat(job[6]), recurrence
            )
            while next_time and next_time <= now:
                next_time = _advance_time(next_time, recurrence)
            update_scheduled_job_run(
                job[0],
                now.strftime("%Y-%m-%d %H:%M:%S"),
                next_time.strftime("%Y-%m-%d %H:%M:%S") if next_time else None,
                "active" if next_time else "completed",
            )
            results.append((job[0], "completed", details))
        except (KeyError, TypeError, ValueError, TelegramError) as exc:
            add_maintenance_run("scheduled_job", "failed", f"#{job[0]}: {exc}")
            results.append((job[0], "failed", str(exc)))
    return results


def cleanup_old_data(now=None):
    now = now or datetime.now()
    con = connect()
    removed = {}
    for table, date_column, days in (
        ("audit_logs", "created_at", 365),
        ("backup_logs", "created_at", 365),
        ("recent_searches", "created_at", 90),
        ("maintenance_runs", "created_at", 90),
    ):
        cur = con.execute(
            f"DELETE FROM {table} WHERE {date_column} < "
            "datetime('now', 'localtime', ?)",
            (f"-{days} days",),
        )
        removed[table] = cur.rowcount
    con.commit()
    con.close()
    removed["backups"] = len(prune_backups(get_backup_retention()))
    removed["temporary_files"] = 0
    roots = {Path(DB_PATH).resolve().parent, BACKUP_DIR.resolve()}
    cutoff = now.timestamp() - 86400
    for root in roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if (
                path.is_file()
                and path.suffix.lower() in {".tmp", ".temp"}
                and path.stat().st_mtime < cutoff
            ):
                path.unlink()
                removed["temporary_files"] += 1
    return removed


def run_maintenance_task(task):
    try:
        if task == "cleanup":
            details = json.dumps(cleanup_old_data(), sort_keys=True)
        elif task == "optimize":
            con = connect()
            con.execute("PRAGMA optimize")
            con.close()
            details = "PRAGMA optimize completed"
        elif task == "vacuum":
            con = connect()
            con.execute("VACUUM")
            con.close()
            details = "VACUUM completed"
        elif task == "analytics":
            data = get_analytics_data("day")
            details = f"analytics refreshed; orders={data['orders']}"
        elif task == "health":
            con = connect()
            result = con.execute("PRAGMA quick_check").fetchone()[0]
            con.close()
            if result != "ok":
                raise RuntimeError(result)
            details = "database quick_check=ok"
        else:
            raise ValueError("Unknown maintenance task")
        add_maintenance_run(task, "success", details)
        return True, details
    except (OSError, ValueError, RuntimeError, sqlite3.DatabaseError) as exc:
        add_maintenance_run(task, "failed", str(exc))
        return False, str(exc)


def run_daily_maintenance(now=None):
    now = now or datetime.now()
    last_text = get_setting("daily_maintenance_last", "")
    try:
        last_run = datetime.fromisoformat(last_text)
    except ValueError:
        last_run = None
    if last_run and now - last_run < timedelta(days=1):
        return []
    results = [(task, *run_maintenance_task(task)) for task in (
        "cleanup", "optimize", "analytics", "health"
    )]
    # VACUUM is deliberately daily too, as requested, after cleanup.
    results.append(("vacuum", *run_maintenance_task("vacuum")))
    set_setting("daily_maintenance_last", now.isoformat(timespec="seconds"))
    return results


async def task_scheduler(bot, interval=60):
    while True:
        try:
            run_due_auto_backup()
            await process_due_jobs(bot)
            run_daily_maintenance()
        except (OSError, RuntimeError, sqlite3.DatabaseError) as exc:
            add_maintenance_run("scheduler", "failed", str(exc))
        await asyncio.sleep(interval)


def _jobs_text(title, jobs):
    if not jobs:
        return f"{title}\n\nNo active schedules."
    lines = [title, ""]
    for job in jobs:
        lines.extend([
            f"#{job[0]} · {job[3]}",
            f"{job[5].replace('_', ' ').title()} · Next: {job[6]}",
            "",
        ])
    return "\n".join(lines).rstrip()


async def handle_scheduler_callback(query, context):
    data = query.data
    if data == "admin:scheduler":
        await query.edit_message_text("🕒 Scheduler & Auto Tasks", reply_markup=scheduler_menu())
        return
    if data == "admin:scheduler:announcements":
        jobs = list_scheduled_jobs(["announcement"])
        await query.edit_message_text(
            _jobs_text("📢 Scheduled Announcements", jobs),
            reply_markup=scheduled_announcements_menu(jobs),
        )
        return
    if data == "admin:scheduler:announcement_new":
        context.user_data["scheduler_mode"] = "announcement_message"
        await query.edit_message_text("📢 Send the announcement message.")
        return
    if data == "admin:scheduler:reminders":
        jobs = list_scheduled_jobs([
            "pending_payment", "pending_order", "customer_followup",
            "custom_reminder",
        ])
        await query.edit_message_text(
            _jobs_text("🔔 Reminder Manager", jobs),
            reply_markup=reminder_manager_menu(jobs),
        )
        return
    if data.startswith("admin:scheduler:reminder_new:"):
        reminder_type = data.rsplit(":", 1)[1]
        if reminder_type not in REMINDER_TYPES:
            return
        context.user_data["scheduler_mode"] = "reminder_schedule"
        context.user_data["scheduler_reminder_type"] = reminder_type
        await query.edit_message_text(
            f"🔔 {REMINDER_TYPES[reminder_type]}\n\n"
            "Send: YYYY-MM-DD HH:MM|daily\n"
            "Recurrence: one_time, daily, weekly, monthly"
        )
        return
    if data == "admin:scheduler:reminder_custom":
        context.user_data["scheduler_mode"] = "custom_reminder"
        await query.edit_message_text(
            "✍ Custom Reminder\n\n"
            "Send: Telegram ID|Message|YYYY-MM-DD HH:MM|recurrence"
        )
        return
    if data.startswith("admin:scheduler:cancel:"):
        _, _, _, raw_id, destination = data.split(":")
        cancelled = cancel_scheduled_job(int(raw_id))
        if destination == "announcements":
            jobs = list_scheduled_jobs(["announcement"])
            await query.edit_message_text(
                ("✅ Schedule cancelled.\n\n" if cancelled else "Schedule not active.\n\n")
                + _jobs_text("📢 Scheduled Announcements", jobs),
                reply_markup=scheduled_announcements_menu(jobs),
            )
        else:
            jobs = list_scheduled_jobs([
                "pending_payment", "pending_order", "customer_followup",
                "custom_reminder",
            ])
            await query.edit_message_text(
                ("✅ Schedule cancelled.\n\n" if cancelled else "Schedule not active.\n\n")
                + _jobs_text("🔔 Reminder Manager", jobs),
                reply_markup=reminder_manager_menu(jobs),
            )
        return
    if data == "admin:scheduler:maintenance":
        await query.edit_message_text("🧹 Maintenance", reply_markup=maintenance_menu())
        return
    if data == "admin:scheduler:maint:history":
        runs = get_maintenance_runs()
        text = "\n".join(
            f"{row[4]} · {row[1]} · {row[2]}\n{row[3]}" for row in runs
        ) or "No maintenance history."
        await query.edit_message_text(
            f"📜 Maintenance History\n\n{text}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Maintenance", callback_data="admin:scheduler:maintenance")
            ]]),
        )
        return
    if data.startswith("admin:scheduler:maint:"):
        task = data.rsplit(":", 1)[1]
        if task == "daily":
            results = [
                (name, *run_maintenance_task(name))
                for name in ("cleanup", "optimize", "vacuum", "analytics", "health")
            ]
            ok = all(result[1] for result in results)
            details = "\n".join(
                f"{'✅' if result[1] else '❌'} {result[0]}: {result[2]}"
                for result in results
            )
        else:
            ok, details = run_maintenance_task(task)
        await query.edit_message_text(
            f"{'✅' if ok else '❌'} Maintenance\n\n{details}",
            reply_markup=maintenance_menu(),
        )


async def handle_scheduler_message(update, context):
    mode = context.user_data.get("scheduler_mode")
    if not mode:
        return False
    text = (update.message.text or "").strip()
    admin_id = update.effective_user.id
    try:
        if mode == "announcement_message":
            if not text or len(text) > 3500:
                raise ValueError("Announcement must be 1–3500 characters.")
            context.user_data["scheduler_announcement"] = text
            context.user_data["scheduler_mode"] = "announcement_schedule"
            await update.message.reply_text(
                "Send: YYYY-MM-DD HH:MM|one_time\n"
                "Recurrence: one_time, daily, weekly, monthly"
            )
            return True
        if mode == "announcement_schedule":
            next_run, recurrence = _parse_schedule(text)
            message = context.user_data["scheduler_announcement"]
            job_id = create_scheduled_job(
                admin_id, "announcement", message[:80],
                {"message": message}, recurrence, next_run,
            )
            action = "Schedule Announcement"
            target = f"Job #{job_id}"
        elif mode == "reminder_schedule":
            next_run, recurrence = _parse_schedule(text)
            reminder_type = context.user_data["scheduler_reminder_type"]
            job_id = create_scheduled_job(
                admin_id, reminder_type, REMINDER_TYPES[reminder_type],
                {}, recurrence, next_run,
            )
            action = "Schedule Reminder"
            target = f"Job #{job_id}"
        elif mode == "custom_reminder":
            target_text, message, date_text, recurrence = [
                value.strip() for value in text.split("|", 3)
            ]
            target_id = int(target_text)
            if not message or recurrence not in RECURRENCES:
                raise ValueError("Invalid custom reminder")
            next_run = datetime.strptime(
                date_text, "%Y-%m-%d %H:%M"
            ).strftime("%Y-%m-%d %H:%M:%S")
            job_id = create_scheduled_job(
                admin_id, "custom_reminder", f"Custom reminder to {target_id}",
                {"target_id": target_id, "message": message},
                recurrence, next_run,
            )
            action = "Schedule Reminder"
            target = f"Job #{job_id}"
        else:
            return False
    except (KeyError, TypeError, ValueError) as exc:
        await update.message.reply_text(
            f"Invalid schedule: {exc}\nPlease follow the requested format."
        )
        return True
    add_audit_log(
        admin_id, admin_display_name(update.effective_user),
        action, target, f"next_run={next_run}; recurrence={recurrence}",
    )
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ Scheduled as Job #{job_id}.", reply_markup=scheduler_menu()
    )
    return True
