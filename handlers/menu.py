from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from urllib.parse import urlparse

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    Update,
)
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes
from handlers.backup import handle_backup_callback, handle_restore_document
from handlers.settings import handle_settings_callback, handle_settings_message
from handlers.orders import (
    handle_admin_order_message,
    handle_admin_order_callback,
    handle_customer_order_callback,
    handle_order_message,
    start_order,
)
from keyboards.buttons import (
    admin_home,
    admin_edit_menu,
    admin_stock_actions,
    admin_stock_picker,
    advanced_search_menu,
    audience_choices,
    confirm_delete,
    confirm_delete_all_photos,
    contact_menu,
    country_choices,
    customer_filters_menu,
    language_choices,
    main_menu,
    organic_reach_choices,
    photo_manager_menu,
    photo_multi_select_menu,
    photo_navigation,
    quality_search_menu,
    quality_percent_choices,
    quick_edit_menu,
    quick_status_choices,
    status_choices,
    statistics_dashboard_menu,
    stock_detail,
    stocks_list,
    yes_no_choices,
)
from database.db import (
    add_stock_photo,
    clear_photo_upload_session,
    create_stock,
    delete_all_stock_photos,
    delete_stock,
    delete_stock_photo,
    delete_stock_photos,
    get_all_stocks,
    get_dashboard_stats,
    get_analytics_totals,
    get_new,
    get_favorite_stocks,
    get_photo_upload_session,
    get_special,
    get_stock,
    get_stock_photo_page,
    get_stock_photo_records,
    get_stock_photos,
    get_trending_stocks,
    get_stocks_by_range,
    get_user_language,
    get_setting,
    is_admin_user,
    is_favorite,
    is_notification_subscriber,
    search_by_followers,
    search_stocks,
    set_user_language,
    toggle_favorite,
    toggle_notification_subscription,
    set_photo_upload_session,
    toggle_stock_flag,
    update_stock_field,
    increment_stock_analytics,
    mark_stock_notification_pending,
    consume_pending_stock_notification,
    get_notification_subscribers,
)

WELCOME = {
    "km": """📦 RS SERVICE - Stock Page Bot

សូមជ្រើសរើស Menu ខាងក្រោម៖
• Stock 1K ដល់ 100K
• ស្វែងរកតាម Followers
• ស្តុកថ្មី / ពិសេស / ប្រូម៉ូសិន
""",
    "en": """📦 RS SERVICE - Stock Page Bot

Please choose a menu below:
• Stock from 1K to 100K
• Search by Followers
• New Stock / Featured / Promotion
""",
}

def is_admin(user_id: int) -> bool:
    return is_admin_user(user_id)


def get_welcome_text(language):
    store_name = get_setting(
        "theme_store_title",
        get_setting("store_name", "RS SERVICE"),
    )
    description = get_setting("store_description", "Stock Page Bot")
    custom_welcome = get_setting(
        "theme_welcome_text",
        get_setting("welcome_message", ""),
    )
    announcement = get_setting("announcement", "")
    welcome_emoji = get_setting("theme_welcome_emoji", "📦")
    footer = get_setting("theme_footer_text", "")
    separator = get_setting("theme_separator", "")
    if custom_welcome:
        body = custom_welcome
    else:
        lines = WELCOME[language].splitlines()
        body = "\n".join(lines[2:]).strip()
    text = f"{welcome_emoji} {store_name} - {description}\n\n{body}"
    if announcement:
        text += f"\n\n📢 {announcement}"
    if footer:
        text += f"\n\n{separator + chr(10) if separator else ''}{footer}"
    return text


def parse_followers_value(text: str):
    cleaned = text.upper().replace("K", "").strip()
    if not cleaned.isdigit():
        raise ValueError("Followers must be numeric")
    value = int(cleaned)
    if not 1 <= value <= 100:
        raise ValueError("Followers must be between 1K and 100K")
    return value


def normalize_quality(text: str) -> str:
    quality = text.strip().upper()
    if quality not in {"A+", "A", "B", "C"}:
        raise ValueError("Quality must be A+, A, B, or C")
    return quality


def normalize_status(text: str) -> str:
    status = text.strip().lower()
    if status not in {"available", "sold"}:
        raise ValueError("Status must be available or sold")
    return status


def parse_percent(text: str) -> int:
    cleaned = text.strip().replace("%", "")
    if not cleaned.isdigit():
        raise ValueError("Percent must be numeric")
    value = int(cleaned)
    if not 0 <= value <= 100:
        raise ValueError("Percent must be between 0 and 100")
    return value


def apply_default_currency(text):
    value = text.strip()
    if not value:
        raise ValueError("Price cannot be empty")
    symbols = {"USD": "$", "KHR": "៛", "THB": "฿", "VND": "₫"}
    existing_symbol = next(
        (symbol for symbol in symbols.values() if value.startswith(symbol)),
        None,
    )
    numeric_text = value[len(existing_symbol):] if existing_symbol else value
    numeric_text = numeric_text.replace(",", "").strip()
    try:
        amount = Decimal(numeric_text)
    except InvalidOperation as exc:
        raise ValueError("Price must be numeric, for example 25 or 25.50") from exc
    if amount <= 0:
        raise ValueError("Price must be greater than zero")
    if existing_symbol:
        return value
    currency = get_setting("currency", "USD")
    return f"{symbols.get(currency, '$')}{value}"


def validate_http_url(value, field_name="Link"):
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid http:// or https:// URL")
    return value


def save_stock_draft(context, status: str) -> int:
    draft = context.user_data["draft"]
    return create_stock(
        draft["followers"],
        draft.get("country") or "Cambodia",
        draft.get("audience", ""),
        draft.get("price", ""),
        f"{draft.get('quality_percent', 100)}%",
        "",
        draft.get("fb_link", ""),
        status,
        0,
        0,
        female_percent=draft.get("female_percent", 0),
        male_percent=draft.get("male_percent", 0),
        quality_percent=draft.get("quality_percent", 100),
        real_followers=draft.get("real_followers", 1),
        organic_reach=draft.get("organic_reach", "high"),
        monetized=draft.get("monetized", 1),
        no_violation=draft.get("no_violation", 1),
        ready_transfer=draft.get("ready_transfer", 1),
        business_ready=draft.get("business_ready", 1),
    )


