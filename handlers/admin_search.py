import csv
import io
import json
import math
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from database.db import (
    add_recent_search,
    advanced_admin_search,
    get_recent_searches,
    get_saved_filters,
    global_admin_search,
    save_search_filter,
)


PER_PAGE = 10


def search_home_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Global Search", callback_data="admin:search:global")],
        [
            InlineKeyboardButton("📦 Stock Search", callback_data="admin:search:type:stock"),
            InlineKeyboardButton("👥 Customer Search", callback_data="admin:search:type:customer"),
        ],
        [InlineKeyboardButton("🧾 Order Search", callback_data="admin:search:type:order")],
        [InlineKeyboardButton("🧠 Smart Filters", callback_data="admin:search:smart")],
        [
            InlineKeyboardButton("⭐ Saved Filters", callback_data="admin:search:saved"),
            InlineKeyboardButton("🕘 Recent Searches", callback_data="admin:search:recent"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def _state(context):
    return context.user_data.setdefault("admin_search", {
        "type": "", "filters": {}, "global_query": "", "global_rows": [],
    })


def _filter_summary(state):
    filters = state.get("filters", {})
    if not filters:
        return "No filters selected."
    return "\n".join(
        f"• {key.replace('_', ' ').title()}: {value}"
        for key, value in filters.items()
    )


def stock_filter_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔤 Keyword", callback_data="admin:search:input:keyword"),
            InlineKeyboardButton("💵 Price Range", callback_data="admin:search:input:price"),
        ],
        [
            InlineKeyboardButton("⭐ Quality", callback_data="admin:search:input:quality"),
            InlineKeyboardButton("🌍 Country", callback_data="admin:search:input:country"),
        ],
        [
            InlineKeyboardButton("🏷 Category", callback_data="admin:search:input:category"),
            InlineKeyboardButton("📌 Status", callback_data="admin:search:stock_status"),
        ],
        [InlineKeyboardButton(
            "📂 Page Type", callback_data="admin:search:input:page_type"
        )],
        [InlineKeyboardButton("🔎 Search", callback_data="admin:search:run")],
        [InlineKeyboardButton("♻ Clear", callback_data="admin:search:clear")],
        [InlineKeyboardButton("⬅ Search Home", callback_data="admin:search")],
    ])


def customer_filter_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Name", callback_data="admin:search:input:name"),
            InlineKeyboardButton("@ Username", callback_data="admin:search:input:username"),
        ],
        [InlineKeyboardButton("📞 Phone", callback_data="admin:search:input:phone")],
        [
            InlineKeyboardButton("📦 Total Orders", callback_data="admin:search:input:orders_min"),
            InlineKeyboardButton("💰 Total Spending", callback_data="admin:search:input:spending_min"),
        ],
        [InlineKeyboardButton("🔎 Search", callback_data="admin:search:run")],
        [InlineKeyboardButton("♻ Clear", callback_data="admin:search:clear")],
        [InlineKeyboardButton("⬅ Search Home", callback_data="admin:search")],
    ])


def order_filter_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏳ Pending", callback_data="admin:search:order_status:pending"),
            InlineKeyboardButton("💳 Paid", callback_data="admin:search:order_status:paid"),
        ],
        [
            InlineKeyboardButton("✅ Completed", callback_data="admin:search:order_status:completed"),
            InlineKeyboardButton("❌ Cancelled", callback_data="admin:search:order_status:cancelled"),
        ],
        [InlineKeyboardButton("📅 Date Range", callback_data="admin:search:input:date_range")],
        [InlineKeyboardButton("🕘 Recent Orders", callback_data="admin:search:recent_orders")],
        [InlineKeyboardButton("🔎 All Orders", callback_data="admin:search:run")],
        [InlineKeyboardButton("♻ Clear", callback_data="admin:search:clear")],
        [InlineKeyboardButton("⬅ Search Home", callback_data="admin:search")],
    ])


