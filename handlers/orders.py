from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from urllib.parse import urlparse

from database.db import (
    create_order,
    get_customer_action_order,
    get_customer_orders,
    get_order,
    get_orders_by_group,
    get_setting,
    get_stock,
    list_admins,
    transition_order,
    update_order_field,
    update_stock_field,
)


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


def admin_receipt_buttons(order_id, stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Confirm Payment",
            callback_data=f"admin:order_confirm:{order_id}",
        ), InlineKeyboardButton(
            "❌ Reject Payment",
            callback_data=f"admin:order_reject:{order_id}",
        )],
        [InlineKeyboardButton(
            "👀 View Stock",
            callback_data=f"admin:stock:{stock_id}",
        )],
    ])


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


def order_history_keyboard(orders, admin=False):
    prefix = "admin:order_view" if admin else "order:view"
    rows = [[InlineKeyboardButton(
        f"Order #{order[0]} · {order[5]}",
        callback_data=f"{prefix}:{order[0]}",
    )] for order in orders]
    rows.append([InlineKeyboardButton(
        "⬅ Back",
        callback_data="admin:orders" if admin else "home",
    )])
    return InlineKeyboardMarkup(rows)


def format_order(order):
    username = f"@{order[3]}" if order[3] else str(order[2])
    return (
        f"📦 Order #{order[0]}\n\n"
        f"Stock #{order[1]}\n"
        f"Customer: {username}\n"
        f"Amount: {order[4]}\n"
        f"Status: {order[5]}\n"
        f"Created: {order[9]}"
    )


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


async def start_order(query, context, stock_id):
    stock = get_stock(stock_id)
    if not stock or stock[8] != "available":
        await query.message.reply_text("This stock is not available.")
        return
    user = query.from_user
    order_id = create_order(
        stock_id,
        user.id,
        user.username or "",
        stock[4],
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

    if data.startswith("order:view:"):
        await query.edit_message_text(
            format_order(order),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ My Orders", callback_data="orders:mine")
            ]]),
        )
        return

    if data.startswith("order:upload:"):
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
        await query.message.reply_text(
            "✅ Order cancelled." if changed else "This order can no longer be cancelled."
        )
        return

    if data.startswith("order:accepted:"):
        changed = transition_order(
            order_id,
            "customer_accepted",
            {"admin_added"},
            user_id,
        )
        if not changed:
            await query.message.reply_text("This action is unavailable.")
            return
        await query.edit_message_text("✅ Thank you. Admin has been notified.")
        await _send_to_admins(
            context,
            "✅ Customer Accepted\n\n"
            f"Order #{order_id}\n\n"
            "Please remove your admin access when finished.",
            reply_markup=admin_complete_buttons(order_id, user_id),
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
        await query.edit_message_text(
            format_order(order),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅ Orders", callback_data="admin:orders")
            ]]),
        )
        return

    if data.startswith("admin:order_confirm:"):
        changed = transition_order(
            order_id,
            "payment_confirmed",
            {"waiting_admin_confirm"},
        )
        if changed:
            transition_order(
                order_id,
                "waiting_customer_info",
                {"payment_confirmed"},
            )
            notified = await _send_to_customer(
                context,
                order[2],
                (
                    "✅ Payment confirmed.\n\n"
                    "Please send your Facebook Profile Link.\n"
                    "Example:\nhttps://facebook.com/username"
                ),
            )
        await _replace_callback_message(
            query,
            (
                "✅ Payment confirmed."
                + ("" if notified else "\n⚠️ Customer notification failed.")
                if changed else "Order status has already changed."
            )
        )
        return

    if data.startswith("admin:order_reject:"):
        changed = transition_order(
            order_id,
            "waiting_payment",
            {"waiting_admin_confirm"},
        )
        if changed:
            update_order_field(order_id, "receipt_file_id", "", "waiting_payment")
            await _send_to_customer(
                context,
                order[2],
                (
                    f"❌ Payment receipt rejected for Order #{order_id}.\n"
                    "Please upload the correct receipt again."
                ),
                reply_markup=payment_buttons(order_id),
            )
        await _replace_callback_message(
            query,
            "Receipt rejected." if changed else "Order status has already changed."
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
            {"customer_accepted"},
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


async def handle_order_message(update, context):
    user_id = update.effective_user.id
    if context.user_data.get("order_mode") == "receipt":
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
        update_order_field(
            order_id,
            "receipt_file_id",
            receipt_file_id,
            "waiting_receipt",
            user_id,
        )
        transition_order(
            order_id,
            "waiting_admin_confirm",
            {"waiting_receipt"},
            user_id,
        )
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Receipt uploaded. Please wait for Admin confirmation."
        )
        username = f"@{order[3]}" if order[3] else str(user_id)
        await _send_to_admins(
            context,
            "🧾 New Payment Receipt\n\n"
            f"Order #{order_id}\n"
            f"Stock #{order[1]}\n"
            f"Customer: {username}\n"
            f"Amount: {order[4]}",
            reply_markup=admin_receipt_buttons(order_id, order[1]),
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
                "waiting_customer_info", user_id,
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
            "waiting_customer_info", user_id,
        )
        transition_order(
            order[0],
            "admin_processing",
            {"waiting_customer_info"},
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
            f"Requested Page Name:\n{text}",
            reply_markup=admin_processing_buttons(order[0], user_id),
        )
        return True

    return False
