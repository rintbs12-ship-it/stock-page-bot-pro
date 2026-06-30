from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.db import (
    add_audit_log,
    get_customer_orders,
    get_customer_profile,
    is_admin_user,
    is_customer_banned,
    list_customers,
    search_customers,
    toggle_customer_flag,
    update_customer_profile_field,
    upsert_customer_profile,
)
from handlers.audit import admin_display_name
from handlers.orders import order_history_keyboard


RESTRICTED_MESSAGE = "🚫 Your account is restricted.\nPlease contact admin."


def profile_text(profile, admin=False):
    username = f"@{profile[2]}" if profile[2] else "Not set"
    name = " ".join(part for part in profile[3:5] if part) or "Not set"
    text = (
        "👤 Customer Profile\n\n" if admin else "👤 My Profile\n\n"
    ) + (
        f"Telegram ID: {profile[1]}\n"
        f"Username: {username}\n"
    )
    if admin:
        text += f"Name: {name}\n"
    text += (
        f"Facebook Link: {profile[5] or 'Not set'}\n"
        f"Default Page Name: {profile[6] or 'Not set'}\n"
        f"Total Orders: {profile[7]}\n"
        f"Completed Orders: {profile[8]}\n"
    )
    if admin:
        text += f"Cancelled Orders: {profile[9]}\n"
    text += (
        f"Total Spent: ${profile[10]:,.2f}\n"
        f"VIP: {'Yes ⭐' if profile[11] else 'No'}\n"
        f"Status: {'Restricted' if profile[12] else 'Active'}"
    )
    if admin:
        text += (
            f"\nBanned: {'Yes' if profile[12] else 'No'}\n"
            f"Created: {profile[14]}\n"
            f"Updated: {profile[15]}\n\n"
            f"Admin Notes:\n{profile[13] or 'No notes'}"
        )
    return text


def customer_profile_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔗 Update Facebook Link", callback_data="profile:update_facebook"
        )],
        [InlineKeyboardButton(
            "📝 Update Page Name", callback_data="profile:update_page"
        )],
        [InlineKeyboardButton("📦 My Orders", callback_data="orders:mine")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])


def crm_home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "👥 View All Customers", callback_data="admin:customers:list"
        )],
        [InlineKeyboardButton(
            "🔎 Telegram ID", callback_data="admin:customers:search:telegram"
        )],
        [InlineKeyboardButton(
            "🔎 Username", callback_data="admin:customers:search:username"
        )],
        [InlineKeyboardButton(
            "🔎 Facebook Link", callback_data="admin:customers:search:facebook"
        )],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin:home")],
    ])


def customer_list_keyboard(customers):
    rows = [[InlineKeyboardButton(
        f"{'⭐ ' if customer[11] else ''}"
        f"{customer[2] or customer[3] or customer[1]} · {customer[7]} orders",
        callback_data=f"admin:customer:view:{customer[1]}",
    )] for customer in customers]
    rows.append([InlineKeyboardButton(
        "⬅️ Customers", callback_data="admin:customers"
    )])
    return InlineKeyboardMarkup(rows)


def admin_customer_keyboard(profile):
    telegram_id = profile[1]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📦 View Orders",
            callback_data=f"admin:customer:orders:{telegram_id}",
        )],
        [InlineKeyboardButton(
            "📝 Add Note",
            callback_data=f"admin:customer:note:{telegram_id}",
        )],
        [InlineKeyboardButton(
            "⭐ Remove VIP" if profile[11] else "⭐ Mark VIP",
            callback_data=f"admin:customer:vip:{telegram_id}",
        )],
        [InlineKeyboardButton(
            "✅ Unban" if profile[12] else "🚫 Ban",
            callback_data=f"admin:customer:ban:{telegram_id}",
        )],
        [InlineKeyboardButton(
            "💬 Message Customer", url=f"tg://user?id={telegram_id}"
        )],
        [InlineKeyboardButton(
            "⬅️ Customers", callback_data="admin:customers"
        )],
    ])


async def handle_customer_profile_callback(query, context):
    user = query.from_user
    upsert_customer_profile(
        user.id,
        getattr(user, "username", "") or "",
        getattr(user, "first_name", "") or "",
        getattr(user, "last_name", "") or "",
    )
    if query.data == "profile:view":
        profile = get_customer_profile(user.id)
        await query.edit_message_text(
            profile_text(profile), reply_markup=customer_profile_keyboard()
        )
        return True
    if query.data in {"profile:update_facebook", "profile:update_page"}:
        if is_customer_banned(user.id):
            await query.message.reply_text(RESTRICTED_MESSAGE)
            return True
        context.user_data["customer_profile_mode"] = (
            "facebook" if query.data.endswith("facebook") else "page"
        )
        prompt = (
            "Send your Facebook profile link (http:// or https://)."
            if query.data.endswith("facebook")
            else "Send your default Page Name."
        )
        await query.edit_message_text(prompt)
        return True
    return False


