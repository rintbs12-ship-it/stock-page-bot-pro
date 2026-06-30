import unittest
import tempfile
import zipfile
import asyncio
import io
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from telegram.error import Forbidden, TelegramError

from database import db
from handlers import backup
from handlers import settings
from handlers.customers import (
    handle_crm_callback,
    profile_text,
)
from handlers.notifications import (
    delivery_report_text,
    execute_broadcast,
    handle_notification_callback,
    process_due_broadcasts,
)
from handlers.analytics import (
    export_analytics_csv,
    export_analytics_txt,
    format_analytics_dashboard,
    get_analytics_data,
    handle_analytics_callback,
)
from handlers.audit import (
    PER_PAGE,
    audit_logs_keyboard,
    export_audit_csv,
)
from handlers.admin_search import (
    PER_PAGE as SEARCH_PER_PAGE,
    export_search_csv,
    search_home_menu,
)
from handlers.scheduler import (
    _advance_time,
    maintenance_menu,
    process_due_jobs,
    reminder_manager_menu,
    scheduled_announcements_menu,
    scheduler_menu,
)
from handlers.orders import (
    format_order,
    handle_admin_order_callback,
    handle_customer_order_callback,
    order_manager_detail_keyboard,
    order_manager_menu,
    order_status_menu,
    start_order,
)
from handlers.menu import (
    begin_photo_upload,
    build_stock_report,
    customer_stock_text,
    apply_default_currency,
    format_statistics_dashboard,
    get_welcome_text,
    handle_command,
    handle_text,
    normalize_quality,
    normalize_status,
    parse_percent,
    parse_followers_value,
    save_stock_draft,
    validate_http_url,
)
from keyboards.buttons import (
    admin_home,
    country_choices,
    main_menu,
    photo_manager_menu,
    quick_edit_menu,
    quality_percent_choices,
    statistics_dashboard_menu,
    stock_detail,
)
from version import PRODUCT_NAME, __version__
from health import start_health_server