def begin_photo_upload(context, user_id: int, stock_id: int) -> None:
    set_photo_upload_session(user_id, stock_id)
    context.user_data.clear()
    context.user_data.update({
        "admin_mode": "upload_photos",
        "admin_step": "photo",
        "last_stock_id": stock_id,
        "photo_count": 0,
    })


async def show_admin_photo(query, stock_id, index):
    record, index, total = get_stock_photo_page(stock_id, index)
    if not record:
        if query.message.photo:
            await query.message.delete()
            await query.message.reply_text(
                "No photos for this stock.",
                reply_markup=photo_manager_menu(stock_id),
            )
        else:
            await query.edit_message_text(
                "No photos for this stock.",
                reply_markup=photo_manager_menu(stock_id),
            )
        return
    photo_id, file_id = record
    caption = f"📷 Photo {index + 1} / {total}\nStock #{stock_id}"
    markup = photo_navigation(stock_id, photo_id, index, total)
    if query.message.photo:
        await query.edit_message_media(
            media=InputMediaPhoto(file_id, caption=caption),
            reply_markup=markup,
        )
    else:
        await query.message.reply_photo(
            photo=file_id,
            caption=caption,
            reply_markup=markup,
        )


def admin_stock_text(row) -> str:
    (
        stock_id, followers, country, audience, price, quality, description,
        fb_link, status, featured, promotion, created_at,
    ) = row[:12]
    return (
        f"📦 Stock #{stock_id}\n\n"
        f"👥 Followers: {followers}K\n"
        f"💵 Price: {price}\n"
        f"🌍 Country: {country}\n"
        f"👤 Audience: {audience}\n"
        f"⭐ Quality: {quality}\n"
        f"📌 Status: {status.title()}\n"
        f"⭐ Featured: {'Yes' if featured else 'No'}\n"
        f"🔥 Promotion: {'Yes' if promotion else 'No'}\n"
        f"📷 Photos: {len(get_stock_photos(stock_id))}\n\n"
        f"📝 {description}\n"
        f"🔗 {fb_link}"
    )


def customer_stock_text(row, language):
    (
        stock_id, followers, country, audience, price, quality, description,
        fb_link, status, featured, promotion, created_at, female_percent,
        male_percent, quality_percent, real_followers, organic_reach,
        monetized, no_violation, ready_transfer, business_ready,
    ) = row
    status_text = status.title()
    status_icon = "🟢" if status == "available" else "🔴"
    stock_icon = get_setting("theme_icon_stock", "📦")
    separator = get_setting("theme_separator", "━━━━━━━━━━━━━━━━━━")
    template = get_setting("theme_stock_card_template", "")
    template_values = {
        "id": stock_id,
        "followers": followers,
        "country": country,
        "audience": audience,
        "female_percent": female_percent,
        "male_percent": male_percent,
        "price": price,
        "quality": quality_percent,
        "status": status_text,
        "facebook_link": fb_link,
    }
    if template:
        try:
            return template.format_map(template_values)
        except (KeyError, ValueError):
            pass
    if language == "en":
        benefits = [
            "✅ Real Followers" if real_followers else "❌ Real Followers",
            f"{'🟢' if organic_reach == 'high' else '🟡' if organic_reach == 'medium' else '🔴'} "
            f"{organic_reach.title()} Organic Reach",
            "💰 Monetized" if monetized else "❌ Not Monetized",
            "🛡️ No Policy Violation" if no_violation else "⚠️ Policy Violation",
            "🔄 Ready to Transfer" if ready_transfer else "❌ Not Ready to Transfer",
            "🏢 Business Ready" if business_ready else "❌ Not Business Ready",
        ]
        detail = (
            f"{stock_icon} Stock #{stock_id}\n\n"
            f"👥 Followers : {followers}K\n"
            f"🌍 Country : {country}\n"
            f"👩 Female Audience : {female_percent}%\n"
            f"👨 Male Audience : {male_percent}%\n\n"
            f"💵 Price : {price}\n"
            f"🟢 Quality : {quality_percent}%\n"
            f"{status_icon} Status : {status_text}\n\n"
        )
        detail += f"{separator}\n\n" if separator else ""
        detail += "\n".join(benefits)
        detail += f"\n\n{separator}\n\n" if separator else "\n\n"
        detail += f"🔗 Facebook Page\n{fb_link}"
        return detail
    benefits = [
        "✅ Followers ពិត" if real_followers else "❌ Followers មិនពិត",
        f"{'🟢' if organic_reach == 'high' else '🟡' if organic_reach == 'medium' else '🔴'} "
        f"Organic Reach {'ខ្ពស់' if organic_reach == 'high' else 'មធ្យម' if organic_reach == 'medium' else 'ទាប'}",
        "💰 រកចំណូលបាន" if monetized else "❌ មិនទាន់រកចំណូលបាន",
        "🛡️ គ្មានការរំលោភគោលការណ៍" if no_violation else "⚠️ មានការរំលោភគោលការណ៍",
        "🔄 ត្រៀមផ្ទេរសិទ្ធិ" if ready_transfer else "❌ មិនទាន់ត្រៀមផ្ទេរសិទ្ធិ",
        "🏢 សាកសមសម្រាប់អាជីវកម្ម" if business_ready else "❌ មិនសាកសមសម្រាប់អាជីវកម្ម",
    ]
    detail = (
        f"{stock_icon} Stock #{stock_id}\n\n"
        f"👥 Followers : {followers}K\n"
        f"🌍 Country : {country}\n"
        f"👩 Audience : ស្រីច្រើន ({female_percent}%)\n"
        f"👨 Audience : ប្រុស ({male_percent}%)\n\n"
        f"💵 Price : {price}\n"
        f"🟢 គុណភាព : {quality_percent}%\n"
        f"{status_icon} Status : {status_text}\n\n"
    )
    detail += f"{separator}\n\n" if separator else ""
    detail += "\n".join(benefits)
    detail += f"\n\n{separator}\n\n" if separator else "\n\n"
    detail += f"🔗 Facebook Page\n{fb_link}"
    return detail


def format_price(value):
    if value is None:
        return "N/A"
    return f"${value:,.2f}".replace(".00", "")