def smart_filter_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕘 Recent Orders", callback_data="admin:search:smart_run:recent_orders")],
        [InlineKeyboardButton("💎 VIP Customers", callback_data="admin:search:smart_run:vip")],
        [InlineKeyboardButton("💰 High Value Customers", callback_data="admin:search:smart_run:high_value")],
        [InlineKeyboardButton("🟢 Recently Active", callback_data="admin:search:smart_run:recent_active")],
        [InlineKeyboardButton("💤 Inactive Customers", callback_data="admin:search:smart_run:inactive")],
        [InlineKeyboardButton("⬅ Search Home", callback_data="admin:search")],
    ])


def _type_menu(search_type):
    return {
        "stock": stock_filter_menu,
        "customer": customer_filter_menu,
        "order": order_filter_menu,
    }[search_type]()


def _format_row(search_type, columns, row):
    item = dict(zip(columns, row))
    if search_type == "stock":
        return (
            f"📦 Stock #{item['id']} · {item['followers']}K\n"
            f"📂 {item['page_type'] or 'Not set'} · {item['country']} · "
            f"{item['price']} · {item['quality']} · {item['status']}"
        )
    if search_type == "customer":
        name = " ".join(
            part for part in (item["first_name"], item["last_name"]) if part
        ) or item["username"] or str(item["telegram_id"])
        vip = " · VIP" if item["is_vip"] else ""
        return (
            f"👤 {name} · {item['telegram_id']}{vip}\n"
            f"@{item['username'] or '—'} · Orders {item['total_orders']} · "
            f"Spent ${item['total_spent']:.2f}"
        )
    return (
        f"🧾 Order #{item['order_id']} · {item['status']}\n"
        f"Customer {item['customer_id']} · Stock #{item['stock_id']} · {item['price']}"
    )


def _results_keyboard(page, total):
    pages = max(1, math.ceil(total / PER_PAGE))
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅ Previous", callback_data=f"admin:search:page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="admin:search:noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next ➡", callback_data=f"admin:search:page:{page + 1}"))
    return InlineKeyboardMarkup([
        nav,
        [
            InlineKeyboardButton("📤 Export CSV", callback_data="admin:search:export"),
            InlineKeyboardButton("⭐ Save Filter", callback_data="admin:search:save"),
        ],
        [InlineKeyboardButton("⬅ Filters", callback_data="admin:search:back_filters")],
        [InlineKeyboardButton("🏠 Search Home", callback_data="admin:search")],
    ])


async def _show_type_filters(query, state):
    await query.edit_message_text(
        f"🔎 {state['type'].title()} Search\n\n{_filter_summary(state)}",
        reply_markup=_type_menu(state["type"]),
    )


async def show_results(query, context, page=1):
    state = _state(context)
    search_type = state["type"]
    if search_type == "global":
        rows = state.get("global_rows", [])
        total = len(rows)
        selected = rows[(page - 1) * PER_PAGE:page * PER_PAGE]
        body = "\n\n".join(
            f"{kind}: {title}\n{subtitle}" for kind, _, title, subtitle in selected
        )
    else:
        columns, selected, total = advanced_admin_search(
            search_type, state.get("filters"), page, PER_PAGE
        )
        body = "\n\n".join(
            _format_row(search_type, columns, row) for row in selected
        )
    await query.edit_message_text(
        f"🔎 Search Results — {total}\n\n{body or 'No results found.'}",
        reply_markup=_results_keyboard(page, total),
    )


def export_search_csv(state):
    search_type = state["type"]
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    if search_type == "global":
        writer.writerow(["type", "id", "title", "details"])
        writer.writerows(state.get("global_rows", []))
    else:
        page = 1
        wrote_header = False
        while True:
            columns, rows, total = advanced_admin_search(
                search_type, state.get("filters"), page, 100
            )
            if not wrote_header:
                writer.writerow(columns)
                wrote_header = True
            writer.writerows(rows)
            if page * 100 >= total:
                break
            page += 1
    return output.getvalue().encode("utf-8-sig")


