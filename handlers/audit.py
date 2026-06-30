import csv
import io
import math
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from database.db import get_audit_actions, get_audit_admins, get_audit_logs


PER_PAGE = 20


def admin_display_name(user):
    username = getattr(user, "username", "") or ""
    if username:
        return f"@{username}"
    full_name = getattr(user, "full_name", "") or ""
    if full_name:
        return full_name
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    return " ".join(part for part in (first, last) if part) or str(user.id)


def _state(context):
    return context.user_data.setdefault("audit_filters", {
        "period": "all", "admin_id": None, "action": None, "search": "",
    })


def _callback_page(page):
    return f"admin:audit:page:{page}"


def audit_logs_keyboard(page, total):
    pages = max(1, math.ceil(total / PER_PAGE))
    rows = [
        [
            InlineKeyboardButton("Today", callback_data="admin:audit:period:today"),
            InlineKeyboardButton("7 Days", callback_data="admin:audit:period:7d"),
            InlineKeyboardButton("30 Days", callback_data="admin:audit:period:30d"),
        ],
        [
            InlineKeyboardButton("👤 By Admin", callback_data="admin:audit:admins"),
            InlineKeyboardButton("⚙ By Action", callback_data="admin:audit:actions"),
        ],
        [
            InlineKeyboardButton("🔎 Search", callback_data="admin:audit:search"),
            InlineKeyboardButton("📤 Export CSV", callback_data="admin:audit:export"),
        ],
        [InlineKeyboardButton("♻ Clear Filters", callback_data="admin:audit:clear")],
    ]
    navigation = []
    if page > 1:
        navigation.append(InlineKeyboardButton("⬅", callback_data=_callback_page(page - 1)))
    navigation.append(InlineKeyboardButton(
        f"{page}/{pages}", callback_data="admin:audit:noop"
    ))
    if page < pages:
        navigation.append(InlineKeyboardButton("➡", callback_data=_callback_page(page + 1)))
    rows.append(navigation)
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def _format_logs(rows, page, total, state):
    lines = [f"📜 Audit Logs — {total} record(s)", ""]
    active = []
    if state["period"] != "all":
        active.append(state["period"])
    if state["admin_id"] is not None:
        active.append(f"admin {state['admin_id']}")
    if state["action"]:
        active.append(state["action"])
    if state["search"]:
        active.append(f'search "{state["search"]}"')
    if active:
        lines.extend(["Filters: " + " · ".join(active), ""])
    if not rows:
        lines.append("No audit logs found.")
    for row in rows:
        _, admin_id, admin_name, action, target, _, created_at = row
        lines.extend([
            created_at,
            f"Admin: {admin_name} ({admin_id})",
            f"Action: {action}",
            f"Target: {target or '—'}",
            "",
        ])
    lines.append(f"Page {page}/{max(1, math.ceil(total / PER_PAGE))}")
    return "\n".join(lines)


async def show_audit_logs(query, context, page=1):
    state = _state(context)
    rows, total = get_audit_logs(page=page, per_page=PER_PAGE, **state)
    await query.edit_message_text(
        _format_logs(rows, page, total, state),
        reply_markup=audit_logs_keyboard(page, total),
    )


def _selection_keyboard(options, kind):
    rows = [[InlineKeyboardButton(
        label, callback_data=f"admin:audit:{kind}:{value}"
    )] for value, label in options]
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:audit")])
    return InlineKeyboardMarkup(rows)


def export_audit_csv(state):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "id", "admin_id", "admin_name", "action", "target", "details", "created_at"
    ])
    page = 1
    while True:
        rows, total = get_audit_logs(page=page, per_page=100, **state)
        writer.writerows(rows)
        if page * 100 >= total:
            break
        page += 1
    return output.getvalue().encode("utf-8-sig")


async def handle_audit_callback(query, context):
    data = query.data
    state = _state(context)
    if data == "admin:audit":
        await show_audit_logs(query, context)
        return
    if data == "admin:audit:noop":
        return
    if data == "admin:audit:clear":
        context.user_data["audit_filters"] = {
            "period": "all", "admin_id": None, "action": None, "search": "",
        }
        await show_audit_logs(query, context)
        return
    if data.startswith("admin:audit:page:"):
        await show_audit_logs(query, context, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("admin:audit:period:"):
        state["period"] = data.rsplit(":", 1)[1]
        await show_audit_logs(query, context)
        return
    if data == "admin:audit:admins":
        options = [
            (str(admin_id), f"{name} ({admin_id}) — {count}")
            for admin_id, name, count in get_audit_admins()
        ]
        await query.edit_message_text(
            "👤 Filter Audit Logs by Admin",
            reply_markup=_selection_keyboard(options, "admin"),
        )
        return
    if data.startswith("admin:audit:admin:"):
        state["admin_id"] = int(data.rsplit(":", 1)[1])
        await show_audit_logs(query, context)
        return
    if data == "admin:audit:actions":
        options = [
            (str(index), f"{action} — {count}")
            for index, (action, count) in enumerate(get_audit_actions())
        ]
        context.user_data["audit_action_options"] = [
            action for action, _ in get_audit_actions()
        ]
        await query.edit_message_text(
            "⚙ Filter Audit Logs by Action",
            reply_markup=_selection_keyboard(options, "action"),
        )
        return
    if data.startswith("admin:audit:action:"):
        index = int(data.rsplit(":", 1)[1])
        options = context.user_data.get("audit_action_options", [])
        if 0 <= index < len(options):
            state["action"] = options[index]
        await show_audit_logs(query, context)
        return
    if data == "admin:audit:search":
        context.user_data["admin_mode"] = "audit_search"
        await query.edit_message_text(
            "🔎 Search Audit Logs\n\n"
            "Send an Order ID, Customer ID, Admin ID, or action.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Back", callback_data="admin:audit")
            ]]),
        )
        return
    if data == "admin:audit:export":
        payload = export_audit_csv(state)
        filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        await query.message.reply_document(
            document=InputFile(io.BytesIO(payload), filename=filename),
            filename=filename,
            caption="📤 Audit log export",
        )
        return


async def handle_audit_message(update, context):
    if context.user_data.get("admin_mode") != "audit_search":
        return False
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Please send a search value.")
        return True
    state = _state(context)
    state["search"] = text
    context.user_data.pop("admin_mode", None)
    rows, total = get_audit_logs(page=1, per_page=PER_PAGE, **state)
    await update.message.reply_text(
        _format_logs(rows, 1, total, state),
        reply_markup=audit_logs_keyboard(1, total),
    )
    return True
