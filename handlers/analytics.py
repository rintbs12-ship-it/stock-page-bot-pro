import csv
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile

from database.db import connect, is_admin_user


PERIODS = {
    "today": "Today",
    "7d": "7 Days",
    "30d": "30 Days",
    "month": "This Month",
    "all": "All Time",
}

PENDING_STATUSES = {
    "waiting_payment", "waiting_receipt", "waiting_admin_confirm",
    "payment_confirmed", "payment_received", "waiting_customer_info",
    "admin_processing", "admin_added", "waiting_customer_accept",
    "customer_accepted", "waiting_remove_admin",
}


def _number(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else 0.0


def _period_start(period, now):
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _within(value, start):
    if not start:
        return True
    if not value:
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") >= start
    except ValueError:
        return False


def get_analytics_data(period="all", now=None):
    if period not in PERIODS:
        period = "all"
    now = now or datetime.now()
    start = _period_start(period, now)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = now - timedelta(days=7)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    con = connect()
    orders = con.execute("""
        SELECT o.order_id, o.stock_id, o.customer_id, o.price, o.status,
               o.created_at, o.completed_at, s.followers
        FROM orders o
        LEFT JOIN stocks s ON s.id=o.stock_id
        ORDER BY o.order_id
    """).fetchall()
    customers = con.execute("""
        SELECT telegram_id, username, total_orders, completed_orders,
               total_spent, is_vip, is_banned, created_at
        FROM customer_profiles ORDER BY created_at DESC
    """).fetchall()
    payments = con.execute("""
        SELECT action, created_at FROM payment_logs ORDER BY id
    """).fetchall()
    con.close()

    selected_orders = [
        row for row in orders if _within(row[5], start)
    ]
    completed = [row for row in selected_orders if row[4] == "completed"]
    cancelled = [row for row in selected_orders if row[4] == "cancelled"]
    pending = [row for row in selected_orders if row[4] in PENDING_STATUSES]
    selected_customers = [
        row for row in customers if _within(row[7], start)
    ]
    selected_payments = [
        row for row in payments if _within(row[1], start)
    ]

    all_completed = [row for row in orders if row[4] == "completed"]
    total_revenue = sum(_number(row[3]) for row in all_completed)
    today_revenue = sum(
        _number(row[3]) for row in all_completed
        if _within(row[6], today)
    )
    monthly_revenue = sum(
        _number(row[3]) for row in all_completed
        if _within(row[6], month)
    )
    revenue = sum(_number(row[3]) for row in completed)

    category_counts = Counter()
    price_counts = Counter()
    stock_counts = Counter()
    customer_spend = defaultdict(float)
    customer_orders = Counter()
    completion_seconds = []
    for row in completed:
        followers = row[7] or 0
        if followers <= 5:
            category = "1K–5K"
        elif followers <= 10:
            category = "6K–10K"
        elif followers <= 20:
            category = "11K–20K"
        elif followers <= 30:
            category = "21K–30K"
        elif followers <= 50:
            category = "31K–50K"
        else:
            category = "51K–100K"
        category_counts[category] += 1
        price = _number(row[3])
        price_range = (
            "$0–$25" if price <= 25 else
            "$26–$50" if price <= 50 else
            "$51–$100" if price <= 100 else "$101+"
        )
        price_counts[price_range] += 1
        stock_counts[row[1]] += 1
        customer_spend[row[2]] += price
        customer_orders[row[2]] += 1
        try:
            created = datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S")
            finished = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S")
            completion_seconds.append((finished - created).total_seconds())
        except (TypeError, ValueError):
            pass

    names = {
        row[0]: (f"@{row[1]}" if row[1] else str(row[0]))
        for row in customers
    }
    customer_rankings = [
        (customer_id, names.get(customer_id, str(customer_id)), count,
         customer_spend[customer_id])
        for customer_id, count in customer_orders.items()
    ]
    top_customers = sorted(
        customer_rankings,
        key=lambda item: (item[2], item[3]),
        reverse=True,
    )[:5]
    highest_spending = sorted(
        customer_rankings, key=lambda item: item[3], reverse=True
    )[:5]
    newest = [
        (row[0], f"@{row[1]}" if row[1] else str(row[0]), row[7])
        for row in selected_customers[:5]
    ]
    returning = sum(1 for row in selected_customers if row[2] > 1)
    average_completion_hours = (
        sum(completion_seconds) / len(completion_seconds) / 3600
        if completion_seconds else 0
    )
    return {
        "period": period,
        "period_label": PERIODS[period],
        "today_orders": sum(_within(row[5], today) for row in orders),
        "week_orders": sum(_within(row[5], week) for row in orders),
        "month_orders": sum(_within(row[5], month) for row in orders),
        "orders": len(selected_orders),
        "completed": len(completed),
        "cancelled": len(cancelled),
        "pending": len(pending),
        "total_customers": len(selected_customers),
        "vip_customers": sum(row[5] == 1 for row in selected_customers),
        "banned_customers": sum(row[6] == 1 for row in selected_customers),
        "total_revenue": total_revenue,
        "today_revenue": today_revenue,
        "monthly_revenue": monthly_revenue,
        "revenue": revenue,
        "average_order": revenue / len(completed) if completed else 0,
        "top_categories": category_counts.most_common(5),
        "top_price_ranges": price_counts.most_common(5),
        "most_purchased_stock": stock_counts.most_common(1),
        "top_customers": top_customers,
        "highest_spending": highest_spending,
        "newest_customers": newest,
        "returning_customers": returning,
        "average_completion_hours": average_completion_hours,
        "pending_payments": sum(
            row[4] in {"waiting_payment", "waiting_receipt",
                       "waiting_admin_confirm"}
            for row in selected_orders
        ),
        "verified_payments": sum(row[0] == "approved" for row in selected_payments),
        "rejected_payments": sum(row[0] == "rejected" for row in selected_payments),
    }


def _bar(value, maximum):
    length = 0 if value <= 0 or maximum <= 0 else max(
        1, round((value / maximum) * 10)
    )
    return "█" * max(0, min(10, length))


def format_analytics_dashboard(data):
    chart_max = max(
        data["revenue"], data["orders"], data["total_customers"], 1
    )
    categories = "\n".join(
        f"• {name}: {count}" for name, count in data["top_categories"]
    ) or "• No sales"
    prices = "\n".join(
        f"• {name}: {count}" for name, count in data["top_price_ranges"]
    ) or "• No sales"
    stock = (
        f"Stock #{data['most_purchased_stock'][0][0]} "
        f"({data['most_purchased_stock'][0][1]})"
        if data["most_purchased_stock"] else "No sales"
    )
    top_customers = "\n".join(
        f"• {name}: {count} orders · ${spent:,.2f}"
        for _, name, count, spent in data["top_customers"]
    ) or "• No completed orders"
    highest_spending = "\n".join(
        f"• {name}: ${spent:,.2f}"
        for _, name, _, spent in data["highest_spending"]
    ) or "• No completed orders"
    newest = "\n".join(
        f"• {name} · {created}" for _, name, created in data["newest_customers"]
    ) or "• None"
    return (
        f"📊 Analytics Dashboard · {data['period_label']}\n\n"
        f"Today's Orders: {data['today_orders']}\n"
        f"This Week Orders: {data['week_orders']}\n"
        f"This Month Orders: {data['month_orders']}\n"
        f"Completed Orders: {data['completed']}\n"
        f"Cancelled Orders: {data['cancelled']}\n"
        f"Pending Orders: {data['pending']}\n\n"
        f"Total Customers: {data['total_customers']}\n"
        f"VIP Customers: {data['vip_customers']}\n"
        f"Banned Customers: {data['banned_customers']}\n\n"
        f"Total Revenue: ${data['total_revenue']:,.2f}\n"
        f"Today's Revenue: ${data['today_revenue']:,.2f}\n"
        f"Monthly Revenue: ${data['monthly_revenue']:,.2f}\n"
        f"Average Order Value: ${data['average_order']:,.2f}\n\n"
        f"Top Selling Stock Categories\n{categories}\n\n"
        f"Top Selling Price Range\n{prices}\n\n"
        f"Most Purchased Stock\n{stock}\n\n"
        f"Top Customers\n{top_customers}\n\n"
        f"Highest Spending Customers\n{highest_spending}\n\n"
        f"Newest Customers\n{newest}\n"
        f"Returning Customers: {data['returning_customers']}\n\n"
        f"Average Completion Time: "
        f"{data['average_completion_hours']:.1f} hours\n\n"
        f"Pending Payments: {data['pending_payments']}\n"
        f"Verified Payments: {data['verified_payments']}\n"
        f"Rejected Payments: {data['rejected_payments']}\n\n"
        f"Revenue   {_bar(data['revenue'], chart_max)}\n"
        f"Orders    {_bar(data['orders'], chart_max)}\n"
        f"Customers {_bar(data['total_customers'], chart_max)}"
    )


def analytics_keyboard(period):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Today", callback_data="admin:analytics_period:today"
            ),
            InlineKeyboardButton(
                "7 Days", callback_data="admin:analytics_period:7d"
            ),
            InlineKeyboardButton(
                "30 Days", callback_data="admin:analytics_period:30d"
            ),
        ],
        [
            InlineKeyboardButton(
                "This Month", callback_data="admin:analytics_period:month"
            ),
            InlineKeyboardButton(
                "All Time", callback_data="admin:analytics_period:all"
            ),
        ],
        [
            InlineKeyboardButton(
                "📄 Export TXT",
                callback_data=f"admin:analytics_export:txt:{period}",
            ),
            InlineKeyboardButton(
                "📊 Export CSV",
                callback_data=f"admin:analytics_export:csv:{period}",
            ),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin:home")],
    ])


