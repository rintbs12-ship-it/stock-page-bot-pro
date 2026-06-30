from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from urllib.parse import urlparse

from database.db import (
    create_order,
    get_customer_action_order,
    get_customer_profile,
    get_customer_orders,
    get_active_orders,
    get_all_orders,
    get_order,
    get_order_history,
    get_order_receipts,
    get_order_timestamps,
    get_orders_by_group,
    get_payment_logs,
    filter_orders,
    get_setting,
    get_stock,
    is_admin_user,
    is_customer_banned,
    list_admins,
    save_order_receipt,
    search_orders,
    transition_order,
    update_order_field,
    update_stock_field,
    upsert_customer_profile,
    verify_payment,
)


STATUS_DISPLAY = {
    "waiting_payment": "🟡 Waiting Payment",
    "waiting_receipt": "🟡 Waiting Payment",
    "waiting_admin_confirm": "🟡 Waiting Payment",
    "payment_confirmed": "🔵 Payment Received",
    "payment_received": "🔵 Payment Received",
    "waiting_customer_info": "🔵 Payment Received",
    "admin_processing": "🟠 Processing",
    "admin_added": "🟣 Admin Added",
    "waiting_customer_accept": "🟢 Waiting Customer Accept",
    "customer_accepted": "🟢 Customer Accepted",
    "waiting_remove_admin": "⚪ Waiting Remove Admin",
    "completed": "✅ Completed",
    "cancelled": "❌ Cancelled",
}

MANAGER_STATUSES = (
    ("waiting_payment", "🟡 Waiting Payment"),
    ("payment_confirmed", "🔵 Payment Received"),
    ("waiting_customer_info", "🔵 Customer Info"),
    ("admin_processing", "🟠 Processing"),
    ("admin_added", "🟣 Admin Added"),
    ("waiting_customer_accept", "🟢 Waiting Customer Accept"),
    ("waiting_remove_admin", "⚪ Waiting Remove Admin"),
    ("completed", "✅ Completed"),
    ("cancelled", "❌ Cancelled"),
)

CUSTOMER_TIMELINE = (
    ("waiting_payment", "🟡 Waiting Payment"),
    ("payment_confirmed", "🔵 Payment Received"),
    ("admin_processing", "🟠 Processing"),
    ("admin_added", "🟣 Admin Added"),
    ("waiting_customer_accept", "🟢 Waiting Customer Accept"),
    ("waiting_remove_admin", "⚪ Waiting Remove Admin"),
    ("completed", "✅ Completed"),
)

STATUS_PROGRESS = {
    "waiting_payment": 0,
    "waiting_receipt": 0,
    "waiting_admin_confirm": 0,
    "payment_confirmed": 1,
    "payment_received": 1,
    "waiting_customer_info": 1,
    "admin_processing": 2,
    "admin_added": 3,
    "waiting_customer_accept": 4,
    "customer_accepted": 4,
    "waiting_remove_admin": 5,
    "completed": 6,
}


def payment_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📤 Upload Receipt",
            callback_data=f"order:upload:{order_id}",
        )],
        [InlineKeyboardButton(
            "❌ Cancel Order",
            callback_data=f"order:cancel:{order_id}",
        )],
    ])


def admin_receipt_buttons(order_id, stock_id, customer_id=None):
    rows = [
        [InlineKeyboardButton(
            "✅ Approve Payment",
            callback_data=f"admin:payment_approve:{order_id}",
        ), InlineKeyboardButton(
            "❌ Reject Payment",
            callback_data=f"admin:payment_reject:{order_id}",
        )],
        [InlineKeyboardButton(
            "👀 View Receipt",
            callback_data=f"admin:payment_receipts:{order_id}",
        ), InlineKeyboardButton(
            "📦 View Order",
            callback_data=f"admin:order_manager_view:{order_id}",
        )],
    ]
    if customer_id is not None:
        rows.append([InlineKeyboardButton(
            "👤 Customer Profile",
            callback_data=f"admin:customer:view:{customer_id}",
        )])
    return InlineKeyboardMarkup(rows)


def rejection_reason_buttons(order_id):
    reasons = (
        ("wrong_amount", "Wrong amount"),
        ("wrong_receipt", "Wrong receipt"),
        ("unclear_image", "Unclear image"),
        ("not_found", "Payment not found"),
    )
    rows = [[InlineKeyboardButton(
        label,
        callback_data=f"admin:payment_reason:{order_id}:{code}",
    )] for code, label in reasons]
    rows.append([InlineKeyboardButton(
        "✍️ Other Reason",
        callback_data=f"admin:payment_reason_custom:{order_id}",
    )])
    rows.append([InlineKeyboardButton(
        "⬅ View Order",
        callback_data=f"admin:order_manager_view:{order_id}",
    )])
    return InlineKeyboardMarkup(rows)


