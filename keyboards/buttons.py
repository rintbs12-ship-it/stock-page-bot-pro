from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import TELEGRAM_CONTACT, FACEBOOK_CONTACT
from database.db import get_menu_items, get_setting

MENUS = [
    ("📁 Menu 1 (1K-5K)", "range:1:5"),
    ("📁 Menu 2 (6K-10K)", "range:6:10"),
    ("📁 Menu 3 (11K-20K)", "range:11:20"),
    ("📁 Menu 4 (21K-30K)", "range:21:30"),
    ("📁 Menu 5 (31K-50K)", "range:31:50"),
    ("📁 Menu 6 (51K-100K)", "range:51:100"),
]


def main_menu(is_admin=False, language="km"):
    style = get_setting("theme_menu_style", "modern")
    category_buttons = [
        InlineKeyboardButton(text, callback_data=callback)
        for text, callback in MENUS
    ]
    if style == "minimal":
        rows = [[button] for button in category_buttons]
    else:
        rows = [
            category_buttons[index:index + 2]
            for index in range(0, len(category_buttons), 2)
        ]
    line = []
    for item_key, emoji, label_km, label_en, callback_data, enabled, position in get_menu_items(
        enabled_only=True
    ):
        label = label_km if language == "km" else label_en
        button = InlineKeyboardButton(
            f"{emoji} {label}".strip(),
            callback_data=callback_data,
        )
        if style in {"minimal", "classic"} or item_key in {"orders", "language"}:
            if line:
                rows.append(line)
                line = []
            rows.append([button])
        else:
            line.append(button)
            if len(line) == 2:
                rows.append(line)
                line = []
    if line:
        rows.append(line)
    if is_admin:
        admin_icon = get_setting("theme_icon_admin", "👑")
        rows.append([InlineKeyboardButton(
            f"{admin_icon} Admin Panel",
            callback_data="admin:home",
        )])
    return InlineKeyboardMarkup(rows)


def stocks_list(rows, back_to="home", language="km"):
    keyboard = []
    line = []
    for stock_id, followers, country, audience, price, quality, status in rows:
        status_icon = "🟢" if status == "available" else "🔴"
        text = f"{status_icon} {followers}K | {price}"
        line.append(InlineKeyboardButton(text, callback_data=f"stock:{stock_id}"))
        if len(line) == 2:
            keyboard.append(line)
            line = []
    if line:
        keyboard.append(line)
    back = "⬅️ ត្រឡប់" if language == "km" else "⬅️ Back"
    keyboard.append([InlineKeyboardButton(back, callback_data=back_to)])
    return InlineKeyboardMarkup(keyboard)


def stock_detail(
    stock_id, fb_link, language="km", is_admin=False,
    favorite=False, subscribed=False,
):
    if language == "km":
        view, open_page = "🖼️ មើលរូបភាព", "🌐 បើកផេក"
        copy, contact = "📋 ចម្លង Link", "💬 ទាក់ទង Admin"
        buy, back = "🛒 ទិញឥឡូវនេះ", "⬅️ ត្រឡប់"
    else:
        view, open_page = "🖼️ View Photos", "🌐 Open Page"
        copy, contact = "📋 Copy Link", "💬 Contact Admin"
        buy, back = "🛒 Buy Now", "⬅️ Back"
    favorite_label = (
        "💔 ដកចេញពីចំណូលចិត្ត" if favorite and language == "km"
        else "❤️ ចំណូលចិត្ត" if language == "km"
        else "💔 Remove Favorite" if favorite
        else "❤️ Favorite"
    )
    notification_label = (
        "🔕 បានបើកការជូនដំណឹង" if subscribed and language == "km"
        else "🔔 ជូនដំណឹង" if language == "km"
        else "🔕 Notifications On" if subscribed
        else "🔔 Notify Me"
    )
    share_label = "📤 ចែករំលែក" if language == "km" else "📤 Share"
    rows = [
        [InlineKeyboardButton(view, callback_data=f"photos:{stock_id}"),
         InlineKeyboardButton(open_page, callback_data=f"openpage:{stock_id}")],
        [InlineKeyboardButton(copy, callback_data=f"copylink:{stock_id}"),
         InlineKeyboardButton(contact, callback_data="contact")],
        [InlineKeyboardButton(
            favorite_label,
            callback_data=f"favorite:toggle:{stock_id}",
        ), InlineKeyboardButton(
            notification_label,
            callback_data=f"notify:toggle:{stock_id}",
        )],
        [InlineKeyboardButton(share_label, callback_data=f"share:{stock_id}")],
        [InlineKeyboardButton(buy, callback_data=f"buy:{stock_id}"),
         InlineKeyboardButton(back, callback_data="home")],
    ]
    if is_admin:
        rows.append([
            InlineKeyboardButton("⚡ Quick Edit", callback_data=f"admin:quick:{stock_id}"),
            InlineKeyboardButton("🛠️ Admin Actions", callback_data=f"admin:stock:{stock_id}"),
        ])
    return InlineKeyboardMarkup(rows)