def format_statistics_dashboard(stats):
    categories = stats["categories"]
    countries = stats["countries"]
    prices = stats["prices"]
    return (
        "📊 STOCK DASHBOARD\n\n"
        f"📦 Total Stock : {stats['total']}\n"
        f"🟢 Available : {stats['available']}\n"
        f"🔴 Sold : {stats['sold']}\n"
        f"⭐ Featured : {stats['featured']}\n"
        f"🔥 Promotion : {stats['promotion']}\n"
        f"🖼 Total Photos : {stats['photos']}\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📈 Followers Categories\n\n"
        + "\n".join(f"{name} : {count}" for name, count in categories.items())
        + "\n\n━━━━━━━━━━━━━━━━\n\n"
        "💰 Price\n\n"
        f"Lowest Price : {format_price(prices['lowest'])}\n"
        f"Highest Price : {format_price(prices['highest'])}\n"
        f"Average Price : {format_price(prices['average'])}\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🌍 Countries\n\n"
        + "\n".join(f"{name} : {count}" for name, count in countries.items())
    )


def build_stock_report(stats, report_date=None):
    report_date = report_date or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    categories = stats["categories"]
    countries = stats["countries"]
    prices = stats["prices"]
    lines = [
        "=====================",
        "Stock Report",
        f"Date: {report_date}",
        "",
        f"Total Stock: {stats['total']}",
        f"Available: {stats['available']}",
        f"Sold: {stats['sold']}",
        f"Featured: {stats['featured']}",
        f"Promotion: {stats['promotion']}",
        f"Photos: {stats['photos']}",
        "",
        "Categories:",
        *[f"{name}: {count}" for name, count in categories.items()],
        "",
        "Countries:",
        *[f"{name}: {count}" for name, count in countries.items()],
        "",
        f"Lowest Price: {format_price(prices['lowest'])}",
        f"Highest Price: {format_price(prices['highest'])}",
        f"Average Price: {format_price(prices['average'])}",
        "=====================",
    ]
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    uid = update.effective_user.id
    language = get_user_language(uid)
    logo_file_id = get_setting("bot_logo_file_id", "")
    if logo_file_id:
        await update.message.reply_photo(
            photo=logo_file_id,
            caption=(
                f"{get_setting('theme_welcome_emoji', '📦')} "
                f"{get_setting('theme_store_title', get_setting('store_name', 'RS SERVICE'))}"
            ),
        )
    await update.message.reply_text(
        get_welcome_text(language),
        reply_markup=main_menu(is_admin(uid), language),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_photo_upload_session(user_id)
    context.user_data.clear()
    if is_admin(user_id):
        await update.message.reply_text(
            "✅ Action cancelled.",
            reply_markup=admin_home(),
        )
    else:
        await start(update, context)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    language = get_user_language(uid)

    # Never allow a non-admin to open an admin action, including through an
    # old Telegram message whose inline keyboard is still visible.
    if data.startswith("admin:") and not is_admin(uid):
        await query.answer("⛔ Admin only", show_alert=True)
        return

    await query.answer()

    if data.startswith("admin:backup"):
        await handle_backup_callback(query, context)
        return

    if data.startswith(("admin:order", "admin:payment")):
        await handle_admin_order_callback(query, context)
        return

    if data.startswith("admin:settings"):
        await handle_settings_callback(query, context)
        return

    if data == "home":
        context.user_data.clear()
        await query.edit_message_text(
            get_welcome_text(language),
            reply_markup=main_menu(is_admin(uid), language),
        )
        return

    if data == "language:choose":
        await query.edit_message_text(
            "🌐 សូមជ្រើសរើសភាសា / Choose language",
            reply_markup=language_choices(),
        )
        return

    if data.startswith("language:set:"):
        selected = data.rsplit(":", 1)[1]
        set_user_language(uid, selected)
        await query.edit_message_text(
            get_welcome_text(selected),
            reply_markup=main_menu(is_admin(uid), selected),
        )
        return

    if data == "orders:mine" or data.startswith("order:"):
        cancelled_stock_id = await handle_customer_order_callback(query, context)
        if cancelled_stock_id:
            row = get_stock(cancelled_stock_id)
            if row:
                await query.message.reply_text(
                    customer_stock_text(row, language),
                    reply_markup=stock_detail(
                        row[0],
                        row[7],
                        language,
                        is_admin(uid),
                        is_favorite(uid, row[0]),
                        is_notification_subscriber(uid),
                    ),
                    disable_web_page_preview=True,
                )
        return

    if data.startswith("range:"):
        _, s, e = data.split(":")
        rows = get_stocks_by_range(int(s), int(e))
        prompt = "ជ្រើស Stock ដែលចង់មើល៖" if language == "km" else "Choose a stock:"
        text = f"📁 Stock Page {s}K - {e}K\n\n{prompt}"
        if not rows:
            text += "\n\n" + ("មិនទាន់មាន Stock ទេ។" if language == "km" else "No stock available.")
        await query.edit_message_text(text, reply_markup=stocks_list(rows, language=language))
        return

    if data.startswith("special:"):
        kind = data.split(":")[1]
        if kind == "new":
            rows = get_new()
            title = "🔥 ស្តុកថ្មី" if language == "km" else "🔥 New Stock"
        elif kind == "featured":
            rows = get_special("featured")
            title = "⭐ ស្តុកពិសេស" if language == "km" else "⭐ Featured Stock"
        else:
            rows = get_special("promotion")
            title = "💰 ស្តុកប្រូម៉ូសិន" if language == "km" else "💰 Promotion Stock"
        prompt = "ជ្រើស Stock ដែលចង់មើល៖" if language == "km" else "Choose a stock:"
        text = f"{title}\n\n{prompt}"
        if not rows:
            text += "\n\n" + ("មិនទាន់មានទេ។" if language == "km" else "None available.")
        await query.edit_message_text(text, reply_markup=stocks_list(rows, language=language))
        return

    if data.startswith("stock:"):
        stock_id = int(data.split(":")[1])
        row = get_stock(stock_id)
        if not row:
            not_found = "រកមិនឃើញ Stock នេះទេ។" if language == "km" else "Stock not found."
            await query.edit_message_text(
                not_found,
                reply_markup=main_menu(is_admin(uid), language),
            )
            return

        increment_stock_analytics(stock_id, "view")
        sid, fb_link = row[0], row[7]
        await query.edit_message_text(
            customer_stock_text(row, language),
            reply_markup=stock_detail(
                sid,
                fb_link,
                language,
                is_admin(uid),
                is_favorite(uid, sid),
                is_notification_subscriber(uid),
            ),
            disable_web_page_preview=True,
        )
        return

    if data.startswith("favorite:toggle:"):
        stock_id = int(data.rsplit(":", 1)[1])
        toggle_favorite(uid, stock_id)
        row = get_stock(stock_id)
        if not row:
            await query.edit_message_text("Stock not found.")
            return
        await query.edit_message_text(
            customer_stock_text(row, language),
            reply_markup=stock_detail(
                stock_id, row[7], language, is_admin(uid),
                is_favorite(uid, stock_id),
                is_notification_subscriber(uid),
            ),
            disable_web_page_preview=True,
        )
        return

    if data == "favorites:list":
        rows = get_favorite_stocks(uid)
        title = "❤️ ស្តុកដែលចូលចិត្ត" if language == "km" else "❤️ Favorite Stocks"
        await query.edit_message_text(
            f"{title}\n\n{len(rows)} stock(s)",
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if data.startswith("notify:toggle"):
        subscribed = toggle_notification_subscription(uid)
        stock_id = int(data.rsplit(":", 1)[1]) if data.count(":") == 2 else None
        if stock_id and (row := get_stock(stock_id)):
            await query.edit_message_text(
                customer_stock_text(row, language),
                reply_markup=stock_detail(
                    stock_id, row[7], language, is_admin(uid),
                    is_favorite(uid, stock_id), subscribed,
                ),
                disable_web_page_preview=True,
            )
        else:
            message = (
                "🔔 New stock notifications enabled."
                if subscribed else "🔕 New stock notifications disabled."
            )
            await query.message.reply_text(message)
        return

    if data.startswith("openpage:"):
        stock_id = int(data.rsplit(":", 1)[1])
        row = get_stock(stock_id)
        if not row:
            await query.message.reply_text("Stock not found.")
            return
        increment_stock_analytics(stock_id, "facebook")
        await query.message.reply_text(
            "🌐 Facebook Page",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 Open Page", url=row[7] or "https://facebook.com")
            ]]),
        )
        return

    if data.startswith("share:"):
        stock_id = int(data.rsplit(":", 1)[1])
        row = get_stock(stock_id)
        if not row:
            await query.message.reply_text("Stock not found.")
            return
        share_text = (
            f"Stock #{row[0]}\nFollowers: {row[1]}K\nPrice: {row[4]}\n"
            f"Country: {row[2]}\nFacebook Page: {row[7]}"
        )
        share_url = f"https://t.me/share/url?url={quote(row[7] or '')}&text={quote(share_text)}"
        await query.message.reply_text(
            share_text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📤 Share on Telegram", url=share_url)
            ]]),
            disable_web_page_preview=True,
        )
        return

    if data.startswith("copylink:"):
        stock_id = int(data.split(":")[1])
        row = get_stock(stock_id)
        link = row[7] if row else ""
        if row:
            increment_stock_analytics(stock_id, "copy")
        label = "📋 ចម្លង Link" if language == "km" else "📋 Copy Link"
        await query.message.reply_text(f"{label}:\n{link}", disable_web_page_preview=True)
        return

    if data.startswith("photos:"):
        stock_id = int(data.split(":")[1])
        photos = get_stock_photos(stock_id)
        if not photos:
            message = (
                "មិនទាន់មានរូបភាពសម្រាប់ Stock នេះទេ។"
                if language == "km"
                else "No photos are available for this stock."
            )
            await query.message.reply_text(message)
            return
        for offset in range(0, len(photos), 10):
            batch = photos[offset:offset + 10]
            if len(batch) == 1:
                await query.message.reply_photo(batch[0])
            else:
                await query.message.reply_media_group([
                    InputMediaPhoto(file_id) for file_id in batch
                ])
        return

    if data.startswith("buy:"):
        stock_id = int(data.split(":")[1])
        increment_stock_analytics(stock_id, "buy")
        await start_order(query, context, stock_id)
        return

    if data == "contact":
        title = "📞 ទាក់ទង Admin" if language == "km" else "📞 Contact Admin"
        await query.edit_message_text(title, reply_markup=contact_menu(language))
        return

    if data == "advanced:home":
        await query.edit_message_text(
            "🔎 Advanced Search",
            reply_markup=advanced_search_menu(),
        )
        return

    if data == "advanced:country":
        context.user_data.clear()
        context.user_data["advanced_search"] = "country"
        await query.edit_message_text("🌍 Send country name:")
        return

    if data == "advanced:price":
        context.user_data.clear()
        context.user_data["advanced_search"] = "price"
        await query.edit_message_text("💰 Send price range, example: 10-100")
        return

    if data == "advanced:quality":
        await query.edit_message_text(
            "⭐ Choose Quality",
            reply_markup=quality_search_menu(),
        )
        return

    if data.startswith("advanced:quality:"):
        quality = int(data.rsplit(":", 1)[1])
        rows = search_stocks("quality", value=quality)
        await query.edit_message_text(
            f"⭐ Quality {quality}% · {len(rows)} stock(s)",
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if data.startswith("advanced:status:"):
        status = data.rsplit(":", 1)[1]
        rows = search_stocks("status", value=status)
        await query.edit_message_text(
            f"{'🟢' if status == 'available' else '🔴'} "
            f"{status.title()} · {len(rows)} stock(s)",
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if data == "filters:home":
        await query.edit_message_text(
            "🎯 Filters",
            reply_markup=customer_filters_menu(),
        )
        return

    if data == "filters:available":
        rows = search_stocks("status", value="available")
        await query.edit_message_text(
            f"🟢 Available · {len(rows)} stock(s)",
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if data == "trending:list":
        trending = get_trending_stocks(10)
        rows = [row[:7] for row in trending]
        scores = "\n".join(
            f"{index}. Stock #{row[0]} · 👀 {row[7]} · 🛒 {row[8]}"
            for index, row in enumerate(trending, start=1)
        )
        await query.edit_message_text(
            f"📈 Top 10 Trending Stocks\n\n{scores or 'No stock available.'}",
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if data == "search:start":
        context.user_data["search_mode"] = True
        prompt = (
            "🔍 សូមផ្ញើលេខ Followers ដែលចង់រក ឧទាហរណ៍៖ 15 ឬ 15K"
            if language == "km"
            else "🔍 Send the follower count to search, for example: 15 or 15K"
        )
        await query.edit_message_text(prompt)
        return

    if data == "admin:home":
        context.user_data.clear()
        await query.edit_message_text("👑 Admin Panel", reply_markup=admin_home())
        return

    if data == "admin:add":
        clear_photo_upload_session(uid)
        context.user_data.clear()
        context.user_data["admin_mode"] = "create"
        context.user_data["admin_step"] = "followers"
        context.user_data["draft"] = {}
        await query.edit_message_text(
            "🛠️ Add Stock Wizard\n\n1/15 Followers\nExample: 15 or 15K"
        )
        return

    if data == "admin:stats_export":
        stats = get_dashboard_stats()
        now = datetime.now()
        report = build_stock_report(
            stats,
            report_date=now.strftime("%Y-%m-%d %H:%M:%S"),
        )
        filename = f"stock_report_{now.strftime('%Y%m%d_%H%M%S')}.txt"
        await query.message.reply_document(
            document=InputFile(report.encode("utf-8"), filename=filename),
            caption="📄 Stock Report",
        )
        return

    if data == "admin:stats":
        stats = get_dashboard_stats()
        try:
            await query.edit_message_text(
                format_statistics_dashboard(stats),
                reply_markup=statistics_dashboard_menu(),
            )
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        return

    if data == "admin:analytics":
        totals = get_analytics_totals()
        trending = get_trending_stocks(10)
        ranking = "\n".join(
            f"{index}. Stock #{row[0]} · 👀 {row[7]} · 🛒 {row[8]}"
            for index, row in enumerate(trending, start=1)
        )
        await query.edit_message_text(
            "📈 CUSTOMER ANALYTICS\n\n"
            f"👀 Stock Views : {totals['views']}\n"
            f"🛒 Buy Clicks : {totals['buy_clicks']}\n"
            f"🌐 Facebook Clicks : {totals['facebook_clicks']}\n"
            f"📋 Copy Link Clicks : {totals['copy_clicks']}\n\n"
            "🔥 Top 10 Trending\n\n"
            f"{ranking or 'No analytics yet.'}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Refresh", callback_data="admin:analytics"),
                InlineKeyboardButton("⬅ Back", callback_data="admin:home"),
            ]]),
        )
        return

    if data == "admin:photos":
        rows = get_all_stocks()
        await query.edit_message_text(
            "🖼️ Choose a stock for Photo Manager:",
            reply_markup=admin_stock_picker(rows, "photo_manager"),
        )
        return

    if data == "admin:manage":
        rows = get_all_stocks()
        await query.edit_message_text(
            f"📂 Manage Stock ({len(rows)})\n\nChoose a stock:",
            reply_markup=admin_stock_picker(rows, "stock"),
        )
        return

    if data in {"admin:list:featured", "admin:list:promotion"}:
        kind = data.rsplit(":", 1)[1]
        rows = get_special(kind)
        await query.edit_message_text(
            f"{'⭐ Featured' if kind == 'featured' else '🔥 Promotion'} "
            f"Stock ({len(rows)})",
            reply_markup=admin_stock_picker(rows, "stock"),
        )
        return

    if data.startswith("admin:photo_manager_return:"):
        stock_id = int(data.rsplit(":", 1)[1])
        await query.message.delete()
        await query.message.reply_text(
            "🖼️ Photo Manager",
            reply_markup=photo_manager_menu(stock_id),
        )
        return

    if data.startswith("admin:photo_delete_all_confirm:"):
        stock_id = int(data.rsplit(":", 1)[1])
        deleted = delete_all_stock_photos(stock_id)
        context.user_data.pop(f"photo_multi:{stock_id}", None)
        await query.edit_message_text(
            f"✅ Deleted {deleted} photo(s).\n\n🖼️ Photo Manager",
            reply_markup=photo_manager_menu(stock_id),
        )
        return

    if data.startswith("admin:photo_delete_all:"):
        stock_id = int(data.rsplit(":", 1)[1])
        await query.edit_message_text(
            f"Delete ALL photos for Stock #{stock_id}?\n"
            "Stock information will be kept.",
            reply_markup=confirm_delete_all_photos(stock_id),
        )
        return

    if data.startswith("admin:photo_delete:"):
        _, _, stock_id, photo_id, index = data.split(":")
        stock_id, photo_id, index = int(stock_id), int(photo_id), int(index)
        delete_stock_photo(stock_id, photo_id)
        await show_admin_photo(query, stock_id, index)
        return

    if data.startswith("admin:photo_view:"):
        _, _, stock_id, index = data.split(":")
        await show_admin_photo(query, int(stock_id), int(index))
        return

    if data.startswith("admin:photo_multi_toggle:"):
        _, _, stock_id, photo_id = data.split(":")
        stock_id, photo_id = int(stock_id), int(photo_id)
        key = f"photo_multi:{stock_id}"
        selected = set(context.user_data.get(key, []))
        if photo_id in selected:
            selected.remove(photo_id)
        else:
            selected.add(photo_id)
        context.user_data[key] = list(selected)
        records = get_stock_photo_records(stock_id)
        valid_ids = {record[0] for record in records}
        selected &= valid_ids
        context.user_data[key] = list(selected)
        await query.edit_message_reply_markup(
            reply_markup=photo_multi_select_menu(stock_id, records, selected)
        )
        return

    if data.startswith("admin:photo_multi_delete:"):
        stock_id = int(data.rsplit(":", 1)[1])
        key = f"photo_multi:{stock_id}"
        selected = context.user_data.pop(key, [])
        deleted = delete_stock_photos(stock_id, selected)
        records = get_stock_photo_records(stock_id)
        await query.edit_message_text(
            f"✅ Deleted {deleted} selected photo(s).",
            reply_markup=photo_multi_select_menu(stock_id, records, set()),
        )
        return

    if data.startswith("admin:photo_multi:"):
        stock_id = int(data.rsplit(":", 1)[1])
        records = get_stock_photo_records(stock_id)
        key = f"photo_multi:{stock_id}"
        context.user_data[key] = []
        if not records:
            await query.edit_message_text(
                "No photos for this stock.",
                reply_markup=photo_manager_menu(stock_id),
            )
            return
        await query.edit_message_text(
            "Select photos to delete:",
            reply_markup=photo_multi_select_menu(stock_id, records, set()),
        )
        return

    if data.startswith("admin:photo_manager:"):
        stock_id = int(data.rsplit(":", 1)[1])
        if not get_stock(stock_id):
            await query.edit_message_text("Stock not found.", reply_markup=admin_home())
            return
        context.user_data.pop(f"photo_multi:{stock_id}", None)
        await query.edit_message_text(
            "🖼️ Photo Manager",
            reply_markup=photo_manager_menu(stock_id),
        )
        return

    if data.startswith("admin:stock:"):
        stock_id = int(data.rsplit(":", 1)[1])
        row = get_stock(stock_id)
        if not row:
            await query.edit_message_text("Stock not found.", reply_markup=admin_home())
            return
        await query.edit_message_text(
            admin_stock_text(row),
            reply_markup=admin_stock_actions(stock_id),
            disable_web_page_preview=True,
        )
        return

    if data.startswith("admin:set_status:"):
        _, _, stock_id, status = data.split(":")
        update_stock_field(int(stock_id), "status", normalize_status(status))
        row = get_stock(int(stock_id))
        await query.edit_message_text(
            admin_stock_text(row),
            reply_markup=admin_stock_actions(int(stock_id)),
            disable_web_page_preview=True,
        )
        return

    if data.startswith("admin:flag:"):
        _, _, field, stock_id = data.split(":")
        toggle_stock_flag(int(stock_id), field)
        row = get_stock(int(stock_id))
        await query.edit_message_text(
            admin_stock_text(row),
            reply_markup=admin_stock_actions(int(stock_id)),
            disable_web_page_preview=True,
        )
        return

    if data.startswith("admin:delete_confirm:"):
        stock_id = int(data.rsplit(":", 1)[1])
        deleted = delete_stock(stock_id)
        await query.edit_message_text(
            f"{'✅ Deleted' if deleted else 'Stock not found'}: Stock #{stock_id}",
            reply_markup=admin_home(),
        )
        return

    if data.startswith("admin:delete:"):
        stock_id = int(data.rsplit(":", 1)[1])
        await query.edit_message_text(
            f"🗑️ Permanently delete Stock #{stock_id} and all its photos?",
            reply_markup=confirm_delete(stock_id),
        )
        return

    if data.startswith("admin:quick_set_status:"):
        _, _, stock_id, status = data.split(":")
        stock_id = int(stock_id)
        update_stock_field(stock_id, "status", normalize_status(status))
        row = get_stock(stock_id)
        await query.edit_message_text(
            admin_stock_text(row),
            reply_markup=admin_stock_actions(stock_id),
            disable_web_page_preview=True,
        )
        return

    if data.startswith("admin:quick_status:"):
        stock_id = int(data.rsplit(":", 1)[1])
        if not get_stock(stock_id):
            await query.edit_message_text("Stock not found.", reply_markup=admin_home())
            return
        await query.edit_message_text(
            f"🟢 Choose Status for Stock #{stock_id}",
            reply_markup=quick_status_choices(stock_id),
        )
        return

    if data.startswith("admin:quick_field:"):
        _, _, stock_id, field = data.split(":")
        if field not in {"followers", "price", "fb_link"} or not get_stock(int(stock_id)):
            await query.edit_message_text("Invalid Quick Edit request.", reply_markup=admin_home())
            return
        context.user_data.clear()
        context.user_data.update({
            "admin_mode": "quick_edit",
            "edit_stock_id": int(stock_id),
            "edit_field": field,
        })
        await query.edit_message_text(
            f"⚡ Send new {field.replace('_', ' ').title()} for Stock #{stock_id}:"
        )
        return

    if data.startswith("admin:quick:"):
        stock_id = int(data.rsplit(":", 1)[1])
        if not get_stock(stock_id):
            await query.edit_message_text("Stock not found.", reply_markup=admin_home())
            return
        await query.edit_message_text(
            f"⚡ Quick Edit · Stock #{stock_id}",
            reply_markup=quick_edit_menu(stock_id),
        )
        return

    if data.startswith("admin:edit_field:"):
        _, _, stock_id, field = data.split(":")
        if field not in {
            "followers", "price", "country", "audience", "quality",
            "description", "fb_link",
        }:
            await query.edit_message_text("Invalid field.", reply_markup=admin_home())
            return
        context.user_data.clear()
        context.user_data.update({
            "admin_mode": "edit_stock",
            "edit_stock_id": int(stock_id),
            "edit_field": field,
        })
        await query.edit_message_text(
            f"✏️ Send the new value for {field.replace('_', ' ').title()}:"
        )
        return

    if data.startswith("admin:edit:"):
        stock_id = int(data.rsplit(":", 1)[1])
        await query.edit_message_text(
            f"✏️ Choose a field to edit for Stock #{stock_id}:",
            reply_markup=admin_edit_menu(stock_id),
        )
        return

    if data.startswith("admin:upload:"):
        stock_id = int(data.rsplit(":", 1)[1])
        if not get_stock(stock_id):
            await query.edit_message_text("Stock not found.", reply_markup=admin_home())
            return
        begin_photo_upload(context, uid, stock_id)
        await query.edit_message_text(
            f"📷 Uploading photos for Stock #{stock_id}\n\n"
            "Send as many photos as needed. Send /done when finished."
        )
        return

    if data.startswith("admin:wizard:country:"):
        if context.user_data.get("admin_step") != "country":
            await query.edit_message_text("This wizard has expired.", reply_markup=admin_home())
            return
        context.user_data["draft"]["country"] = data.rsplit(":", 1)[1]
        context.user_data["admin_step"] = "audience"
        await query.edit_message_text(
            "4/15 Audience type",
            reply_markup=audience_choices(),
        )
        return

    if data.startswith("admin:wizard:audience:"):
        if context.user_data.get("admin_step") != "audience":
            await query.edit_message_text("This wizard has expired.", reply_markup=admin_home())
            return
        context.user_data["draft"]["audience"] = data.rsplit(":", 1)[1]
        context.user_data["admin_step"] = "female_percent"
        await query.edit_message_text("5/15 Female percent\nExample: 55")
        return

    if data.startswith("admin:wizard:quality_percent:"):
        if context.user_data.get("admin_step") != "quality_percent":
            await query.edit_message_text("This wizard has expired.", reply_markup=admin_home())
            return
        context.user_data["draft"]["quality_percent"] = int(data.rsplit(":", 1)[1])
        context.user_data["admin_step"] = "real_followers"
        await query.edit_message_text(
            "8/15 Real Followers",
            reply_markup=yes_no_choices("real_followers"),
        )
        return

    if data.startswith("admin:wizard:reach:"):
        if context.user_data.get("admin_step") != "organic_reach":
            await query.edit_message_text("This wizard has expired.", reply_markup=admin_home())
            return
        context.user_data["draft"]["organic_reach"] = data.rsplit(":", 1)[1]
        context.user_data["admin_step"] = "monetized"
        await query.edit_message_text(
            "10/15 Monetized",
            reply_markup=yes_no_choices("monetized"),
        )
        return

    if data.startswith("admin:wizard:bool:"):
        _, _, _, field, raw_value = data.split(":")
        expected_steps = {
            "real_followers": ("organic_reach", "9/15 Organic Reach", organic_reach_choices()),
            "monetized": ("no_violation", "11/15 No Policy Violation", yes_no_choices("no_violation")),
            "no_violation": ("ready_transfer", "12/15 Ready to Transfer", yes_no_choices("ready_transfer")),
            "ready_transfer": ("business_ready", "13/15 Business Ready", yes_no_choices("business_ready")),
        }
        if context.user_data.get("admin_step") != field:
            await query.edit_message_text("This wizard has expired.", reply_markup=admin_home())
            return
        context.user_data["draft"][field] = int(raw_value)
        if field == "business_ready":
            context.user_data["admin_step"] = "fb_link"
            await query.edit_message_text("14/15 Facebook Page Link")
            return
        next_step, prompt, markup = expected_steps[field]
        context.user_data["admin_step"] = next_step
        await query.edit_message_text(prompt, reply_markup=markup)
        return

    if data.startswith("admin:wizard:status:"):
        if context.user_data.get("admin_mode") != "create" or context.user_data.get("admin_step") != "status":
            await query.edit_message_text("This wizard has expired.", reply_markup=admin_home())
            return
        status = normalize_status(data.rsplit(":", 1)[1])
        stock_id = save_stock_draft(context, status)
        mark_stock_notification_pending(stock_id)
        begin_photo_upload(context, uid, stock_id)
        await query.edit_message_text(
            f"✅ Stock #{stock_id} saved to SQLite.\n\n"
            "📷 Now send as many photos as needed. Send /done when finished.",
        )
        return

    await query.message.reply_text(
        "⚠️ This action is unavailable or has expired. Please open the menu again."
    )