async def handle_customer_profile_message(update, context):
    mode = context.user_data.get("customer_profile_mode")
    if not mode:
        return False
    user = update.effective_user
    if is_customer_banned(user.id):
        context.user_data.pop("customer_profile_mode", None)
        await update.message.reply_text(RESTRICTED_MESSAGE)
        return True
    text = (update.message.text or "").strip()
    if mode == "facebook":
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            await update.message.reply_text(
                "Please send a valid http:// or https:// Facebook link."
            )
            return True
        field = "facebook_profile_link"
    else:
        if not text or len(text) > 100:
            await update.message.reply_text(
                "Page Name must be between 1 and 100 characters."
            )
            return True
        field = "default_page_name"
    update_customer_profile_field(user.id, field, text)
    context.user_data.pop("customer_profile_mode", None)
    profile = get_customer_profile(user.id)
    await update.message.reply_text(
        "✅ Profile updated.\n\n" + profile_text(profile),
        reply_markup=customer_profile_keyboard(),
    )
    return True


async def handle_crm_callback(query, context):
    if not is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ Admin only")
        return True
    data = query.data
    if data == "admin:customers":
        await query.edit_message_text(
            "👥 CUSTOMER CRM", reply_markup=crm_home_keyboard()
        )
        return True
    if data == "admin:customers:list":
        customers = list_customers()
        await query.edit_message_text(
            f"👥 Customers\n\n{len(customers)} customer(s)",
            reply_markup=customer_list_keyboard(customers),
        )
        return True
    if data.startswith("admin:customers:search:"):
        search_type = data.rsplit(":", 1)[1]
        if search_type not in {"telegram", "username", "facebook"}:
            await query.message.reply_text("Invalid search type.")
            return True
        context.user_data["crm_mode"] = "search"
        context.user_data["crm_search_type"] = search_type
        await query.edit_message_text(
            f"🔎 Send the customer {search_type}."
        )
        return True
    parts = data.split(":")
    if len(parts) != 4 or parts[:2] != ["admin", "customer"]:
        return False
    action = parts[2]
    try:
        telegram_id = int(parts[3])
    except ValueError:
        await query.message.reply_text("Invalid customer.")
        return True
    profile = get_customer_profile(telegram_id)
    if not profile:
        await query.message.reply_text("Customer not found.")
        return True
    if action == "view":
        await query.edit_message_text(
            profile_text(profile, admin=True),
            reply_markup=admin_customer_keyboard(profile),
        )
    elif action == "orders":
        orders = get_customer_orders(telegram_id)
        await query.edit_message_text(
            f"📦 Customer Orders\n\n{len(orders)} order(s)",
            reply_markup=order_history_keyboard(orders, admin=True),
        )
    elif action == "note":
        context.user_data["crm_mode"] = "note"
        context.user_data["crm_customer_id"] = telegram_id
        await query.edit_message_text("📝 Send the private admin note.")
    elif action in {"vip", "ban"}:
        toggle_customer_flag(
            telegram_id, "is_vip" if action == "vip" else "is_banned"
        )
        add_audit_log(
            query.from_user.id, admin_display_name(query.from_user),
            "Edit Customer Profile", f"Customer {telegram_id}",
            f"toggle {'is_vip' if action == 'vip' else 'is_banned'}",
        )
        profile = get_customer_profile(telegram_id)
        await query.edit_message_text(
            profile_text(profile, admin=True),
            reply_markup=admin_customer_keyboard(profile),
        )
    else:
        await query.message.reply_text("Invalid customer action.")
    return True


async def handle_crm_message(update, context):
    mode = context.user_data.get("crm_mode")
    if not mode:
        return False
    if not is_admin_user(update.effective_user.id):
        context.user_data.clear()
        await update.message.reply_text("⛔ Admin only")
        return True
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Please send a value.")
        return True
    if mode == "search":
        customers = search_customers(
            context.user_data.get("crm_search_type"), text
        )
        context.user_data.clear()
        await update.message.reply_text(
            f"🔎 Search Results\n\n{len(customers)} customer(s)",
            reply_markup=customer_list_keyboard(customers),
        )
        return True
    if mode == "note":
        if len(text) > 2000:
            await update.message.reply_text(
                "Admin note must be 2000 characters or fewer."
            )
            return True
        telegram_id = context.user_data.get("crm_customer_id")
        update_customer_profile_field(telegram_id, "admin_notes", text)
        add_audit_log(
            update.effective_user.id, admin_display_name(update.effective_user),
            "Edit Customer Profile", f"Customer {telegram_id}",
            "updated admin notes",
        )
        context.user_data.clear()
        profile = get_customer_profile(telegram_id)
        await update.message.reply_text(
            "✅ Note saved.\n\n" + profile_text(profile, admin=True),
            reply_markup=admin_customer_keyboard(profile),
        )
        return True
    return False