def export_analytics_txt(data):
    return format_analytics_dashboard(data).encode("utf-8")


def export_analytics_csv(data):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Metric", "Value"])
    fields = (
        ("Period", data["period_label"]),
        ("Orders", data["orders"]),
        ("Completed Orders", data["completed"]),
        ("Cancelled Orders", data["cancelled"]),
        ("Pending Orders", data["pending"]),
        ("Customers", data["total_customers"]),
        ("VIP Customers", data["vip_customers"]),
        ("Banned Customers", data["banned_customers"]),
        ("Revenue", f"{data['revenue']:.2f}"),
        ("Total Revenue", f"{data['total_revenue']:.2f}"),
        ("Average Order Value", f"{data['average_order']:.2f}"),
        ("Pending Payments", data["pending_payments"]),
        ("Verified Payments", data["verified_payments"]),
        ("Rejected Payments", data["rejected_payments"]),
    )
    writer.writerows(fields)
    return output.getvalue().encode("utf-8")


async def handle_analytics_callback(query, context):
    if not is_admin_user(query.from_user.id):
        await query.message.reply_text("⛔ Admin only")
        return True
    data = query.data
    if data == "admin:analytics_dashboard":
        period = "all"
    elif data.startswith("admin:analytics_period:"):
        period = data.rsplit(":", 1)[1]
    elif data.startswith("admin:analytics_export:"):
        parts = data.split(":")
        if len(parts) != 4 or parts[2] not in {"txt", "csv"}:
            await query.message.reply_text("Invalid export.")
            return True
        export_type, period = parts[2], parts[3]
        analytics = get_analytics_data(period)
        payload = (
            export_analytics_txt(analytics)
            if export_type == "txt" else export_analytics_csv(analytics)
        )
        await query.message.reply_document(
            document=InputFile(
                io.BytesIO(payload),
                filename=f"analytics_{period}.{export_type}",
            )
        )
        return True
    else:
        return False
    analytics = get_analytics_data(period)
    await query.edit_message_text(
        format_analytics_dashboard(analytics),
        reply_markup=analytics_keyboard(analytics["period"]),
    )
    return True