def admin_processing_buttons(order_id, customer_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Admin Added",
            callback_data=f"admin:order_added:{order_id}",
        )],
        [InlineKeyboardButton(
            "💬 Contact Customer",
            url=f"tg://user?id={customer_id}",
        )],
        [InlineKeyboardButton(
            "❌ Cancel Order",
            callback_data=f"admin:order_cancel:{order_id}",
        )],
    ])


def customer_accept_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ I Accepted",
            callback_data=f"order:accepted:{order_id}",
        )],
        [InlineKeyboardButton(
            "🆘 Need Help",
            callback_data=f"order:help:{order_id}",
        )],
    ])


def admin_complete_buttons(order_id, customer_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Mark Completed",
            callback_data=f"admin:order_complete:{order_id}",
        )],
        [InlineKeyboardButton(
            "🆘 Contact Customer",
            url=f"tg://user?id={customer_id}",
        )],
    ])


def orders_admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🧾 Waiting Payment Confirm",
            callback_data="admin:orders:waiting",
        )],
        [InlineKeyboardButton(
            "⚙️ Processing",
            callback_data="admin:orders:processing",
        )],
        [InlineKeyboardButton(
            "✅ Completed",
            callback_data="admin:orders:completed",
        )],
        [InlineKeyboardButton(
            "❌ Cancelled",
            callback_data="admin:orders:cancelled",
        )],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def order_manager_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Active Orders", callback_data="admin:order_manager_active")],
        [InlineKeyboardButton("🔍 Search Orders", callback_data="admin:order_manager_search")],
        [InlineKeyboardButton("🎯 Filters", callback_data="admin:order_manager_filters")],
        [InlineKeyboardButton("📚 Complete History", callback_data="admin:order_manager_history")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def order_search_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Order ID", callback_data="admin:order_search:order_id")],
        [InlineKeyboardButton("Telegram ID", callback_data="admin:order_search:telegram_id")],
        [InlineKeyboardButton("Customer Name", callback_data="admin:order_search:customer_name")],
        [InlineKeyboardButton("Stock ID", callback_data="admin:order_search:stock_id")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:order_manager")],
    ])


def order_filters_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟡 Pending", callback_data="admin:order_filter:pending")],
        [InlineKeyboardButton("🟣 Processing", callback_data="admin:order_filter:processing")],
        [InlineKeyboardButton("✅ Completed", callback_data="admin:order_filter:completed")],
        [InlineKeyboardButton("❌ Cancelled", callback_data="admin:order_filter:cancelled")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:order_manager")],
    ])


def order_manager_list_keyboard(orders):
    rows = [[InlineKeyboardButton(
        f"#{order[0]} · {STATUS_DISPLAY.get(order[5], order[5])}",
        callback_data=f"admin:order_manager_view:{order[0]}",
    )] for order in orders]
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:order_manager")])
    return InlineKeyboardMarkup(rows)


def order_status_menu(order_id):
    rows = [[InlineKeyboardButton(
        label,
        callback_data=f"admin:order_status:{order_id}:{status}",
    )] for status, label in MANAGER_STATUSES]
    rows.append([InlineKeyboardButton(
        "⬅ Back",
        callback_data=f"admin:order_manager_view:{order_id}",
    )])
    return InlineKeyboardMarkup(rows)


def order_manager_detail_keyboard(order):
    rows = [
        [InlineKeyboardButton("💰 Payment Received",
                              callback_data=f"admin:order_workflow:payment:{order[0]}")],
        [InlineKeyboardButton("⚙ Start Processing",
                              callback_data=f"admin:order_workflow:processing:{order[0]}")],
        [InlineKeyboardButton("👤 Admin Added",
                              callback_data=f"admin:order_workflow:admin_added:{order[0]}")],
        [InlineKeyboardButton("✅ Customer Accepted",
                              callback_data=f"admin:order_workflow:customer_accept:{order[0]}")],
        [InlineKeyboardButton("🚪 Remove Admin",
                              callback_data=f"admin:order_workflow:remove_admin:{order[0]}")],
        [InlineKeyboardButton("✔ Complete",
                              callback_data=f"admin:order_workflow:complete:{order[0]}")],
        [InlineKeyboardButton("❌ Cancel Order",
                              callback_data=f"admin:order_workflow:cancel:{order[0]}")],
        [InlineKeyboardButton(
            "👤 Customer Profile",
            callback_data=f"admin:customer:view:{order[2]}",
        )],
    ]
    if order[8]:
        rows.append([InlineKeyboardButton(
            "🧾 View Receipt",
            callback_data=f"admin:order_receipt:{order[0]}",
        )])
    rows.extend([
        [InlineKeyboardButton(
            "💬 Contact Customer",
            url=f"tg://user?id={order[2]}",
        )],
        [InlineKeyboardButton("⬅ Active Orders", callback_data="admin:order_manager_active")],
    ])
    return InlineKeyboardMarkup(rows)