def contact_menu(language="km"):
    back = "⬅️ ត្រឡប់" if language == "km" else "⬅️ Back"
    telegram_url = get_setting("contact_telegram", TELEGRAM_CONTACT)
    facebook_url = get_setting("contact_facebook", FACEBOOK_CONTACT)
    website_url = get_setting("contact_website", "")
    rows = [
        [InlineKeyboardButton("💬 Telegram Chat", url=telegram_url)],
        [InlineKeyboardButton("💬 Facebook", url=facebook_url)],
    ]
    if website_url:
        rows.append([InlineKeyboardButton("🌐 Website", url=website_url)])
    rows.append([InlineKeyboardButton(back, callback_data="home")])
    return InlineKeyboardMarkup(rows)


def language_choices():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇰🇭 Khmer", callback_data="language:set:km"),
         InlineKeyboardButton("🇺🇸 English", callback_data="language:set:en")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])


def advanced_search_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Followers", callback_data="search:start")],
        [InlineKeyboardButton("🌍 Country", callback_data="advanced:country")],
        [InlineKeyboardButton("💰 Price Range", callback_data="advanced:price")],
        [InlineKeyboardButton("⭐ Quality", callback_data="advanced:quality")],
        [InlineKeyboardButton("🟢 Available only", callback_data="advanced:status:available")],
        [InlineKeyboardButton("🔴 Sold only", callback_data="advanced:status:sold")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])


def quality_search_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{quality}%",
            callback_data=f"advanced:quality:{quality}",
        ) for quality in (100, 95, 90)],
        [InlineKeyboardButton(
            f"{quality}%",
            callback_data=f"advanced:quality:{quality}",
        ) for quality in (85, 80, 70)],
        [InlineKeyboardButton("⬅️ Back", callback_data="advanced:home")],
    ])


def customer_filters_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Featured", callback_data="special:featured"),
         InlineKeyboardButton("🔥 Promotion", callback_data="special:promotion")],
        [InlineKeyboardButton("🟢 Available", callback_data="filters:available")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")],
    ])


def admin_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Stock", callback_data="admin:add"),
         InlineKeyboardButton("📂 Manage Stock", callback_data="admin:manage")],
        [InlineKeyboardButton("📷 Upload Photos", callback_data="admin:photos"),
         InlineKeyboardButton("⭐ Featured", callback_data="admin:list:featured")],
        [InlineKeyboardButton("🔥 Promotion", callback_data="admin:list:promotion"),
         InlineKeyboardButton("📊 Statistics", callback_data="admin:stats")],
        [InlineKeyboardButton("📈 Customer Analytics", callback_data="admin:analytics")],
        [InlineKeyboardButton(
            "📊 Analytics Dashboard",
            callback_data="admin:analytics_dashboard",
        )],
        [InlineKeyboardButton("📦 Order Manager", callback_data="admin:order_manager")],
        [InlineKeyboardButton("👥 Customers", callback_data="admin:customers")],
        [InlineKeyboardButton(
            "📢 Notification Center", callback_data="admin:notify"
        )],
        [InlineKeyboardButton("📜 Audit Logs", callback_data="admin:audit")],
        [InlineKeyboardButton("🔎 Advanced Search", callback_data="admin:search")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin:settings"),
         InlineKeyboardButton("💾 Backup Manager", callback_data="admin:backup")],
        [InlineKeyboardButton("⬅️ Back", callback_data="home")]
    ])