def _list_keyboard(records, kind):
    rows = []
    for record in records:
        record_id, name, search_type, filters, created_at = record
        label = name if kind == "saved" else (
            f"{search_type.title()}: {name or json.dumps(filters, ensure_ascii=False)}"
        )
        rows.append([InlineKeyboardButton(
            label[:50], callback_data=f"admin:search:load:{kind}:{record_id}"
        )])
    rows.append([InlineKeyboardButton("⬅ Search Home", callback_data="admin:search")])
    return InlineKeyboardMarkup(rows)


async def handle_admin_search_callback(query, context):
    data = query.data
    state = _state(context)
    admin_id = query.from_user.id
    if data == "admin:search":
        context.user_data.pop("admin_search_mode", None)
        await query.edit_message_text("🔎 Advanced Search & Smart Filter", reply_markup=search_home_menu())
        return
    if data == "admin:search:noop":
        return
    if data == "admin:search:global":
        context.user_data["admin_search_mode"] = "global"
        await query.edit_message_text(
            "🌐 Global Search\n\nSend a Stock ID, Customer ID, Telegram User ID, "
            "Order ID, or customer name."
        )
        return
    if data.startswith("admin:search:type:"):
        state.clear()
        state.update({"type": data.rsplit(":", 1)[1], "filters": {}})
        await _show_type_filters(query, state)
        return
    if data == "admin:search:smart":
        await query.edit_message_text("🧠 Smart Filters", reply_markup=smart_filter_menu())
        return
    if data.startswith("admin:search:smart_run:"):
        smart = data.rsplit(":", 1)[1]
        if smart == "recent_orders":
            state.clear()
            state.update({"type": "order", "filters": {"recent": True}})
        else:
            state.clear()
            state.update({"type": "customer", "filters": {"smart": smart}})
        add_recent_search(admin_id, state["type"], filters=state["filters"])
        await show_results(query, context)
        return
    if data.startswith("admin:search:input:"):
        field = data.rsplit(":", 1)[1]
        context.user_data["admin_search_mode"] = field
        examples = {
            "price": "Send minimum and maximum price, for example: 20-100",
            "date_range": "Send dates as YYYY-MM-DD to YYYY-MM-DD",
            "orders_min": "Send minimum total orders.",
            "spending_min": "Send minimum total spending.",
        }
        await query.edit_message_text(examples.get(field, f"Send the {field.replace('_', ' ')}."))
        return
    if data == "admin:search:stock_status":
        await query.edit_message_text("Choose stock status:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(value.title(), callback_data=f"admin:search:set_status:{value}")]
            for value in ("available", "reserved", "sold")
        ] + [[InlineKeyboardButton("⬅ Filters", callback_data="admin:search:back_filters")]]))
        return
    if data.startswith("admin:search:set_status:"):
        state["filters"]["status"] = data.rsplit(":", 1)[1]
        await _show_type_filters(query, state)
        return
    if data.startswith("admin:search:order_status:"):
        state["filters"]["status"] = data.rsplit(":", 1)[1]
        add_recent_search(admin_id, "order", filters=state["filters"])
        await show_results(query, context)
        return
    if data == "admin:search:recent_orders":
        state["filters"] = {"recent": True}
        add_recent_search(admin_id, "order", filters=state["filters"])
        await show_results(query, context)
        return
    if data == "admin:search:clear":
        state["filters"] = {}
        await _show_type_filters(query, state)
        return
    if data == "admin:search:run":
        add_recent_search(admin_id, state["type"], filters=state["filters"])
        await show_results(query, context)
        return
    if data.startswith("admin:search:page:"):
        await show_results(query, context, int(data.rsplit(":", 1)[1]))
        return
    if data == "admin:search:back_filters":
        if state.get("type") == "global":
            await query.edit_message_text("🔎 Advanced Search & Smart Filter", reply_markup=search_home_menu())
        else:
            await _show_type_filters(query, state)
        return
    if data == "admin:search:export":
        filename = f"{state['type']}_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        await query.message.reply_document(
            document=InputFile(io.BytesIO(export_search_csv(state)), filename=filename),
            filename=filename,
            caption="📤 Search results export",
        )
        return
    if data == "admin:search:save":
        if state.get("type") == "global":
            await query.answer("Global searches are stored in Recent Searches.", show_alert=True)
            return
        context.user_data["admin_search_mode"] = "save_name"
        await query.edit_message_text("⭐ Send a name for this filter.")
        return
    if data == "admin:search:saved":
        records = get_saved_filters(admin_id)
        context.user_data["admin_search_saved"] = {row[0]: row for row in records}
        await query.edit_message_text(
            "⭐ Saved Filters" if records else "⭐ Saved Filters\n\nNo saved filters.",
            reply_markup=_list_keyboard(records, "saved"),
        )
        return
    if data == "admin:search:recent":
        recent = get_recent_searches(admin_id)
        records = [(row[0], row[2], row[1], row[3], row[4]) for row in recent]
        context.user_data["admin_search_recent"] = {row[0]: row for row in records}
        await query.edit_message_text(
            "🕘 Recent Searches" if records else "🕘 Recent Searches\n\nNo recent searches.",
            reply_markup=_list_keyboard(records, "recent"),
        )
        return
    if data.startswith("admin:search:load:"):
        _, _, _, kind, raw_id = data.split(":")
        record = context.user_data.get(f"admin_search_{kind}", {}).get(int(raw_id))
        if not record:
            await query.answer("Search record expired. Open the list again.", show_alert=True)
            return
        _, name, search_type, filters, _ = record
        state.clear()
        state.update({"type": search_type, "filters": filters})
        if search_type == "global":
            state["global_query"] = name
            state["global_rows"] = global_admin_search(name)
        await show_results(query, context)