def format_order_manager_detail(order):
    history = get_order_history(order[0])
    payment_logs = get_payment_logs(order[0])
    timestamps = get_order_timestamps(order[0]) or {}
    timeline = "\n".join(
        f"• {STATUS_DISPLAY.get(entry[2], entry[2])}\n  {entry[5]}"
        for entry in history
    )
    payment_timeline = "\n".join(
        f"• {entry[3].title()} · {entry[6]}"
        + (f"\n  Reason: {entry[4]}" if entry[4] else "")
        for entry in payment_logs
    )
    customer = f"@{order[3]}" if order[3] else "No username"
    return (
        f"📦 Order #{order[0]}\n\n"
        f"Customer: {customer}\n"
        f"Telegram ID: {order[2]}\n"
        f"Stock ID: {order[1]}\n"
        f"Price: {order[4]}\n"
        f"Current Status: {STATUS_DISPLAY.get(order[5], order[5])}\n"
        f"Created Time: {order[9]}\n\n"
        f"Payment Time: {timestamps.get('payment_at') or 'Not recorded'}\n"
        f"Processing Time: {timestamps.get('processing_at') or 'Not recorded'}\n"
        f"Admin Added Time: {timestamps.get('admin_added_at') or 'Not recorded'}\n"
        f"Accepted Time: {timestamps.get('accepted_at') or 'Not recorded'}\n"
        f"Remove Admin Time: {timestamps.get('removed_admin_at') or 'Not recorded'}\n"
        f"Facebook: {order[6] or 'Not provided'}\n"
        f"Page Name: {order[7] or 'Not provided'}\n"
        f"Receipt: {'Uploaded' if order[8] else 'Not uploaded'}\n"
        f"Completion Time: {timestamps.get('completed_at') or 'Not completed'}\n"
        f"Cancelled Time: {timestamps.get('cancelled_at') or 'Not cancelled'}\n\n"
        f"Status Timeline:\n{timeline or 'No history'}\n\n"
        f"Payment Review History:\n{payment_timeline or 'No payment reviews'}"
    )


def remove_admin_confirmation(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("YES", callback_data=f"order:remove_admin_yes:{order_id}")],
        [InlineKeyboardButton("NO", callback_data=f"order:remove_admin_no:{order_id}")],
    ])


def customer_remove_admin_button(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Remove Admin",
            callback_data=f"order:remove_admin:{order_id}",
        )
    ]])


def order_history_keyboard(orders, admin=False):
    prefix = "admin:order_view" if admin else "order:view"
    rows = [[InlineKeyboardButton(
        f"Order #{order[0]} · {STATUS_DISPLAY.get(order[5], order[5])}",
        callback_data=f"{prefix}:{order[0]}",
    )] for order in orders]
    rows.append([InlineKeyboardButton(
        "⬅ Back",
        callback_data="admin:orders" if admin else "home",
    )])
    return InlineKeyboardMarkup(rows)


def format_order(order):
    current_progress = STATUS_PROGRESS.get(order[5], -1)
    timeline = []
    for index, (_, label) in enumerate(CUSTOMER_TIMELINE):
        marker = "✔" if index <= current_progress else "⬜"
        timeline.append(f"{marker} {label}")
    if order[5] == "cancelled":
        timeline.append("❌ Cancelled ✔")
    return (
        f"📦 Order #{order[0]}\n\n"
        f"Stock #{order[1]}\n"
        f"Price: {order[4]}\n"
        f"Status: {STATUS_DISPLAY.get(order[5], order[5])}\n\n"
        "Timeline\n\n"
        + "\n".join(timeline)
    )


def customer_order_detail_keyboard(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 Refresh Order",
            callback_data=f"order:refresh:{order_id}",
        )],
        [InlineKeyboardButton("⬅ My Orders", callback_data="orders:mine")],
    ])


async def _replace_callback_message(query, text, reply_markup=None):
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup)
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup)


async def _send_to_admins(context, text, reply_markup=None, photo=None):
    for admin_id, added_at in list_admins():
        try:
            if photo:
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=photo,
                    caption=text,
                    reply_markup=reply_markup,
                )
            else:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    reply_markup=reply_markup,
                )
        except TelegramError:
            continue


async def _send_to_customer(context, customer_id, text, reply_markup=None):
    try:
        await context.bot.send_message(
            chat_id=customer_id,
            text=text,
            reply_markup=reply_markup,
        )
        return True
    except TelegramError:
        return False


