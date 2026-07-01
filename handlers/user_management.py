import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import (
    add_audit_log,
    get_customer_orders,
    get_telegram_user,
    get_telegram_user_stats,
    is_admin_user,
    list_telegram_users,
    set_telegram_user_status,
)
from handlers.audit import admin_display_name


PER_PAGE = 20


def dashboard_text():
    total, active_today, new_today, blocked, buyers = get_telegram_user_stats()
    return (
        "👥 ការគ្រប់គ្រងអ្នកប្រើ\n\n"
        f"👥 អ្នកប្រើសរុប : {total}\n\n"
        f"🟢 កំពុងប្រើថ្ងៃនេះ : {active_today}\n\n"
        f"🆕 អ្នកប្រើថ្មីថ្ងៃនេះ : {new_today}\n\n"
        f"🚫 Blocked : {blocked}\n\n"
        f"💰 អ្នកធ្លាប់ទិញ : {buyers}"
    )


def dashboard_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 User List", callback_data="admin:users:list:1"
            ),
            InlineKeyboardButton(
                "🔍 Search User", callback_data="admin:users:search"
            ),
        ],
        [InlineKeyboardButton(
            "📊 Statistics", callback_data="admin:users:stats"
        )],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin:home")],
        [InlineKeyboardButton("❌ Cancel", callback_data="global:cancel")],
    ])


def user_list_text(rows, total, page, search=""):
    heading = "🔍 លទ្ធផលស្វែងរក" if search else "👥 បញ្ជីអ្នកប្រើ"
    lines = []
    for offset, row in enumerate(rows, start=(page - 1) * PER_PAGE + 1):
        display = f"@{row[1]}" if row[1] else (
            " ".join(value for value in row[2:4] if value)
            or str(row[0])
        )
        lines.append(f"{offset}. {display}")
    return (
        f"{heading}\n\n"
        f"{chr(10).join(lines) if lines else 'រកមិនឃើញអ្នកប្រើទេ។'}\n\n"
        f"សរុប: {total}"
    )


def user_list_keyboard(rows, total, page, search=""):
    pages = max(1, math.ceil(total / PER_PAGE))
    page = min(max(1, page), pages)
    prefix = "admin:users:search_results" if search else "admin:users:list"
    rows_markup = [[InlineKeyboardButton(
        f"@{row[1]}" if row[1] else (
            " ".join(value for value in row[2:4] if value) or str(row[0])
        ),
        callback_data=f"admin:users:view:{row[0]}:{page}",
    )] for row in rows]
    navigation = []
    if page > 1:
        navigation.append(InlineKeyboardButton(
            "◀️ Prev", callback_data=f"{prefix}:{page - 1}"
        ))
    navigation.append(InlineKeyboardButton(
        f"{page}/{pages}", callback_data="admin:users:noop"
    ))
    if page < pages:
        navigation.append(InlineKeyboardButton(
            "▶️ Next", callback_data=f"{prefix}:{page + 1}"
        ))
    rows_markup.append(navigation)
    rows_markup.extend([
        [InlineKeyboardButton(
            "⬅️ Back", callback_data="admin:users"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="global:cancel")],
    ])
    return InlineKeyboardMarkup(rows_markup)


def user_detail_text(user):
    username = f"@{user[1]}" if user[1] else "មិនមាន"
    name = " ".join(value for value in user[2:4] if value) or "មិនមាន"
    status = "🟢 Active" if user[10] == "active" else "🚫 Blocked"
    return (
        "👤 ព័ត៌មានអ្នកប្រើ\n\n"
        f"Telegram ID: {user[0]}\n"
        f"Username: {username}\n"
        f"Name: {name}\n"
        f"First Seen: {user[5]}\n"
        f"Last Seen: {user[6]}\n"
        f"Messages: {user[7]}\n"
        f"Orders: {user[8]}\n"
        f"Total Spent: ${user[9]:,.2f}\n"
        f"Status: {status}\n"
        f"Admin: {'Yes' if user[11] else 'No'}"
    )


def user_detail_keyboard(user, page=1):
    rows = []
    if not user[11]:
        if user[10] == "blocked":
            rows.append([InlineKeyboardButton(
                "✅ Unblock",
                callback_data=f"admin:users:unblock:{user[0]}:{page}",
            )])
        else:
            rows.append([InlineKeyboardButton(
                "🚫 Block",
                callback_data=f"admin:users:block:{user[0]}:{page}",
            )])
    rows.extend([
        [InlineKeyboardButton(
            "📜 Order History",
            callback_data=f"admin:users:orders:{user[0]}:{page}",
        )],
        [InlineKeyboardButton(
            "⬅️ Back", callback_data=f"admin:users:list:{page}"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="global:cancel")],
    ])
    return InlineKeyboardMarkup(rows)