async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stock_id = get_photo_upload_session(user_id) if is_admin(user_id) else None
    if stock_id:
        clear_photo_upload_session(user_id)
        if consume_pending_stock_notification(stock_id):
            row = get_stock(stock_id)
            if row:
                notification = (
                    f"🔥 New Stock #{row[0]}\n"
                    f"👥 {row[1]}K Followers\n"
                    f"💵 {row[4]}\n"
                    f"🌍 {row[2]}"
                )
                for subscriber_id in get_notification_subscribers():
                    try:
                        await context.bot.send_message(
                            chat_id=subscriber_id,
                            text=notification,
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton(
                                    "📦 View Stock",
                                    callback_data=f"stock:{stock_id}",
                                )
                            ]]),
                        )
                    except TelegramError:
                        continue
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Stock created successfully.",
            reply_markup=admin_home(),
        )
        return
    await start(update, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    language = get_user_language(user_id)
    if getattr(update.message, "document", None):
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Admin only")
            return
        if not await handle_restore_document(update, context):
            await update.message.reply_text(
                "Use Admin Panel → Backup → Restore Database first."
            )
        return

    if is_admin(user_id) and await handle_admin_order_message(update, context):
        return

    if await handle_order_message(update, context):
        return

    if is_admin(user_id) and await handle_settings_message(update, context):
        return

    active_stock_id = (
        context.user_data.get("last_stock_id")
        or (get_photo_upload_session(user_id) if is_admin(user_id) else None)
    )
    if update.message.photo and is_admin(user_id) and active_stock_id:
        stock_id = active_stock_id
        if context.user_data.get("admin_mode") != "upload_photos":
            begin_photo_upload(context, user_id, stock_id)
        file_id = update.message.photo[-1].file_id
        if add_stock_photo(stock_id, file_id):
            context.user_data["photo_count"] = context.user_data.get("photo_count", 0) + 1
        total = len(get_stock_photos(stock_id))
        await update.message.reply_text(
            f"✅ Photo saved ({total} total). Send another photo or /done."
        )
        return

    if update.message.photo:
        await update.message.reply_text(
            "Complete the Add Stock information before sending photos."
        )
        return

    if context.user_data.get("advanced_search"):
        search_type = context.user_data["advanced_search"]
        text = (update.message.text or "").strip()
        if search_type == "country":
            rows = search_stocks("country", value=text)
            label = f"🌍 {text}"
        else:
            cleaned = text.replace("$", "").replace(",", "").replace(" ", "")
            parts = cleaned.split("-", 1)
            try:
                minimum, maximum = float(parts[0]), float(parts[1])
                if minimum > maximum:
                    raise ValueError
            except (ValueError, IndexError):
                await update.message.reply_text(
                    "Invalid range. Use format: 10-100"
                )
                return
            rows = search_stocks("price", minimum=minimum, maximum=maximum)
            label = f"💰 {minimum:g}–{maximum:g}"
        context.user_data.clear()
        await update.message.reply_text(
            f"{label} · {len(rows)} stock(s)",
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if context.user_data.get("search_mode"):
        text = update.message.text.upper().replace("K", "").strip()
        if not text.isdigit():
            error = (
                "សូមបញ្ចូលលេខតែប៉ុណ្ណោះ ឧ. 15 ឬ 15K"
                if language == "km"
                else "Please enter a number, for example 15 or 15K."
            )
            await update.message.reply_text(error)
            return
        k = int(text)
        rows = search_by_followers(k)
        context.user_data["search_mode"] = False
        msg = (
            f"🔍 លទ្ធផលស្វែងរក: {k}K"
            if language == "km"
            else f"🔍 Search Result: {k}K"
        )
        if not rows:
            msg += "\n\n" + ("រកមិនឃើញ Stock ទេ។" if language == "km" else "No stock found.")
        await update.message.reply_text(
            msg,
            reply_markup=stocks_list(rows, language=language),
        )
        return

    if context.user_data.get("admin_mode") and not is_admin(update.effective_user.id):
        context.user_data.clear()
        await update.message.reply_text("⛔ Admin only")
        return

    if context.user_data.get("admin_mode"):
        if context.user_data.get("admin_mode") == "upload_photos":
            await update.message.reply_text(
                "Send a photo, or send /done to finish uploading."
            )
            return

        if context.user_data.get("admin_mode") == "quick_edit":
            stock_id = context.user_data["edit_stock_id"]
            field = context.user_data["edit_field"]
            value = update.message.text.strip()
            try:
                if field == "followers":
                    value = parse_followers_value(value)
                elif field == "fb_link":
                    value = validate_http_url(value, "Facebook Link")
                elif field == "price":
                    value = apply_default_currency(value)
            except ValueError as exc:
                await update.message.reply_text(f"Invalid value: {exc}")
                return
            update_stock_field(stock_id, field, value)
            context.user_data.clear()
            row = get_stock(stock_id)
            await update.message.reply_text(
                f"✅ {field.replace('_', ' ').title()} updated.\n\n"
                f"{admin_stock_text(row)}",
                reply_markup=admin_stock_actions(stock_id),
                disable_web_page_preview=True,
            )
            return

        if context.user_data.get("admin_mode") == "edit_stock":
            stock_id = context.user_data["edit_stock_id"]
            field = context.user_data["edit_field"]
            value = update.message.text.strip()
            try:
                if field == "followers":
                    value = parse_followers_value(value)
                elif field == "quality":
                    value = normalize_quality(value)
                elif field == "fb_link":
                    value = validate_http_url(value, "Facebook Link")
                elif field == "price":
                    value = apply_default_currency(value)
            except ValueError as exc:
                await update.message.reply_text(f"Invalid value: {exc}")
                return
            update_stock_field(stock_id, field, value)
            context.user_data.clear()
            row = get_stock(stock_id)
            await update.message.reply_text(
                f"✅ {field.replace('_', ' ').title()} updated.\n\n"
                f"{admin_stock_text(row)}",
                reply_markup=admin_stock_actions(stock_id),
                disable_web_page_preview=True,
            )
            return

        if context.user_data.get("admin_step") == "followers":
            try:
                followers = parse_followers_value(update.message.text)
            except ValueError:
                await update.message.reply_text("សូមបញ្ចូល Followers เป็นตัวเลขเท่านั้น (ឧ. 15 ឬ 15K)")
                return
            context.user_data.setdefault("draft", {})["followers"] = followers
            context.user_data["admin_step"] = "price"
            await update.message.reply_text("2/15 Price\nExample: $25")
            return

        if context.user_data.get("admin_step") == "price":
            try:
                price = apply_default_currency(update.message.text)
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return
            context.user_data.setdefault("draft", {})["price"] = price
            context.user_data["admin_step"] = "country"
            default_country = get_setting("default_country", "Cambodia")
            await update.message.reply_text(
                "3/15 Country",
                reply_markup=country_choices(default_country),
            )
            return

        if context.user_data.get("admin_step") == "country":
            await update.message.reply_text(
                "Please use the country button.",
                reply_markup=country_choices(
                    get_setting("default_country", "Cambodia")
                ),
            )
            return

        if context.user_data.get("admin_step") == "audience":
            await update.message.reply_text(
                "Please choose an Audience type.",
                reply_markup=audience_choices(),
            )
            return

        if context.user_data.get("admin_step") == "female_percent":
            try:
                female_percent = parse_percent(update.message.text)
            except ValueError as exc:
                await update.message.reply_text(f"Invalid percent: {exc}")
                return
            context.user_data["draft"]["female_percent"] = female_percent
            context.user_data["admin_step"] = "male_percent"
            await update.message.reply_text("6/15 Male percent\nExample: 45")
            return

        if context.user_data.get("admin_step") == "male_percent":
            try:
                male_percent = parse_percent(update.message.text)
            except ValueError as exc:
                await update.message.reply_text(f"Invalid percent: {exc}")
                return
            female_percent = context.user_data["draft"]["female_percent"]
            if female_percent + male_percent != 100:
                await update.message.reply_text(
                    f"Female + Male must equal 100 (currently {female_percent + male_percent})."
                )
                return
            context.user_data["draft"]["male_percent"] = male_percent
            context.user_data["admin_step"] = "quality_percent"
            await update.message.reply_text(
                "7/15 Quality percent",
                reply_markup=quality_percent_choices(
                    get_setting("default_quality", "100")
                ),
            )
            return

        if context.user_data.get("admin_step") == "quality_percent":
            await update.message.reply_text(
                "Please choose a Quality percent.",
                reply_markup=quality_percent_choices(
                    get_setting("default_quality", "100")
                ),
            )
            return

        if context.user_data.get("admin_step") in {
            "real_followers", "monetized", "no_violation",
            "ready_transfer", "business_ready",
        }:
            field = context.user_data["admin_step"]
            await update.message.reply_text(
                "Please use Yes or No.",
                reply_markup=yes_no_choices(field),
            )
            return

        if context.user_data.get("admin_step") == "organic_reach":
            await update.message.reply_text(
                "Please choose Organic Reach.",
                reply_markup=organic_reach_choices(),
            )
            return

        if context.user_data.get("admin_step") == "fb_link":
            try:
                fb_link = validate_http_url(
                    update.message.text,
                    "Facebook Link",
                )
            except ValueError as exc:
                await update.message.reply_text(f"Invalid value: {exc}")
                return
            context.user_data.setdefault("draft", {})["fb_link"] = fb_link
            context.user_data["admin_step"] = "status"
            await update.message.reply_text(
                "15/15 Status",
                reply_markup=status_choices(),
            )
            return

        if context.user_data.get("admin_step") == "status":
            try:
                status = normalize_status(update.message.text)
            except ValueError:
                await update.message.reply_text(
                    "Choose Available or Sold.",
                    reply_markup=status_choices(),
                )
                return
            stock_id = save_stock_draft(context, status)
            mark_stock_notification_pending(stock_id)
            begin_photo_upload(context, update.effective_user.id, stock_id)
            await update.message.reply_text(
                f"✅ Stock #{stock_id} saved to SQLite.\n\n"
                "📷 Now send as many photos as needed. Send /done when finished.",
            )
            return

    await start(update, context)