async def reject_payment(query, context, order_id, reason):
    order = get_order(order_id)
    if not order:
        await query.message.reply_text("Order not found.")
        return False
    changed = verify_payment(
        order_id, query.from_user.id, "rejected", reason,
    )
    if not changed:
        await query.message.reply_text(
            "Payment review was already completed or is unavailable."
        )
        return False
    await _send_to_customer(
        context,
        order[2],
        (
            "❌ Payment rejected.\n\n"
            f"Reason:\n{reason}\n\n"
            "Please upload a correct receipt again."
        ),
        reply_markup=payment_buttons(order_id),
    )
    return True


async def start_order(query, context, stock_id):
    stock = get_stock(stock_id)
    if not stock or stock[8] != "available":
        await query.message.reply_text("This stock is not available.")
        return
    user = query.from_user
    profile = upsert_customer_profile(
        user.id,
        getattr(user, "username", "") or "",
        getattr(user, "first_name", "") or "",
        getattr(user, "last_name", "") or "",
    )
    if is_customer_banned(user.id):
        await query.message.reply_text(
            "🚫 Your account is restricted.\nPlease contact admin."
        )
        return
    order_id = create_order(
        stock_id,
        user.id,
        user.username or "",
        stock[4],
    )
    if profile and profile[11]:
        await _send_to_admins(
            context,
            "⭐ VIP Customer\n\n"
            f"New Order #{order_id}\n"
            f"Stock #{stock_id}\n"
            f"Customer: @{getattr(user, 'username', '') or user.id}\n"
            f"Telegram ID: {user.id}\n"
            f"Amount: {stock[4]}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "📦 View Order",
                    callback_data=f"admin:order_manager_view:{order_id}",
                ),
                InlineKeyboardButton(
                    "👤 Customer Profile",
                    callback_data=f"admin:customer:view:{user.id}",
                ),
            ]]),
        )
    text = (
        "💳 Payment\n\n"
        f"Order #{order_id}\n"
        f"Stock #{stock_id}\n"
        f"Amount: {stock[4]}\n\n"
        "Please pay via Bakong QR.\n"
        "Then upload your payment receipt."
    )
    qr_file_id = get_setting("payment_qr_file_id", "")
    if qr_file_id:
        await query.message.reply_photo(
            photo=qr_file_id,
            caption=text,
            reply_markup=payment_buttons(order_id),
        )
    else:
        await query.message.reply_text(
            text + "\n\nPayment QR is not configured. Please contact admin.",
            reply_markup=payment_buttons(order_id),
        )


async def handle_customer_order_callback(query, context):
    data = query.data
    user_id = query.from_user.id
    upsert_customer_profile(
        user_id,
        getattr(query.from_user, "username", "") or "",
        getattr(query.from_user, "first_name", "") or "",
        getattr(query.from_user, "last_name", "") or "",
    )

    if data == "orders:mine":
        orders = get_customer_orders(user_id)
        await query.edit_message_text(
            f"📦 My Orders\n\n{len(orders)} order(s)",
            reply_markup=order_history_keyboard(orders),
        )
        return

    try:
        order_id = int(data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await query.message.reply_text("Invalid order action.")
        return
    order = get_order(order_id)
    if not order or order[2] != user_id:
        await query.message.reply_text("⛔ This order does not belong to you.")
        return

    if data.startswith("order:remove_admin_yes:"):
        if order[5] != "waiting_remove_admin":
            await query.message.reply_text("This action is unavailable.")
            return
        changed = transition_order(
            order_id, "completed", {"waiting_remove_admin"}, user_id,
            changed_by=user_id, note="Customer confirmed admin removal",
        )
        if not changed:
            await query.message.reply_text("Order status has already changed.")
            return
        update_stock_field(order[1], "status", "sold")
        await query.edit_message_text(
            "🎉 Order completed.\nThank you for choosing RS SERVICE."
        )
        await _send_to_admins(
            context,
            "✅ Remove Admin confirmed\n\n"
            f"Order #{order_id}\n"
            f"Customer: {user_id}\n\n"
            "The customer confirmed the transfer is complete.",
        )
        return

    if data.startswith("order:remove_admin_no:"):
        if order[5] != "waiting_remove_admin":
            await query.message.reply_text("This action is unavailable.")
            return
        await query.edit_message_text(
            '🧹 If everything is OK,\npress "Remove Admin".',
            reply_markup=customer_remove_admin_button(order_id),
        )
        return

    if data.startswith("order:remove_admin:"):
        if order[5] != "waiting_remove_admin":
            await query.message.reply_text("This action is unavailable.")
            return
        await query.edit_message_text(
            "Are you sure?",
            reply_markup=remove_admin_confirmation(order_id),
        )
        return

    if data.startswith("order:view:") or data.startswith("order:refresh:"):
        await query.edit_message_text(
            format_order(order),
            reply_markup=customer_order_detail_keyboard(order_id),
        )
        return

    if data.startswith("order:upload:"):
        if is_customer_banned(user_id):
            await query.message.reply_text(
                "🚫 Your account is restricted.\nPlease contact admin."
            )
            return
        if order[5] == "waiting_payment":
            transition_order(order_id, "waiting_receipt", {"waiting_payment"}, user_id)
        elif order[5] != "waiting_receipt":
            await query.message.reply_text("Receipt upload is not available for this order.")
            return
        context.user_data.clear()
        context.user_data.update({
            "order_mode": "receipt",
            "order_id": order_id,
        })
        await query.message.reply_text(
            f"📤 Send the payment receipt photo for Order #{order_id}."
        )
        return

    if data.startswith("order:cancel:"):
        changed = transition_order(
            order_id,
            "cancelled",
            {
                "waiting_payment", "waiting_receipt", "waiting_admin_confirm",
                "payment_confirmed", "waiting_customer_info",
            },
            user_id,
        )
        if not changed:
            await query.message.reply_text("This order can no longer be cancelled.")
            return None
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Order cancelled.")
        return order[1]

    if data.startswith("order:accepted:"):
        changed = transition_order(
            order_id,
            "customer_accepted",
            {"admin_added", "waiting_customer_accept"},
            user_id,
            changed_by=user_id,
            note="Customer accepted page invite",
        )
        if not changed:
            await query.message.reply_text("This action is unavailable.")
            return
        transition_order(
            order_id,
            "waiting_remove_admin",
            {"customer_accepted"},
            user_id,
            changed_by="system",
            note="Waiting for customer removal confirmation",
        )
        await query.edit_message_text(
            '🧹 If everything is OK,\npress "Remove Admin".',
            reply_markup=customer_remove_admin_button(order_id),
        )
        await _send_to_admins(
            context,
            "✅ Customer Accepted\n\n"
            f"Order #{order_id}\n\n"
            "Waiting for the customer to confirm Remove Admin.",
        )
        return

    if data.startswith("order:help:"):
        await query.message.reply_text(
            f"🆘 Help requested for Order #{order_id}.\nAdmin has been notified."
        )
        await _send_to_admins(
            context,
            f"🆘 Customer needs help\n\nOrder #{order_id}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 Contact Customer", url=f"tg://user?id={user_id}")
            ]]),
        )


