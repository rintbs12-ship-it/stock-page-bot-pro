from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import FACEBOOK_CONTACT, TELEGRAM_CONTACT
from database.db import (
    add_admin,
    clear_photo_upload_session,
    get_setting,
    list_admins,
    remove_admin,
    set_setting,
)


OWNER_ID = 619658883


def settings_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏪 Store Profile", callback_data="admin:settings_profile")],
        [InlineKeyboardButton("🖼 Bot Logo", callback_data="admin:settings_logo")],
        [InlineKeyboardButton("💳 Payment QR", callback_data="admin:settings_payment_qr")],
        [InlineKeyboardButton("👋 Welcome Message", callback_data="admin:settings_welcome")],
        [InlineKeyboardButton("📞 Contact Information", callback_data="admin:settings_contact")],
        [InlineKeyboardButton("🌍 Language", callback_data="admin:settings_language")],
        [InlineKeyboardButton("💵 Currency", callback_data="admin:settings_currency")],
        [InlineKeyboardButton("🇰🇭 Default Country", callback_data="admin:settings_country")],
        [InlineKeyboardButton("⭐ Default Quality", callback_data="admin:settings_quality")],
        [InlineKeyboardButton("👑 Admin Manager", callback_data="admin:settings_admins")],
        [InlineKeyboardButton("📢 Announcement", callback_data="admin:settings_announcement")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def back_to_settings():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅ Back", callback_data="admin:settings")
    ]])


def profile_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Store Name", callback_data="admin:settings_edit:store_name")],
        [InlineKeyboardButton(
            "📝 Store Description",
            callback_data="admin:settings_edit:store_description",
        )],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:settings")],
    ])


def contact_settings_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💬 Telegram",
            callback_data="admin:settings_edit:contact_telegram",
        )],
        [InlineKeyboardButton(
            "📘 Facebook",
            callback_data="admin:settings_edit:contact_facebook",
        )],
        [InlineKeyboardButton(
            "🌐 Website",
            callback_data="admin:settings_edit:contact_website",
        )],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:settings")],
    ])


def choice_menu(setting, choices):
    rows = [
        [InlineKeyboardButton(label, callback_data=f"admin:settings_set:{setting}:{value}")]
        for value, label in choices
    ]
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:settings")])
    return InlineKeyboardMarkup(rows)


def admin_manager_menu(admins, owner):
    rows = []
    if owner:
        rows.append([InlineKeyboardButton(
            "➕ Add Admin",
            callback_data="admin:settings_admin_add",
        )])
        for user_id, added_at in admins:
            if user_id != OWNER_ID:
                rows.append([InlineKeyboardButton(
                    f"🗑 Remove {user_id}",
                    callback_data=f"admin:settings_admin_remove:{user_id}",
                )])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="admin:settings")])
    return InlineKeyboardMarkup(rows)


def settings_summary():
    return (
        "⚙️ SETTINGS\n\n"
        f"🏪 Store: {get_setting('store_name', 'RS SERVICE')}\n"
        f"🌍 Language: {get_setting('default_language', 'km').upper()}\n"
        f"💵 Currency: {get_setting('currency', 'USD')}\n"
        f"🇰🇭 Country: {get_setting('default_country', 'Cambodia')}\n"
        f"⭐ Quality: {get_setting('default_quality', '100')}%"
    )


def _begin_text_edit(context, key):
    context.user_data.clear()
    context.user_data.update({
        "admin_mode": "settings_text",
        "settings_key": key,
    })