def statistics_dashboard_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin:stats")],
        [InlineKeyboardButton("📄 Export Report", callback_data="admin:stats_export")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin:home")],
    ])


def admin_stock_actions(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Quick Edit", callback_data=f"admin:quick:{stock_id}")],
        [InlineKeyboardButton("✏️ Edit Stock", callback_data=f"admin:edit:{stock_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"admin:delete:{stock_id}")],
        [InlineKeyboardButton("🟢 Mark Available", callback_data=f"admin:set_status:{stock_id}:available"),
         InlineKeyboardButton("🔴 Mark Sold", callback_data=f"admin:set_status:{stock_id}:sold")],
        [InlineKeyboardButton("⭐ Toggle Featured", callback_data=f"admin:flag:featured:{stock_id}"),
         InlineKeyboardButton("🔥 Toggle Promotion", callback_data=f"admin:flag:promotion:{stock_id}")],
        [InlineKeyboardButton("🖼️ Photos", callback_data=f"admin:photo_manager:{stock_id}")],
        [InlineKeyboardButton("⬅️ Manage Stock", callback_data="admin:manage")],
    ])


def quick_edit_menu(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Followers", callback_data=f"admin:quick_field:{stock_id}:followers"),
         InlineKeyboardButton("💰 Price", callback_data=f"admin:quick_field:{stock_id}:price")],
        [InlineKeyboardButton("🔗 Facebook Link", callback_data=f"admin:quick_field:{stock_id}:fb_link")],
        [InlineKeyboardButton("🟢 Status", callback_data=f"admin:quick_status:{stock_id}")],
        [InlineKeyboardButton("🖼️ Photos", callback_data=f"admin:photo_manager:{stock_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"admin:stock:{stock_id}")],
    ])


def quick_status_choices(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🟢 Available",
            callback_data=f"admin:quick_set_status:{stock_id}:available",
        ), InlineKeyboardButton(
            "🔴 Sold",
            callback_data=f"admin:quick_set_status:{stock_id}:sold",
        )],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"admin:quick:{stock_id}")],
    ])


def photo_manager_menu(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Photos", callback_data=f"admin:upload:{stock_id}")],
        [InlineKeyboardButton("👀 View Photos", callback_data=f"admin:photo_view:{stock_id}:0")],
        [InlineKeyboardButton("🗑️ Delete One Photo", callback_data=f"admin:photo_view:{stock_id}:0")],
        [InlineKeyboardButton("🗑️ Delete Multiple Photos", callback_data=f"admin:photo_multi:{stock_id}")],
        [InlineKeyboardButton("🗑️ Delete All Photos", callback_data=f"admin:photo_delete_all:{stock_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"admin:stock:{stock_id}")],
    ])


def photo_navigation(stock_id, photo_id, index, total):
    previous_index = (index - 1) % total
    next_index = (index + 1) % total
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Previous", callback_data=f"admin:photo_view:{stock_id}:{previous_index}"),
         InlineKeyboardButton("➡️ Next", callback_data=f"admin:photo_view:{stock_id}:{next_index}")],
        [InlineKeyboardButton(
            "🗑️ Delete This Photo",
            callback_data=f"admin:photo_delete:{stock_id}:{photo_id}:{index}",
        )],
        [InlineKeyboardButton(
            "⬅️ Back to Photo Manager",
            callback_data=f"admin:photo_manager_return:{stock_id}",
        )],
    ])


def confirm_delete_all_photos(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Yes, delete all photos",
            callback_data=f"admin:photo_delete_all_confirm:{stock_id}",
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"admin:photo_manager:{stock_id}")],
    ])


