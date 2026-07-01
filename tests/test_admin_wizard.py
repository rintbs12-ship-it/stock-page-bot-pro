import unittest
import tempfile
import zipfile
import asyncio
import io
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from telegram import Chat, Message, Update, User
from telegram.error import Forbidden, TelegramError
from telegram.ext import ApplicationHandlerStop, ConversationHandler

import bot
from localization import translate_reply_markup, translate_ui_text
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
from handlers.user_management import (
    dashboard_text as user_dashboard_text,
    handle_user_management_callback,
    handle_user_management_message,
    user_detail_keyboard,
    user_list_keyboard,
)
from handlers.orders import (
    format_order,
    handle_admin_order_callback,
    handle_customer_order_callback,
    handle_order_message,
    order_manager_detail_keyboard,
    order_manager_menu,
    order_status_menu,
    start_order,
)
from handlers.menu import (
    WIZARD_PROMPTS,
    WIZARD_STEPS,
    _wizard_keyboard,
    admin_stock_text,
    begin_photo_upload,
    build_stock_report,
    customer_stock_text,
    apply_default_currency,
    format_statistics_dashboard,
    get_welcome_text,
    handle_callback,
    handle_command,
    handle_text,
    normalize_quality,
    normalize_status,
    parse_percent,
    parse_followers_value,
    save_stock_draft,
    start,
    cancel,
    validate_http_url,
)
from keyboards.buttons import (
    admin_home,
    admin_stock_actions,
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
    def test_global_khmer_ui_translation_preserves_callbacks_and_emojis(self):
        translated = translate_ui_text(
            "✅ Information saved. Admin is processing your order."
        )
        self.assertTrue(translated.startswith("✅"))
        self.assertIn("ព័ត៌មានត្រូវបានរក្សាទុករួចរាល់", translated)
        markup = admin_stock_actions(42)
        translated_markup = translate_reply_markup(markup)
        original_callbacks = [
            button.callback_data
            for row in markup.inline_keyboard for button in row
        ]
        translated_callbacks = [
            button.callback_data
            for row in translated_markup.inline_keyboard for button in row
        ]
        self.assertEqual(translated_callbacks, original_callbacks)
        translated_labels = {
            button.text
            for row in translated_markup.inline_keyboard for button in row
        }
        self.assertIn("❌ បោះបង់", translated_labels)
        self.assertTrue(any("ប្រូម៉ូសិន" in label for label in translated_labels))

    def test_production_main_provides_ptb_22_current_event_loop(self):
        app = SimpleNamespace(run_polling=Mock(), bot_data={})
        socket = SimpleNamespace(getsockname=Mock(return_value=("0.0.0.0", 10000)))
        health_server = SimpleNamespace(
            sockets=[socket],
            close=Mock(),
            wait_closed=AsyncMock(),
        )

        def verify_polling_loop(**kwargs):
            loop = asyncio.get_event_loop()
            self.assertFalse(loop.is_running())
            self.assertFalse(kwargs["close_loop"])

        app.run_polling.side_effect = verify_polling_loop
        with (
            patch.object(bot, "init_db"),
            patch.object(bot, "verify_database", return_value={
                "integrity": "ok", "foreign_key_errors": [],
            }),
            patch.object(bot, "add_demo_stock_if_empty"),
            patch.object(bot, "run_due_auto_backup", return_value=None),
            patch.object(bot, "build_application", return_value=app),
            patch.object(
                bot, "start_health_server",
                new=AsyncMock(return_value=health_server),
            ),
        ):
            bot.main()

        app.run_polling.assert_called_once()
        health_server.close.assert_called_once()
        health_server.wait_closed.assert_awaited_once()

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
                con = db.connect()
                con.execute(
                    "UPDATE stocks SET page_type='Movie' "
                    "WHERE id=(SELECT MIN(id) FROM stocks)"
                )
                con.commit()
                con.close()
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
                self.assertIn(("Movie", 2), data["top_categories"])
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
                self.assertNotIn("global:cancel", callbacks)
                self.assertFalse(any(
                    button.text in {"⬅️ Back", "❌ Cancel"}
                    for row in menu.inline_keyboard
                    for button in row
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
                "admin:users",
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
                    "UPDATE stocks SET category='Gaming', page_type='Gaming' WHERE id=?",
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
                _, page_type_rows, page_type_total = db.advanced_admin_search(
                    "stock", {"page_type": "Gaming"}
                )
                self.assertEqual(page_type_total, 1)
                self.assertEqual(page_type_rows[0][-1], "Gaming")
                self.assertEqual(
                    db.search_stocks("page_type", value="Gaming")[0][0],
                    stock_ids[0],
                )
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
                    "category", "page_type",
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
                    "available", page_type="Movie",
                )
                self.assertEqual(
                    db.get_stock(stock_id)[21],
                    "Movie",
                )
                card = customer_stock_text(db.get_stock(stock_id), "en")
                self.assertIn("📂 Page Type : Movie", card)
                self.assertLess(
                    card.index("📂 Page Type"), card.index("Followers")
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
        self.assertIn("📂 Page Type : Not set", english)
        self.assertIn("💵 តម្លៃ/1K : 2$", english)
        self.assertIn("👥 ចំនួន Follower : 15K", english)
        self.assertIn("💰 តម្លៃសរុប : 25$", english)

        price_row = (
            8, 6.2, "Cambodia", "female", "$56", "95%", "",
            "https://fb.test", "available", 0, 0, "",
            55, 45, 95, 1, "high", 1, 1, 1, 1,
        )
        expected = (
            "👥 ចំនួន Follower : 6.2K\n"
            "💵 តម្លៃ/1K : 9$\n"
            "💰 តម្លៃសរុប : 56$"
        )
        self.assertIn(expected, customer_stock_text(price_row, "km"))
        total_only = customer_stock_text(
            (*price_row, None, "total_only"), "km"
        )
        self.assertNotIn("តម្លៃ/1K", total_only)
        self.assertIn("💰 តម្លៃសរុប : 56$", total_only)
        per_1k_only = customer_stock_text(
            (*price_row, None, "per_1k_only"), "km"
        )
        self.assertIn("💵 តម្លៃ/1K : 9$", per_1k_only)
        self.assertNotIn("តម្លៃសរុប", per_1k_only)

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
            "❌ Cancel",
        })
        self.assertEqual(english_labels, {
            "🖼️ View Photos", "🌐 Open Page", "📋 Copy Link",
            "💬 Contact Admin", "🛒 Buy Now", "⬅️ Back",
            "❤️ Favorite", "🔔 Notify Me", "📤 Share",
            "❌ Cancel",
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
                "admin:quick_field:42:page_type",
                "admin:quick_field:42:fb_link",
            "admin:quick_status:42",
            "admin:photo_manager:42",
            "admin:stock:42",
            "global:cancel",
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
            "global:cancel",
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
            {"admin:stats", "admin:stats_export", "admin:home", "global:cancel"},
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
            "global:cancel",
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
                    "global:cancel",
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
                self.assertEqual(apply_default_currency("50$"), "$50")
                self.assertEqual(apply_default_currency("$50"), "$50")
                self.assertEqual(apply_default_currency("25.50$"), "$25.50")
                self.assertEqual(apply_default_currency("$25.50"), "$25.50")
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
                    "🪪 Stock #7\n"
                    "👥 ចំនួន Follower : 15K\n"
                    "💵 តម្លៃ/1K : 2$\n"
                    "💰 តម្លៃសរុប : 25$",
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
            "global:cancel",
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
    @staticmethod
    def _ready_transfer_context(value=None):
        draft = {
            field: value if value is not None else f"{field}-value"
            for field in WIZARD_STEPS[:13]
        }
        return SimpleNamespace(
            user_data={
                "admin_mode": "create",
                "admin_step": "ready_transfer",
                "draft": draft,
            },
            chat_data={},
        )

    @staticmethod
    def _wizard_query(data):
        return SimpleNamespace(
            data=data,
            from_user=SimpleNamespace(id=619658883),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(reply_text=AsyncMock()),
        )

    async def test_manage_stock_selection_back_and_cancel_navigation(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "manage-navigation.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "All", "$25", "100%", "Managed",
                    "https://facebook.com/manage", "available",
                )
                context = SimpleNamespace(user_data={}, chat_data={})

                list_query = self._wizard_query("admin:manage")
                await handle_callback(
                    SimpleNamespace(callback_query=list_query), context
                )
                list_callbacks = {
                    button.callback_data
                    for row in list_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertIn(f"admin:stock:{stock_id}", list_callbacks)
                self.assertIn("admin:home", list_callbacks)
                self.assertIn("global:cancel", list_callbacks)

                detail_query = self._wizard_query(f"admin:stock:{stock_id}")
                result = await handle_callback(
                    SimpleNamespace(callback_query=detail_query), context
                )
                self.assertIsNone(result)
                detail_callbacks = {
                    button.callback_data
                    for row in detail_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertIn(f"admin:edit:{stock_id}", detail_callbacks)
                self.assertIn(f"admin:delete:{stock_id}", detail_callbacks)
                self.assertIn(f"admin:photo_manager:{stock_id}", detail_callbacks)
                self.assertIn("admin:manage", detail_callbacks)
                self.assertIn("global:cancel", detail_callbacks)

                quick_query = self._wizard_query(f"admin:quick:{stock_id}")
                self.assertIsNone(await handle_callback(
                    SimpleNamespace(callback_query=quick_query), context
                ))
                self.assertIn(
                    "Quick Edit",
                    quick_query.edit_message_text.await_args.args[0],
                )

                edit_query = self._wizard_query(f"admin:edit:{stock_id}")
                self.assertIsNone(await handle_callback(
                    SimpleNamespace(callback_query=edit_query), context
                ))
                self.assertIn(
                    "Choose a field",
                    edit_query.edit_message_text.await_args.args[0],
                )

                delete_query = self._wizard_query(f"admin:delete:{stock_id}")
                self.assertIsNone(await handle_callback(
                    SimpleNamespace(callback_query=delete_query), context
                ))
                self.assertIn(
                    "Permanently delete",
                    delete_query.edit_message_text.await_args.args[0],
                )
                self.assertIsNotNone(db.get_stock(stock_id))

                for status in ("sold", "available"):
                    status_query = self._wizard_query(
                        f"admin:set_status:{stock_id}:{status}"
                    )
                    self.assertIsNone(await handle_callback(
                        SimpleNamespace(callback_query=status_query), context
                    ))
                    self.assertEqual(db.get_stock(stock_id)[8], status)
                    self.assertIn(
                        f"Status changed to {status.title()}",
                        status_query.edit_message_text.await_args.args[0],
                    )

                for field, column in (("featured", 9), ("promotion", 10)):
                    for expected in (1, 0):
                        flag_query = self._wizard_query(
                            f"admin:flag:{field}:{stock_id}"
                        )
                        self.assertIsNone(await handle_callback(
                            SimpleNamespace(callback_query=flag_query), context
                        ))
                        self.assertEqual(
                            db.get_stock(stock_id)[column], expected
                        )
                        self.assertIn(
                            "enabled" if expected else "disabled",
                            flag_query.edit_message_text.await_args.args[0],
                        )
                        refreshed_callbacks = {
                            button.callback_data
                            for row in flag_query.edit_message_text.await_args
                            .kwargs["reply_markup"].inline_keyboard
                            for button in row
                        }
                        self.assertIn(
                            f"admin:flag:promotion:{stock_id}",
                            refreshed_callbacks,
                        )
                        self.assertIn("admin:manage", refreshed_callbacks)
                        self.assertIn("global:cancel", refreshed_callbacks)

                photos_query = self._wizard_query(
                    f"admin:photo_manager:{stock_id}"
                )
                self.assertIsNone(await handle_callback(
                    SimpleNamespace(callback_query=photos_query), context
                ))
                self.assertIn(
                    "Photo Manager",
                    photos_query.edit_message_text.await_args.args[0],
                )

                back_query = self._wizard_query("admin:manage")
                self.assertIsNone(await handle_callback(
                    SimpleNamespace(callback_query=back_query), context
                ))
                self.assertIn(
                    "Manage Stock",
                    back_query.edit_message_text.await_args.args[0],
                )

                cancel_query = self._wizard_query("global:cancel")
                result = await handle_callback(
                    SimpleNamespace(callback_query=cancel_query), context
                )
                self.assertEqual(result, -1)
                self.assertEqual(context.user_data, {})
            finally:
                db.DB_PATH = old_path

    async def test_sold_stock_admin_marking_actions_and_customer_guard(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "sold-stock-visibility.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    8, "Cambodia", "All", "$56", "100%", "",
                    "https://facebook.com/sold", "available",
                    featured=1, promotion=1,
                )
                order_id = db.create_order(
                    stock_id, 700001, "buyer", "$56"
                )
                db.update_stock_field(stock_id, "status", "sold")
                row = db.get_stock(stock_id)

                detail = admin_stock_text(row)
                self.assertTrue(detail.startswith("🚫 SOLD / លក់រួច"))
                self.assertIn("🔴 ស្ថានភាព : លក់រួច", detail)

                sold_markup = admin_stock_actions(stock_id, "sold")
                sold_callbacks = {
                    button.callback_data
                    for markup_row in sold_markup.inline_keyboard
                    for button in markup_row
                }
                self.assertEqual(sold_callbacks, {
                    f"admin:set_status:{stock_id}:available",
                    f"admin:delete:{stock_id}",
                    f"admin:stock_orders:{stock_id}",
                    f"admin:photo_manager:{stock_id}",
                    "admin:manage",
                    "global:cancel",
                })
                self.assertFalse(any(
                    callback.startswith("admin:flag:")
                    for callback in sold_callbacks
                ))
                self.assertIn(
                    stock_id, {stock[0] for stock in db.get_all_stocks()}
                )
                self.assertNotIn(
                    stock_id, {stock[0] for stock in db.get_new()}
                )
                self.assertEqual(
                    db.get_stock_orders(stock_id)[0][0], order_id
                )

                customer_query = SimpleNamespace(
                    data=f"stock:{stock_id}",
                    from_user=SimpleNamespace(id=700001),
                    answer=AsyncMock(),
                    edit_message_text=AsyncMock(),
                    message=SimpleNamespace(reply_text=AsyncMock()),
                )
                await handle_callback(
                    SimpleNamespace(callback_query=customer_query),
                    SimpleNamespace(user_data={}, chat_data={}),
                )
                self.assertEqual(
                    customer_query.edit_message_text.await_args.args[0],
                    "❌ Stock នេះត្រូវបានលក់រួចហើយ។",
                )

                flag_query = self._wizard_query(
                    f"admin:flag:promotion:{stock_id}"
                )
                await handle_callback(
                    SimpleNamespace(callback_query=flag_query),
                    SimpleNamespace(user_data={}, chat_data={}),
                )
                self.assertEqual(db.get_stock(stock_id)[10], 1)
                returned_markup = (
                    flag_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ]
                )
                self.assertNotIn(
                    f"admin:flag:promotion:{stock_id}",
                    {
                        button.callback_data
                        for markup_row in returned_markup.inline_keyboard
                        for button in markup_row
                    },
                )

                active_markup = admin_stock_actions(stock_id, "available")
                active_callbacks = {
                    button.callback_data
                    for markup_row in active_markup.inline_keyboard
                    for button in markup_row
                }
                self.assertIn(
                    f"admin:flag:promotion:{stock_id}", active_callbacks
                )
            finally:
                db.DB_PATH = old_path

    async def test_promotion_preview_share_back_and_cancel_navigation(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "promotion-navigation.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    20, "Cambodia", "All", "$50", "100%", "Promotion",
                    "https://facebook.com/promotion", "available",
                    promotion=1,
                )
                context = SimpleNamespace(user_data={}, chat_data={})

                list_query = self._wizard_query("admin:list:promotion")
                await handle_callback(
                    SimpleNamespace(callback_query=list_query), context
                )
                list_callbacks = {
                    button.callback_data
                    for row in list_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertIn(
                    f"admin:promotion_preview:{stock_id}", list_callbacks
                )
                self.assertIn("admin:home", list_callbacks)
                self.assertIn("global:cancel", list_callbacks)

                preview_query = self._wizard_query(
                    f"admin:promotion_preview:{stock_id}"
                )
                result = await handle_callback(
                    SimpleNamespace(callback_query=preview_query), context
                )
                self.assertIsNone(result)
                preview_markup = (
                    preview_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ]
                )
                preview_callbacks = {
                    button.callback_data
                    for row in preview_markup.inline_keyboard for button in row
                    if button.callback_data
                }
                self.assertEqual(preview_callbacks, {
                    "admin:list:promotion", "global:cancel",
                })
                self.assertTrue(any(
                    button.text == "📤 Share on Telegram" and button.url
                    for row in preview_markup.inline_keyboard for button in row
                ))

                share_query = self._wizard_query(f"share:{stock_id}")
                await handle_callback(
                    SimpleNamespace(callback_query=share_query), context
                )
                share_markup = (
                    share_query.message.reply_text.await_args.kwargs[
                        "reply_markup"
                    ]
                )
                share_callbacks = {
                    button.callback_data
                    for row in share_markup.inline_keyboard for button in row
                    if button.callback_data
                }
                self.assertEqual(share_callbacks, {
                    f"stock:{stock_id}", "global:cancel",
                })
            finally:
                db.DB_PATH = old_path

    async def test_ready_transfer_yes_and_no_advance_to_business_ready(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "ready-transfer-values.db")
            try:
                db.init_db()
                markup = _wizard_keyboard("ready_transfer")
                callbacks = {
                    button.text: button.callback_data
                    for row in markup.inline_keyboard for button in row
                }
                self.assertEqual(
                    callbacks["✅ បាទ / Yes"],
                    "admin:wizard:bool:ready_transfer:1",
                )
                self.assertEqual(
                    callbacks["❌ ទេ / No"],
                    "admin:wizard:bool:ready_transfer:0",
                )

                for raw_value, expected in (("1", 1), ("0", 0)):
                    context = self._ready_transfer_context()
                    query = self._wizard_query(
                        f"admin:wizard:bool:ready_transfer:{raw_value}"
                    )
                    await handle_callback(
                        SimpleNamespace(callback_query=query), context
                    )
                    self.assertEqual(
                        context.user_data["draft"]["ready_transfer"], expected
                    )
                    self.assertEqual(
                        context.user_data["admin_step"], "business_ready"
                    )
                    self.assertIn(
                        "15/17 Business Ready",
                        query.edit_message_text.await_args.args[0],
                    )
            finally:
                db.DB_PATH = old_path

    async def test_ready_transfer_accepts_visible_labels_and_text_fallback(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "ready-transfer-text.db")
            try:
                db.init_db()
                for text, expected in (
                    ("✅ បាទ / Yes", 1),
                    ("❌ ទេ / No", 0),
                    ("Yes", 1),
                    ("No", 0),
                ):
                    context = self._ready_transfer_context()
                    message = SimpleNamespace(
                        text=text, photo=None, reply_text=AsyncMock()
                    )
                    await handle_text(
                        SimpleNamespace(
                            effective_user=SimpleNamespace(id=619658883),
                            message=message,
                        ),
                        context,
                    )
                    self.assertEqual(
                        context.user_data["draft"]["ready_transfer"], expected
                    )
                    self.assertEqual(
                        context.user_data["admin_step"], "business_ready"
                    )
                    self.assertIn(
                        "15/17 Business Ready",
                        message.reply_text.await_args.args[0],
                    )

                context = self._ready_transfer_context()
                message = SimpleNamespace(
                    text="maybe", photo=None, reply_text=AsyncMock()
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=message,
                    ),
                    context,
                )
                self.assertEqual(
                    context.user_data["admin_step"], "ready_transfer"
                )
                self.assertNotIn(
                    "ready_transfer", context.user_data["draft"]
                )
                self.assertIn(
                    "Please choose",
                    message.reply_text.await_args.args[0],
                )
            finally:
                db.DB_PATH = old_path

    async def test_ready_transfer_back_and_cancel_navigation(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "ready-transfer-navigation.db")
            try:
                db.init_db()
                context = self._ready_transfer_context()
                original_draft = context.user_data["draft"]
                back_query = self._wizard_query("admin:wizard:back")
                await handle_callback(
                    SimpleNamespace(callback_query=back_query), context
                )
                self.assertEqual(context.user_data["admin_step"], "no_violation")
                self.assertIs(context.user_data["draft"], original_draft)
                self.assertIn(
                    "13/17 No Policy Violation",
                    back_query.edit_message_text.await_args.args[0],
                )

                context = self._ready_transfer_context()
                cancel_query = self._wizard_query("admin:wizard:cancel")
                result = await handle_callback(
                    SimpleNamespace(callback_query=cancel_query), context
                )
                self.assertEqual(result, -1)
                self.assertEqual(context.user_data, {})
                self.assertEqual(
                    cancel_query.edit_message_text.await_args.args[0],
                    "❌ Add Stock cancelled.",
                )
            finally:
                db.DB_PATH = old_path

    def test_ready_transfer_is_present_in_wizard_state_and_prompt_mappings(self):
        self.assertEqual(set(WIZARD_STEPS), set(WIZARD_PROMPTS))
        self.assertEqual(WIZARD_STEPS[13], "ready_transfer")
        self.assertEqual(WIZARD_STEPS[14], "business_ready")
        callbacks = {
            button.callback_data
            for row in _wizard_keyboard("ready_transfer").inline_keyboard
            for button in row
        }
        self.assertEqual(callbacks, {
            "admin:wizard:bool:ready_transfer:1",
            "admin:wizard:bool:ready_transfer:0",
            "admin:wizard:back",
            "admin:wizard:cancel",
        })

    async def test_add_stock_page_type_reply_keyboard_and_selection(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "wizard-page-type.db")
            try:
                db.init_db()
                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create",
                        "admin_step": "page_type",
                        "draft": {
                            "followers": 15,
                            "price": "$50",
                            "price_display_mode": "both",
                            "country": "Cambodia",
                            "audience": "female",
                        },
                    },
                    chat_data={},
                )
                markup = _wizard_keyboard("page_type")
                labels = {
                    button.text for row in markup.keyboard for button in row
                }
                self.assertEqual(labels, {
                    "🎬 ប្រភេទផេករឿងសម្រាយ",
                    "📈 ប្រភេទផេក PE",
                    "⬅️ ត្រឡប់ក្រោយ",
                    "❌ បោះបង់",
                })
                self.assertIn("⬅️ ត្រឡប់ក្រោយ", labels)
                self.assertIn("❌ បោះបង់", labels)

                invalid_message = SimpleNamespace(
                    text="Movie", photo=None, reply_text=AsyncMock()
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=invalid_message,
                    ),
                    context,
                )
                self.assertEqual(
                    context.user_data["admin_step"], "page_type"
                )
                self.assertNotIn(
                    "page_type", context.user_data["draft"]
                )

                message = SimpleNamespace(
                    text="🎬 ប្រភេទផេករឿងសម្រាយ",
                    photo=None,
                    reply_text=AsyncMock(),
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=message,
                    ),
                    context,
                )
                self.assertEqual(
                    context.user_data["draft"]["page_type"],
                    "ប្រភេទផេករឿងសម្រាយ",
                )
                self.assertEqual(context.user_data["admin_step"], "female_percent")
                self.assertEqual(message.reply_text.await_count, 2)
                self.assertIn(
                    "7/17 Female percent",
                    message.reply_text.await_args_list[1].args[0],
                )

                pe_context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create",
                        "admin_step": "page_type",
                        "draft": {
                            "followers": 15,
                            "price": "$50",
                            "price_display_mode": "both",
                            "country": "Cambodia",
                            "audience": "female",
                        },
                    },
                    chat_data={},
                )
                pe_message = SimpleNamespace(
                    text="📈 ប្រភេទផេក PE",
                    photo=None,
                    reply_text=AsyncMock(),
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=pe_message,
                    ),
                    pe_context,
                )
                self.assertEqual(
                    pe_context.user_data["draft"]["page_type"],
                    "ប្រភេទផេក PE",
                )
            finally:
                db.DB_PATH = old_path

    async def test_price_display_mode_add_edit_and_sqlite_default(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "price-display-mode.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    8, "Cambodia", "All", "$56", "100%", "",
                    "https://facebook.com/price-mode", "available",
                )
                self.assertEqual(db.get_stock(stock_id)[22], "both")

                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create",
                        "admin_step": "price",
                        "draft": {"followers": 8},
                    },
                    chat_data={},
                )
                price_message = SimpleNamespace(
                    text="56", photo=None, reply_text=AsyncMock()
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=price_message,
                    ),
                    context,
                )
                self.assertEqual(
                    context.user_data["admin_step"], "price_display_mode"
                )
                self.assertIn(
                    "តើចង់បង្ហាញតម្លៃបែបណា?",
                    price_message.reply_text.await_args.args[0],
                )
                callbacks = {
                    button.callback_data
                    for row in price_message.reply_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertTrue({
                    "admin:wizard:price_mode:both",
                    "admin:wizard:price_mode:total_only",
                    "admin:wizard:price_mode:per_1k_only",
                    "admin:wizard:back",
                    "admin:wizard:cancel",
                }.issubset(callbacks))

                query = self._wizard_query(
                    "admin:wizard:price_mode:total_only"
                )
                await handle_callback(
                    SimpleNamespace(callback_query=query), context
                )
                self.assertEqual(
                    context.user_data["draft"]["price_display_mode"],
                    "total_only",
                )
                self.assertEqual(context.user_data["admin_step"], "audience")

                edit_context = SimpleNamespace(
                    user_data={
                        "admin_mode": "edit_stock",
                        "edit_stock_id": stock_id,
                        "edit_field": "price",
                    },
                    chat_data={},
                )
                edit_message = SimpleNamespace(
                    text="$64", photo=None, reply_text=AsyncMock()
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(
                            id=619658883, username="owner",
                            first_name="Owner", last_name="",
                        ),
                        message=edit_message,
                    ),
                    edit_context,
                )
                self.assertEqual(
                    edit_context.user_data["pending_price"], "$64"
                )
                edit_query = self._wizard_query(
                    f"admin:edit_price_mode:edit:{stock_id}:per_1k_only"
                )
                await handle_callback(
                    SimpleNamespace(callback_query=edit_query),
                    edit_context,
                )
                stock = db.get_stock(stock_id)
                self.assertEqual(stock[4], "$64")
                self.assertEqual(stock[22], "per_1k_only")
            finally:
                db.DB_PATH = old_path

    async def test_add_stock_back_preserves_draft_and_renders_previous_step(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "wizard-back.db")
            try:
                db.init_db()
                draft = {
                    "followers": 15,
                    "price": "$50",
                    "price_display_mode": "both",
                    "country": "Cambodia",
                    "audience": "female",
                    "page_type": "Movie",
                    "female_percent": 55,
                }
                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create",
                        "admin_step": "male_percent",
                        "draft": draft,
                    },
                    chat_data={},
                )
                query = SimpleNamespace(
                    data="admin:wizard:back",
                    from_user=SimpleNamespace(id=619658883),
                    answer=AsyncMock(),
                    edit_message_text=AsyncMock(),
                    message=SimpleNamespace(reply_text=AsyncMock()),
                )
                update = SimpleNamespace(callback_query=query)

                await handle_callback(update, context)

                self.assertEqual(context.user_data["admin_step"], "female_percent")
                self.assertIs(context.user_data["draft"], draft)
                self.assertEqual(context.user_data["draft"]["female_percent"], 55)
                self.assertIn("7/17 Female percent", query.edit_message_text.await_args.args[0])
                markup = query.edit_message_text.await_args.kwargs["reply_markup"]
                callbacks = {
                    button.callback_data
                    for row in markup.inline_keyboard for button in row
                }
                self.assertIn("admin:wizard:back", callbacks)
                self.assertIn("admin:wizard:cancel", callbacks)
            finally:
                db.DB_PATH = old_path

    async def test_add_stock_cancel_button_and_command_clear_wizard_state(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "wizard-cancel.db")
            try:
                db.init_db()
                for step in WIZARD_STEPS:
                    markup = _wizard_keyboard(step)
                    if step == "page_type":
                        labels = {
                            button.text
                            for row in markup.keyboard for button in row
                        }
                        self.assertIn("⬅️ ត្រឡប់ក្រោយ", labels)
                        self.assertIn("❌ បោះបង់", labels)
                    else:
                        callbacks = {
                            button.callback_data
                            for row in markup.inline_keyboard for button in row
                        }
                        self.assertIn("admin:wizard:back", callbacks)
                        self.assertIn("admin:wizard:cancel", callbacks)

                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create", "admin_step": "followers",
                        "draft": {},
                    },
                    chat_data={"wizard_note": "temporary", "other": "keep"},
                )
                query = SimpleNamespace(
                    data="admin:wizard:cancel",
                    from_user=SimpleNamespace(id=619658883),
                    answer=AsyncMock(),
                    edit_message_text=AsyncMock(),
                    message=SimpleNamespace(reply_text=AsyncMock()),
                )
                result = await handle_callback(
                    SimpleNamespace(callback_query=query), context
                )
                self.assertEqual(result, -1)
                self.assertEqual(context.user_data, {})
                self.assertNotIn("wizard_note", context.chat_data)
                self.assertEqual(context.chat_data["other"], "keep")
                self.assertEqual(
                    query.edit_message_text.await_args.args[0],
                    "❌ Add Stock cancelled.",
                )

                command_context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create", "admin_step": "followers",
                        "draft": {},
                    },
                    chat_data={"add_stock_temp": True},
                )
                message = SimpleNamespace(reply_text=AsyncMock())
                command_result = await cancel(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=message,
                    ),
                    command_context,
                )
                self.assertEqual(command_result, -1)
                self.assertEqual(command_context.user_data, {})
                self.assertEqual(command_context.chat_data, {})
                self.assertEqual(
                    message.reply_text.await_args.args[0],
                    "❌ Add Stock cancelled.",
                )
            finally:
                db.DB_PATH = old_path

    async def test_submenu_back_and_global_cancel_clear_temporary_state(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "global-navigation.db")
            try:
                db.init_db()
                callbacks = {
                    button.callback_data
                    for row in settings.settings_menu().inline_keyboard
                    for button in row
                }
                self.assertIn("admin:home", callbacks)
                self.assertIn("global:cancel", callbacks)

                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "settings_welcome",
                        "settings_draft": "temporary",
                    },
                    chat_data={"workflow_state": "editing"},
                )
                query = SimpleNamespace(
                    data="global:cancel",
                    from_user=SimpleNamespace(id=619658883),
                    answer=AsyncMock(),
                    edit_message_text=AsyncMock(),
                    message=SimpleNamespace(reply_text=AsyncMock()),
                )
                result = await handle_callback(
                    SimpleNamespace(callback_query=query), context
                )

                self.assertEqual(result, -1)
                self.assertEqual(context.user_data, {})
                self.assertEqual(context.chat_data, {})
                self.assertEqual(
                    query.edit_message_text.await_args.args[0],
                    "❌ Cancelled.",
                )
            finally:
                db.DB_PATH = old_path

    async def test_start_during_add_stock_clears_wizard_and_shows_main_menu(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "wizard-start.db")
            try:
                db.init_db()
                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create", "admin_step": "price",
                        "draft": {"followers": 15},
                    },
                    chat_data={"wizard_state": "price"},
                )
                message = SimpleNamespace(
                    reply_text=AsyncMock(), reply_photo=AsyncMock()
                )
                result = await start(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(
                            id=619658883, username="owner",
                            first_name="DORN", last_name="",
                        ),
                        message=message,
                    ),
                    context,
                )
                self.assertEqual(result, -1)
                self.assertEqual(context.user_data, {})
                self.assertEqual(context.chat_data, {})
                self.assertTrue(any(
                    getattr(call.kwargs.get("reply_markup"), "keyboard", None)
                    and call.kwargs["reply_markup"].keyboard[0][0].text
                    == "🚀 /start"
                    for call in message.reply_text.await_args_list
                ))
                markup = message.reply_text.await_args.kwargs["reply_markup"]
                callbacks = {
                    button.callback_data
                    for row in markup.inline_keyboard for button in row
                }
                self.assertIn("admin:home", callbacks)
            finally:
                db.DB_PATH = old_path

    async def test_start_is_global_across_all_active_and_finished_flows(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "global-start.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "All", "$50", "100%", "",
                    "https://facebook.com/global-start", "available",
                )
                order_id = db.create_order(
                    stock_id, 700002, "flow_user", "$50"
                )
                states = (
                    (
                        "photo upload",
                        {
                            "admin_mode": "upload_photos",
                            "admin_step": "photo",
                            "last_stock_id": stock_id,
                            "waiting_for_photos": True,
                        },
                    ),
                    (
                        "add stock",
                        {
                            "admin_mode": "create",
                            "admin_step": "price",
                            "draft": {"followers": 10},
                        },
                    ),
                    (
                        "order",
                        {"order_mode": "customer_info", "order_id": order_id},
                    ),
                    (
                        "payment",
                        {"order_mode": "receipt", "order_id": order_id},
                    ),
                    ("after cancel", {}),
                    ("after completed", {"completed_flow": True}),
                )
                for name, user_data in states:
                    with self.subTest(flow=name):
                        if name == "photo upload":
                            db.set_photo_upload_session(
                                619658883, stock_id
                            )
                        context = SimpleNamespace(
                            user_data=dict(user_data),
                            chat_data={
                                "flow": name,
                                "waiting_for_photos": True,
                            },
                        )
                        message = SimpleNamespace(
                            reply_text=AsyncMock(),
                            reply_photo=AsyncMock(),
                        )
                        result = await start(
                            SimpleNamespace(
                                effective_user=SimpleNamespace(
                                    id=619658883,
                                    username="owner",
                                    first_name="Owner",
                                    last_name="",
                                ),
                                message=message,
                            ),
                            context,
                        )
                        self.assertEqual(result, ConversationHandler.END)
                        self.assertEqual(context.user_data, {})
                        self.assertEqual(context.chat_data, {})
                        self.assertIsNone(
                            db.get_photo_upload_session(619658883)
                        )
                        self.assertTrue(
                            message.reply_text.await_args.kwargs[
                                "reply_markup"
                            ].inline_keyboard
                        )
                self.assertIsNotNone(db.get_order(order_id))
            finally:
                db.DB_PATH = old_path

    async def test_global_start_priority_and_khmer_fallback(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "start-priority.db")
            try:
                db.init_db()
                with patch.object(bot, "BOT_TOKEN", "123456:ABCDEF"):
                    app = bot.build_application()
                start_handler = app.handlers[-100][0]
                self.assertIs(start_handler.callback, bot.global_start)
                self.assertFalse(any(
                    handler.callback is start
                    for handler in app.handlers[0]
                ))

                context = SimpleNamespace(
                    user_data={"order_mode": "receipt"},
                    chat_data={"payment": True},
                )
                message = SimpleNamespace(
                    reply_text=AsyncMock(),
                    reply_photo=AsyncMock(),
                )
                update = SimpleNamespace(
                    effective_user=SimpleNamespace(
                        id=700003,
                        username="fallback",
                        first_name="Fallback",
                        last_name="",
                        language_code="km",
                    ),
                    message=message,
                )
                with (
                    patch(
                        "handlers.menu.get_welcome_text",
                        side_effect=RuntimeError("theme unavailable"),
                    ),
                    self.assertLogs("handlers.menu", level="INFO") as logs,
                ):
                    result = await start(update, context)
                self.assertEqual(result, ConversationHandler.END)
                self.assertEqual(
                    message.reply_text.await_args.args[0],
                    "⚠️ មានបញ្ហាបន្តិច សូមសាកល្បងម្ដងទៀត។",
                )
                self.assertTrue(any(
                    "/start received" in entry for entry in logs.output
                ))

                db.track_telegram_user(
                    700003, "fallback", "Fallback", language_code="km"
                )
                db.set_telegram_user_status(700003, "blocked")
                global_message = SimpleNamespace(
                    reply_text=AsyncMock(),
                    reply_photo=AsyncMock(),
                )
                global_update = SimpleNamespace(
                    effective_user=update.effective_user,
                    message=global_message,
                )
                with self.assertRaises(ApplicationHandlerStop):
                    await bot.global_start(
                        global_update,
                        SimpleNamespace(
                            user_data={"order_mode": "receipt"},
                            chat_data={"payment": True},
                        ),
                    )
                self.assertTrue(
                    global_message.reply_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                )
            finally:
                db.DB_PATH = old_path

    async def test_invalid_add_stock_state_recovers_to_main_menu(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "wizard-invalid.db")
            try:
                db.init_db()
                context = SimpleNamespace(
                    user_data={
                        "admin_mode": "create",
                        "admin_step": "male_percent",
                        "draft": {},
                    },
                    chat_data={"wizard_invalid": True},
                )
                message = SimpleNamespace(
                    text="45", photo=None, reply_text=AsyncMock()
                )
                result = await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=message,
                    ),
                    context,
                )
                self.assertEqual(result, -1)
                self.assertEqual(context.user_data, {})
                self.assertEqual(context.chat_data, {})
                self.assertIn(
                    "Add Stock session expired",
                    message.reply_text.await_args.args[0],
                )
                markup = message.reply_text.await_args.kwargs["reply_markup"]
                self.assertTrue(any(
                    button.callback_data == "admin:home"
                    for row in markup.inline_keyboard for button in row
                ))
            finally:
                db.DB_PATH = old_path

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
                    f"លេខបញ្ជាទិញ #{orders[0][0]}",
                    message.reply_text.await_args.args[0],
                )
                self.assertIn(
                    "មិនទាន់បានកំណត់ Payment QR",
                    message.reply_text.await_args.args[0],
                )
                self.assertIn(
                    "សូមទូទាត់តាម Bakong QR",
                    message.reply_text.await_args.args[0],
                )
            finally:
                db.DB_PATH = old_path

    async def test_receipt_auto_approves_and_hides_sold_stock(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "receipt-auto-approve.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$10", "100%", "Auto approve",
                    "https://facebook.com/auto", "available",
                    featured=1, promotion=1,
                )
                user_id = 900
                db.upsert_customer_profile(
                    user_id, "sarin1515hsaron", "Sarin", "Customer"
                )
                db.toggle_favorite(user_id, stock_id)
                order_id = db.create_order(
                    stock_id, user_id, "sarin1515hsaron", "$10"
                )
                self.assertTrue(db.transition_order(
                    order_id, "waiting_receipt", {"waiting_payment"}, user_id
                ))
                message = SimpleNamespace(
                    text=None,
                    photo=[SimpleNamespace(file_id="receipt-auto")],
                    reply_text=AsyncMock(),
                )
                update = SimpleNamespace(
                    effective_user=SimpleNamespace(
                        id=user_id,
                        username="sarin1515hsaron",
                        full_name="Sarin Customer",
                        first_name="Sarin",
                        last_name="Customer",
                    ),
                    message=message,
                )
                context = SimpleNamespace(
                    user_data={"order_mode": "receipt", "order_id": order_id},
                    bot=SimpleNamespace(
                        send_photo=AsyncMock(), send_message=AsyncMock()
                    ),
                )

                self.assertTrue(await handle_order_message(update, context))
                self.assertEqual(context.user_data, {})
                self.assertIn(
                    "✅ Payment approved by @sarin1515hsaron",
                    message.reply_text.await_args.args[0],
                )
                self.assertEqual(db.get_order(order_id)[5], "payment_received")
                stock = db.get_stock(stock_id)
                self.assertEqual(stock[8:11], ("sold", 0, 0))
                self.assertIsNotNone(db.get_order(order_id))
                self.assertEqual(len(db.get_payment_logs(order_id)), 1)

                self.assertNotIn(
                    stock_id, {row[0] for row in db.get_stocks_by_range(1, 20)}
                )
                self.assertNotIn(
                    stock_id, {row[0] for row in db.search_by_followers(10)}
                )
                search_message = SimpleNamespace(
                    text="Cambodia", photo=None, reply_text=AsyncMock()
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=901),
                        message=search_message,
                    ),
                    SimpleNamespace(
                        user_data={"advanced_search": "country"},
                        chat_data={},
                    ),
                )
                search_callbacks = {
                    button.callback_data
                    for row in search_message.reply_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertNotIn(f"stock:{stock_id}", search_callbacks)
                self.assertNotIn(
                    stock_id, {row[0] for row in db.get_special("promotion")}
                )
                self.assertNotIn(
                    stock_id, {row[0] for row in db.get_special("featured")}
                )
                self.assertNotIn(
                    stock_id, {row[0] for row in db.get_new()}
                )
                self.assertNotIn(
                    stock_id, {row[0] for row in db.get_trending_stocks()}
                )
                self.assertNotIn(
                    stock_id, {row[0] for row in db.get_favorite_stocks(user_id)}
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

    async def test_page_invite_accept_help_back_and_cancel_flow(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "page-invite-flow.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$25", "100%", "",
                    "https://facebook.com/page", "sold",
                )
                user_id = 900
                order_id = db.create_order(stock_id, user_id, "buyer", "$25")
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
                context = SimpleNamespace(
                    user_data={"order_flow": "page_invite"},
                    chat_data={"order_flow": "page_invite"},
                    bot=SimpleNamespace(send_message=AsyncMock()),
                )

                help_query = self._wizard_query(f"order:help:{order_id}")
                help_query.from_user = SimpleNamespace(
                    id=user_id, username="buyer",
                    first_name="Buyer", last_name="",
                )
                self.assertIsNone(await handle_customer_order_callback(
                    help_query, context
                ))
                self.assertIn(
                    "ជំនួយសម្រាប់ការកម្មង់",
                    help_query.edit_message_text.await_args.args[0],
                )
                help_callbacks = {
                    button.callback_data
                    for row in help_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertTrue({
                    f"order:accepted:{order_id}",
                    f"order:help:{order_id}",
                    f"order:invite:{order_id}",
                    "global:cancel",
                }.issubset(help_callbacks))

                invite_query = self._wizard_query(f"order:invite:{order_id}")
                invite_query.from_user = help_query.from_user
                self.assertIsNone(await handle_customer_order_callback(
                    invite_query, context
                ))
                self.assertIn(
                    "Page Invite",
                    invite_query.edit_message_text.await_args.args[0],
                )
                invite_callbacks = {
                    button.callback_data
                    for row in invite_query.edit_message_text.await_args.kwargs[
                        "reply_markup"
                    ].inline_keyboard
                    for button in row
                }
                self.assertIn(f"order:view:{order_id}", invite_callbacks)
                self.assertIn("global:cancel", invite_callbacks)

                accepted_query = self._wizard_query(
                    f"order:accepted:{order_id}"
                )
                accepted_query.from_user = help_query.from_user
                self.assertIsNone(await handle_customer_order_callback(
                    accepted_query, context
                ))
                self.assertEqual(
                    db.get_order(order_id)[5], "waiting_remove_admin"
                )
                self.assertIn(
                    "សូមចុចដក Admin",
                    accepted_query.edit_message_text.await_args.args[0],
                )

                cancel_context = SimpleNamespace(
                    user_data={"order_flow": "page_invite"},
                    chat_data={"order_flow": "page_invite"},
                )
                cancel_query = self._wizard_query("global:cancel")
                cancel_query.from_user = help_query.from_user
                result = await handle_callback(
                    SimpleNamespace(callback_query=cancel_query),
                    cancel_context,
                )
                self.assertEqual(result, -1)
                self.assertEqual(cancel_context.user_data, {})
                self.assertEqual(cancel_context.chat_data, {})
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

                page_type_message = SimpleNamespace(
                    photo=[],
                    text="📈 ប្រភេទផេក PE",
                    reply_text=AsyncMock(),
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=page_type_message,
                    ),
                    SimpleNamespace(user_data={
                        "admin_mode": "quick_edit",
                        "edit_stock_id": stock_id,
                        "edit_field": "page_type",
                    }),
                )
                self.assertEqual(
                    db.get_stock(stock_id)[21], "ប្រភេទផេក PE"
                )
                self.assertIn(
                    "Page Type updated",
                    page_type_message.reply_text.await_args.args[0],
                )
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
                        "price_display_mode": "both",
                        "country": "Cambodia",
                        "audience": "All",
                        "page_type": "ប្រភេទផេករឿងសម្រាយ",
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
                self.assertEqual(
                    db.get_stock(stock_id)[21],
                    "ប្រភេទផេករឿងសម្រាយ",
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
                    update.message.reply_text.await_args_list[0].args[0],
                    "✅ បានបន្ថែមរូបភាពដោយជោគជ័យ\n"
                    "📷 បានបន្ថែម 1 រូបភាព",
                )
            finally:
                db.DB_PATH = old_path

    async def test_photo_upload_buttons_done_start_and_khmer_cancel(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "photo-buttons.db")
            try:
                db.init_db()
                stock_id = db.create_stock(
                    10, "Cambodia", "", "$50", "100%", "",
                    "https://facebook.com/photo", "available",
                )
                context = SimpleNamespace(user_data={}, chat_data={})
                begin_photo_upload(context, 619658883, stock_id)
                photo_message = SimpleNamespace(
                    text=None,
                    photo=[SimpleNamespace(file_id="photo-button-file")],
                    reply_text=AsyncMock(),
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=photo_message,
                    ),
                    context,
                )
                labels = {
                    button.text
                    for row in photo_message.reply_text.await_args.kwargs[
                        "reply_markup"
                    ].keyboard
                    for button in row
                }
                self.assertEqual(labels, {
                    "✅ /រួចរាល់", "🚀 /start", "❌ បោះបង់",
                })
                self.assertEqual(
                    db.get_stock_photos(stock_id), ["photo-button-file"]
                )

                done_message = SimpleNamespace(
                    text="✅ /រួចរាល់", photo=None, reply_text=AsyncMock()
                )
                result = await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=done_message,
                    ),
                    context,
                )
                self.assertEqual(result, ConversationHandler.END)
                self.assertIsNone(db.get_photo_upload_session(619658883))
                start_markup = (
                    done_message.reply_text.await_args_list[-2].kwargs[
                        "reply_markup"
                    ]
                )
                self.assertEqual(
                    start_markup.keyboard[0][0].text, "🚀 /start"
                )
                self.assertEqual(
                    done_message.reply_text.await_args_list[0].args[0],
                    "✅ បានបន្ថែមរូបភាពដោយជោគជ័យ\n"
                    "📷 បានបន្ថែម 1 រូបភាព",
                )
                self.assertNotIn("waiting_for_photos", context.user_data)
                self.assertNotIn("waiting_for_photos", context.chat_data)

                for finish_text in ("/done", "/រួចរាល់", "✅ /done"):
                    begin_photo_upload(context, 619658883, stock_id)
                    context.user_data["waiting_for_photos"] = True
                    context.chat_data["waiting_for_photos"] = True
                    finish_message = SimpleNamespace(
                        text=finish_text, photo=None, reply_text=AsyncMock()
                    )
                    result = await handle_text(
                        SimpleNamespace(
                            effective_user=SimpleNamespace(id=619658883),
                            message=finish_message,
                        ),
                        context,
                    )
                    self.assertEqual(result, ConversationHandler.END)
                    self.assertIsNone(db.get_photo_upload_session(619658883))
                    self.assertEqual(context.user_data, {})
                    self.assertNotIn("waiting_for_photos", context.chat_data)

                begin_photo_upload(context, 619658883, stock_id)
                cancel_message = SimpleNamespace(
                    text="❌ បោះបង់", photo=None, reply_text=AsyncMock()
                )
                await handle_text(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=cancel_message,
                    ),
                    context,
                )
                self.assertIsNone(db.get_photo_upload_session(619658883))
                self.assertEqual(context.user_data, {})
            finally:
                db.DB_PATH = old_path

    def test_photo_finish_aliases_use_dedicated_first_handler(self):
        with patch.object(bot, "BOT_TOKEN", "123456:ABCDEF"):
            app = bot.build_application()
        handler = app.handlers[0][0]
        self.assertIs(handler.callback, handle_command)
        for index, text in enumerate(
            ("/done", "/រួចរាល់", "✅ /រួចរាល់", "✅️ /រួចរាល់"),
            start=1,
        ):
            message = Message(
                message_id=index,
                date=datetime.now(),
                chat=Chat(id=619658883, type="private"),
                from_user=User(
                    id=619658883,
                    first_name="Admin",
                    is_bot=False,
                ),
                text=text,
            )
            update = Update(update_id=index, message=message)
            self.assertTrue(handler.check_update(update), text)

    async def test_user_management_tracking_search_block_and_guard(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "telegram-users.db")
            try:
                db.init_db()
                for user_id in range(100001, 100023):
                    db.track_telegram_user(
                        user_id,
                        username=f"user{user_id}",
                        first_name=f"Name {user_id}",
                        language_code="km",
                        count_message=True,
                    )
                db.track_telegram_user(
                    619658883,
                    username="owner",
                    first_name="Owner",
                    is_admin=True,
                    count_message=True,
                )
                stock_id = db.create_stock(
                    10, "Cambodia", "All", "$25.50", "100%", "",
                    "https://facebook.com/user-module", "available",
                )
                db.create_order(
                    stock_id, 100005, "user100005", "$25.50"
                )
                con = db.connect()
                con.execute(
                    "UPDATE orders SET status='completed' WHERE customer_id=?",
                    (100005,),
                )
                con.commit()
                con.close()
                buyer = db.get_telegram_user(100005)
                self.assertEqual(buyer[8], 1)
                self.assertEqual(buyer[9], 25.50)

                rows, total = db.list_telegram_users(page=1, per_page=20)
                self.assertEqual(len(rows), 20)
                self.assertEqual(total, 23)
                search_rows, search_total = db.list_telegram_users(
                    search="@user100005"
                )
                self.assertEqual(search_total, 1)
                self.assertEqual(search_rows[0][0], 100005)
                self.assertIn("អ្នកប្រើសរុប : 23", user_dashboard_text())

                markup = admin_home()
                buttons = {
                    (button.text, button.callback_data)
                    for row in markup.inline_keyboard for button in row
                }
                self.assertIn(
                    ("👥 គ្រប់គ្រងអ្នកប្រើ", "admin:users"),
                    buttons,
                )
                self.assertEqual(
                    sum(
                        button.callback_data == "admin:users"
                        for row in markup.inline_keyboard for button in row
                    ),
                    1,
                )
                page_markup = user_list_keyboard(rows, total, 1)
                callbacks = {
                    button.callback_data
                    for row in page_markup.inline_keyboard for button in row
                }
                self.assertIn("admin:users:list:2", callbacks)

                self.assertTrue(
                    db.set_telegram_user_status(100005, "blocked")
                )
                blocked = db.get_telegram_user(100005)
                self.assertEqual(blocked[10], "blocked")
                self.assertFalse(
                    db.set_telegram_user_status(619658883, "blocked")
                )
                self.assertNotIn(
                    "admin:users:block:619658883:1",
                    {
                        button.callback_data
                        for row in user_detail_keyboard(
                            db.get_telegram_user(619658883), 1
                        ).inline_keyboard
                        for button in row
                    },
                )

                message = SimpleNamespace(reply_text=AsyncMock())
                update = SimpleNamespace(
                    effective_user=SimpleNamespace(
                        id=100005,
                        username="user100005",
                        first_name="Blocked",
                        last_name="User",
                        language_code="km",
                    ),
                    message=message,
                    callback_query=None,
                    effective_message=message,
                )
                with self.assertRaises(ApplicationHandlerStop):
                    await bot.track_and_guard_user(
                        update, SimpleNamespace()
                    )
                message.reply_text.assert_awaited_once_with(
                    bot.BLOCKED_USER_MESSAGE
                )
                self.assertEqual(
                    db.get_telegram_user(100005)[7], 2
                )
            finally:
                db.DB_PATH = old_path

    async def test_user_management_callbacks_and_search_message(self):
        old_path = db.DB_PATH
        with tempfile.TemporaryDirectory() as folder:
            db.DB_PATH = str(Path(folder) / "user-management-ui.db")
            try:
                db.init_db()
                db.track_telegram_user(
                    200001, "searchme", "Search", "Person",
                    language_code="km",
                )
                context = SimpleNamespace(user_data={}, chat_data={})
                query = SimpleNamespace(
                    data="admin:users",
                    from_user=SimpleNamespace(
                        id=619658883, username="owner",
                        first_name="Owner", last_name="",
                    ),
                    edit_message_text=AsyncMock(),
                    answer=AsyncMock(),
                    message=SimpleNamespace(reply_text=AsyncMock()),
                )
                self.assertTrue(
                    await handle_user_management_callback(query, context)
                )
                self.assertIn(
                    "ការគ្រប់គ្រងអ្នកប្រើ",
                    query.edit_message_text.await_args.args[0],
                )

                context.user_data["user_management_mode"] = "search"
                search_message = SimpleNamespace(
                    text="searchme", reply_text=AsyncMock()
                )
                handled = await handle_user_management_message(
                    SimpleNamespace(
                        effective_user=SimpleNamespace(id=619658883),
                        message=search_message,
                    ),
                    context,
                )
                self.assertTrue(handled)
                self.assertIn(
                    "1. @searchme",
                    search_message.reply_text.await_args.args[0],
                )
            finally:
                db.DB_PATH = old_path


if __name__ == "__main__":
    unittest.main()