async def handle_settings_callback(query, context):
    data = query.data
    user_id = query.from_user.id

    if data == "admin:settings":
        await query.edit_message_text(settings_summary(), reply_markup=settings_menu())
        return

    if data == "admin:settings_profile":
        await query.edit_message_text(
            "🏪 Store Profile\n\n"
            f"Store Name: {get_setting('store_name', 'RS SERVICE')}\n"
            f"Description: {get_setting('store_description', 'Stock Page Bot')}",
            reply_markup=profile_menu(),
        )
        return

    if data == "admin:settings_logo":
        clear_photo_upload_session(user_id)
        context.user_data.clear()
        context.user_data["admin_mode"] = "settings_logo"
        await query.edit_message_text(
            "🖼 Send one photo for the new Bot Logo.",
            reply_markup=back_to_settings(),
        )
        return

    if data == "admin:settings_payment_qr":
        clear_photo_upload_session(user_id)
        context.user_data.clear()
        context.user_data["admin_mode"] = "settings_payment_qr"
        await query.edit_message_text(
            "💳 Send one Bakong QR photo.",
            reply_markup=back_to_settings(),
        )
        return

    if data == "admin:settings_welcome":
        _begin_text_edit(context, "welcome_message")
        await query.edit_message_text(
            "👋 Send the new Welcome Message.\n"
            "Text, emoji, and multiple lines are supported.",
            reply_markup=back_to_settings(),
        )
        return

    if data == "admin:settings_contact":
        await query.edit_message_text(
            "📞 Contact Information\n\n"
            f"Telegram: {get_setting('contact_telegram', TELEGRAM_CONTACT)}\n"
            f"Facebook: {get_setting('contact_facebook', FACEBOOK_CONTACT)}\n"
            f"Website: {get_setting('contact_website', '') or 'Not set'}",
            reply_markup=contact_settings_menu(),
        )
        return

    if data == "admin:settings_language":
        await query.edit_message_text(
            "🌍 Default Language",
            reply_markup=choice_menu("default_language", [
                ("km", "🇰🇭 Khmer"),
                ("en", "🇺🇸 English"),
            ]),
        )
        return

    if data == "admin:settings_currency":
        await query.edit_message_text(
            "💵 Currency",
            reply_markup=choice_menu("currency", [
                ("USD", "USD $"),
                ("KHR", "KHR ៛"),
                ("THB", "THB ฿"),
                ("VND", "VND ₫"),
            ]),
        )
        return

    if data == "admin:settings_country":
        await query.edit_message_text(
            "Default Country",
            reply_markup=choice_menu("default_country", [
                ("Cambodia", "🇰🇭 Cambodia"),
                ("Thailand", "🇹🇭 Thailand"),
                ("Vietnam", "🇻🇳 Vietnam"),
                ("Other", "🌍 Other"),
            ]),
        )
        return

    if data == "admin:settings_quality":
        await query.edit_message_text(
            "⭐ Default Quality",
            reply_markup=choice_menu("default_quality", [
                ("100", "100%"),
                ("95", "95%"),
                ("90", "90%"),
                ("85", "85%"),
                ("80", "80%"),
            ]),
        )
        return

    if data == "admin:settings_admins":
        admins = list_admins()
        text = "👑 Admin Manager\n\nCurrent Admins:\n" + "\n".join(
            f"• {admin_id}" for admin_id, added_at in admins
        )
        if user_id != OWNER_ID:
            text += "\n\nOnly the main owner can modify admins."
        await query.edit_message_text(
            text,
            reply_markup=admin_manager_menu(admins, user_id == OWNER_ID),
        )
        return

    if data == "admin:settings_admin_add":
        if user_id != OWNER_ID:
            await query.edit_message_text("⛔ Main owner only.", reply_markup=settings_menu())
            return
        context.user_data.clear()
        context.user_data["admin_mode"] = "settings_add_admin"
        await query.edit_message_text(
            "➕ Send the Telegram numeric User ID.",
            reply_markup=back_to_settings(),
        )
        return

    if data.startswith("admin:settings_admin_remove:"):
        if user_id != OWNER_ID:
            await query.edit_message_text("⛔ Main owner only.", reply_markup=settings_menu())
            return
        admin_id = int(data.rsplit(":", 1)[1])
        removed = remove_admin(admin_id)
        await query.edit_message_text(
            f"{'✅ Admin removed.' if removed else 'Cannot remove this admin.'}",
            reply_markup=admin_manager_menu(list_admins(), True),
        )
        return

    if data == "admin:settings_announcement":
        _begin_text_edit(context, "announcement")
        await query.edit_message_text(
            "📢 Send announcement text.\nSend a single dash (-) to clear it.",
            reply_markup=back_to_settings(),
        )
        return

    if data.startswith("admin:settings_edit:"):
        key = data.rsplit(":", 1)[1]
        allowed = {
            "store_name", "store_description", "contact_telegram",
            "contact_facebook", "contact_website",
        }
        if key not in allowed:
            return
        _begin_text_edit(context, key)
        await query.edit_message_text(
            f"Send new {key.replace('_', ' ').title()}:",
            reply_markup=back_to_settings(),
        )
        return

    if data.startswith("admin:settings_set:"):
        _, _, setting, value = data.split(":", 3)
        allowed = {
            "default_language": {"km", "en"},
            "currency": {"USD", "KHR", "THB", "VND"},
            "default_country": {"Cambodia", "Thailand", "Vietnam", "Other"},
            "default_quality": {"100", "95", "90", "85", "80"},
        }
        if value not in allowed.get(setting, set()):
            return
        if setting == "default_country" and value == "Other":
            _begin_text_edit(context, "default_country")
            await query.edit_message_text(
                "🌍 Send the default country name:",
                reply_markup=back_to_settings(),
            )
            return
        set_setting(setting, value)
        await query.edit_message_text(
            f"✅ {setting.replace('_', ' ').title()}: {value}",
            reply_markup=settings_menu(),
        )


async def handle_settings_message(update, context):
    mode = context.user_data.get("admin_mode")
    if mode == "settings_logo":
        if not update.message.photo:
            await update.message.reply_text("Please send one photo.")
            return True
        set_setting("bot_logo_file_id", update.message.photo[-1].file_id)
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Bot Logo updated.",
            reply_markup=settings_menu(),
        )
        return True

    if mode == "settings_payment_qr":
        if not update.message.photo:
            await update.message.reply_text("Please send one QR photo.")
            return True
        set_setting("payment_qr_file_id", update.message.photo[-1].file_id)
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Payment QR updated.",
            reply_markup=settings_menu(),
        )
        return True

    if mode == "settings_add_admin":
        text = (update.message.text or "").strip()
        if not text.isdigit():
            await update.message.reply_text("Send a numeric Telegram User ID.")
            return True
        added = add_admin(int(text))
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Admin added." if added else "Admin already exists.",
            reply_markup=admin_manager_menu(list_admins(), True),
        )
        return True

    if mode == "settings_text":
        if update.message.photo or not update.message.text:
            await update.message.reply_text("Please send text.")
            return True
        key = context.user_data["settings_key"]
        value = update.message.text
        if key == "announcement" and value.strip() == "-":
            value = ""
        if key == "contact_telegram" and value.strip().startswith("@"):
            value = f"https://t.me/{value.strip()[1:]}"
        if key in {"contact_telegram", "contact_facebook", "contact_website"}:
            value = value.strip()
            if value and not value.lower().startswith(("http://", "https://")):
                await update.message.reply_text("Contact URL must start with http:// or https://")
                return True
        elif not value.strip():
            await update.message.reply_text("Value cannot be empty.")
            return True
        if key == "default_country" and len(value.strip()) > 30:
            await update.message.reply_text("Country name must be 30 characters or fewer.")
            return True
        set_setting(key, value)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ {key.replace('_', ' ').title()} updated.",
            reply_markup=settings_menu(),
        )
        return True

    return False
