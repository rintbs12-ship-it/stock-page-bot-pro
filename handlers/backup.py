import io
import csv
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from config import DB_PATH
from database.db import (
    add_audit_log,
    add_backup_log,
    connect,
    get_backup_logs,
    get_all_settings,
    get_setting,
    init_db,
    is_admin_user,
    set_setting,
)
from handlers.audit import admin_display_name
from keyboards.buttons import with_cancel


BACKUP_DIR = Path(DB_PATH).resolve().parent / "backups"
BACKUP_NAME_PATTERN = re.compile(r"^backup_\d{8}_\d{6}(?:_\d+)?\.zip$")
AUTO_BACKUP_INTERVALS = {
    "off": None,
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}


def get_backup_retention():
    try:
        return max(1, min(100, int(get_setting("auto_backup_keep", "10"))))
    except (TypeError, ValueError):
        return 10


def backup_manager_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 Create Backup", callback_data="admin:backup_create")],
        [InlineKeyboardButton("📂 List Backups", callback_data="admin:backup_history")],
        [InlineKeyboardButton("♻ Restore Backup", callback_data="admin:backup_restore")],
        [InlineKeyboardButton("🗑 Delete Backup", callback_data="admin:backup_delete_menu")],
        [InlineKeyboardButton("📤 Export Database", callback_data="admin:backup_export")],
        [InlineKeyboardButton("📥 Import Database", callback_data="admin:backup_import")],
        [InlineKeyboardButton("📜 Backup Logs", callback_data="admin:backup_logs")],
        [InlineKeyboardButton("⚙ Auto Backup", callback_data="admin:backup_auto")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def auto_backup_menu(current):
    def label(value, text):
        return f"✅ {text}" if current == value else text

    keep = get_backup_retention()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label("off", "OFF"), callback_data="admin:backup_auto_set:off")],
        [InlineKeyboardButton(label("daily", "Every Day"), callback_data="admin:backup_auto_set:daily")],
        [InlineKeyboardButton(label("weekly", "Every Week"), callback_data="admin:backup_auto_set:weekly")],
        [InlineKeyboardButton(label("monthly", "Every Month"), callback_data="admin:backup_auto_set:monthly")],
        [InlineKeyboardButton(
            f"Keep Latest: {keep}",
            callback_data="admin:backup_retention",
        )],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:backup")],
    ])


def retention_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"Keep {amount}",
            callback_data=f"admin:backup_retention_set:{amount}",
        ) for amount in (3, 5, 10)],
        [InlineKeyboardButton(
            "Keep 20", callback_data="admin:backup_retention_set:20"
        )],
        [InlineKeyboardButton("⬅ Auto Backup", callback_data="admin:backup_auto")],
    ])


def export_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📤 database.db", callback_data="admin:backup_export_db"
        )],
        [InlineKeyboardButton(
            "📦 Database ZIP", callback_data="admin:backup_export_zip"
        )],
        [InlineKeyboardButton(
            "📊 All Tables CSV", callback_data="admin:backup_export_csv"
        )],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:backup")],
    ])


def restore_confirmation_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES", callback_data="admin:backup_restore_confirm")],
        [InlineKeyboardButton("❌ NO", callback_data="admin:backup_restore_cancel")],
    ])


def _snapshot_database(destination):
    source = sqlite3.connect(DB_PATH)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def export_database_bytes():
    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / "database.db"
        _snapshot_database(snapshot)
        return snapshot.read_bytes()