def photo_multi_select_menu(stock_id, records, selected):
    rows = [
        [InlineKeyboardButton(
            f"{'☑️' if photo_id in selected else '☐'} Photo {index}",
            callback_data=f"admin:photo_multi_toggle:{stock_id}:{photo_id}",
        )]
        for index, (photo_id, file_id) in enumerate(records, start=1)
    ]
    rows.extend([
        [InlineKeyboardButton(
            f"🗑️ Delete Selected ({len(selected)})",
            callback_data=f"admin:photo_multi_delete:{stock_id}",
        )],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"admin:photo_manager:{stock_id}")],
    ])
    return InlineKeyboardMarkup(rows)


def admin_edit_menu(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Followers", callback_data=f"admin:edit_field:{stock_id}:followers"),
         InlineKeyboardButton("Price", callback_data=f"admin:edit_field:{stock_id}:price")],
        [InlineKeyboardButton("Country", callback_data=f"admin:edit_field:{stock_id}:country"),
         InlineKeyboardButton("Audience", callback_data=f"admin:edit_field:{stock_id}:audience")],
        [InlineKeyboardButton("Quality", callback_data=f"admin:edit_field:{stock_id}:quality"),
         InlineKeyboardButton("Description", callback_data=f"admin:edit_field:{stock_id}:description")],
        [InlineKeyboardButton("Facebook Link", callback_data=f"admin:edit_field:{stock_id}:fb_link")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"admin:stock:{stock_id}")],
    ])


def confirm_delete(stock_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, delete", callback_data=f"admin:delete_confirm:{stock_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"admin:stock:{stock_id}")],
    ])


def country_choices(country="Cambodia"):
    flags = {
        "Cambodia": "🇰🇭",
        "Thailand": "🇹🇭",
        "Vietnam": "🇻🇳",
    }
    flag = flags.get(country, "🌍")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{flag} {country}",
            callback_data=f"admin:wizard:country:{country}",
        )
    ]])


def audience_choices():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "👩 ស្រីច្រើន / Female Most",
            callback_data="admin:wizard:audience:female",
        )],
        [InlineKeyboardButton(
            "👨 ប្រុសច្រើន / Male Most",
            callback_data="admin:wizard:audience:male",
        )],
        [InlineKeyboardButton(
            "⚖️ ស្មើគ្នា / Equal",
            callback_data="admin:wizard:audience:equal",
        )],
    ])


def quality_percent_choices(default_quality="100"):
    values = []
    for value in [default_quality, "100", "95", "90", "85", "80", "70"]:
        if value not in values:
            values.append(value)
    icons = {"100": "🟢", "95": "🟢", "90": "🟢", "85": "🟡", "80": "🟡", "70": "🔴"}
    rows = []
    for offset in range(0, len(values), 2):
        rows.append([
            InlineKeyboardButton(
                f"{icons.get(value, '⭐')} {value}%",
                callback_data=f"admin:wizard:quality_percent:{value}",
            )
            for value in values[offset:offset + 2]
        ])
    return InlineKeyboardMarkup(rows)


def yes_no_choices(field):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ បាទ / Yes", callback_data=f"admin:wizard:bool:{field}:1"),
        InlineKeyboardButton("❌ ទេ / No", callback_data=f"admin:wizard:bool:{field}:0"),
    ]])


def organic_reach_choices():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 ខ្ពស់ / High", callback_data="admin:wizard:reach:high")],
        [InlineKeyboardButton("🟡 មធ្យម / Medium", callback_data="admin:wizard:reach:medium")],
        [InlineKeyboardButton("🔴 ទាប / Low", callback_data="admin:wizard:reach:low")],
    ])


def status_choices():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Available", callback_data="admin:wizard:status:available"),
            InlineKeyboardButton("🔴 Sold", callback_data="admin:wizard:status:sold"),
        ]
    ])


def admin_stock_picker(rows, action):
    keyboard = [
        [InlineKeyboardButton(
            f"#{stock_id} · {followers}K · {price}",
            callback_data=f"admin:{action}:{stock_id}",
        )]
        for stock_id, followers, country, audience, price, quality, status in rows
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin:home")])
    return InlineKeyboardMarkup(keyboard)