async def handle_admin_search_message(update, context):
    mode = context.user_data.get("admin_search_mode")
    if not mode:
        return False
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Please send a value.")
        return True
    state = _state(context)
    try:
        if mode == "global":
            state.clear()
            state.update({
                "type": "global", "filters": {}, "global_query": text,
                "global_rows": global_admin_search(text),
            })
            add_recent_search(update.effective_user.id, "global", query=text)
        elif mode == "price":
            minimum, maximum = [float(value.strip()) for value in text.split("-", 1)]
            if minimum > maximum:
                raise ValueError
            state["filters"].update({"price_min": minimum, "price_max": maximum})
        elif mode == "date_range":
            start, end = [value.strip() for value in text.split("to", 1)]
            datetime.strptime(start, "%Y-%m-%d")
            datetime.strptime(end, "%Y-%m-%d")
            if start > end:
                raise ValueError
            state["filters"].update({"date_from": start, "date_to": end})
        elif mode in {"orders_min", "spending_min"}:
            value = float(text) if mode == "spending_min" else int(text)
            if value < 0:
                raise ValueError
            state["filters"][mode] = value
        elif mode == "save_name":
            save_search_filter(
                update.effective_user.id, text, state["type"], state["filters"]
            )
            context.user_data.pop("admin_search_mode", None)
            await update.message.reply_text(
                "✅ Filter saved.", reply_markup=search_home_menu()
            )
            return True
        else:
            state["filters"][mode] = text
    except (TypeError, ValueError):
        await update.message.reply_text("Invalid value. Please follow the requested format.")
        return True
    context.user_data.pop("admin_search_mode", None)
    if state["type"] == "global":
        columns = ()
        rows = state["global_rows"][:PER_PAGE]
        total = len(state["global_rows"])
        body = "\n\n".join(
            f"{kind}: {title}\n{details}" for kind, _, title, details in rows
        )
        await update.message.reply_text(
            f"🔎 Search Results — {total}\n\n{body or 'No results found.'}",
            reply_markup=_results_keyboard(1, total),
        )
    else:
        await update.message.reply_text(
            f"✅ Filter added.\n\n{_filter_summary(state)}",
            reply_markup=_type_menu(state["type"]),
        )
    return True