def create_backup(now=None, admin_id=0, admin_name=""):
    now = now or datetime.now()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    base_name = f"backup_{now.strftime('%Y%m%d_%H%M%S')}"
    destination = BACKUP_DIR / f"{base_name}.zip"
    suffix = 1
    while destination.exists():
        destination = BACKUP_DIR / f"{base_name}_{suffix}.zip"
        suffix += 1

    database_bytes = export_database_bytes()
    settings = get_all_settings()
    info = {
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "database": "database.db",
        "settings": settings,
        "format_version": 1,
    }
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("database.db", database_bytes)
        archive.writestr(
            "settings.json",
            json.dumps(settings, ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "backup_info.json",
            json.dumps(info, ensure_ascii=False, indent=2),
        )
    add_backup_log("created", destination.name, admin_id)
    if admin_id:
        add_audit_log(
            admin_id, admin_name or admin_id, "Create Backup", destination.name
        )
    return destination


def list_backups(limit=10):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = [
        path for path in BACKUP_DIR.iterdir()
        if path.is_file() and BACKUP_NAME_PATTERN.fullmatch(path.name)
    ]
    backups.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return backups[:limit]


def get_backup_path(filename):
    if not BACKUP_NAME_PATTERN.fullmatch(filename):
        return None
    path = (BACKUP_DIR / filename).resolve()
    if path.parent != BACKUP_DIR.resolve() or not path.is_file():
        return None
    return path


def delete_backup(filename, admin_id=0):
    path = get_backup_path(filename)
    if not path:
        return False
    path.unlink()
    add_backup_log("delete", filename, admin_id)
    return True


def prune_backups(keep):
    keep = max(1, int(keep))
    backups = list_backups(limit=10000)
    deleted = []
    for path in backups[keep:]:
        path.unlink()
        deleted.append(path.name)
    return deleted


def export_database_zip_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("database.db", export_database_bytes())
    return output.getvalue()


def export_database_csv_bytes():
    output = io.BytesIO()
    con = connect()
    try:
        tables = [
            row[0] for row in con.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """).fetchall()
        ]
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for table in tables:
                cursor = con.execute(f'SELECT * FROM "{table}"')
                text = io.StringIO()
                writer = csv.writer(text, lineterminator="\n")
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor.fetchall())
                archive.writestr(f"{table}.csv", text.getvalue().encode("utf-8"))
    finally:
        con.close()
    return output.getvalue()


def extract_database_bytes(filename, payload):
    lower_name = filename.lower()
    if lower_name == "database.db" or lower_name.endswith(".db"):
        database_bytes = bytes(payload)
    elif lower_name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            database_names = [
                name for name in archive.namelist()
                if Path(name).name.lower() == "database.db"
            ]
            if not database_names:
                raise ValueError("Backup ZIP does not contain database.db")
            database_bytes = archive.read(database_names[0])
    else:
        raise ValueError("Upload database.db or a backup ZIP")
    validate_database_bytes(database_bytes)
    return database_bytes


def validate_database_bytes(database_bytes):
    if not database_bytes.startswith(b"SQLite format 3\x00"):
        raise ValueError("The uploaded file is not a valid SQLite database")
    with tempfile.TemporaryDirectory() as folder:
        candidate = Path(folder) / "candidate.db"
        candidate.write_bytes(database_bytes)
        con = sqlite3.connect(candidate)
        try:
            result = con.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            con.close()
        if result != "ok" or "stocks" not in tables or "stock_photos" not in tables:
            raise ValueError("The uploaded database failed validation")


def restore_database_bytes(
    database_bytes, admin_id=0, action="restore", filename="", admin_name=""
):
    validate_database_bytes(database_bytes)
    create_backup()
    database_path = Path(DB_PATH).resolve()
    temporary_path = database_path.with_suffix(".restore.tmp")
    temporary_path.write_bytes(database_bytes)
    os.replace(temporary_path, database_path)
    init_db()
    add_backup_log(action, filename, admin_id)
    if admin_id:
        add_audit_log(
            admin_id, admin_name or admin_id, "Restore Backup",
            filename or "Uploaded database", f"source={action}",
        )


def format_backup_history(backups):
    if not backups:
        return "📋 Backup History\n\nNo backups found."
    lines = ["📋 Backup History", ""]
    for index, path in enumerate(backups, start=1):
        stat = path.stat()
        date = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size = stat.st_size / 1024
        lines.extend([
            f"{index}. {path.name}",
            f"Date: {date}",
            f"Size: {size:.1f} KB",
            "",
        ])
    return "\n".join(lines).rstrip()


def backup_history_menu(backups, delete_only=False):
    rows = []
    for path in backups:
        if delete_only:
            rows.append([InlineKeyboardButton(
                f"🗑 {path.name}",
                callback_data=f"admin:backup_delete_ask:{path.name}",
            )])
        else:
            rows.append([
                InlineKeyboardButton(
                    f"📥 {path.name}",
                    callback_data=f"admin:backup_download:{path.name}",
                ),
                InlineKeyboardButton(
                    "🗑",
                    callback_data=f"admin:backup_delete_ask:{path.name}",
                ),
            ])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:backup")])
    return InlineKeyboardMarkup(rows)


def backup_restore_menu(backups):
    rows = [[InlineKeyboardButton(
        f"♻ {path.name}",
        callback_data=f"admin:backup_restore_ask:{path.name}",
    )] for path in backups]
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:backup")])
    return InlineKeyboardMarkup(rows)


def backup_restore_confirmation(filename):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ YES",
            callback_data=f"admin:backup_restore_file:{filename}",
        )],
        [InlineKeyboardButton("❌ NO", callback_data="admin:backup")],
    ])


def format_backup_logs(logs):
    if not logs:
        return "📜 Backup Logs\n\nNo backup activity."
    lines = ["📜 Backup Logs", ""]
    for row in logs:
        lines.append(
            f"#{row[0]} · {row[1].title()}\n"
            f"File: {row[2] or '-'}\n"
            f"Admin: {row[4]}\n"
            f"Time: {row[5]}"
        )
    return "\n\n".join(lines)


def backup_delete_confirmation(filename):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Delete Backup",
            callback_data=f"admin:backup_delete_confirm:{filename}",
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin:backup_history")],
    ])


def run_due_auto_backup(now=None):
    now = now or datetime.now()
    schedule = get_setting("auto_backup_schedule", "off")
    interval = AUTO_BACKUP_INTERVALS.get(schedule)
    if interval is None:
        return None
    last_text = get_setting("auto_backup_last", "")
    try:
        last_run = datetime.fromisoformat(last_text)
    except ValueError:
        last_run = None
    if last_run and now - last_run < interval:
        return None
    backup = create_backup(now)
    prune_backups(get_backup_retention())
    set_setting("auto_backup_last", now.isoformat(timespec="seconds"))
    return backup


async def handle_backup_callback(query, context):
    data = query.data

    if not is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ Admin only")
        return

    if data == "admin:backup":
        await query.edit_message_text(
            "💾 Backup Manager",
            reply_markup=backup_manager_menu(),
        )
        return

    if data == "admin:backup_create":
        backup = create_backup(
            admin_id=query.from_user.id,
            admin_name=admin_display_name(query.from_user),
        )
        with backup.open("rb") as document:
            await query.message.reply_document(
                document=document,
                filename=backup.name,
                caption="✅ Backup created.",
            )
        return

    if data == "admin:backup_export":
        await query.edit_message_text(
            "📤 Export Database",
            reply_markup=export_menu(),
        )
        return

    if data == "admin:backup_export_db":
        await query.message.reply_document(
            document=InputFile(export_database_bytes(), filename="database.db"),
            caption="📥 SQLite Database",
        )
        return

    if data == "admin:backup_export_zip":
        await query.message.reply_document(
            document=InputFile(
                export_database_zip_bytes(), filename="database_export.zip"
            ),
            caption="📦 Database ZIP",
        )
        return

    if data == "admin:backup_export_csv":
        await query.message.reply_document(
            document=InputFile(
                export_database_csv_bytes(), filename="database_csv.zip"
            ),
            caption="📊 Database CSV Export",
        )
        return

    if data == "admin:backup_restore":
        backups = list_backups()
        await query.edit_message_text(
            "♻ Select a backup to restore:",
            reply_markup=backup_restore_menu(backups),
        )
        return

    if data.startswith("admin:backup_restore_ask:"):
        filename = data.split(":", 2)[2]
        if not get_backup_path(filename):
            await query.message.reply_text("Backup not found.")
            return
        await query.edit_message_text(
            f"⚠ Restore this backup?\n\n{filename}",
            reply_markup=backup_restore_confirmation(filename),
        )
        return

    if data.startswith("admin:backup_restore_file:"):
        filename = data.split(":", 2)[2]
        path = get_backup_path(filename)
        if not path:
            await query.message.reply_text("Backup not found.")
            return
        try:
            database_bytes = extract_database_bytes(
                path.name, path.read_bytes()
            )
            restore_database_bytes(
                database_bytes,
                admin_id=query.from_user.id,
                action="restore",
                filename=filename,
                admin_name=admin_display_name(query.from_user),
            )
        except (ValueError, zipfile.BadZipFile, sqlite3.DatabaseError) as exc:
            await query.message.reply_text(f"❌ Restore failed: {exc}")
            return
        await query.edit_message_text(
            "✅ Restore completed.",
            reply_markup=backup_manager_menu(),
        )
        return

    if data == "admin:backup_import":
        context.user_data.clear()
        context.user_data["admin_mode"] = "import_database"
        await query.edit_message_text(
            "📥 Upload database.db or a backup ZIP.\n"
            "The current database will not change until you confirm."
        )
        return

    if data == "admin:backup_restore_cancel":
        context.user_data.clear()
        await query.edit_message_text(
            "Restore cancelled.\n\n💾 Backup Manager",
            reply_markup=backup_manager_menu(),
        )
        return

    if data == "admin:backup_restore_confirm":
        payload = context.user_data.get("restore_payload")
        if not payload:
            await query.edit_message_text(
                "Restore file expired. Upload it again.",
                reply_markup=backup_manager_menu(),
            )
            return
        source = context.user_data.get("restore_source", "import")
        filename = context.user_data.get("restore_filename", "")
        restore_database_bytes(
            payload,
            admin_id=query.from_user.id,
            action=source,
            filename=filename,
            admin_name=admin_display_name(query.from_user),
        )
        context.user_data.clear()
        await query.edit_message_text(
            "✅ Restore completed.",
            reply_markup=backup_manager_menu(),
        )
        return

    if data in {"admin:backup_history", "admin:backup_delete_menu"}:
        backups = list_backups()
        await query.edit_message_text(
            format_backup_history(backups),
            reply_markup=backup_history_menu(
                backups,
                delete_only=data == "admin:backup_delete_menu",
            ),
        )
        return

    if data == "admin:backup_logs":
        await query.edit_message_text(
            format_backup_logs(get_backup_logs()),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Back", callback_data="admin:backup")
            ]]),
        )
        return

    if data.startswith("admin:backup_download:"):
        filename = data.split(":", 2)[2]
        path = get_backup_path(filename)
        if not path:
            await query.message.reply_text("Backup not found.")
            return
        with path.open("rb") as document:
            await query.message.reply_document(document=document, filename=path.name)
        return

    if data.startswith("admin:backup_delete_ask:"):
        filename = data.split(":", 2)[2]
        if not get_backup_path(filename):
            await query.edit_message_text(
                "Backup not found.",
                reply_markup=backup_manager_menu(),
            )
            return
        await query.edit_message_text(
            f"⚠ Delete backup?\n\n{filename}",
            reply_markup=backup_delete_confirmation(filename),
        )
        return

    if data.startswith("admin:backup_delete_confirm:"):
        filename = data.split(":", 2)[2]
        deleted = delete_backup(filename, query.from_user.id)
        backups = list_backups()
        await query.edit_message_text(
            ("✅ Backup deleted.\n\n" if deleted else "Backup not found.\n\n")
            + format_backup_history(backups),
            reply_markup=backup_history_menu(backups),
        )
        return

    if data == "admin:backup_auto":
        schedule = get_setting("auto_backup_schedule", "off")
        await query.edit_message_text(
            f"⚙ Auto Backup\n\nCurrent: {schedule.title()}",
            reply_markup=auto_backup_menu(schedule),
        )
        return

    if data == "admin:backup_retention":
        await query.edit_message_text(
            "⚙ Keep latest backups:",
            reply_markup=retention_menu(),
        )
        return

    if data.startswith("admin:backup_retention_set:"):
        try:
            keep = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        if keep not in {3, 5, 10, 20}:
            return
        set_setting("auto_backup_keep", keep)
        prune_backups(keep)
        await query.edit_message_text(
            f"✅ Keep latest {keep} backups.",
            reply_markup=auto_backup_menu(
                get_setting("auto_backup_schedule", "off")
            ),
        )
        return

    if data.startswith("admin:backup_auto_set:"):
        schedule = data.rsplit(":", 1)[1]
        if schedule not in AUTO_BACKUP_INTERVALS:
            return
        set_setting("auto_backup_schedule", schedule)
        if schedule == "off":
            set_setting("auto_backup_last", "")
        await query.edit_message_text(
            f"✅ Auto Backup: {schedule.title()}",
            reply_markup=auto_backup_menu(schedule),
        )


async def handle_restore_document(update, context):
    mode = context.user_data.get("admin_mode")
    if mode not in {"restore_database", "import_database"}:
        return False
    document = update.message.document
    try:
        telegram_file = await document.get_file()
        payload = bytes(await telegram_file.download_as_bytearray())
        database_bytes = extract_database_bytes(document.file_name or "", payload)
    except (ValueError, zipfile.BadZipFile, sqlite3.DatabaseError) as exc:
        await update.message.reply_text(f"❌ Restore file rejected: {exc}")
        return True
    context.user_data["restore_payload"] = database_bytes
    context.user_data["restore_filename"] = document.file_name
    context.user_data["restore_source"] = (
        "import" if mode == "import_database" else "restore"
    )
    await update.message.reply_text(
        "⚠ Restore database?",
        reply_markup=restore_confirmation_menu(),
    )
    return True


for _navigation_name in (
    "backup_manager_menu", "auto_backup_menu", "retention_menu",
    "export_menu", "restore_confirmation_menu", "backup_history_menu",
    "backup_restore_menu", "backup_restore_confirmation",
    "backup_delete_confirmation",
):
    globals()[_navigation_name] = with_cancel(globals()[_navigation_name])