async def handle_admin_order_callback(query, context):
    data = query.data

    if not is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ Admin only")
        return

    if data.startswith("admin:payment_approve:") or data.startswith(
        "admin:order_confirm:"
    ):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        order = get_order(order_id)
        if not order:
            await query.message.reply_text("Order not found.")
            return
        changed = verify_payment(
            order_id, query.from_user.id, "approved",
        )
        if not changed:
            await query.message.reply_text(
                "Payment was already reviewed or is unavailable."
            )
            return
        notified = await _send_to_customer(
            context,
            order[2],
            (
                "✅ Payment approved.\n\n"
                "Your order is now being processed.\n\n"
                "Please send your Facebook account link."
            ),
        )
        await _replace_callback_message(
            query,
            "✅ Payment approved."
            + ("" if notified else "\n⚠️ Customer notification failed."),
        )
        return

    if data.startswith("admin:payment_reject:") or data.startswith(
        "admin:order_reject:"
    ):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        order = get_order(order_id)
        if not order or order[5] != "waiting_admin_confirm":
            await query.message.reply_text(
                "Payment was already reviewed or is unavailable."
            )
            return
        await _replace_callback_message(
            query,
            f"❌ Reject Payment · Order #{order_id}\n\nChoose a reason:",
            rejection_reason_buttons(order_id),
        )
        return

    if data.startswith("admin:payment_reason_custom:"):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        order = get_order(order_id)
        if not order or order[5] != "waiting_admin_confirm":
            await query.message.reply_text(
                "Payment was already reviewed or is unavailable."
            )
            return
        context.user_data["admin_mode"] = "payment_rejection_reason"
        context.user_data["payment_order_id"] = order_id
        await _replace_callback_message(
            query,
            f"✍️ Send the rejection reason for Order #{order_id}.",
        )
        return

    if data.startswith("admin:payment_reason:"):
        parts = data.split(":")
        if len(parts) != 4:
            await query.message.reply_text("Invalid rejection reason.")
            return
        try:
            order_id = int(parts[2])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        reasons = {
            "wrong_amount": "Wrong amount",
            "wrong_receipt": "Wrong receipt",
            "unclear_image": "Unclear image",
            "not_found": "Payment not found",
        }
        reason = reasons.get(parts[3])
        if not reason:
            await query.message.reply_text("Invalid rejection reason.")
            return
        if await reject_payment(query, context, order_id, reason):
            await _replace_callback_message(
                query,
                f"❌ Payment rejected.\n\nReason: {reason}",
            )
        return

    if data.startswith("admin:payment_receipts:"):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        receipts = get_order_receipts(order_id)
        if not receipts:
            await query.message.reply_text("No receipts for this order.")
            return
        for index, receipt in enumerate(receipts, start=1):
            await query.message.reply_photo(
                photo=receipt[2],
                caption=(
                    f"🧾 Receipt {index} / {len(receipts)}\n"
                    f"Order #{order_id}\n"
                    f"Uploaded: {receipt[4]}"
                ),
            )
        return

    if data == "admin:order_manager":
        context.user_data.pop("admin_mode", None)
        context.user_data.pop("order_search_type", None)
        await query.edit_message_text(
            "📦 ORDER MANAGER",
            reply_markup=order_manager_menu(),
        )
        return

    if data == "admin:order_manager_active":
        orders = get_active_orders()
        await query.edit_message_text(
            f"📦 Active Orders\n\n{len(orders)} order(s)",
            reply_markup=order_manager_list_keyboard(orders),
        )
        return

    if data == "admin:order_manager_history":
        orders = get_all_orders()
        await query.edit_message_text(
            f"📚 Complete Order History\n\n{len(orders)} order(s)",
            reply_markup=order_manager_list_keyboard(orders),
        )
        return

    if data == "admin:order_manager_search":
        await query.edit_message_text(
            "🔍 Search Orders\n\nSearch by:",
            reply_markup=order_search_menu(),
        )
        return

    if data.startswith("admin:order_search:"):
        search_type = data.rsplit(":", 1)[1]
        if search_type not in {
            "order_id", "telegram_id", "customer_name", "stock_id",
        }:
            await query.message.reply_text("Invalid search type.")
            return
        context.user_data["admin_mode"] = "order_search"
        context.user_data["order_search_type"] = search_type
        await query.edit_message_text(
            f"🔍 Send the {search_type.replace('_', ' ').title()}."
        )
        return

    if data == "admin:order_manager_filters":
        await query.edit_message_text(
            "🎯 Order Filters",
            reply_markup=order_filters_menu(),
        )
        return

    if data.startswith("admin:order_filter:"):
        filter_name = data.rsplit(":", 1)[1]
        orders = filter_orders(filter_name)
        await query.edit_message_text(
            f"🎯 {filter_name.title()} Orders\n\n{len(orders)} order(s)",
            reply_markup=order_manager_list_keyboard(orders),
        )
        return

    if data.startswith("admin:order_workflow:"):
        parts = data.split(":")
        if len(parts) != 4:
            await query.message.reply_text("Invalid order action.")
            return
        action = parts[2]
        try:
            order_id = int(parts[3])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        order = get_order(order_id)
        workflow = {
            "payment": (
                "payment_confirmed",
                {"waiting_payment", "waiting_receipt", "waiting_admin_confirm"},
            ),
            "processing": (
                "admin_processing",
                {"payment_confirmed", "waiting_customer_info"},
            ),
            "admin_added": ("admin_added", {"admin_processing"}),
            "customer_accept": (
                "waiting_customer_accept", {"admin_added"},
            ),
            "remove_admin": (
                "waiting_remove_admin",
                {"waiting_customer_accept", "customer_accepted"},
            ),
            "complete": ("completed", {"waiting_remove_admin"}),
            "cancel": (
                "cancelled",
                {
                    "waiting_payment", "waiting_receipt",
                    "waiting_admin_confirm", "payment_confirmed",
                    "waiting_customer_info", "admin_processing",
                    "admin_added", "waiting_customer_accept",
                    "customer_accepted", "waiting_remove_admin",
                },
            ),
        }
        target = workflow.get(action)
        if not order or not target:
            await query.message.reply_text("Order action not found.")
            return
        new_status, expected = target
        changed = transition_order(
            order_id,
            new_status,
            expected,
            changed_by=query.from_user.id,
            note=f"Admin workflow: {action}",
        )
        if not changed:
            await query.message.reply_text(
                "This status change is invalid or was already completed."
            )
            return
        notification, markup = status_customer_notification(
            new_status, order_id,
        )
        notified = await _send_to_customer(
            context, order[2], notification, reply_markup=markup,
        )
        if new_status == "completed":
            update_stock_field(order[1], "status", "sold")
        updated_order = get_order(order_id)
        await query.edit_message_text(
            format_order_manager_detail(updated_order)
            + ("" if notified else "\n\n⚠️ Customer notification failed."),
            reply_markup=order_manager_detail_keyboard(updated_order),
        )
        return

    if data.startswith("admin:order_manager_view:"):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        order = get_order(order_id)
        if not order:
            await query.message.reply_text("Order not found.")
            return
        upsert_customer_profile(order[2], order[3] or "")
        await _replace_callback_message(
            query,
            format_order_manager_detail(order),
            order_manager_detail_keyboard(order),
        )
        return

    if data.startswith("admin:order_status_menu:"):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        if not get_order(order_id):
            await query.message.reply_text("Order not found.")
            return
        await query.edit_message_text(
            f"🔄 Change Status · Order #{order_id}",
            reply_markup=order_status_menu(order_id),
        )
        return

    if data.startswith("admin:order_status:"):
        parts = data.split(":")
        if len(parts) != 4:
            await query.message.reply_text("Invalid status action.")
            return
        try:
            order_id = int(parts[2])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        new_status = parts[3]
        valid_statuses = {status for status, _ in MANAGER_STATUSES}
        order = get_order(order_id)
        if not order or new_status not in valid_statuses:
            await query.message.reply_text("Invalid order status.")
            return
        changed = transition_order(
            order_id,
            new_status,
            {order[5]},
            changed_by=query.from_user.id,
            note="Admin workflow update",
        )
        if not changed:
            await query.message.reply_text("Order status has already changed.")
            return
        notification, markup = status_customer_notification(new_status, order_id)
        notified = await _send_to_customer(
            context, order[2], notification, reply_markup=markup,
        )
        if new_status == "completed":
            update_stock_field(order[1], "status", "sold")
        order = get_order(order_id)
        await query.edit_message_text(
            format_order_manager_detail(order)
            + ("" if notified else "\n\n⚠️ Customer notification failed."),
            reply_markup=order_manager_detail_keyboard(order),
        )
        return

    if data.startswith("admin:order_receipt:"):
        try:
            order_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await query.message.reply_text("Invalid order.")
            return
        order = get_order(order_id)
        if not order or not order[8]:
            await query.message.reply_text("Receipt not found.")
            return
        await query.message.reply_photo(
            photo=order[8],
            caption=f"🧾 Receipt · Order #{order_id}",
        )
        return

    if data == "admin:orders":
        await query.edit_message_text("📋 Orders", reply_markup=orders_admin_menu())
        return

    if data.startswith("admin:orders:"):
        group = data.rsplit(":", 1)[1]
        orders = get_orders_by_group(group)
        await query.edit_message_text(
            f"📋 {group.title()} Orders\n\n{len(orders)} order(s)",
            reply_markup=order_history_keyboard(orders, admin=True),
        )
        return

    try:
        order_id = int(data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await query.message.reply_text("Invalid order action.")
        return
    order = get_order(order_id)
    if not order:
        await query.message.reply_text("Order not found.")
        return

    if data.startswith("admin:order_view:"):
        upsert_customer_profile(order[2], order[3] or "")
        await query.edit_message_text(
            format_order(order),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Orders", callback_data="admin:orders")
            ]]),
        )
        return

    if data.startswith("admin:order_added:"):
        changed = transition_order(
            order_id,
            "admin_added",
            {"admin_processing"},
        )
        if changed:
            await _send_to_customer(
                context,
                order[2],
                (
                    "🎉 Admin has been added to the page.\n\n"
                    "Please open Facebook and accept the page invite."
                ),
                reply_markup=customer_accept_buttons(order_id),
            )
        await query.edit_message_text(
            "✅ Customer notified." if changed else "Order status has already changed."
        )
        return

    if data.startswith("admin:order_complete:"):
        changed = transition_order(
            order_id,
            "completed",
            {"waiting_remove_admin"},
        )
        if changed:
            update_stock_field(order[1], "status", "sold")
            await _send_to_customer(
                context,
                order[2],
                "🎉 Order completed.\nThank you.",
            )
        await query.edit_message_text(
            "✅ Order completed." if changed else "Order status has already changed."
        )
        return

    if data.startswith("admin:order_cancel:"):
        changed = transition_order(
            order_id,
            "cancelled",
            {
                "waiting_admin_confirm", "payment_confirmed",
                "waiting_customer_info", "admin_processing", "admin_added",
            },
        )
        if changed:
            await _send_to_customer(
                context,
                order[2],
                f"❌ Order #{order_id} was cancelled by Admin.",
            )
        await query.edit_message_text(
            "Order cancelled." if changed else "Order cannot be cancelled."
        )