class AdminWizardTests(unittest.TestCase):
    def _create_analytics_fixture(self):
        db.init_db()
        first_stock = db.create_stock(
            5, "Cambodia", "", "$25", "100%", "",
            "https://facebook.com/one", "available",
        )
        second_stock = db.create_stock(
            20, "Cambodia", "", "$50", "95%", "",
            "https://facebook.com/two", "available",
        )
        orders = [
            db.create_order(first_stock, 700, "topbuyer", "$25"),
            db.create_order(first_stock, 700, "topbuyer", "$75"),
            db.create_order(second_stock, 701, "vipbuyer", "$50"),
            db.create_order(second_stock, 702, "cancelled", "$40"),
            db.create_order(second_stock, 703, "pending", "$30"),
        ]
        rows = (
            ("completed", "2026-06-30 09:00:00", "2026-06-30 11:00:00"),
            ("completed", "2026-06-25 09:00:00", "2026-06-25 15:00:00"),
            ("completed", "2026-06-10 09:00:00", "2026-06-11 09:00:00"),
            ("cancelled", "2026-06-30 08:00:00", ""),
            ("waiting_payment", "2026-05-01 08:00:00", ""),
        )
        con = db.connect()
        for order_id, (status, created_at, completed_at) in zip(orders, rows):
            con.execute("""
                UPDATE orders
                SET status=?, created_at=?, completed_at=?, updated_at=?
                WHERE order_id=?
            """, (
                status, created_at, completed_at,
                completed_at or created_at, order_id,
            ))
        con.executemany("""
            INSERT INTO payment_logs (
                order_id, admin_id, action, reason,
                receipt_file_id, created_at
            ) VALUES (?, 619658883, ?, '', '', ?)
        """, [
            (orders[0], "approved", "2026-06-30 10:00:00"),
            (orders[3], "rejected", "2026-06-30 10:00:00"),
        ])
        con.commit()
        con.close()
        for user_id, username in (
            (700, "topbuyer"), (701, "vipbuyer"),
            (702, "cancelled"), (703, "pending"),
        ):
            db.upsert_customer_profile(user_id, username)
        db.toggle_customer_flag(701, "is_vip")
        db.toggle_customer_flag(702, "is_banned")
        con = db.connect()
        con.execute(
            "UPDATE customer_profiles SET created_at='2026-06-30 07:00:00'"
        )
        con.commit()
        con.close()
        return datetime(2026, 6, 30, 12, 0, 0)

    def test_production_release_version(self):
        self.assertEqual(PRODUCT_NAME, "Stock Page Bot Pro")
        self.assertEqual(__version__, "1.0 Stable")

    def test_analytics_dashboard_summary_and_revenue(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "analytics-summary.db")
            try:
                now = self._create_analytics_fixture()
                data = get_analytics_data("all", now)
                self.assertEqual(
                    (data["orders"], data["completed"], data["cancelled"],
                     data["pending"]),
                    (5, 3, 1, 1),
                )
                self.assertEqual(data["total_revenue"], 150.0)
                self.assertEqual(data["today_revenue"], 25.0)
                self.assertEqual(data["monthly_revenue"], 150.0)
                self.assertEqual(data["average_order"], 50.0)
                dashboard = format_analytics_dashboard(data)
                self.assertIn("📊 Analytics Dashboard", dashboard)
                self.assertIn("Revenue", dashboard)
                self.assertIn("████", dashboard)
            finally:
                db.DB_PATH = old_path

    def test_analytics_customer_statistics_and_top_customers(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "analytics-customers.db")
            try:
                now = self._create_analytics_fixture()
                data = get_analytics_data("all", now)
                self.assertEqual(data["total_customers"], 4)
                self.assertEqual(data["vip_customers"], 1)
                self.assertEqual(data["banned_customers"], 1)
                self.assertEqual(data["top_customers"][0][0], 700)
                self.assertEqual(data["top_customers"][0][2:], (2, 100.0))
                self.assertEqual(data["highest_spending"][0][0], 700)
                self.assertEqual(data["most_purchased_stock"][0][1], 2)
            finally:
                db.DB_PATH = old_path

    def test_analytics_filters_and_exports(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "analytics-export.db")
            try:
                now = self._create_analytics_fixture()
                self.assertEqual(get_analytics_data("today", now)["orders"], 2)
                self.assertEqual(get_analytics_data("7d", now)["orders"], 3)
                self.assertEqual(get_analytics_data("30d", now)["orders"], 4)
                self.assertEqual(get_analytics_data("month", now)["orders"], 4)
                all_time = get_analytics_data("all", now)
                csv_text = export_analytics_csv(all_time).decode("utf-8")
                txt_text = export_analytics_txt(all_time).decode("utf-8")
                self.assertIn("Metric,Value", csv_text)
                self.assertIn("Total Revenue,150.00", csv_text)
                self.assertIn("VIP Customers: 1", txt_text)
                self.assertIn("Verified Payments: 1", txt_text)
            finally:
                db.DB_PATH = old_path

    def test_parse_followers_value_accepts_plain_and_k_suffix(self):
        self.assertEqual(parse_followers_value("15"), 15)
        self.assertEqual(parse_followers_value("15K"), 15)
        with self.assertRaises(ValueError):
            parse_followers_value("0")
        with self.assertRaises(ValueError):
            parse_followers_value("101K")

    def test_customer_menu_has_no_admin_callback(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "menu.db")
            try:
                db.init_db()
                menu = main_menu(False)
                callbacks = [
                    button.callback_data
                    for row in menu.inline_keyboard
                    for button in row
                ]
                self.assertFalse(any(
                    value and value.startswith("admin:") for value in callbacks
                ))
                self.assertEqual(
                    [len(row) for row in menu.inline_keyboard],
                    [2, 2, 2, 2, 2, 2, 1, 1, 1],
                )
                self.assertTrue({
                    "range:1:5", "range:6:10", "range:11:20", "range:21:30",
                    "range:31:50", "range:51:100", "special:featured",
                    "special:promotion", "contact", "search:start",
                    "language:choose", "notify:toggle", "orders:mine",
                    "profile:view",
                }.issubset(set(callbacks)))
                self.assertTrue({
                    "advanced:home", "favorites:list", "trending:list",
                    "filters:home",
                }.isdisjoint(set(callbacks)))
            finally:
                db.DB_PATH = old_path

    def test_admin_panel_has_all_required_actions(self):
        callbacks = {
            button.callback_data
            for row in admin_home().inline_keyboard
            for button in row
        }
        self.assertEqual(
            callbacks,
            {
                "admin:add",
                "admin:manage",
                "admin:photos",
                "admin:list:featured",
                "admin:list:promotion",
                "admin:stats",
                "admin:analytics",
                "admin:analytics_dashboard",
                "admin:order_manager",
                "admin:customers",
                "admin:notify",
                "admin:audit",
                "admin:search",
                "admin:scheduler",
                "admin:scheduler:announcements",
                "admin:scheduler:reminders",
                "admin:scheduler:maintenance",
                "admin:settings",
                "admin:backup",
                "home",
            },
        )

    def test_scheduler_persistence_recurrence_and_admin_menus(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "scheduler.db")
            try:
                db.init_db()
                db.upsert_customer_profile(9001, "scheduled_customer")
                due = "2026-06-30 08:00:00"
                announcement_id = db.create_scheduled_job(
                    619658883, "announcement", "Morning news",
                    {"message": "Hello customers"}, "daily", due,
                )
                reminder_id = db.create_scheduled_job(
                    619658883, "custom_reminder", "Follow up",
                    {"target_id": 9001, "message": "Remember this"},
                    "one_time", due,
                )
                self.assertEqual(
                    {row[0] for row in db.list_scheduled_jobs()},
                    {announcement_id, reminder_id},
                )

                bot = SimpleNamespace(send_message=AsyncMock())
                results = asyncio.run(process_due_jobs(
                    bot, datetime(2026, 6, 30, 9, 0, 0)
                ))
                self.assertEqual(len(results), 2)
                self.assertEqual(bot.send_message.await_count, 2)
                active = db.list_scheduled_jobs(status="active")
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0][0], announcement_id)
                self.assertEqual(active[0][6], "2026-07-01 08:00:00")
                completed = db.list_scheduled_jobs(status="completed")
                self.assertEqual(completed[0][0], reminder_id)

                self.assertEqual(
                    _advance_time(
                        datetime(2026, 1, 31, 10, 0), "monthly"
                    ),
                    datetime(2026, 2, 28, 10, 0),
                )
                self.assertTrue(db.cancel_scheduled_job(announcement_id))
                self.assertFalse(db.cancel_scheduled_job(announcement_id))

                scheduler_callbacks = {
                    button.callback_data
                    for row in scheduler_menu().inline_keyboard
                    for button in row
                }
                self.assertTrue({
                    "admin:backup_auto", "admin:scheduler:announcements",
                    "admin:scheduler:reminders",
                    "admin:scheduler:maintenance",
                }.issubset(scheduler_callbacks))
                self.assertIn(
                    "admin:scheduler:announcement_new",
                    {
                        button.callback_data
                        for row in scheduled_announcements_menu([]).inline_keyboard
                        for button in row
                    },
                )
                self.assertIn(
                    "admin:scheduler:reminder_custom",
                    {
                        button.callback_data
                        for row in reminder_manager_menu([]).inline_keyboard
                        for button in row
                    },
                )
                maintenance_callbacks = {
                    button.callback_data
                    for row in maintenance_menu().inline_keyboard
                    for button in row
                }
                self.assertTrue({
                    "admin:scheduler:maint:cleanup",
                    "admin:scheduler:maint:optimize",
                    "admin:scheduler:maint:vacuum",
                    "admin:scheduler:maint:analytics",
                    "admin:scheduler:maint:health",
                    "admin:scheduler:maint:daily",
                }.issubset(maintenance_callbacks))
            finally:
                db.DB_PATH = old_path

    def test_advanced_search_persistence_filters_and_pagination(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "advanced-search.db")
            try:
                db.init_db()
                stock_ids = []
                for index in range(12):
                    stock_id = db.create_stock(
                        10 + index, "Cambodia" if index % 2 == 0 else "Thailand",
                        "Business", f"${50 + index * 10}", "100%", "Gaming page",
                        f"https://facebook.com/{index}",
                        "available" if index < 10 else "sold",
                    )
                    stock_ids.append(stock_id)
                con = db.connect()
                con.execute(
                    "UPDATE stocks SET category='Gaming' WHERE id=?",
                    (stock_ids[0],),
                )
                con.commit()
                con.close()

                for index in range(3):
                    telegram_id = 8000 + index
                    db.upsert_customer_profile(
                        telegram_id, f"user{index}", f"Name{index}", "Buyer"
                    )
                    order_id = db.create_order(
                        stock_ids[index], telegram_id, f"user{index}",
                        f"${100 + index * 100}",
                    )
                    con = db.connect()
                    con.execute(
                        "UPDATE customer_profiles SET phone=?, is_vip=?, "
                        "total_orders=?, total_spent=?, updated_at=? "
                        "WHERE telegram_id=?",
                        (
                            f"01200000{index}", 1 if index == 0 else 0,
                            index + 1, 150 + index * 200,
                            "2020-01-01 00:00:00" if index == 2
                            else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            telegram_id,
                        ),
                    )
                    con.execute(
                        "UPDATE orders SET status=?, created_at=? WHERE order_id=?",
                        (
                            ("waiting_payment", "payment_received", "completed")[index],
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            order_id,
                        ),
                    )
                    con.commit()
                    con.close()

                columns, rows, total = db.advanced_admin_search(
                    "stock", {"keyword": "Gaming"}, 1, SEARCH_PER_PAGE
                )
                self.assertEqual(total, 12)
                self.assertEqual(len(rows), SEARCH_PER_PAGE)
                _, category_rows, category_total = db.advanced_admin_search(
                    "stock", {"category": "Gaming"}
                )
                self.assertEqual(category_total, 1)
                _, price_rows, price_total = db.advanced_admin_search(
                    "stock", {"price_min": 100, "price_max": 120}
                )
                self.assertEqual(price_total, 3)
                _, vip_rows, vip_total = db.advanced_admin_search(
                    "customer", {"smart": "vip"}
                )
                self.assertEqual(vip_total, 1)
                self.assertEqual(vip_rows[0][1], 8000)
                _, inactive_rows, inactive_total = db.advanced_admin_search(
                    "customer", {"smart": "inactive"}
                )
                self.assertEqual(inactive_total, 1)
                self.assertEqual(inactive_rows[0][1], 8002)
                _, phone_rows, phone_total = db.advanced_admin_search(
                    "customer", {"phone": "012000001"}
                )
                self.assertEqual(phone_total, 1)
                _, paid_rows, paid_total = db.advanced_admin_search(
                    "order", {"status": "paid"}
                )
                self.assertEqual(paid_total, 1)
                self.assertEqual(paid_rows[0][2], 8001)

                global_rows = db.global_admin_search("Name1")
                self.assertTrue(any(row[0] == "Customer" for row in global_rows))
                global_order = db.global_admin_search("2")
                self.assertTrue(any(row[0] == "Order" for row in global_order))

                saved_id = db.save_search_filter(
                    619658883, "VIP buyers", "customer", {"smart": "vip"}
                )
                saved = db.get_saved_filters(619658883)
                self.assertEqual(saved[0][0], saved_id)
                self.assertEqual(saved[0][3], {"smart": "vip"})
                db.add_recent_search(
                    619658883, "stock", query="Gaming",
                    filters={"country": "Cambodia"},
                )
                recent = db.get_recent_searches(619658883)
                self.assertEqual(recent[0][2], "Gaming")
                self.assertEqual(recent[0][3], {"country": "Cambodia"})
                csv_text = export_search_csv({
                    "type": "stock", "filters": {"keyword": "Gaming"}
                }).decode("utf-8-sig")
                self.assertEqual(len(csv_text.splitlines()), 13)
                self.assertIn("followers", csv_text.splitlines()[0])

                callbacks = {
                    button.callback_data
                    for row in search_home_menu().inline_keyboard
                    for button in row
                }
                self.assertTrue({
                    "admin:search:global", "admin:search:type:stock",
                    "admin:search:type:customer", "admin:search:type:order",
                    "admin:search:smart", "admin:search:saved",
                    "admin:search:recent",
                }.issubset(callbacks))
            finally:
                db.DB_PATH = old_path

    def test_audit_log_migration_filters_search_pagination_and_csv(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "audit.db")
            try:
                db.init_db()
                con = db.connect()
                columns = {
                    row[1] for row in con.execute(
                        "PRAGMA table_info(audit_logs)"
                    ).fetchall()
                }
                con.close()
                self.assertEqual(columns, {
                    "id", "admin_id", "admin_name", "action", "target",
                    "details", "created_at",
                })
                for index in range(25):
                    db.add_audit_log(
                        100 if index < 20 else 200,
                        "DORN" if index < 20 else "SECOND",
                        "Approve Payment" if index % 2 == 0 else "Edit Stock",
                        f"Order #{index}",
                        f"Customer {500 + index}",
                    )
                rows, total = db.get_audit_logs(page=1, per_page=PER_PAGE)
                self.assertEqual((len(rows), total), (20, 25))
                second_page, _ = db.get_audit_logs(page=2, per_page=PER_PAGE)
                self.assertEqual(len(second_page), 5)
                admin_rows, admin_total = db.get_audit_logs(admin_id=200)
                self.assertEqual((len(admin_rows), admin_total), (5, 5))
                action_rows, action_total = db.get_audit_logs(
                    action="Approve Payment"
                )
                self.assertEqual(action_total, 13)
                self.assertTrue(all(row[3] == "Approve Payment" for row in action_rows))
                search_rows, search_total = db.get_audit_logs(search="Order #24")
                self.assertEqual((len(search_rows), search_total), (1, 1))
                keyboard = audit_logs_keyboard(1, 25)
                callbacks = {
                    button.callback_data
                    for row in keyboard.inline_keyboard for button in row
                }
                self.assertIn("admin:audit:page:2", callbacks)
                csv_text = export_audit_csv({
                    "period": "all", "admin_id": None,
                    "action": None, "search": "",
                }).decode("utf-8-sig")
                self.assertEqual(len(csv_text.splitlines()), 26)
                self.assertIn("Approve Payment", csv_text)
            finally:
                db.DB_PATH = old_path

    def test_wizard_choice_validation(self):
        self.assertEqual(normalize_quality("a+"), "A+")
        self.assertEqual(normalize_status("Sold"), "sold")
        with self.assertRaises(ValueError):
            normalize_quality("excellent")
        with self.assertRaises(ValueError):
            normalize_status("pending")
        self.assertEqual(parse_percent("55%"), 55)
        with self.assertRaises(ValueError):
            parse_percent("101")
        self.assertEqual(validate_http_url("https://facebook.com/page"), "https://facebook.com/page")
        with self.assertRaises(ValueError):
            validate_http_url("not-a-link")

    def test_safe_migration_and_language_preference(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "migration.db")
            try:
                db.init_db()
                db.init_db()
                con = db.connect()
                columns = {
                    row[1] for row in con.execute(
                        "PRAGMA table_info(stocks)"
                    ).fetchall()
                }
                con.close()
                self.assertTrue({
                    "female_percent", "male_percent", "quality_percent",
                    "real_followers", "organic_reach", "monetized",
                    "no_violation", "ready_transfer", "business_ready",
                    "category",
                }.issubset(columns))
                report = db.verify_database()
                self.assertEqual(report["integrity"], "ok")
                self.assertEqual(report["foreign_key_errors"], [])
                self.assertEqual(report["missing_tables"], [])
                self.assertEqual(report["missing_indexes"], [])
                self.assertEqual(db.get_setting("cache_test", "missing"), "missing")
                db.set_setting("cache_test", "ready")
                self.assertEqual(db.get_setting("cache_test"), "ready")
                self.assertFalse(db.is_admin_user(987654321))
                self.assertTrue(db.add_admin(987654321))
                self.assertTrue(db.is_admin_user(987654321))
                self.assertTrue(db.remove_admin(987654321))
                self.assertFalse(db.is_admin_user(987654321))
                self.assertEqual(db.get_user_language(100), "km")
                self.assertTrue(db.set_user_language(100, "en"))
                self.assertEqual(db.get_user_language(100), "en")
            finally:
                db.DB_PATH = old_path

    def test_create_stock_persists_all_wizard_fields(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "test.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    25, "Cambodia", "Women", "$125", "A+",
                    "Test description", "https://facebook.com/test",
                    "available",
                )
                self.assertEqual(
                    db.get_stock(stock_id)[1:11],
                    (
                        25, "Cambodia", "Women", "$125", "A+",
                        "Test description", "https://facebook.com/test",
                        "available", 0, 0,
                    ),
                )
            finally:
                db.DB_PATH = old_path

    def test_stock_detail_is_formatted_in_both_languages(self):
        row = (
            7, 15, "Cambodia", "female", "$25", "95%", "", "https://fb.test",
            "available", 0, 0, "", 55, 45, 95, 1, "high", 1, 1, 1, 1,
        )
        khmer = customer_stock_text(row, "km")
        english = customer_stock_text(row, "en")
        self.assertIn("ស្រីច្រើន (55%)", khmer)
        self.assertIn("គុណភាព : 95%", khmer)
        self.assertIn("Female Audience : 55%", english)
        self.assertIn("Quality : 95%", english)

    def test_stock_detail_buttons_are_localized(self):
        khmer_labels = {
            button.text
            for row in stock_detail(1, "https://facebook.com", "km").inline_keyboard
            for button in row
        }
        english_labels = {
            button.text
            for row in stock_detail(1, "https://facebook.com", "en").inline_keyboard
            for button in row
        }
        self.assertEqual(khmer_labels, {
            "🖼️ មើលរូបភាព", "🌐 បើកផេក", "📋 ចម្លង Link",
            "💬 ទាក់ទង Admin", "🛒 ទិញឥឡូវនេះ", "⬅️ ត្រឡប់",
            "❤️ ចំណូលចិត្ត", "🔔 ជូនដំណឹង", "📤 ចែករំលែក",
        })
        self.assertEqual(english_labels, {
            "🖼️ View Photos", "🌐 Open Page", "📋 Copy Link",
            "💬 Contact Admin", "🛒 Buy Now", "⬅️ Back",
            "❤️ Favorite", "🔔 Notify Me", "📤 Share",
        })

    def test_quick_edit_menu_has_required_actions(self):
        callbacks = {
            button.callback_data
            for row in quick_edit_menu(42).inline_keyboard
            for button in row
        }
        self.assertEqual(callbacks, {
            "admin:quick_field:42:followers",
            "admin:quick_field:42:price",
            "admin:quick_field:42:fb_link",
            "admin:quick_status:42",
            "admin:photo_manager:42",
            "admin:stock:42",
        })

    def test_photo_manager_has_all_required_actions(self):
        callbacks = {
            button.callback_data
            for row in photo_manager_menu(9).inline_keyboard
            for button in row
        }
        self.assertEqual(callbacks, {
            "admin:upload:9",
            "admin:photo_view:9:0",
            "admin:photo_multi:9",
            "admin:photo_delete_all:9",
            "admin:stock:9",
        })

    def test_unlimited_photo_file_ids_are_persisted_without_duplicates(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "photos.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$10", "A", "", "",
                    "available",
                )
                for number in range(30):
                    self.assertTrue(db.add_stock_photo(stock_id, f"file-{number}"))
                self.assertFalse(db.add_stock_photo(stock_id, "file-0"))
                self.assertEqual(
                    db.get_stock_photos(stock_id),
                    [f"file-{number}" for number in range(30)],
                )
                records = db.get_stock_photo_records(stock_id)
                record, index, total = db.get_stock_photo_page(stock_id, 999)
                self.assertEqual((record, index, total), (records[-1], 29, 30))
                self.assertTrue(db.delete_stock_photo(stock_id, records[1][0]))
                selected_ids = [records[3][0], records[5][0]]
                self.assertEqual(db.delete_stock_photos(stock_id, selected_ids), 2)
                self.assertEqual(len(db.get_stock_photos(stock_id)), 27)
                self.assertEqual(db.delete_all_stock_photos(stock_id), 27)
                self.assertEqual(db.get_stock_photos(stock_id), [])
                self.assertIsNotNone(db.get_stock(stock_id))
            finally:
                db.DB_PATH = old_path

    def test_manage_stock_updates_flags_status_and_deletes_photos(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "manage.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    8, "Cambodia", "All", "$20", "B", "Before",
                    "https://facebook.com/test", "available",
                )
                db.add_stock_photo(stock_id, "photo-1")
                self.assertTrue(db.update_stock_field(stock_id, "description", "After"))
                self.assertEqual(db.toggle_stock_flag(stock_id, "featured"), 1)
                self.assertEqual(db.toggle_stock_flag(stock_id, "promotion"), 1)
                self.assertTrue(db.update_stock_field(stock_id, "status", "sold"))
                row = db.get_stock(stock_id)
                self.assertEqual((row[6], row[8], row[9], row[10]), ("After", "sold", 1, 1))
                self.assertTrue(db.delete_stock(stock_id))
                self.assertIsNone(db.get_stock(stock_id))
                self.assertEqual(db.get_stock_photos(stock_id), [])
            finally:
                db.DB_PATH = old_path

    def test_statistics_include_all_required_counts(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "stats.db")
            try:
                db.init_db()
                first = db.create_stock(
                    5, "Cambodia", "", "$10", "A", "", "",
                    "available", featured=1,
                )
                db.create_stock(
                    6, "Cambodia", "", "$20", "B", "", "",
                    "sold", promotion=1,
                )
                db.add_stock_photo(first, "photo-a")
                db.add_stock_photo(first, "photo-b")
                self.assertEqual(db.get_stock_stats(), (2, 1, 1, 1, 1, 2))
            finally:
                db.DB_PATH = old_path

    def test_dashboard_uses_sqlite_aggregates_and_formats_report(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "dashboard.db")
            try:
                db.init_db()
                first = db.create_stock(
                    3, "Cambodia", "", "$10", "A", "", "",
                    "available", featured=1,
                )
                db.create_stock(
                    8, "Thailand", "", "$20", "A", "", "",
                    "sold", promotion=1,
                )
                db.create_stock(
                    55, "Vietnam", "", "$1,000", "A", "", "",
                    "available",
                )
                db.create_stock(
                    25, "Laos", "", "invalid", "A", "", "",
                    "available",
                )
                db.add_stock_photo(first, "photo-1")
                stats = db.get_dashboard_stats()
                self.assertEqual(
                    (
                        stats["total"], stats["available"], stats["sold"],
                        stats["featured"], stats["promotion"], stats["photos"],
                    ),
                    (4, 3, 1, 1, 1, 1),
                )
                self.assertEqual(stats["categories"], {
                    "1K–5K": 1, "6K–10K": 1, "11K–20K": 0,
                    "21K–30K": 1, "31K–50K": 0, "51K–100K": 1,
                })
                self.assertEqual(stats["countries"], {
                    "Cambodia": 1, "Thailand": 1, "Vietnam": 1, "Others": 1,
                })
                self.assertEqual(stats["prices"], {
                    "lowest": 10.0, "highest": 1000.0,
                    "average": 1030.0 / 3,
                })
                dashboard = format_statistics_dashboard(stats)
                report = build_stock_report(stats, "2026-06-30 10:00:00")
                self.assertIn("1K–5K : 1", dashboard)
                self.assertIn("Average Price : $343.33", dashboard)
                self.assertIn("Date: 2026-06-30 10:00:00", report)
                self.assertIn("Vietnam: 1", report)
            finally:
                db.DB_PATH = old_path

    def test_statistics_dashboard_buttons(self):
        callbacks = {
            button.callback_data
            for row in statistics_dashboard_menu().inline_keyboard
            for button in row
        }
        self.assertEqual(
            callbacks,
            {"admin:stats", "admin:stats_export", "admin:home"},
        )

    def test_backup_create_extract_restore_history_and_delete(self):
        old_db_path = db.DB_PATH
        old_backup_db_path = backup.DB_PATH
        old_backup_dir = backup.BACKUP_DIR
        with tempfile.TemporaryDirectory() as folder:
            database_path = Path(folder) / "database.db"
            db.DB_PATH = str(database_path)
            backup.DB_PATH = str(database_path)
            backup.BACKUP_DIR = Path(folder) / "backups"
            try:
                db.init_db()
                stock_id = db.create_stock(
                    12, "Cambodia", "", "$25", "A", "", "",
                    "available",
                )
                db.add_stock_photo(stock_id, "telegram-photo")
                db.set_setting("auto_backup_schedule", "weekly")
                archive = backup.create_backup(
                    datetime(2026, 6, 30, 12, 30, 45)
                )
                self.assertEqual(archive.name, "backup_20260630_123045.zip")
                with zipfile.ZipFile(archive) as zipped:
                    self.assertEqual(
                        set(zipped.namelist()),
                        {"database.db", "settings.json", "backup_info.json"},
                    )
                restored_bytes = backup.extract_database_bytes(
                    archive.name,
                    archive.read_bytes(),
                )
                db.delete_stock(stock_id)
                self.assertIsNone(db.get_stock(stock_id))
                backup.restore_database_bytes(restored_bytes)
                self.assertIsNotNone(db.get_stock(stock_id))
                self.assertEqual(
                    db.get_stock_photos(stock_id),
                    ["telegram-photo"],
                )
                history = backup.list_backups()
                self.assertGreaterEqual(len(history), 2)
                self.assertTrue(backup.delete_backup(archive.name))
                self.assertFalse(backup.delete_backup("../../database.db"))
            finally:
                db.DB_PATH = old_db_path
                backup.DB_PATH = old_backup_db_path
                backup.BACKUP_DIR = old_backup_dir

    def test_auto_backup_schedule_is_persisted_and_respects_due_time(self):
        old_db_path = db.DB_PATH
        old_backup_db_path = backup.DB_PATH
        old_backup_dir = backup.BACKUP_DIR
        with tempfile.TemporaryDirectory() as folder:
            database_path = Path(folder) / "database.db"
            db.DB_PATH = str(database_path)
            backup.DB_PATH = str(database_path)
            backup.BACKUP_DIR = Path(folder) / "backups"
            try:
                db.init_db()
                db.set_setting("auto_backup_schedule", "daily")
                db.set_setting("auto_backup_keep", "1")
                first = backup.run_due_auto_backup(datetime(2026, 6, 1, 8, 0, 0))
                second = backup.run_due_auto_backup(datetime(2026, 6, 1, 12, 0, 0))
                third = backup.run_due_auto_backup(datetime(2026, 6, 2, 8, 0, 0))
                self.assertIsNotNone(first)
                self.assertIsNone(second)
                self.assertIsNotNone(third)
                self.assertEqual(len(backup.list_backups()), 1)
                self.assertEqual(db.get_setting("auto_backup_schedule"), "daily")
            finally:
                db.DB_PATH = old_db_path
                backup.DB_PATH = old_backup_db_path
                backup.BACKUP_DIR = old_backup_dir

    def test_backup_manager_has_all_required_buttons(self):
        callbacks = {
            button.callback_data
            for row in backup.backup_manager_menu().inline_keyboard
            for button in row
        }
        self.assertEqual(callbacks, {
            "admin:backup_create",
            "admin:backup_export",
            "admin:backup_restore",
            "admin:backup_delete_menu",
            "admin:backup_history",
            "admin:backup_import",
            "admin:backup_logs",
            "admin:backup_auto",
            "admin:home",
        })

    def test_backup_exports_import_logs_and_invalid_restore(self):
        old_db_path = db.DB_PATH
        old_backup_db_path = backup.DB_PATH
        old_backup_dir = backup.BACKUP_DIR
        with tempfile.TemporaryDirectory() as folder:
            database_path = Path(folder) / "database.db"
            db.DB_PATH = str(database_path)
            backup.DB_PATH = str(database_path)
            backup.BACKUP_DIR = Path(folder) / "backups"
            try:
                db.init_db()
                db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                raw = backup.export_database_bytes()
                self.assertTrue(raw.startswith(b"SQLite format 3\x00"))
                with zipfile.ZipFile(
                    io.BytesIO(backup.export_database_zip_bytes())
                ) as archive:
                    self.assertIn("database.db", archive.namelist())
                with zipfile.ZipFile(
                    io.BytesIO(backup.export_database_csv_bytes())
                ) as archive:
                    self.assertIn("stocks.csv", archive.namelist())
                    self.assertIn("customer_profiles.csv", archive.namelist())

                imported = backup.extract_database_bytes(
                    "database.db", raw
                )
                backup.restore_database_bytes(
                    imported,
                    admin_id=619658883,
                    action="import",
                    filename="database.db",
                )
                self.assertEqual(db.get_backup_logs(1)[0][1], "import")
                with self.assertRaises(ValueError):
                    backup.extract_database_bytes("invalid.db", b"not sqlite")
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    backup.extract_database_bytes(
                        "invalid.zip",
                        io.BytesIO().getvalue(),
                    )
            finally:
                db.DB_PATH = old_db_path
                backup.DB_PATH = old_backup_db_path
                backup.BACKUP_DIR = old_backup_dir

    def test_settings_center_and_dynamic_admin_storage(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "settings.db")
            try:
                db.init_db()
                self.assertTrue(db.is_admin_user(619658883))
                self.assertTrue(db.add_admin(123456))
                self.assertTrue(db.is_admin_user(123456))
                self.assertTrue(db.remove_admin(123456))
                self.assertFalse(db.remove_admin(619658883))
                db.set_setting("store_name", "My Store")
                db.set_setting("announcement", "New stock today!")
                self.assertIn("My Store", get_welcome_text("en"))
                self.assertIn("New stock today!", get_welcome_text("en"))
                callbacks = {
                    button.callback_data
                    for row in settings.settings_menu().inline_keyboard
                    for button in row
                }
                self.assertEqual(callbacks, {
                    "admin:settings_profile", "admin:settings_logo",
                    "admin:settings_payment_qr",
                    "admin:settings_welcome", "admin:settings_contact",
                    "admin:settings_language", "admin:settings_currency",
                    "admin:settings_country", "admin:settings_quality",
                    "admin:settings_admins", "admin:settings_announcement",
                    "admin:settings_menu",
                    "admin:settings_theme",
                    "admin:home",
                })
            finally:
                db.DB_PATH = old_path

    def test_default_language_currency_country_and_quality_settings(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "defaults.db")
            try:
                db.init_db()
                db.set_setting("default_language", "en")
                db.set_setting("currency", "THB")
                db.set_setting("default_country", "Thailand")
                db.set_setting("default_quality", "90")
                self.assertEqual(db.get_user_language(999), "en")
                self.assertEqual(apply_default_currency("250"), "฿250")
                country_button = country_choices("Thailand").inline_keyboard[0][0]
                self.assertEqual(
                    country_button.callback_data,
                    "admin:wizard:country:Thailand",
                )
                quality_callbacks = {
                    button.callback_data
                    for row in quality_percent_choices("90").inline_keyboard
                    for button in row
                }
                self.assertIn("admin:wizard:quality_percent:90", quality_callbacks)
            finally:
                db.DB_PATH = old_path

    def test_menu_editor_persists_text_emoji_enabled_order_and_reset(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "menu-editor.db")
            try:
                db.init_db()
                items = db.get_menu_items()
                self.assertEqual(len(items), 9)
                self.assertEqual(
                    [(item[1], item[2]) for item in items],
                    [
                        ("🔥", "ផុសថ្មី"), ("⭐", "ពិសេស"),
                        ("💰", "ប្រូម៉ូសិន"), ("📞", "ទាក់ទង"),
                        ("🔍", "ស្វែងរក Followers"), ("🔔", "Notify Me"),
                        ("📦", "My Orders"), ("👤", "My Profile"),
                        ("🌐", "Language"),
                    ],
                )

                self.assertTrue(db.update_menu_item("new", "label_km", "New Launch"))
                self.assertTrue(db.update_menu_item("new", "label_en", "New Launch"))
                self.assertTrue(db.update_menu_item("new", "emoji", "🚀"))
                menu = main_menu(False, "km")
                labels = [
                    button.text
                    for row in menu.inline_keyboard
                    for button in row
                ]
                self.assertIn("🚀 New Launch", labels)

                self.assertTrue(db.update_menu_item("contact", "enabled", False))
                callbacks = {
                    button.callback_data
                    for row in main_menu(False).inline_keyboard
                    for button in row
                }
                self.assertNotIn("contact", callbacks)

                self.assertTrue(db.move_menu_item("featured", "down"))
                ordered_keys = [item[0] for item in db.get_menu_items()]
                self.assertGreater(
                    ordered_keys.index("featured"),
                    ordered_keys.index("promotion"),
                )

                db.reset_menu_items()
                reset_new = db.get_menu_item("new")
                reset_contact = db.get_menu_item("contact")
                self.assertEqual(reset_new[1:3], ("🔥", "ផុសថ្មី"))
                self.assertEqual(reset_new[5:], (1, 10))
                self.assertEqual(reset_contact[5], 1)
            finally:
                db.DB_PATH = old_path

    def test_theme_settings_apply_immediately_to_welcome_menu_and_stock_card(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "theme.db")
            try:
                db.init_db()
                db.set_setting("theme_welcome_emoji", "🚀")
                db.set_setting("theme_store_title", "Rocket Store")
                db.set_setting("theme_welcome_text", "Welcome aboard!")
                db.set_setting("theme_footer_text", "Thank you.")
                db.set_setting("theme_separator", "══════════════")
                welcome = get_welcome_text("en")
                self.assertIn("🚀 Rocket Store", welcome)
                self.assertIn("Welcome aboard!", welcome)
                self.assertIn("══════════════\nThank you.", welcome)

                db.set_setting("theme_menu_style", "minimal")
                minimal = main_menu(False, "en")
                self.assertTrue(all(len(row) == 1 for row in minimal.inline_keyboard))
                db.set_setting("theme_menu_style", "classic")
                classic = main_menu(False, "en")
                self.assertEqual(
                    [len(row) for row in classic.inline_keyboard[:3]],
                    [2, 2, 2],
                )
                self.assertTrue(all(
                    len(row) == 1 for row in classic.inline_keyboard[3:]
                ))

                db.set_setting(
                    "theme_stock_card_template",
                    "🪪 Stock #{id}\nPrice: {price}\nFollowers: {followers}K",
                )
                row = (
                    7, 15, "Cambodia", "female", "$25", "95%", "",
                    "https://fb.test", "available", 0, 0, "",
                    55, 45, 95, 1, "high", 1, 1, 1, 1,
                )
                self.assertEqual(
                    customer_stock_text(row, "en"),
                    "🪪 Stock #7\nPrice: $25\nFollowers: 15K",
                )

                db.set_setting("theme_stock_card_template", "")
                db.set_setting("theme_separator", "")
                detail = customer_stock_text(row, "en")
                self.assertNotIn("━━━━━━━━", detail)
                self.assertNotIn("════════", detail)
            finally:
                db.DB_PATH = old_path

    def test_customer_favorites_notifications_search_and_analytics(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "customer-pro.db")
            try:
                db.init_db()
                first = db.create_stock(
                    5, "Cambodia", "", "$25", "95%", "", "https://fb/1",
                    "available", quality_percent=95,
                )
                second = db.create_stock(
                    20, "Thailand", "", "$100", "85%", "", "https://fb/2",
                    "sold", quality_percent=85,
                )

                self.assertTrue(db.toggle_favorite(700, first))
                self.assertTrue(db.is_favorite(700, first))
                self.assertEqual(db.get_favorite_stocks(700)[0][0], first)
                self.assertFalse(db.toggle_favorite(700, first))

                self.assertTrue(db.toggle_notification_subscription(700))
                self.assertTrue(db.is_notification_subscriber(700))
                self.assertEqual(db.get_notification_subscribers(), [700])
                db.mark_stock_notification_pending(first)
                self.assertTrue(db.consume_pending_stock_notification(first))
                self.assertFalse(db.consume_pending_stock_notification(first))

                self.assertEqual(db.search_stocks("country", value="thailand")[0][0], second)
                self.assertEqual(db.search_stocks("quality", value=95)[0][0], first)
                self.assertEqual(db.search_stocks("status", value="sold")[0][0], second)
                self.assertEqual(
                    {row[0] for row in db.search_stocks("price", minimum=20, maximum=30)},
                    {first},
                )

                for event in ("view", "view", "buy", "facebook", "copy"):
                    self.assertTrue(db.increment_stock_analytics(first, event))
                totals = db.get_analytics_totals()
                self.assertEqual(totals, {
                    "views": 2, "buy_clicks": 1,
                    "facebook_clicks": 1, "copy_clicks": 1,
                })
                trending = db.get_trending_stocks(10)
                self.assertEqual(trending[0][0], first)
                self.assertEqual(trending[0][7:9], (2, 1))
            finally:
                db.DB_PATH = old_path

    def test_order_lifecycle_enforces_owner_and_status_transitions(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "orders.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    15, "Cambodia", "", "$50", "95%", "", "https://fb/page",
                    "available", quality_percent=95,
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$50")
                self.assertEqual(db.get_order(order_id)[5], "waiting_payment")
                self.assertFalse(db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, customer_id=701
                ))
                self.assertTrue(db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, customer_id=700
                ))
                self.assertTrue(db.update_order_field(
                    order_id, "receipt_file_id", "receipt-file",
                    "waiting_receipt", customer_id=700,
                ))
                self.assertTrue(db.transition_order(
                    order_id, "waiting_admin_confirm", {"waiting_receipt"}, customer_id=700
                ))
                self.assertTrue(db.transition_order(
                    order_id, "payment_confirmed", {"waiting_admin_confirm"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "waiting_customer_info", {"payment_confirmed"}
                ))
                self.assertTrue(db.update_order_field(
                    order_id, "facebook_profile_link", "https://facebook.com/buyer",
                    "waiting_customer_info", customer_id=700,
                ))
                self.assertTrue(db.update_order_field(
                    order_id, "requested_page_name", "My New Page",
                    "waiting_customer_info", customer_id=700,
                ))
                self.assertTrue(db.transition_order(
                    order_id, "admin_processing", {"waiting_customer_info"}, customer_id=700
                ))
                self.assertTrue(db.transition_order(
                    order_id, "admin_added", {"admin_processing"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "customer_accepted", {"admin_added"}, customer_id=700
                ))
                self.assertTrue(db.transition_order(
                    order_id, "waiting_remove_admin", {"customer_accepted"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "completed", {"waiting_remove_admin"}
                ))
                db.update_stock_field(stock_id, "status", "sold")
                order = db.get_order(order_id)
                self.assertEqual(order[5], "completed")
                self.assertEqual(order[6:9], (
                    "https://facebook.com/buyer", "My New Page", "receipt-file"
                ))
                self.assertEqual(db.get_stock(stock_id)[8], "sold")
                self.assertEqual(db.get_customer_orders(700)[0][0], order_id)
                self.assertEqual(db.get_orders_by_group("completed")[0][0], order_id)
                self.assertEqual(db.search_orders("order_id", order_id)[0][0], order_id)
                self.assertEqual(db.search_orders("telegram_id", 700)[0][0], order_id)
                self.assertEqual(db.search_orders("customer_name", "buy")[0][0], order_id)
                self.assertEqual(db.search_orders("stock_id", stock_id)[0][0], order_id)
                self.assertEqual(db.filter_orders("completed")[0][0], order_id)
                history = [row[2] for row in db.get_order_history(order_id)]
                self.assertEqual(history[0], "waiting_payment")
                self.assertEqual(history[-1], "completed")
                self.assertIn("payment_confirmed", history)
                self.assertFalse(db.delete_stock(stock_id))
                profile = db.get_customer_profile(700)
                self.assertEqual(profile[7:11], (1, 1, 0, 50.0))
            finally:
                db.DB_PATH = old_path

    def test_create_update_and_view_customer_profile(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "customer-profile.db")
            try:
                db.init_db()
                profile = db.upsert_customer_profile(
                    700, "buyer", "First", "Last"
                )
                self.assertEqual(profile[1:5], (
                    700, "buyer", "First", "Last"
                ))
                self.assertTrue(db.update_customer_profile_field(
                    700, "facebook_profile_link",
                    "https://facebook.com/buyer",
                ))
                self.assertTrue(db.update_customer_profile_field(
                    700, "default_page_name", "Buyer Page"
                ))
                profile = db.get_customer_profile(700)
                customer_view = profile_text(profile)
                self.assertIn("https://facebook.com/buyer", customer_view)
                self.assertIn("Buyer Page", customer_view)
            finally:
                db.DB_PATH = old_path

    def test_admin_customer_search_vip_ban_and_private_notes(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "customer-crm.db")
            try:
                db.init_db()
                db.upsert_customer_profile(
                    700, "specialbuyer", "First", "Last",
                    facebook_profile_link="https://facebook.com/special",
                )
                self.assertEqual(
                    db.search_customers("telegram", "700")[0][1], 700
                )
                self.assertEqual(
                    db.search_customers("username", "special")[0][1], 700
                )
                self.assertEqual(
                    db.search_customers("facebook", "facebook.com")[0][1],
                    700,
                )
                self.assertTrue(db.toggle_customer_flag(700, "is_vip"))
                self.assertTrue(db.toggle_customer_flag(700, "is_banned"))
                self.assertTrue(db.is_customer_banned(700))
                self.assertFalse(db.toggle_customer_flag(700, "is_banned"))
                self.assertFalse(db.is_customer_banned(700))
                db.update_customer_profile_field(
                    700, "admin_notes", "Private CRM note"
                )
                profile = db.get_customer_profile(700)
                self.assertNotIn("Private CRM note", profile_text(profile))
                self.assertIn(
                    "Private CRM note", profile_text(profile, admin=True)
                )
            finally:
                db.DB_PATH = old_path

    def test_broadcast_audiences_exclude_banned_customers(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "broadcast-audiences.db")
            try:
                db.init_db()
                for user_id in (700, 701, 702):
                    db.upsert_customer_profile(user_id, f"user{user_id}")
                db.toggle_customer_flag(701, "is_vip")
                db.toggle_customer_flag(702, "is_banned")
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                db.create_order(stock_id, 700, "user700", "$25")
                self.assertEqual(
                    db.get_broadcast_recipients("all"), [700, 701]
                )
                self.assertEqual(
                    db.get_broadcast_recipients("vip"), [701]
                )
                self.assertEqual(
                    db.get_broadcast_recipients("orders"), [700]
                )
            finally:
                db.DB_PATH = old_path

    def test_order_manager_has_workflow_search_and_filter_actions(self):
        manager_callbacks = {
            button.callback_data
            for row in order_manager_menu().inline_keyboard
            for button in row
        }
        self.assertEqual(manager_callbacks, {
            "admin:order_manager_active",
            "admin:order_manager_search",
            "admin:order_manager_filters",
            "admin:order_manager_history",
            "admin:home",
        })
        status_callbacks = {
            button.callback_data
            for row in order_status_menu(12).inline_keyboard
            for button in row
        }
        self.assertTrue({
            "admin:order_status:12:waiting_payment",
            "admin:order_status:12:payment_confirmed",
            "admin:order_status:12:waiting_customer_info",
            "admin:order_status:12:admin_processing",
            "admin:order_status:12:admin_added",
            "admin:order_status:12:waiting_customer_accept",
            "admin:order_status:12:waiting_remove_admin",
            "admin:order_status:12:completed",
            "admin:order_status:12:cancelled",
        }.issubset(status_callbacks))

    def test_customer_timeline_and_admin_workflow_buttons(self):
        order = (
            25, 15, 700, "buyer", "$35", "admin_processing",
            "", "", "", "2026-01-01 10:00:00", "2026-01-01 10:05:00",
        )
        detail = format_order(order)
        self.assertIn("Order #25", detail)
        self.assertIn("✔ 🟡 Waiting Payment", detail)
        self.assertIn("✔ 🔵 Payment Received", detail)
        self.assertIn("✔ 🟠 Processing", detail)
        self.assertIn("⬜ 🟣 Admin Added", detail)
        callbacks = {
            button.callback_data
            for row in order_manager_detail_keyboard(order).inline_keyboard
            for button in row
            if button.callback_data
        }
        self.assertTrue({
            "admin:order_workflow:payment:25",
            "admin:order_workflow:processing:25",
            "admin:order_workflow:admin_added:25",
            "admin:order_workflow:customer_accept:25",
            "admin:order_workflow:remove_admin:25",
            "admin:order_workflow:complete:25",
            "admin:order_workflow:cancel:25",
        }.issubset(callbacks))

    def test_order_timestamp_migration_and_invalid_transitions(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "order-timestamps.db")
            try:
                db.init_db()
                db.init_db()
                con = db.connect()
                columns = {
                    row[1] for row in con.execute(
                        "PRAGMA table_info(orders)"
                    ).fetchall()
                }
                con.close()
                self.assertTrue({
                    "payment_at", "processing_at", "admin_added_at",
                    "accepted_at", "removed_admin_at", "completed_at",
                    "cancelled_at",
                }.issubset(columns))
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$25")
                self.assertFalse(db.transition_order(
                    order_id, "completed", {"waiting_payment"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "payment_confirmed", {"waiting_payment"}
                ))
                payment_at = db.get_order_timestamps(order_id)["payment_at"]
                self.assertTrue(payment_at)
                self.assertFalse(db.transition_order(
                    order_id, "payment_confirmed", {"waiting_payment"}
                ))
                self.assertEqual(
                    db.get_order_timestamps(order_id)["payment_at"],
                    payment_at,
                )
            finally:
                db.DB_PATH = old_path

    def test_approve_payment_records_timestamp_and_log(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "approve-payment.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$25")
                db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, 700
                )
                db.save_order_receipt(order_id, 700, "receipt-1")
                self.assertTrue(db.verify_payment(
                    order_id, 619658883, "approved"
                ))
                self.assertEqual(
                    db.get_order(order_id)[5], "payment_received"
                )
                self.assertTrue(
                    db.get_order_timestamps(order_id)["payment_at"]
                )
                log = db.get_payment_logs(order_id)[0]
                self.assertEqual(log[3:6], ("approved", "", "receipt-1"))
            finally:
                db.DB_PATH = old_path

    def test_duplicate_payment_approval_is_ignored(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "duplicate-approval.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$25")
                db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, 700
                )
                db.save_order_receipt(order_id, 700, "receipt-1")
                self.assertTrue(db.verify_payment(
                    order_id, 619658883, "approved"
                ))
                self.assertFalse(db.verify_payment(
                    order_id, 619658883, "approved"
                ))
                self.assertEqual(len(db.get_payment_logs(order_id)), 1)
            finally:
                db.DB_PATH = old_path

    def test_reject_payment_saves_reason(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "reject-payment.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$25")
                db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, 700
                )
                db.save_order_receipt(order_id, 700, "receipt-1")
                self.assertTrue(db.verify_payment(
                    order_id, 619658883, "rejected", "Wrong amount"
                ))
                self.assertEqual(db.get_order(order_id)[5], "waiting_payment")
                log = db.get_payment_logs(order_id)[0]
                self.assertEqual(log[3:5], ("rejected", "Wrong amount"))
                con = db.connect()
                saved_reason = con.execute(
                    "SELECT rejection_reason FROM orders WHERE order_id=?",
                    (order_id,),
                ).fetchone()[0]
                con.close()
                self.assertEqual(saved_reason, "Wrong amount")
            finally:
                db.DB_PATH = old_path

    def test_receipt_history_keeps_customer_reuploads(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "receipt-history.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$25")
                db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, 700
                )
                self.assertTrue(db.save_order_receipt(
                    order_id, 700, "receipt-1"
                ))
                db.verify_payment(
                    order_id, 619658883, "rejected", "Unclear image"
                )
                self.assertTrue(db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, 700
                ))
                self.assertTrue(db.save_order_receipt(
                    order_id, 700, "receipt-2"
                ))
                receipts = db.get_order_receipts(order_id)
                self.assertEqual(
                    [receipt[2] for receipt in receipts],
                    ["receipt-1", "receipt-2"],
                )
                self.assertEqual(
                    db.get_order(order_id)[8], "receipt-2"
                )
            finally:
                db.DB_PATH = old_path


class AddStockWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_access_backup_manager(self):
        query = SimpleNamespace(
            data="admin:backup",
            from_user=SimpleNamespace(id=700),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={})
        await backup.handle_backup_callback(query, context)
        self.assertIn(
            "Admin only", query.message.reply_text.await_args.args[0]
        )

    async def test_non_admin_cannot_access_analytics_dashboard(self):
        query = SimpleNamespace(
            data="admin:analytics_dashboard",
            from_user=SimpleNamespace(id=700),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={})
        self.assertTrue(await handle_analytics_callback(query, context))
        self.assertIn(
            "Admin only", query.message.reply_text.await_args.args[0]
        )

    async def test_broadcast_delivery_report_and_history_are_saved(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "broadcast-delivery.db")
            try:
                db.init_db()
                for user_id in (700, 701, 702):
                    db.upsert_customer_profile(user_id, f"user{user_id}")
                broadcast_id = db.create_broadcast(
                    619658883, "all", "Hello customers"
                )
                bot = SimpleNamespace(send_message=AsyncMock(
                    side_effect=[
                        None,
                        Forbidden("bot blocked"),
                        TelegramError("delivery failed"),
                    ]
                ))
                result = await execute_broadcast(bot, broadcast_id)
                self.assertEqual(result[6:10], (3, 1, 1, 1))
                self.assertIn(
                    "Total Customers: 3", delivery_report_text(result)
                )
                self.assertEqual(
                    db.get_broadcast_history(1)[0][0], broadcast_id
                )
            finally:
                db.DB_PATH = old_path

    async def test_vip_and_order_customer_broadcast_delivery(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "broadcast-groups.db")
            try:
                db.init_db()
                db.upsert_customer_profile(700, "buyer")
                db.upsert_customer_profile(701, "vip")
                db.toggle_customer_flag(701, "is_vip")
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                db.create_order(stock_id, 700, "buyer", "$25")
                bot = SimpleNamespace(send_message=AsyncMock())
                vip_id = db.create_broadcast(
                    619658883, "vip", "VIP promotion"
                )
                order_id = db.create_broadcast(
                    619658883, "orders", "Order customer news"
                )
                vip_result = await execute_broadcast(bot, vip_id)
                order_result = await execute_broadcast(bot, order_id)
                self.assertEqual(vip_result[6:10], (1, 1, 0, 0))
                self.assertEqual(order_result[6:10], (1, 1, 0, 0))
                sent_ids = [
                    call.kwargs["chat_id"]
                    for call in bot.send_message.await_args_list
                ]
                self.assertEqual(sent_ids, [701, 700])
            finally:
                db.DB_PATH = old_path

    async def test_scheduled_broadcast_runs_when_due(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "scheduled-broadcast.db")
            try:
                db.init_db()
                db.upsert_customer_profile(700, "buyer")
                scheduled = datetime.now() + timedelta(hours=1)
                broadcast_id = db.create_broadcast(
                    619658883,
                    "all",
                    "Scheduled message",
                    scheduled_at=scheduled.strftime("%Y-%m-%d %H:%M:%S"),
                )
                self.assertEqual(db.get_due_broadcasts(datetime.now()), [])
                bot = SimpleNamespace(send_message=AsyncMock())
                results = await process_due_broadcasts(
                    bot, scheduled + timedelta(minutes=1)
                )
                self.assertEqual(results[0][0], broadcast_id)
                self.assertEqual(results[0][12], "completed")
                bot.send_message.assert_awaited_once_with(
                    chat_id=700, text="Scheduled message"
                )
            finally:
                db.DB_PATH = old_path

    async def test_non_admin_cannot_access_notification_center(self):
        query = SimpleNamespace(
            data="admin:notify",
            from_user=SimpleNamespace(id=700),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={})
        self.assertTrue(
            await handle_notification_callback(query, context)
        )
        self.assertIn(
            "Admin only", query.message.reply_text.await_args.args[0]
        )

    async def test_banned_customer_cannot_create_order(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "banned-order.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                db.upsert_customer_profile(700, "buyer")
                db.toggle_customer_flag(700, "is_banned")
                message = SimpleNamespace(
                    reply_text=AsyncMock(), reply_photo=AsyncMock()
                )
                query = SimpleNamespace(
                    from_user=SimpleNamespace(
                        id=700, username="buyer",
                        first_name="Buyer", last_name="",
                    ),
                    message=message,
                )
                context = SimpleNamespace(user_data={})
                await start_order(query, context, stock_id)
                self.assertEqual(db.get_customer_orders(700), [])
                self.assertIn(
                    "restricted", message.reply_text.await_args.args[0]
                )
            finally:
                db.DB_PATH = old_path

    async def test_non_admin_cannot_access_customer_crm(self):
        query = SimpleNamespace(
            data="admin:customers",
            from_user=SimpleNamespace(id=700),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )
        context = SimpleNamespace(user_data={})
        self.assertTrue(await handle_crm_callback(query, context))
        self.assertIn(
            "Admin only", query.message.reply_text.await_args.args[0]
        )

    async def test_non_admin_cannot_approve_payment(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "payment-security.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 700, "buyer", "$25")
                db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, 700
                )
                db.save_order_receipt(order_id, 700, "receipt-1")
                message = SimpleNamespace(reply_text=AsyncMock())
                query = SimpleNamespace(
                    data=f"admin:payment_approve:{order_id}",
                    from_user=SimpleNamespace(id=700),
                    message=message,
                )
                context = SimpleNamespace(
                    user_data={},
                    bot=SimpleNamespace(send_message=AsyncMock()),
                )
                await handle_admin_order_callback(query, context)
                self.assertEqual(
                    db.get_order(order_id)[5], "waiting_admin_confirm"
                )
                self.assertIn(
                    "Admin only", message.reply_text.await_args.args[0]
                )
                context.bot.send_message.assert_not_awaited()
            finally:
                db.DB_PATH = old_path

    async def test_admin_status_change_notifies_once_and_ignores_duplicate(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "workflow-notification.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 900, "buyer", "$25")
                message = SimpleNamespace(reply_text=AsyncMock())
                query = SimpleNamespace(
                    data=f"admin:order_workflow:payment:{order_id}",
                    from_user=SimpleNamespace(id=619658883),
                    message=message,
                    edit_message_text=AsyncMock(),
                )
                context = SimpleNamespace(
                    user_data={},
                    bot=SimpleNamespace(send_message=AsyncMock()),
                )

                await handle_admin_order_callback(query, context)
                self.assertEqual(
                    db.get_order(order_id)[5], "payment_confirmed"
                )
                self.assertEqual(context.bot.send_message.await_count, 1)

                await handle_admin_order_callback(query, context)
                self.assertEqual(context.bot.send_message.await_count, 1)
                self.assertIn(
                    "invalid or was already completed",
                    message.reply_text.await_args.args[0],
                )
            finally:
                db.DB_PATH = old_path

    async def test_menu_editor_rejects_non_owner_admin(self):
        query = SimpleNamespace(
            data="admin:settings_menu",
            from_user=SimpleNamespace(id=123456),
            edit_message_text=AsyncMock(),
        )
        context = SimpleNamespace(user_data={})
        await settings.handle_settings_callback(query, context)
        self.assertIn(
            "Only the main owner",
            query.edit_message_text.await_args.args[0],
        )

    async def test_cancel_order_removes_keyboard_and_returns_stock_without_duplicate(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "cancel-order.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 900, "buyer", "$25")
                message = SimpleNamespace(reply_text=AsyncMock())
                query = SimpleNamespace(
                    data=f"order:cancel:{order_id}",
                    from_user=SimpleNamespace(id=900),
                    message=message,
                    edit_message_reply_markup=AsyncMock(),
                )
                context = SimpleNamespace(user_data={})

                returned_stock_id = await handle_customer_order_callback(
                    query,
                    context,
                )

                self.assertEqual(returned_stock_id, stock_id)
                self.assertEqual(db.get_order(order_id)[5], "cancelled")
                self.assertEqual(len(db.get_customer_orders(900)), 1)
                query.edit_message_reply_markup.assert_awaited_once_with(
                    reply_markup=None
                )
                message.reply_text.assert_awaited_once_with(
                    "✅ Order cancelled."
                )
            finally:
                db.DB_PATH = old_path

    async def test_buy_starts_order_and_shows_payment_screen(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "buy-order.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                message = SimpleNamespace(
                    reply_text=AsyncMock(),
                    reply_photo=AsyncMock(),
                )
                query = SimpleNamespace(
                    from_user=SimpleNamespace(id=900, username="buyer"),
                    message=message,
                )
                context = SimpleNamespace(user_data={})
                await start_order(query, context, stock_id)
                orders = db.get_customer_orders(900)
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0][5], "waiting_payment")
                self.assertIn(
                    f"Order #{orders[0][0]}",
                    message.reply_text.await_args.args[0],
                )
                self.assertIn(
                    "Payment QR is not configured",
                    message.reply_text.await_args.args[0],
                )
            finally:
                db.DB_PATH = old_path

    async def test_remove_admin_requires_confirmation_and_completes_order(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "remove-admin.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "available",
                )
                order_id = db.create_order(stock_id, 900, "buyer", "$25")
                self.assertTrue(db.transition_order(
                    order_id, "payment_confirmed", {"waiting_payment"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "admin_processing", {"payment_confirmed"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "admin_added", {"admin_processing"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "waiting_customer_accept", {"admin_added"}
                ))
                self.assertTrue(db.transition_order(
                    order_id, "waiting_remove_admin",
                    {"waiting_customer_accept"},
                ))
                message = SimpleNamespace(reply_text=AsyncMock())
                query = SimpleNamespace(
                    data=f"order:remove_admin:{order_id}",
                    from_user=SimpleNamespace(id=900),
                    message=message,
                    edit_message_text=AsyncMock(),
                )
                context = SimpleNamespace(
                    user_data={},
                    bot=SimpleNamespace(send_message=AsyncMock()),
                )

                await handle_customer_order_callback(query, context)
                self.assertEqual(
                    query.edit_message_text.await_args.args[0],
                    "Are you sure?",
                )
                self.assertEqual(
                    db.get_order(order_id)[5],
                    "waiting_remove_admin",
                )

                query.data = f"order:remove_admin_yes:{order_id}"
                await handle_customer_order_callback(query, context)
                self.assertEqual(db.get_order(order_id)[5], "completed")
                self.assertEqual(db.get_stock(stock_id)[8], "sold")
                context.bot.send_message.assert_awaited()
            finally:
                db.DB_PATH = old_path

    async def test_health_server_returns_ok_and_404(self):
        server = await start_health_server(host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            self.assertIn(b"HTTP/1.1 200 OK", response)
            self.assertTrue(response.endswith(b"OK"))

            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /missing HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            self.assertIn(b"HTTP/1.1 404 Not Found", response)
        finally:
            server.close()
            await server.wait_closed()

    async def test_quick_edit_followers_updates_sqlite_and_returns_detail(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "quick-edit.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "equal", "$20", "100%", "",
                    "https://facebook.com/test", "available",
                )
                message = SimpleNamespace(
                    photo=[],
                    text="25K",
                    reply_text=AsyncMock(),
                )
                update = SimpleNamespace(
                    effective_user=SimpleNamespace(id=619658883),
                    message=message,
                )
                context = SimpleNamespace(user_data={
                    "admin_mode": "quick_edit",
                    "edit_stock_id": stock_id,
                    "edit_field": "followers",
                })
                await handle_text(update, context)
                self.assertEqual(db.get_stock(stock_id)[1], 25)
                self.assertEqual(context.user_data, {})
                self.assertIn("Followers updated", message.reply_text.await_args.args[0])
            finally:
                db.DB_PATH = old_path

    async def test_saved_stock_switches_to_persistent_photo_mode_and_done(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "workflow.db")
            try:
                db.init_db()
                context = SimpleNamespace(user_data={
                    "admin_mode": "create",
                    "admin_step": "status",
                    "draft": {
                        "followers": 15,
                        "price": "$50",
                        "country": "Cambodia",
                        "audience": "All",
                        "female_percent": 55,
                        "male_percent": 45,
                        "quality_percent": 95,
                        "real_followers": 1,
                        "organic_reach": "high",
                        "monetized": 1,
                        "no_violation": 1,
                        "ready_transfer": 1,
                        "business_ready": 1,
                        "fb_link": "https://facebook.com/test",
                    },
                })
                stock_id = save_stock_draft(context, "available")
                begin_photo_upload(context, 619658883, stock_id)

                self.assertIsNotNone(db.get_stock(stock_id))
                self.assertEqual(
                    db.get_stock(stock_id)[12:21],
                    (55, 45, 95, 1, "high", 1, 1, 1, 1),
                )
                self.assertEqual(db.get_photo_upload_session(619658883), stock_id)
                self.assertEqual(context.user_data["admin_mode"], "upload_photos")

                # The SQLite session survives loss of in-memory context.
                self.assertTrue(db.add_stock_photo(
                    db.get_photo_upload_session(619658883),
                    "telegram-file-id",
                ))
                update = SimpleNamespace(
                    effective_user=SimpleNamespace(id=619658883),
                    message=SimpleNamespace(reply_text=AsyncMock()),
                )
                restarted_context = SimpleNamespace(user_data={})
                await handle_command(update, restarted_context)

                self.assertEqual(db.get_stock_photos(stock_id), ["telegram-file-id"])
                self.assertIsNone(db.get_photo_upload_session(619658883))
                self.assertEqual(
                    update.message.reply_text.await_args.args[0],
                    "✅ Stock created successfully.",
                )
            finally:
                db.DB_PATH = old_path


if __name__ == "__main__":
    unittest.main()