def order_history_keyboard(orders, telegram_id, page):
    rows = [[InlineKeyboardButton(
        f"Order #{order[0]} · {order[5]}",
        callback_data=f"admin:order_view:{order[0]}",
    )] for order in orders]
    rows.extend([
        [InlineKeyboardButton(
            "⬅️ Back",
            callback_data=f"admin:users:view:{telegram_id}:{page}",
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="global:cancel")],
    ])
    return InlineKeyboardMarkup(rows)


async def handle_user_management_callback(query, context):
    if not is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ សម្រាប់ Admin ប៉ុណ្ណោះ។")
        return True
    data = query.data
    if data in {"admin:users", "admin:users:stats"}:
        context.user_data.pop("user_management_mode", None)
        await query.edit_message_text(
            dashboard_text(), reply_markup=dashboard_keyboard()
        )
        return True
    if data == "admin:users:noop":
        return True
    if data == "admin:users:search":
        context.user_data["user_management_mode"] = "search"
        await query.edit_message_text(
            "🔍 សូមផ្ញើ Username, Telegram ID ឬឈ្មោះអ្នកប្រើ។",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Back", callback_data="admin:users"
                )],
                [InlineKeyboardButton(
                    "❌ Cancel", callback_data="global:cancel"
                )],
            ]),
        )
        return True
    parts = data.split(":")
    if len(parts) == 4 and parts[2] in {"list", "search_results"}:
        page = max(1, int(parts[3]))
        search = (
            context.user_data.get("user_management_search", "")
            if parts[2] == "search_results" else ""
        )
        rows, total = list_telegram_users(page, PER_PAGE, search)
        await query.edit_message_text(
            user_list_text(rows, total, page, search),
            reply_markup=user_list_keyboard(rows, total, page, search),
        )
        return True
    if len(parts) != 5 or parts[:2] != ["admin", "users"]:
        return False
    action = parts[2]
    try:
        telegram_id = int(parts[3])
        page = max(1, int(parts[4]))
    except (TypeError, ValueError):
        await query.message.reply_text("❌ ទិន្នន័យអ្នកប្រើមិនត្រឹមត្រូវ។")
        return True
    user = get_telegram_user(telegram_id)
    if not user:
        await query.message.reply_text("❌ រកមិនឃើញអ្នកប្រើទេ។")
        return True
    if action in {"block", "unblock"}:
        status = "blocked" if action == "block" else "active"
        changed = set_telegram_user_status(telegram_id, status)
        if not changed and status == "blocked":
            await query.message.reply_text(
                "❌ Admin មិនអាចត្រូវបាន Block ទេ។"
            )
        else:
            add_audit_log(
                query.from_user.id,
                admin_display_name(query.from_user),
                "Block User" if status == "blocked" else "Unblock User",
                f"Telegram User {telegram_id}",
            )
        user = get_telegram_user(telegram_id)
        await query.edit_message_text(
            user_detail_text(user),
            reply_markup=user_detail_keyboard(user, page),
        )
        return True
    if action == "view":
        await query.edit_message_text(
            user_detail_text(user),
            reply_markup=user_detail_keyboard(user, page),
        )
        return True
    if action == "orders":
        orders = get_customer_orders(telegram_id, limit=100)
        await query.edit_message_text(
            f"📜 ប្រវត្តិការកម្មង់\n\nសរុប: {len(orders)}",
            reply_markup=order_history_keyboard(orders, telegram_id, page),
        )
        return True
    return False


async def handle_user_management_message(update, context):
    if context.user_data.get("user_management_mode") != "search":
        return False
    if not is_admin_user(update.effective_user.id):
        context.user_data.pop("user_management_mode", None)
        await update.message.reply_text("⛔ សម្រាប់ Admin ប៉ុណ្ណោះ។")
        return True
    search = (update.message.text or "").strip()
    if not search:
        await update.message.reply_text(
            "សូមផ្ញើ Username, Telegram ID ឬឈ្មោះអ្នកប្រើ។"
        )
        return True
    context.user_data.pop("user_management_mode", None)
    context.user_data["user_management_search"] = search
    rows, total = list_telegram_users(1, PER_PAGE, search)
    await update.message.reply_text(
        user_list_text(rows, total, 1, search),
        reply_markup=user_list_keyboard(rows, total, 1, search),
    )
    return True


__all__ = [
    "PER_PAGE",
    "dashboard_keyboard",
    "dashboard_text",
    "handle_user_management_callback",
    "handle_user_management_message",
    "user_detail_keyboard",
    "user_detail_text",
    "user_list_keyboard",
    "user_list_text",
]