def status_customer_notification(status, order_id):
    messages = {
        "waiting_payment": "🟡 Waiting for payment.",
        "payment_confirmed": (
            "💰 Payment received.\n\n"
            "Your order is ready for processing."
        ),
        "waiting_customer_info": "👤 Please send your Facebook account link.",
        "admin_processing": "🟠 Your order is now being processed.",
        "admin_added": (
            "👤 Admin has been added.\n\n"
            "Please check your Facebook page."
        ),
        "waiting_customer_accept": (
            "✅ Please accept the page invitation."
        ),
        "waiting_remove_admin": (
            "🚪 Please remove our admin account after verification."
        ),
        "completed": (
            "🎉 Order completed.\n\nThank you for your purchase."
        ),
        "cancelled": f"❌ Order #{order_id} was cancelled.",
    }
    markup = None
    if status == "waiting_customer_accept":
        markup = customer_accept_buttons(order_id)
    elif status == "waiting_remove_admin":
        markup = customer_remove_admin_button(order_id)
    return messages.get(status, f"Order #{order_id}: {STATUS_DISPLAY[status]}"), markup


async def handle_admin_order_message(update, context):
    if context.user_data.get("admin_mode") == "payment_rejection_reason":
        order_id = context.user_data.get("payment_order_id")
        reason = (update.message.text or "").strip()
        if not reason or len(reason) > 500:
            await update.message.reply_text(
                "Reason must be between 1 and 500 characters."
            )
            return True
        query = type("MessageQuery", (), {
            "from_user": update.effective_user,
            "message": update.message,
        })()
        if await reject_payment(query, context, order_id, reason):
            context.user_data.clear()
            await update.message.reply_text(
                f"❌ Payment rejected.\n\nReason: {reason}"
            )
        return True

    if context.user_data.get("admin_mode") != "order_search":
        return False
    search_type = context.user_data.get("order_search_type")
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Please send a search value.")
        return True
    orders = search_orders(search_type, text)
    context.user_data.pop("admin_mode", None)
    context.user_data.pop("order_search_type", None)
    await update.message.reply_text(
        f"🔍 Search Results\n\n{len(orders)} order(s)",
        reply_markup=order_manager_list_keyboard(orders),
    )
    return True


async def handle_order_message(update, context):
    user_id = update.effective_user.id
    if context.user_data.get("order_mode") == "receipt":
        if is_customer_banned(user_id):
            context.user_data.clear()
            await update.message.reply_text(
                "🚫 Your account is restricted.\nPlease contact admin."
            )
            return True
        order_id = context.user_data.get("order_id")
        order = get_order(order_id)
        if not order or order[2] != user_id or order[5] != "waiting_receipt":
            context.user_data.clear()
            await update.message.reply_text("Receipt session expired.")
            return True
        if not update.message.photo:
            await update.message.reply_text("Please send the receipt as a photo.")
            return True
        receipt_file_id = update.message.photo[-1].file_id
        if not save_order_receipt(order_id, user_id, receipt_file_id):
            context.user_data.clear()
            await update.message.reply_text("Receipt session expired.")
            return True
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Receipt uploaded. Please wait for Admin confirmation."
        )
        username = f"@{order[3]}" if order[3] else str(user_id)
        profile = get_customer_profile(user_id)
        vip_label = "\n⭐ VIP Customer" if profile and profile[11] else ""
        await _send_to_admins(
            context,
            "🧾 Payment Receipt Review\n\n"
            f"Order ID: {order_id}\n"
            f"Stock ID: {order[1]}\n"
            f"Customer: {username}\n"
            f"Telegram ID: {user_id}\n"
            f"Amount: {order[4]}\n"
            f"Status: Waiting Admin Confirm{vip_label}",
            reply_markup=admin_receipt_buttons(order_id, order[1], user_id),
            photo=receipt_file_id,
        )
        return True

    if update.message.text:
        order = get_customer_action_order(user_id)
        if not order:
            return False
        text = update.message.text.strip()
        if not order[6]:
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                await update.message.reply_text(
                    "Please send a valid http:// or https:// Facebook Profile Link."
                )
                return True
            update_order_field(
                order[0], "facebook_profile_link", text,
                order[5], user_id,
            )
            upsert_customer_profile(
                user_id,
                update.effective_user.username or "",
                getattr(update.effective_user, "first_name", "") or "",
                getattr(update.effective_user, "last_name", "") or "",
                facebook_profile_link=text,
            )
            await update.message.reply_text(
                "Please send the new Page Name you want."
            )
            return True
        if not text or len(text) > 100:
            await update.message.reply_text(
                "Page Name must be between 1 and 100 characters."
            )
            return True
        update_order_field(
            order[0], "requested_page_name", text,
            order[5], user_id,
        )
        upsert_customer_profile(
            user_id,
            update.effective_user.username or "",
            getattr(update.effective_user, "first_name", "") or "",
            getattr(update.effective_user, "last_name", "") or "",
            default_page_name=text,
        )
        transition_order(
            order[0],
            "admin_processing",
            {"waiting_customer_info", "payment_received"},
            user_id,
        )
        await update.message.reply_text(
            "✅ Information saved. Admin is processing your order."
        )
        await _send_to_admins(
            context,
            "📦 Order Ready for Processing\n\n"
            f"Order #{order[0]}\n"
            f"Stock #{order[1]}\n"
            f"Customer Facebook:\n{order[6]}\n\n"
            f"Requested Page Name:\n{text}"
            + (
                "\n\n⭐ VIP Customer"
                if (get_customer_profile(user_id) or [None] * 12)[11]
                else ""
            ),
            reply_markup=admin_processing_buttons(order[0], user_id),
        )
        return True

    return False
