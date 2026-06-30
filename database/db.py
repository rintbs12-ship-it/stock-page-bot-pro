import sqlite3
import re
import json
from datetime import datetime
from config import ADMIN_IDS, DB_PATH


DEFAULT_MENU_ITEMS = (
    ("new", "🔥", "ផុសថ្មី", "New Stock", "special:new", 1, 10),
    ("featured", "⭐", "ពិសេស", "Featured", "special:featured", 1, 20),
    ("promotion", "💰", "ប្រូម៉ូសិន", "Promotion", "special:promotion", 1, 30),
    ("contact", "📞", "ទាក់ទង", "Contact", "contact", 1, 40),
    ("search", "🔍", "ស្វែងរក Followers", "Search Followers", "search:start", 1, 50),
    ("notify", "🔔", "Notify Me", "Notify Me", "notify:toggle", 1, 60),
    ("orders", "📦", "My Orders", "My Orders", "orders:mine", 1, 70),
    ("profile", "👤", "My Profile", "My Profile", "profile:view", 1, 75),
    ("language", "🌐", "Language", "Language", "language:choose", 1, 80),
)

_SETTING_CACHE = {}
_ADMIN_CACHE = {}


def clear_runtime_caches():
    _SETTING_CACHE.clear()
    _ADMIN_CACHE.clear()


def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


def init_db():
    clear_runtime_caches()
    con = connect()
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        followers INTEGER NOT NULL,
        country TEXT DEFAULT 'Cambodia',
        audience TEXT DEFAULT '',
        price TEXT DEFAULT '',
        quality TEXT DEFAULT 'A',
        description TEXT DEFAULT '',
        fb_link TEXT DEFAULT '',
        status TEXT DEFAULT 'available',
        featured INTEGER DEFAULT 0,
        promotion INTEGER DEFAULT 0,
        created_at TEXT DEFAULT ''
    )
    """)

    required_stock_columns = {
        "female_percent": "INTEGER DEFAULT 0",
        "male_percent": "INTEGER DEFAULT 0",
        "quality_percent": "INTEGER DEFAULT 100",
        "real_followers": "INTEGER DEFAULT 1",
        "organic_reach": "TEXT DEFAULT 'high'",
        "monetized": "INTEGER DEFAULT 1",
        "no_violation": "INTEGER DEFAULT 1",
        "ready_transfer": "INTEGER DEFAULT 1",
        "business_ready": "INTEGER DEFAULT 1",
        "category": "TEXT DEFAULT ''",
    }
    existing_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(stocks)").fetchall()
    }
    for column, definition in required_stock_columns.items():
        if column not in existing_columns:
            cur.execute(f"ALTER TABLE stocks ADD COLUMN {column} {definition}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id INTEGER NOT NULL,
        file_id TEXT NOT NULL,
        created_at TEXT DEFAULT '',
        FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS photo_upload_sessions (
        user_id INTEGER PRIMARY KEY,
        stock_id INTEGER NOT NULL,
        started_at TEXT DEFAULT '',
        FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INTEGER PRIMARY KEY,
        language TEXT NOT NULL DEFAULT 'km'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_at TEXT DEFAULT ''
    )
    """)
    admin_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.executemany(
        "INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)",
        [(admin_id, admin_time) for admin_id in {619658883, *ADMIN_IDS}],
    )

    cur.execute("""
    CREATE TABLE IF NOT EXISTS favorites (
        user_id INTEGER NOT NULL,
        stock_id INTEGER NOT NULL,
        created_at TEXT DEFAULT '',
        PRIMARY KEY (user_id, stock_id),
        FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notification_subscribers (
        user_id INTEGER PRIMARY KEY,
        subscribed_at TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pending_stock_notifications (
        stock_id INTEGER PRIMARY KEY,
        created_at TEXT DEFAULT '',
        FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock_analytics (
        stock_id INTEGER PRIMARY KEY,
        views INTEGER DEFAULT 0,
        buy_clicks INTEGER DEFAULT 0,
        facebook_clicks INTEGER DEFAULT 0,
        copy_clicks INTEGER DEFAULT 0,
        FOREIGN KEY(stock_id) REFERENCES stocks(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        stock_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        customer_username TEXT DEFAULT '',
        price TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'waiting_payment',
        facebook_profile_link TEXT DEFAULT '',
        requested_page_name TEXT DEFAULT '',
        receipt_file_id TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT '',
        FOREIGN KEY(stock_id) REFERENCES stocks(id)
    )
    """)

    required_order_columns = {
        "payment_at": "TEXT DEFAULT ''",
        "processing_at": "TEXT DEFAULT ''",
        "admin_added_at": "TEXT DEFAULT ''",
        "accepted_at": "TEXT DEFAULT ''",
        "removed_admin_at": "TEXT DEFAULT ''",
        "completed_at": "TEXT DEFAULT ''",
        "cancelled_at": "TEXT DEFAULT ''",
        "rejection_reason": "TEXT DEFAULT ''",
    }
    existing_order_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(orders)").fetchall()
    }
    for column, definition in required_order_columns.items():
        if column not in existing_order_columns:
            cur.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")

    cur.execute("""
        UPDATE orders
        SET completed_at=COALESCE(NULLIF(completed_at, ''), updated_at)
        WHERE status='completed' AND completed_at=''
    """)
    cur.execute("""
        UPDATE orders
        SET cancelled_at=COALESCE(NULLIF(cancelled_at, ''), updated_at)
        WHERE status='cancelled' AND cancelled_at=''
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_status_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        changed_by TEXT DEFAULT 'system',
        note TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        FOREIGN KEY(order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        file_id TEXT NOT NULL,
        uploaded_by INTEGER NOT NULL,
        created_at TEXT DEFAULT '',
        FOREIGN KEY(order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payment_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        admin_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        reason TEXT DEFAULT '',
        receipt_file_id TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        FOREIGN KEY(order_id) REFERENCES orders(order_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS customer_profiles (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL UNIQUE,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',
        last_name TEXT DEFAULT '',
        facebook_profile_link TEXT DEFAULT '',
        default_page_name TEXT DEFAULT '',
        total_orders INTEGER DEFAULT 0,
        completed_orders INTEGER DEFAULT 0,
        cancelled_orders INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0,
        is_vip INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        admin_notes TEXT DEFAULT '',
        created_at TEXT DEFAULT '',
        updated_at TEXT DEFAULT ''
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS broadcasts (
        broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        type TEXT NOT NULL DEFAULT 'all',
        message TEXT DEFAULT '',
        media_type TEXT DEFAULT 'text',
        media_file_id TEXT DEFAULT '',
        total_sent INTEGER DEFAULT 0,
        success INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        blocked INTEGER DEFAULT 0,
        duration REAL DEFAULT 0,
        scheduled_at TEXT DEFAULT '',
        status TEXT DEFAULT 'draft',
        created_at TEXT DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS backup_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        filename TEXT DEFAULT '',
        details TEXT DEFAULT '',
        admin_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        admin_name TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        target TEXT NOT NULL DEFAULT '',
        details TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS saved_filters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        search_type TEXT NOT NULL,
        filters TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS recent_searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        search_type TEXT NOT NULL,
        query TEXT NOT NULL DEFAULT '',
        filters TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        job_type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}',
        recurrence TEXT NOT NULL DEFAULT 'one_time',
        next_run TEXT NOT NULL,
        last_run TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS maintenance_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task TEXT NOT NULL,
        status TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS broadcast_recipients (
        broadcast_id INTEGER NOT NULL,
        telegram_id INTEGER NOT NULL,
        PRIMARY KEY (broadcast_id, telegram_id),
        FOREIGN KEY(broadcast_id) REFERENCES broadcasts(broadcast_id)
            ON DELETE CASCADE
    )
    """)
    required_customer_columns = {
        "username": "TEXT DEFAULT ''",
        "first_name": "TEXT DEFAULT ''",
        "last_name": "TEXT DEFAULT ''",
        "facebook_profile_link": "TEXT DEFAULT ''",
        "default_page_name": "TEXT DEFAULT ''",
        "total_orders": "INTEGER DEFAULT 0",
        "completed_orders": "INTEGER DEFAULT 0",
        "cancelled_orders": "INTEGER DEFAULT 0",
        "total_spent": "REAL DEFAULT 0",
        "is_vip": "INTEGER DEFAULT 0",
        "is_banned": "INTEGER DEFAULT 0",
        "admin_notes": "TEXT DEFAULT ''",
        "created_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
        "phone": "TEXT DEFAULT ''",
    }
    existing_customer_columns = {
        row[1]
        for row in cur.execute("PRAGMA table_info(customer_profiles)").fetchall()
    }
    for column, definition in required_customer_columns.items():
        if column not in existing_customer_columns:
            cur.execute(
                f"ALTER TABLE customer_profiles ADD COLUMN {column} {definition}"
            )
    cur.execute("""
        INSERT OR IGNORE INTO customer_profiles (
            telegram_id, username, created_at, updated_at
        )
        SELECT DISTINCT customer_id, customer_username,
               COALESCE(NULLIF(created_at, ''), datetime('now')),
               COALESCE(NULLIF(updated_at, ''), datetime('now'))
        FROM orders
    """)
    profile_ids = cur.execute(
        "SELECT telegram_id FROM customer_profiles"
    ).fetchall()
    migration_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for (telegram_id,) in profile_ids:
        _refresh_customer_stats_cursor(
            cur, telegram_id, migration_time, touch_activity=False
        )
    cur.execute("""
        INSERT INTO order_receipts (order_id, file_id, uploaded_by, created_at)
        SELECT o.order_id, o.receipt_file_id, o.customer_id,
               COALESCE(NULLIF(o.updated_at, ''), o.created_at)
        FROM orders o
        WHERE o.receipt_file_id <> ''
          AND NOT EXISTS (
              SELECT 1 FROM order_receipts r
              WHERE r.order_id=o.order_id AND r.file_id=o.receipt_file_id
          )
    """)
    cur.execute("""
        INSERT INTO order_status_history (
            order_id, status, changed_by, note, created_at
        )
        SELECT o.order_id, o.status, 'migration', 'Existing order imported',
               COALESCE(NULLIF(o.updated_at, ''), o.created_at)
        FROM orders o
        WHERE NOT EXISTS (
            SELECT 1 FROM order_status_history h WHERE h.order_id=o.order_id
        )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS menu_items (
        item_key TEXT PRIMARY KEY,
        emoji TEXT NOT NULL DEFAULT '',
        label_km TEXT NOT NULL DEFAULT '',
        label_en TEXT NOT NULL DEFAULT '',
        callback_data TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        position INTEGER NOT NULL DEFAULT 0
    )
    """)
    cur.executemany("""
        INSERT OR IGNORE INTO menu_items (
            item_key, emoji, label_km, label_en, callback_data, enabled, position
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, DEFAULT_MENU_ITEMS)

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_followers ON stocks(followers)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_status ON stocks(status)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_country ON stocks(country)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_featured ON stocks(featured)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_promotion ON stocks(promotion)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_category ON stocks(category)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocks_created ON stocks(created_at DESC, id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock_photos_stock ON stock_photos(stock_id, id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id, order_id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, order_id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status_created "
        "ON orders(status, created_at DESC, order_id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_created "
        "ON orders(created_at, order_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_completed "
        "ON orders(completed_at, order_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_history_order "
        "ON order_status_history(order_id, history_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_receipts_order "
        "ON order_receipts(order_id, id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_logs_order "
        "ON payment_logs(order_id, id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_username "
        "ON customer_profiles(username)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_created "
        "ON customer_profiles(created_at, telegram_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_facebook "
        "ON customer_profiles(facebook_profile_link)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_phone "
        "ON customer_profiles(phone)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_activity "
        "ON customer_profiles(updated_at DESC, telegram_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_value "
        "ON customer_profiles(total_spent DESC, total_orders DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_profiles_vip "
        "ON customer_profiles(is_vip, updated_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_broadcasts_schedule "
        "ON broadcasts(status, scheduled_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_backup_logs_created "
        "ON backup_logs(created_at, id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_created "
        "ON audit_logs(created_at DESC, id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_admin "
        "ON audit_logs(admin_id, created_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_action "
        "ON audit_logs(action, created_at DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_saved_filters_admin "
        "ON saved_filters(admin_id, id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_recent_searches_admin "
        "ON recent_searches(admin_id, id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_due "
        "ON scheduled_jobs(status, next_run, id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_maintenance_runs_created "
        "ON maintenance_runs(created_at DESC, id DESC)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_payment_logs_action_created "
        "ON payment_logs(action, created_at)"
    )

    con.commit()
    con.close()


def verify_database():
    required_tables = {
        "admins", "app_settings", "audit_logs", "backup_logs",
        "broadcast_recipients", "broadcasts", "customer_profiles",
        "favorites", "maintenance_runs", "menu_items",
        "notification_subscribers", "order_receipts",
        "order_status_history", "orders", "payment_logs",
        "pending_stock_notifications", "photo_upload_sessions",
        "recent_searches", "saved_filters", "scheduled_jobs",
        "stock_analytics", "stock_photos", "stocks", "user_preferences",
    }
    required_indexes = {
        "idx_stocks_status", "idx_orders_customer", "idx_orders_status_created",
        "idx_customer_profiles_activity", "idx_scheduled_jobs_due",
        "idx_audit_logs_created",
    }
    con = connect()
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = con.execute("PRAGMA foreign_key_check").fetchall()
        tables = {
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    finally:
        con.close()
    missing_tables = sorted(required_tables - tables)
    missing_indexes = sorted(required_indexes - indexes)
    report = {
        "integrity": integrity,
        "foreign_key_errors": foreign_key_errors,
        "missing_tables": missing_tables,
        "missing_indexes": missing_indexes,
    }
    if integrity != "ok" or foreign_key_errors or missing_tables or missing_indexes:
        raise RuntimeError(f"Database verification failed: {report}")
    return report


def add_audit_log(admin_id, admin_name, action, target="", details=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO audit_logs (
            admin_id, admin_name, action, target, details, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        int(admin_id), str(admin_name or admin_id), str(action),
        str(target or ""), str(details or ""), now,
    ))
    log_id = cur.lastrowid
    con.commit()
    con.close()
    return log_id


def get_audit_logs(
    page=1, per_page=20, period="all", admin_id=None, action=None, search=""
):
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    clauses = []
    params = []
    if period in {"today", "7d", "30d"}:
        modifier = {"today": "start of day", "7d": "-7 days", "30d": "-30 days"}[period]
        clauses.append("created_at >= datetime('now', 'localtime', ?)")
        params.append(modifier)
    if admin_id is not None:
        clauses.append("admin_id=?")
        params.append(int(admin_id))
    if action:
        clauses.append("action=?")
        params.append(str(action))
    if search:
        term = f"%{str(search).strip()}%"
        clauses.append("""(
            CAST(admin_id AS TEXT) LIKE ? OR action LIKE ? OR target LIKE ?
            OR details LIKE ?
        )""")
        params.extend([term] * 4)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    con = connect()
    total = con.execute(
        f"SELECT COUNT(*) FROM audit_logs{where}", params
    ).fetchone()[0]
    rows = con.execute(f"""
        SELECT id, admin_id, admin_name, action, target, details, created_at
        FROM audit_logs{where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, (page - 1) * per_page]).fetchall()
    con.close()
    return rows, total


def get_audit_admins():
    con = connect()
    rows = con.execute("""
        SELECT admin_id, MAX(admin_name), COUNT(*)
        FROM audit_logs GROUP BY admin_id ORDER BY MAX(admin_name), admin_id
    """).fetchall()
    con.close()
    return rows


def get_audit_actions():
    con = connect()
    rows = con.execute("""
        SELECT action, COUNT(*) FROM audit_logs
        GROUP BY action ORDER BY action
    """).fetchall()
    con.close()
    return rows


def add_recent_search(admin_id, search_type, query="", filters=None):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO recent_searches (
            admin_id, search_type, query, filters, created_at
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        int(admin_id), search_type, str(query or ""),
        json.dumps(filters or {}, ensure_ascii=False, sort_keys=True),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    search_id = cur.lastrowid
    con.execute("""
        DELETE FROM recent_searches
        WHERE admin_id=? AND id NOT IN (
            SELECT id FROM recent_searches
            WHERE admin_id=? ORDER BY id DESC LIMIT 20
        )
    """, (int(admin_id), int(admin_id)))
    con.commit()
    con.close()
    return search_id


def get_recent_searches(admin_id, limit=10):
    con = connect()
    rows = con.execute("""
        SELECT id, search_type, query, filters, created_at
        FROM recent_searches WHERE admin_id=?
        ORDER BY id DESC LIMIT ?
    """, (int(admin_id), int(limit))).fetchall()
    con.close()
    return [
        (row[0], row[1], row[2], json.loads(row[3] or "{}"), row[4])
        for row in rows
    ]


def save_search_filter(admin_id, name, search_type, filters):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO saved_filters (
            admin_id, name, search_type, filters, created_at
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        int(admin_id), str(name)[:80], search_type,
        json.dumps(filters or {}, ensure_ascii=False, sort_keys=True),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    filter_id = cur.lastrowid
    con.commit()
    con.close()
    return filter_id


def get_saved_filters(admin_id, limit=20):
    con = connect()
    rows = con.execute("""
        SELECT id, name, search_type, filters, created_at
        FROM saved_filters WHERE admin_id=?
        ORDER BY id DESC LIMIT ?
    """, (int(admin_id), int(limit))).fetchall()
    con.close()
    return [
        (row[0], row[1], row[2], json.loads(row[3] or "{}"), row[4])
        for row in rows
    ]


def delete_saved_filter(filter_id, admin_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM saved_filters WHERE id=? AND admin_id=?",
        (int(filter_id), int(admin_id)),
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def global_admin_search(term, limit=100):
    text = str(term or "").strip()
    like = f"%{text.lstrip('@')}%"
    numeric = int(text.lstrip("#")) if text.lstrip("#").isdigit() else -1
    con = connect()
    rows = []
    for row in con.execute("""
        SELECT id, followers, country, status FROM stocks WHERE id=? LIMIT ?
    """, (numeric, limit)).fetchall():
        rows.append(("Stock", row[0], f"Stock #{row[0]}", f"{row[1]}K · {row[2]} · {row[3]}"))
    for row in con.execute("""
        SELECT customer_id, telegram_id, username, first_name, last_name
        FROM customer_profiles
        WHERE customer_id=? OR telegram_id=?
           OR LOWER(username) LIKE LOWER(?)
           OR LOWER(first_name || ' ' || last_name) LIKE LOWER(?)
        ORDER BY customer_id DESC LIMIT ?
    """, (numeric, numeric, like, like, limit)).fetchall():
        name = " ".join(part for part in row[3:5] if part) or row[2] or str(row[1])
        rows.append(("Customer", row[1], f"Customer: {name}", f"Telegram {row[1]} · Profile #{row[0]}"))
    for row in con.execute("""
        SELECT order_id, customer_id, customer_username, status
        FROM orders
        WHERE order_id=? OR customer_id=?
           OR LOWER(customer_username) LIKE LOWER(?)
        ORDER BY order_id DESC LIMIT ?
    """, (numeric, numeric, like, limit)).fetchall():
        rows.append(("Order", row[0], f"Order #{row[0]}", f"Customer {row[1]} · {row[2]} · {row[3]}"))
    con.close()
    return rows[:limit]


def advanced_admin_search(search_type, filters=None, page=1, per_page=10):
    filters = filters or {}
    page = max(1, int(page))
    per_page = max(1, min(100, int(per_page)))
    clauses = []
    params = []
    if search_type == "stock":
        columns = ("id", "followers", "country", "audience", "price", "quality", "status", "category")
        table = "stocks"
        keyword = str(filters.get("keyword", "")).strip()
        if keyword:
            like = f"%{keyword}%"
            clauses.append("""(
                CAST(id AS TEXT) LIKE ? OR description LIKE ? OR country LIKE ?
                OR audience LIKE ? OR category LIKE ?
            )""")
            params.extend([like] * 5)
        if filters.get("price_min") not in (None, ""):
            clauses.append("CAST(REPLACE(REPLACE(price, '$', ''), ',', '') AS REAL)>=?")
            params.append(float(filters["price_min"]))
        if filters.get("price_max") not in (None, ""):
            clauses.append("CAST(REPLACE(REPLACE(price, '$', ''), ',', '') AS REAL)<=?")
            params.append(float(filters["price_max"]))
        for key in ("quality", "country", "status"):
            if filters.get(key):
                clauses.append(f"LOWER({key})=LOWER(?)")
                params.append(filters[key])
        if filters.get("category"):
            clauses.append("(LOWER(category)=LOWER(?) OR LOWER(audience)=LOWER(?))")
            params.extend([filters["category"], filters["category"]])
        order_by = "id DESC"
    elif search_type == "customer":
        columns = (
            "customer_id", "telegram_id", "username", "first_name", "last_name",
            "phone", "total_orders", "total_spent", "is_vip", "updated_at",
        )
        table = "customer_profiles"
        for key, expression in (
            ("name", "LOWER(first_name || ' ' || last_name) LIKE LOWER(?)"),
            ("username", "LOWER(username) LIKE LOWER(?)"),
            ("phone", "phone LIKE ?"),
        ):
            if filters.get(key):
                clauses.append(expression)
                params.append(f"%{str(filters[key]).lstrip('@')}%")
        if filters.get("orders_min") not in (None, ""):
            clauses.append("total_orders>=?")
            params.append(int(filters["orders_min"]))
        if filters.get("spending_min") not in (None, ""):
            clauses.append("total_spent>=?")
            params.append(float(filters["spending_min"]))
        smart = filters.get("smart")
        if smart == "vip":
            clauses.append("is_vip=1")
        elif smart == "high_value":
            clauses.append("total_spent>=?")
            params.append(float(filters.get("high_value_min", 100)))
        elif smart == "recent_active":
            clauses.append("updated_at>=datetime('now', 'localtime', '-7 days')")
        elif smart == "inactive":
            clauses.append("(updated_at='' OR updated_at<datetime('now', 'localtime', '-30 days'))")
        order_by = "updated_at DESC, customer_id DESC"
    elif search_type == "order":
        columns = (
            "order_id", "stock_id", "customer_id", "customer_username",
            "price", "status", "created_at", "updated_at",
        )
        table = "orders"
        status_groups = {
            "pending": ("waiting_payment", "waiting_receipt", "waiting_admin_confirm"),
            "paid": ("payment_confirmed", "payment_received", "waiting_customer_info", "admin_processing", "admin_added", "waiting_customer_accept", "customer_accepted", "waiting_remove_admin"),
            "completed": ("completed",),
            "cancelled": ("cancelled",),
        }
        if filters.get("status") in status_groups:
            statuses = status_groups[filters["status"]]
            clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
        if filters.get("date_from"):
            clauses.append("date(created_at)>=date(?)")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            clauses.append("date(created_at)<=date(?)")
            params.append(filters["date_to"])
        if filters.get("recent"):
            clauses.append("created_at>=datetime('now', 'localtime', '-7 days')")
        order_by = "order_id DESC"
    else:
        return (), [], 0
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    con = connect()
    total = con.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0]
    rows = con.execute(
        f"SELECT {', '.join(columns)} FROM {table}{where} "
        f"ORDER BY {order_by} LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page],
    ).fetchall()
    con.close()
    return columns, rows, total


def create_scheduled_job(
    admin_id, job_type, title, payload, recurrence, next_run
):
    allowed_recurrence = {"one_time", "daily", "weekly", "monthly"}
    if recurrence not in allowed_recurrence:
        raise ValueError("Invalid recurrence")
    if job_type not in {
        "announcement", "pending_payment", "pending_order",
        "customer_followup", "custom_reminder",
    }:
        raise ValueError("Invalid job type")
    datetime.fromisoformat(str(next_run))
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO scheduled_jobs (
            admin_id, job_type, title, payload, recurrence, next_run,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        int(admin_id), str(job_type), str(title)[:120],
        json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        recurrence, str(next_run),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    job_id = cur.lastrowid
    con.commit()
    con.close()
    return job_id


def list_scheduled_jobs(job_types=None, status="active", limit=100):
    clauses = []
    params = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if job_types:
        placeholders = ",".join("?" for _ in job_types)
        clauses.append(f"job_type IN ({placeholders})")
        params.extend(job_types)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    con = connect()
    rows = con.execute(f"""
        SELECT id, admin_id, job_type, title, payload, recurrence,
               next_run, last_run, status, created_at
        FROM scheduled_jobs{where}
        ORDER BY next_run, id LIMIT ?
    """, params + [int(limit)]).fetchall()
    con.close()
    return [
        row[:4] + (json.loads(row[4] or "{}"),) + row[5:] for row in rows
    ]


def get_due_scheduled_jobs(now=None, limit=100):
    now_text = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    rows = con.execute("""
        SELECT id, admin_id, job_type, title, payload, recurrence,
               next_run, last_run, status, created_at
        FROM scheduled_jobs
        WHERE status='active' AND next_run<=?
        ORDER BY next_run, id LIMIT ?
    """, (now_text, int(limit))).fetchall()
    con.close()
    return [
        row[:4] + (json.loads(row[4] or "{}"),) + row[5:] for row in rows
    ]


def update_scheduled_job_run(job_id, last_run, next_run=None, status="active"):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        UPDATE scheduled_jobs
        SET last_run=?, next_run=COALESCE(?, next_run), status=?
        WHERE id=? AND status='active'
    """, (str(last_run), next_run, status, int(job_id)))
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def cancel_scheduled_job(job_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "UPDATE scheduled_jobs SET status='cancelled' "
        "WHERE id=? AND status='active'",
        (int(job_id),),
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def add_maintenance_run(task, status, details=""):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO maintenance_runs (task, status, details, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        str(task), str(status), str(details),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    run_id = cur.lastrowid
    con.commit()
    con.close()
    return run_id


def get_maintenance_runs(limit=20):
    con = connect()
    rows = con.execute("""
        SELECT id, task, status, details, created_at
        FROM maintenance_runs ORDER BY id DESC LIMIT ?
    """, (int(limit),)).fetchall()
    con.close()
    return rows


def add_demo_stock_if_empty():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM stocks")
    total = cur.fetchone()[0]
    if total == 0:
        demo = [
            (1, "Cambodia", "ស្រីច្រើន", "$10", "A", "Demo stock 1K", "https://facebook.com/", "available", 1, 0),
            (5, "Cambodia", "ប្រុសច្រើន", "$35", "A+", "Demo stock 5K", "https://facebook.com/", "available", 0, 1),
            (10, "Cambodia", "ស្រីច្រើន", "$70", "B", "Demo stock 10K", "https://facebook.com/", "available", 0, 0),
        ]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.executemany("""
            INSERT INTO stocks
            (followers,country,audience,price,quality,description,fb_link,status,featured,promotion,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, [x + (now,) for x in demo])
        con.commit()
    con.close()


def create_stock(
    followers, country, audience, price, quality, description, fb_link,
    status, featured=0, promotion=0, female_percent=0, male_percent=0,
    quality_percent=100, real_followers=1, organic_reach="high",
    monetized=1, no_violation=1, ready_transfer=1, business_ready=1,
):
    con = connect()
    cur = con.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO stocks (
            followers, country, audience, price, quality, description,
            fb_link, status, featured, promotion, created_at,
            female_percent, male_percent, quality_percent, real_followers,
            organic_reach, monetized, no_violation, ready_transfer,
            business_ready
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        followers, country, audience, price, quality, description, fb_link,
        status, featured, promotion, now, female_percent, male_percent,
        quality_percent, real_followers, organic_reach, monetized,
        no_violation, ready_transfer, business_ready,
    ))
    stock_id = cur.lastrowid
    con.commit()
    con.close()
    return stock_id


def add_stock_photo(stock_id, file_id):
    if not stock_id or not file_id:
        return False
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT id FROM stock_photos WHERE stock_id=? AND file_id=?", (stock_id, file_id))
    if cur.fetchone():
        con.close()
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO stock_photos (stock_id, file_id, created_at) VALUES (?,?,?)", (stock_id, file_id, now))
    con.commit()
    con.close()
    return True


def get_stock_photos(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT file_id FROM stock_photos WHERE stock_id=? ORDER BY id ASC", (stock_id,))
    rows = [row[0] for row in cur.fetchall()]
    con.close()
    return rows


def get_stock_photo_records(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT id, file_id FROM stock_photos WHERE stock_id=? ORDER BY id ASC",
        (stock_id,),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def get_stock_photo_page(stock_id, index):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM stock_photos WHERE stock_id=?", (stock_id,))
    total = cur.fetchone()[0]
    if total == 0:
        con.close()
        return None, 0, 0
    safe_index = max(0, min(int(index), total - 1))
    cur.execute(
        "SELECT id, file_id FROM stock_photos "
        "WHERE stock_id=? ORDER BY id ASC LIMIT 1 OFFSET ?",
        (stock_id, safe_index),
    )
    record = cur.fetchone()
    con.close()
    return record, safe_index, total


def delete_stock_photo(stock_id, photo_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM stock_photos WHERE stock_id=? AND id=?",
        (stock_id, photo_id),
    )
    deleted = cur.rowcount > 0
    con.commit()
    con.close()
    return deleted


def delete_stock_photos(stock_id, photo_ids):
    unique_ids = sorted({int(photo_id) for photo_id in photo_ids})
    if not unique_ids:
        return 0
    placeholders = ",".join("?" for _ in unique_ids)
    con = connect()
    cur = con.cursor()
    cur.execute(
        f"DELETE FROM stock_photos WHERE stock_id=? AND id IN ({placeholders})",
        (stock_id, *unique_ids),
    )
    deleted = cur.rowcount
    con.commit()
    con.close()
    return deleted


def delete_all_stock_photos(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute("DELETE FROM stock_photos WHERE stock_id=?", (stock_id,))
    deleted = cur.rowcount
    con.commit()
    con.close()
    return deleted


def set_photo_upload_session(user_id, stock_id):
    con = connect()
    cur = con.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("""
        INSERT INTO photo_upload_sessions (user_id, stock_id, started_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            stock_id=excluded.stock_id,
            started_at=excluded.started_at
    """, (user_id, stock_id, now))
    con.commit()
    con.close()


def get_photo_upload_session(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT stock_id FROM photo_upload_sessions WHERE user_id=?",
        (user_id,),
    )
    row = cur.fetchone()
    con.close()
    return row[0] if row else None


def clear_photo_upload_session(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute("DELETE FROM photo_upload_sessions WHERE user_id=?", (user_id,))
    con.commit()
    con.close()


def get_stocks_by_range(start_k, end_k):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT id, followers, country, audience, price, quality, status
        FROM stocks
        WHERE followers BETWEEN ? AND ?
        ORDER BY followers ASC, id DESC
    """, (start_k, end_k))
    rows = cur.fetchall()
    con.close()
    return rows


def get_stock(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT id, followers, country, audience, price, quality, description,
               fb_link, status, featured, promotion, created_at,
               female_percent, male_percent, quality_percent, real_followers,
               organic_reach, monetized, no_violation, ready_transfer,
               business_ready
        FROM stocks WHERE id=?
    """, (stock_id,))
    row = cur.fetchone()
    con.close()
    return row


def get_user_language(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT language FROM user_preferences WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    if row and row[0] in {"km", "en"}:
        return row[0]
    default = get_setting("default_language", "km")
    return default if default in {"km", "en"} else "km"


def set_user_language(user_id, language):
    if language not in {"km", "en"}:
        return False
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO user_preferences (user_id, language)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET language=excluded.language
    """, (user_id, language))
    con.commit()
    con.close()
    return True


def get_setting(key, default=""):
    cache_key = (DB_PATH, str(key))
    if cache_key in _SETTING_CACHE:
        value = _SETTING_CACHE[cache_key]
        return default if value is None else value
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key=?", (key,))
    row = cur.fetchone()
    con.close()
    _SETTING_CACHE[cache_key] = row[0] if row else None
    return row[0] if row else default


def set_setting(key, value):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO app_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))
    con.commit()
    con.close()
    _SETTING_CACHE[(DB_PATH, str(key))] = str(value)


def get_all_settings():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT key, value FROM app_settings ORDER BY key")
    settings = dict(cur.fetchall())
    con.close()
    for key, value in settings.items():
        _SETTING_CACHE[(DB_PATH, key)] = value
    return settings


def add_backup_log(action, filename="", admin_id=0, details=""):
    if action not in {"created", "restore", "import", "delete"}:
        return False
    con = connect()
    con.execute("""
        INSERT INTO backup_logs (
            action, filename, details, admin_id, created_at
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        action, filename or "", details or "", int(admin_id),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    con.commit()
    con.close()
    return True


def get_backup_logs(limit=50):
    con = connect()
    rows = con.execute("""
        SELECT id, action, filename, details, admin_id, created_at
        FROM backup_logs ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return rows


def is_admin_user(user_id):
    cache_key = (DB_PATH, int(user_id))
    if cache_key in _ADMIN_CACHE:
        return _ADMIN_CACHE[cache_key]
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (int(user_id),))
    exists = cur.fetchone() is not None
    con.close()
    _ADMIN_CACHE[cache_key] = exists
    return exists


def list_admins():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT user_id, added_at FROM admins ORDER BY user_id")
    rows = cur.fetchall()
    con.close()
    return rows


def add_admin(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)",
        (int(user_id), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    added = cur.rowcount > 0
    con.commit()
    con.close()
    _ADMIN_CACHE[(DB_PATH, int(user_id))] = True
    return added


def remove_admin(user_id):
    user_id = int(user_id)
    if user_id == 619658883:
        return False
    con = connect()
    cur = con.cursor()
    cur.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    removed = cur.rowcount > 0
    con.commit()
    con.close()
    _ADMIN_CACHE[(DB_PATH, user_id)] = False
    return removed


def is_favorite(user_id, stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM favorites WHERE user_id=? AND stock_id=?",
        (user_id, stock_id),
    )
    exists = cur.fetchone() is not None
    con.close()
    return exists


def toggle_favorite(user_id, stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM favorites WHERE user_id=? AND stock_id=?",
        (user_id, stock_id),
    )
    if cur.fetchone():
        cur.execute(
            "DELETE FROM favorites WHERE user_id=? AND stock_id=?",
            (user_id, stock_id),
        )
        saved = False
    else:
        cur.execute(
            "INSERT INTO favorites (user_id, stock_id, created_at) VALUES (?, ?, ?)",
            (user_id, stock_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        saved = True
    con.commit()
    con.close()
    return saved


def get_favorite_stocks(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT s.id, s.followers, s.country, s.audience, s.price, s.quality, s.status
        FROM favorites f
        JOIN stocks s ON s.id=f.stock_id
        WHERE f.user_id=?
        ORDER BY f.created_at DESC, s.id DESC
    """, (user_id,))
    rows = cur.fetchall()
    con.close()
    return rows


def is_notification_subscriber(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM notification_subscribers WHERE user_id=?",
        (user_id,),
    )
    subscribed = cur.fetchone() is not None
    con.close()
    return subscribed


def toggle_notification_subscription(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT 1 FROM notification_subscribers WHERE user_id=?",
        (user_id,),
    )
    if cur.fetchone():
        cur.execute("DELETE FROM notification_subscribers WHERE user_id=?", (user_id,))
        subscribed = False
    else:
        cur.execute(
            "INSERT INTO notification_subscribers (user_id, subscribed_at) VALUES (?, ?)",
            (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        subscribed = True
    con.commit()
    con.close()
    return subscribed


def get_notification_subscribers():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT user_id FROM notification_subscribers ORDER BY user_id")
    users = [row[0] for row in cur.fetchall()]
    con.close()
    return users


def mark_stock_notification_pending(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO pending_stock_notifications (stock_id, created_at) VALUES (?, ?)",
        (stock_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    con.commit()
    con.close()


def consume_pending_stock_notification(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute(
        "DELETE FROM pending_stock_notifications WHERE stock_id=?",
        (stock_id,),
    )
    pending = cur.rowcount > 0
    con.commit()
    con.close()
    return pending


def increment_stock_analytics(stock_id, event):
    columns = {
        "view": "views",
        "buy": "buy_clicks",
        "facebook": "facebook_clicks",
        "copy": "copy_clicks",
    }
    column = columns.get(event)
    if not column:
        return False
    con = connect()
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO stock_analytics (stock_id) VALUES (?)",
        (stock_id,),
    )
    cur.execute(
        f"UPDATE stock_analytics SET {column}={column}+1 WHERE stock_id=?",
        (stock_id,),
    )
    con.commit()
    con.close()
    return True


def get_analytics_totals():
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(views), 0), COALESCE(SUM(buy_clicks), 0),
               COALESCE(SUM(facebook_clicks), 0), COALESCE(SUM(copy_clicks), 0)
        FROM stock_analytics
    """)
    row = cur.fetchone()
    con.close()
    return {
        "views": row[0], "buy_clicks": row[1],
        "facebook_clicks": row[2], "copy_clicks": row[3],
    }


def get_trending_stocks(limit=10):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT s.id, s.followers, s.country, s.audience, s.price, s.quality, s.status,
               COALESCE(a.views, 0), COALESCE(a.buy_clicks, 0)
        FROM stocks s
        LEFT JOIN stock_analytics a ON a.stock_id=s.id
        ORDER BY COALESCE(a.views, 0) DESC, COALESCE(a.buy_clicks, 0) DESC, s.id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


ORDER_STATUSES = {
    "waiting_payment", "waiting_receipt", "waiting_admin_confirm",
    "payment_confirmed", "payment_received", "waiting_customer_info",
    "admin_processing",
    "admin_added", "customer_accepted", "waiting_customer_accept",
    "waiting_remove_admin", "completed", "cancelled",
}

ORDER_TRANSITIONS = {
    "waiting_payment": {
        "waiting_receipt", "payment_confirmed", "payment_received", "cancelled",
    },
    "waiting_receipt": {
        "waiting_admin_confirm", "payment_confirmed",
        "payment_received", "cancelled",
    },
    "waiting_admin_confirm": {
        "waiting_payment", "payment_confirmed", "payment_received", "cancelled",
    },
    "payment_confirmed": {
        "waiting_customer_info", "admin_processing", "cancelled",
    },
    "payment_received": {"admin_processing", "cancelled"},
    "waiting_customer_info": {"admin_processing", "cancelled"},
    "admin_processing": {"admin_added", "cancelled"},
    "admin_added": {
        "waiting_customer_accept", "customer_accepted", "cancelled",
    },
    "waiting_customer_accept": {
        "customer_accepted", "waiting_remove_admin", "cancelled",
    },
    "customer_accepted": {"waiting_remove_admin", "cancelled"},
    "waiting_remove_admin": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

ORDER_STATUS_TIMESTAMPS = {
    "payment_confirmed": "payment_at",
    "payment_received": "payment_at",
    "admin_processing": "processing_at",
    "admin_added": "admin_added_at",
    "customer_accepted": "accepted_at",
    "waiting_remove_admin": "removed_admin_at",
    "completed": "completed_at",
    "cancelled": "cancelled_at",
}


def create_order(stock_id, customer_id, customer_username, price):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO customer_profiles (
            telegram_id, username, created_at, updated_at
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=CASE WHEN excluded.username<>''
                THEN excluded.username ELSE customer_profiles.username END,
            updated_at=excluded.updated_at
    """, (customer_id, customer_username or "", now, now))
    cur.execute("""
        INSERT INTO orders (
            stock_id, customer_id, customer_username, price, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'waiting_payment', ?, ?)
    """, (stock_id, customer_id, customer_username or "", price, now, now))
    order_id = cur.lastrowid
    cur.execute("""
        INSERT INTO order_status_history (
            order_id, status, changed_by, note, created_at
        ) VALUES (?, 'waiting_payment', ?, 'Order created', ?)
    """, (order_id, str(customer_id), now))
    _refresh_customer_stats_cursor(cur, customer_id, now)
    con.commit()
    con.close()
    return order_id


def get_order(order_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders WHERE order_id=?
    """, (order_id,))
    row = cur.fetchone()
    con.close()
    return row


def transition_order(
    order_id, new_status, expected_statuses, customer_id=None,
    changed_by="system", note="",
):
    if new_status not in ORDER_STATUSES:
        return False
    expected = tuple(expected_statuses)
    if not expected or any(status not in ORDER_STATUSES for status in expected):
        return False
    valid_expected = tuple(
        status for status in expected
        if new_status in ORDER_TRANSITIONS.get(status, set())
    )
    if not valid_expected:
        return False
    expected = valid_expected
    placeholders = ",".join("?" for _ in expected)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timestamp_column = ORDER_STATUS_TIMESTAMPS.get(new_status)
    timestamp_sql = (
        f", {timestamp_column}=CASE WHEN {timestamp_column}='' "
        f"THEN ? ELSE {timestamp_column} END"
        if timestamp_column else ""
    )
    params = [
        new_status,
        now,
    ]
    if timestamp_column:
        params.append(now)
    params.extend([
        order_id,
        *expected,
    ])
    owner_clause = ""
    if customer_id is not None:
        owner_clause = " AND customer_id=?"
        params.append(customer_id)
    con = connect()
    cur = con.cursor()
    cur.execute(
        f"UPDATE orders SET status=?, updated_at=?{timestamp_sql} "
        f"WHERE order_id=? AND status IN ({placeholders}){owner_clause}",
        params,
    )
    changed = cur.rowcount > 0
    if changed:
        cur.execute("""
            INSERT INTO order_status_history (
                order_id, status, changed_by, note, created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            order_id, new_status, str(changed_by), note,
            now,
        ))
        if new_status in {"completed", "cancelled"}:
            customer_row = cur.execute(
                "SELECT customer_id FROM orders WHERE order_id=?",
                (order_id,),
            ).fetchone()
            if customer_row:
                _refresh_customer_stats_cursor(cur, customer_row[0], now)
    con.commit()
    con.close()
    return changed


def get_order_timestamps(order_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT created_at, payment_at, processing_at, admin_added_at,
               accepted_at, removed_admin_at, completed_at, cancelled_at
        FROM orders WHERE order_id=?
    """, (order_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    keys = (
        "created_at", "payment_at", "processing_at", "admin_added_at",
        "accepted_at", "removed_admin_at", "completed_at", "cancelled_at",
    )
    return dict(zip(keys, row))


def update_order_field(order_id, field, value, expected_status, customer_id=None):
    allowed = {
        "facebook_profile_link", "requested_page_name", "receipt_file_id",
    }
    if field not in allowed or expected_status not in ORDER_STATUSES:
        return False
    params = [
        value,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        order_id,
        expected_status,
    ]
    owner_clause = ""
    if customer_id is not None:
        owner_clause = " AND customer_id=?"
        params.append(customer_id)
    con = connect()
    cur = con.cursor()
    cur.execute(
        f"UPDATE orders SET {field}=?, updated_at=? "
        f"WHERE order_id=? AND status=?{owner_clause}",
        params,
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def save_order_receipt(order_id, customer_id, file_id):
    if not file_id:
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    cur = con.cursor()
    cur.execute("""
        UPDATE orders
        SET receipt_file_id=?, status='waiting_admin_confirm', updated_at=?
        WHERE order_id=? AND customer_id=? AND status='waiting_receipt'
    """, (file_id, now, order_id, customer_id))
    changed = cur.rowcount > 0
    if changed:
        cur.execute("""
            INSERT INTO order_receipts (
                order_id, file_id, uploaded_by, created_at
            ) VALUES (?, ?, ?, ?)
        """, (order_id, file_id, customer_id, now))
        cur.execute("""
            INSERT INTO order_status_history (
                order_id, status, changed_by, note, created_at
            ) VALUES (?, 'waiting_admin_confirm', ?, 'Receipt uploaded', ?)
        """, (order_id, str(customer_id), now))
    con.commit()
    con.close()
    return changed


def verify_payment(order_id, admin_id, action, reason=""):
    if action not in {"approved", "rejected"} or not is_admin_user(admin_id):
        return False
    reason = (reason or "").strip()
    if action == "rejected" and (not reason or len(reason) > 500):
        return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_status = "payment_received" if action == "approved" else "waiting_payment"
    con = connect()
    cur = con.cursor()
    if action == "approved":
        cur.execute("""
            UPDATE orders
            SET status='payment_received', payment_at=CASE
                    WHEN payment_at='' THEN ? ELSE payment_at END,
                rejection_reason='', updated_at=?
            WHERE order_id=? AND status='waiting_admin_confirm'
        """, (now, now, order_id))
    else:
        cur.execute("""
            UPDATE orders
            SET status='waiting_payment', rejection_reason=?, updated_at=?
            WHERE order_id=? AND status='waiting_admin_confirm'
        """, (reason, now, order_id))
    changed = cur.rowcount > 0
    if changed:
        receipt_row = cur.execute(
            "SELECT receipt_file_id FROM orders WHERE order_id=?",
            (order_id,),
        ).fetchone()
        receipt_file_id = receipt_row[0] if receipt_row else ""
        cur.execute("""
            INSERT INTO payment_logs (
                order_id, admin_id, action, reason,
                receipt_file_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            order_id, admin_id, action, reason, receipt_file_id, now,
        ))
        cur.execute("""
            INSERT INTO order_status_history (
                order_id, status, changed_by, note, created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            order_id, new_status, str(admin_id),
            f"Payment {action}" + (f": {reason}" if reason else ""),
            now,
        ))
    con.commit()
    con.close()
    return changed


def get_order_receipts(order_id):
    con = connect()
    rows = con.execute("""
        SELECT id, order_id, file_id, uploaded_by, created_at
        FROM order_receipts
        WHERE order_id=?
        ORDER BY id ASC
    """, (order_id,)).fetchall()
    con.close()
    return rows


def get_payment_logs(order_id):
    con = connect()
    rows = con.execute("""
        SELECT id, order_id, admin_id, action, reason,
               receipt_file_id, created_at
        FROM payment_logs
        WHERE order_id=?
        ORDER BY id ASC
    """, (order_id,)).fetchall()
    con.close()
    return rows


def _price_number(value):
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else 0.0


def _refresh_customer_stats_cursor(
    cur, telegram_id, now=None, touch_activity=True
):
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = cur.execute(
        "SELECT status, price FROM orders WHERE customer_id=?",
        (telegram_id,),
    ).fetchall()
    completed = [row for row in rows if row[0] == "completed"]
    activity_update = ", updated_at=?" if touch_activity else ""
    params = [
        len(rows),
        len(completed),
        sum(1 for row in rows if row[0] == "cancelled"),
        sum(_price_number(row[1]) for row in completed),
    ]
    if touch_activity:
        params.append(now)
    params.append(telegram_id)
    cur.execute(f"""
        UPDATE customer_profiles
        SET total_orders=?, completed_orders=?, cancelled_orders=?,
            total_spent=?{activity_update}
        WHERE telegram_id=?
    """, params)


def upsert_customer_profile(
    telegram_id, username="", first_name="", last_name="",
    facebook_profile_link="", default_page_name="",
):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO customer_profiles (
            telegram_id, username, first_name, last_name,
            facebook_profile_link, default_page_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=CASE WHEN excluded.username<>''
                THEN excluded.username ELSE customer_profiles.username END,
            first_name=CASE WHEN excluded.first_name<>''
                THEN excluded.first_name ELSE customer_profiles.first_name END,
            last_name=CASE WHEN excluded.last_name<>''
                THEN excluded.last_name ELSE customer_profiles.last_name END,
            facebook_profile_link=CASE WHEN excluded.facebook_profile_link<>''
                THEN excluded.facebook_profile_link
                ELSE customer_profiles.facebook_profile_link END,
            default_page_name=CASE WHEN excluded.default_page_name<>''
                THEN excluded.default_page_name
                ELSE customer_profiles.default_page_name END,
            updated_at=excluded.updated_at
    """, (
        telegram_id, username or "", first_name or "", last_name or "",
        facebook_profile_link or "", default_page_name or "", now, now,
    ))
    _refresh_customer_stats_cursor(cur, telegram_id, now)
    con.commit()
    con.close()
    return get_customer_profile(telegram_id)


def get_customer_profile(telegram_id):
    con = connect()
    row = con.execute("""
        SELECT customer_id, telegram_id, username, first_name, last_name,
               facebook_profile_link, default_page_name, total_orders,
               completed_orders, cancelled_orders, total_spent, is_vip,
               is_banned, admin_notes, created_at, updated_at
        FROM customer_profiles WHERE telegram_id=?
    """, (telegram_id,)).fetchone()
    con.close()
    return row


def update_customer_profile_field(telegram_id, field, value):
    if field not in {"facebook_profile_link", "default_page_name", "admin_notes"}:
        return False
    con = connect()
    cur = con.cursor()
    cur.execute(
        f"UPDATE customer_profiles SET {field}=?, updated_at=? "
        "WHERE telegram_id=?",
        (value, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), telegram_id),
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def list_customers(limit=50):
    con = connect()
    rows = con.execute("""
        SELECT customer_id, telegram_id, username, first_name, last_name,
               facebook_profile_link, default_page_name, total_orders,
               completed_orders, cancelled_orders, total_spent, is_vip,
               is_banned, admin_notes, created_at, updated_at
        FROM customer_profiles ORDER BY updated_at DESC LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return rows


def search_customers(search_type, value, limit=50):
    fields = {
        "telegram": ("telegram_id=?", int),
        "username": ("LOWER(username) LIKE LOWER(?)", str),
        "facebook": ("LOWER(facebook_profile_link) LIKE LOWER(?)", str),
    }
    field = fields.get(search_type)
    if not field:
        return []
    clause, converter = field
    try:
        value = converter(value)
    except (TypeError, ValueError):
        return []
    if search_type != "telegram":
        value = f"%{str(value).lstrip('@')}%"
    con = connect()
    rows = con.execute(f"""
        SELECT customer_id, telegram_id, username, first_name, last_name,
               facebook_profile_link, default_page_name, total_orders,
               completed_orders, cancelled_orders, total_spent, is_vip,
               is_banned, admin_notes, created_at, updated_at
        FROM customer_profiles WHERE {clause}
        ORDER BY updated_at DESC LIMIT ?
    """, (value, limit)).fetchall()
    con.close()
    return rows


def toggle_customer_flag(telegram_id, field):
    if field not in {"is_vip", "is_banned"}:
        return None
    con = connect()
    cur = con.cursor()
    cur.execute(
        f"UPDATE customer_profiles SET {field}=CASE WHEN {field}=1 THEN 0 ELSE 1 END, "
        "updated_at=? WHERE telegram_id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), telegram_id),
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    if not changed:
        return None
    return bool(get_customer_profile(telegram_id)[11 if field == "is_vip" else 12])


def is_customer_banned(telegram_id):
    profile = get_customer_profile(telegram_id)
    return bool(profile and profile[12])


def get_broadcast_recipients(audience, selected_ids=None):
    con = connect()
    if audience == "vip":
        rows = con.execute("""
            SELECT telegram_id FROM customer_profiles
            WHERE is_banned=0 AND is_vip=1 ORDER BY telegram_id
        """).fetchall()
    elif audience == "orders":
        rows = con.execute("""
            SELECT telegram_id FROM customer_profiles
            WHERE is_banned=0 AND total_orders>0 ORDER BY telegram_id
        """).fetchall()
    elif audience == "selected":
        selected = tuple({
            int(value) for value in (selected_ids or [])
            if str(value).lstrip("-").isdigit()
        })
        if not selected:
            con.close()
            return []
        placeholders = ",".join("?" for _ in selected)
        rows = con.execute(
            f"SELECT telegram_id FROM customer_profiles "
            f"WHERE is_banned=0 AND telegram_id IN ({placeholders}) "
            "ORDER BY telegram_id",
            selected,
        ).fetchall()
    else:
        rows = con.execute("""
            SELECT telegram_id FROM customer_profiles
            WHERE is_banned=0 ORDER BY telegram_id
        """).fetchall()
    con.close()
    return [row[0] for row in rows]


def create_broadcast(
    admin_id, audience, message, media_type="text", media_file_id="",
    scheduled_at="", selected_ids=None,
):
    if audience not in {"all", "vip", "orders", "selected"}:
        return None
    if media_type not in {"text", "photo", "video", "document"}:
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "scheduled" if scheduled_at else "pending"
    con = connect()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO broadcasts (
            admin_id, type, message, media_type, media_file_id,
            scheduled_at, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        admin_id, audience, message or "", media_type,
        media_file_id or "", scheduled_at or "", status, now,
    ))
    broadcast_id = cur.lastrowid
    if audience == "selected":
        recipients = get_broadcast_recipients("selected", selected_ids)
        cur.executemany("""
            INSERT OR IGNORE INTO broadcast_recipients (
                broadcast_id, telegram_id
            ) VALUES (?, ?)
        """, ((broadcast_id, telegram_id) for telegram_id in recipients))
    con.commit()
    con.close()
    return broadcast_id


def get_broadcast(broadcast_id):
    con = connect()
    row = con.execute("""
        SELECT broadcast_id, admin_id, type, message, media_type,
               media_file_id, total_sent, success, failed, blocked,
               duration, scheduled_at, status, created_at
        FROM broadcasts WHERE broadcast_id=?
    """, (broadcast_id,)).fetchone()
    con.close()
    return row


def get_saved_broadcast_recipients(broadcast_id):
    con = connect()
    rows = con.execute("""
        SELECT telegram_id FROM broadcast_recipients
        WHERE broadcast_id=? ORDER BY telegram_id
    """, (broadcast_id,)).fetchall()
    con.close()
    return [row[0] for row in rows]


def complete_broadcast(
    broadcast_id, total_sent, success, failed, blocked, duration,
):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        UPDATE broadcasts
        SET total_sent=?, success=?, failed=?, blocked=?,
            duration=?, status='completed'
        WHERE broadcast_id=? AND status IN ('pending', 'sending', 'scheduled')
    """, (
        total_sent, success, failed, blocked, float(duration), broadcast_id,
    ))
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def mark_broadcast_sending(broadcast_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        UPDATE broadcasts SET status='sending'
        WHERE broadcast_id=? AND status IN ('pending', 'scheduled')
    """, (broadcast_id,))
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def get_due_broadcasts(now=None):
    now_text = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    rows = con.execute("""
        SELECT broadcast_id, admin_id, type, message, media_type,
               media_file_id, total_sent, success, failed, blocked,
               duration, scheduled_at, status, created_at
        FROM broadcasts
        WHERE status='scheduled' AND scheduled_at<=?
        ORDER BY scheduled_at, broadcast_id
    """, (now_text,)).fetchall()
    con.close()
    return rows


def get_broadcast_history(limit=20):
    con = connect()
    rows = con.execute("""
        SELECT broadcast_id, admin_id, type, message, media_type,
               media_file_id, total_sent, success, failed, blocked,
               duration, scheduled_at, status, created_at
        FROM broadcasts ORDER BY broadcast_id DESC LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return rows


def get_customer_orders(customer_id, limit=20):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders WHERE customer_id=?
        ORDER BY order_id DESC LIMIT ?
    """, (customer_id, limit))
    rows = cur.fetchall()
    con.close()
    return rows


def get_customer_action_order(customer_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders
        WHERE customer_id=?
          AND status IN ('waiting_customer_info', 'payment_received')
        ORDER BY order_id DESC LIMIT 1
    """, (customer_id,))
    row = cur.fetchone()
    con.close()
    return row


def get_orders_by_group(group_name, limit=30):
    groups = {
        "waiting": ("waiting_admin_confirm",),
        "processing": (
            "payment_confirmed", "payment_received", "waiting_customer_info",
            "admin_processing", "admin_added", "waiting_customer_accept",
            "customer_accepted", "waiting_remove_admin",
        ),
        "completed": ("completed",),
        "cancelled": ("cancelled",),
    }
    statuses = groups.get(group_name)
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    con = connect()
    cur = con.cursor()
    cur.execute(f"""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders WHERE status IN ({placeholders})
        ORDER BY order_id DESC LIMIT ?
    """, (*statuses, limit))
    rows = cur.fetchall()
    con.close()
    return rows


def get_active_orders(limit=50):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders
        WHERE status NOT IN ('completed', 'cancelled')
        ORDER BY order_id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


def get_all_orders(limit=100):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders
        ORDER BY order_id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


def get_order_history(order_id):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT history_id, order_id, status, changed_by, note, created_at
        FROM order_status_history
        WHERE order_id=?
        ORDER BY history_id ASC
    """, (order_id,))
    rows = cur.fetchall()
    con.close()
    return rows


def search_orders(search_type, value, limit=50):
    fields = {
        "order_id": ("order_id=?", int),
        "telegram_id": ("customer_id=?", int),
        "customer_name": ("LOWER(customer_username) LIKE LOWER(?)", str),
        "stock_id": ("stock_id=?", int),
    }
    field = fields.get(search_type)
    if not field:
        return []
    clause, converter = field
    try:
        converted = converter(value)
    except (TypeError, ValueError):
        return []
    if search_type == "customer_name":
        converted = f"%{converted.lstrip('@')}%"
    con = connect()
    cur = con.cursor()
    cur.execute(f"""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders WHERE {clause}
        ORDER BY order_id DESC LIMIT ?
    """, (converted, limit))
    rows = cur.fetchall()
    con.close()
    return rows


def filter_orders(filter_name, limit=50):
    groups = {
        "pending": (
            "waiting_payment", "waiting_receipt", "waiting_admin_confirm",
        ),
        "processing": (
            "payment_confirmed", "payment_received", "waiting_customer_info",
            "admin_processing",
            "admin_added", "waiting_customer_accept", "customer_accepted",
            "waiting_remove_admin",
        ),
        "completed": ("completed",),
        "cancelled": ("cancelled",),
    }
    statuses = groups.get(filter_name)
    if not statuses:
        return []
    placeholders = ",".join("?" for _ in statuses)
    con = connect()
    cur = con.cursor()
    cur.execute(f"""
        SELECT order_id, stock_id, customer_id, customer_username, price,
               status, facebook_profile_link, requested_page_name,
               receipt_file_id, created_at, updated_at
        FROM orders WHERE status IN ({placeholders})
        ORDER BY order_id DESC LIMIT ?
    """, (*statuses, limit))
    rows = cur.fetchall()
    con.close()
    return rows


def get_menu_items(enabled_only=False):
    con = connect()
    cur = con.cursor()
    query = """
        SELECT item_key, emoji, label_km, label_en, callback_data, enabled, position
        FROM menu_items
    """
    if enabled_only:
        query += " WHERE enabled=1"
    query += " ORDER BY position ASC, item_key ASC"
    cur.execute(query)
    rows = cur.fetchall()
    con.close()
    return rows


def get_menu_item(item_key):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT item_key, emoji, label_km, label_en, callback_data, enabled, position
        FROM menu_items WHERE item_key=?
    """, (item_key,))
    row = cur.fetchone()
    con.close()
    return row


def update_menu_item(item_key, field, value):
    if field not in {"emoji", "label_km", "label_en", "enabled"}:
        return False
    if field == "enabled":
        value = 1 if value else 0
    con = connect()
    cur = con.cursor()
    cur.execute(
        f"UPDATE menu_items SET {field}=? WHERE item_key=?",
        (value, item_key),
    )
    changed = cur.rowcount > 0
    con.commit()
    con.close()
    return changed


def move_menu_item(item_key, direction):
    if direction not in {"up", "down"}:
        return False
    con = connect()
    cur = con.cursor()
    cur.execute(
        "SELECT position FROM menu_items WHERE item_key=?",
        (item_key,),
    )
    current = cur.fetchone()
    if not current:
        con.close()
        return False
    operator = "<" if direction == "up" else ">"
    ordering = "DESC" if direction == "up" else "ASC"
    cur.execute(
        f"SELECT item_key, position FROM menu_items "
        f"WHERE position {operator} ? ORDER BY position {ordering} LIMIT 1",
        (current[0],),
    )
    neighbor = cur.fetchone()
    if not neighbor:
        con.close()
        return False
    cur.execute(
        "UPDATE menu_items SET position=? WHERE item_key=?",
        (neighbor[1], item_key),
    )
    cur.execute(
        "UPDATE menu_items SET position=? WHERE item_key=?",
        (current[0], neighbor[0]),
    )
    con.commit()
    con.close()
    return True


def reset_menu_items():
    con = connect()
    cur = con.cursor()
    cur.executemany("""
        INSERT INTO menu_items (
            item_key, emoji, label_km, label_en, callback_data, enabled, position
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_key) DO UPDATE SET
            emoji=excluded.emoji,
            label_km=excluded.label_km,
            label_en=excluded.label_en,
            callback_data=excluded.callback_data,
            enabled=excluded.enabled,
            position=excluded.position
    """, DEFAULT_MENU_ITEMS)
    con.commit()
    con.close()


def search_by_followers(k):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT id, followers, country, audience, price, quality, status
        FROM stocks
        WHERE followers=?
        ORDER BY id DESC
    """, (k,))
    rows = cur.fetchall()
    con.close()
    return rows


def search_stocks(field, value=None, minimum=None, maximum=None):
    base = """
        SELECT id, followers, country, audience, price, quality, status
        FROM stocks
    """
    params = ()
    if field == "country":
        query = base + " WHERE LOWER(country)=LOWER(?)"
        params = (value,)
    elif field == "quality":
        query = base + " WHERE quality_percent=?"
        params = (int(value),)
    elif field == "status":
        query = base + " WHERE status=?"
        params = (value,)
    elif field == "price":
        query = """
            WITH priced AS (
                SELECT id, followers, country, audience, price, quality, status,
                       CAST(TRIM(REPLACE(REPLACE(price, '$', ''), ',', '')) AS REAL) AS amount,
                       TRIM(REPLACE(REPLACE(price, '$', ''), ',', '')) AS cleaned
                FROM stocks
            )
            SELECT id, followers, country, audience, price, quality, status
            FROM priced
            WHERE cleaned <> ''
              AND cleaned GLOB '*[0-9]*'
              AND cleaned NOT GLOB '*[^0-9.]*'
              AND amount BETWEEN ? AND ?
        """
        params = (float(minimum), float(maximum))
    else:
        return []
    con = connect()
    cur = con.cursor()
    cur.execute(query + " ORDER BY id DESC", params)
    rows = cur.fetchall()
    con.close()
    return rows


def get_special(kind):
    field = "featured" if kind == "featured" else "promotion"
    con = connect()
    cur = con.cursor()
    cur.execute(f"""
        SELECT id, followers, country, audience, price, quality, status
        FROM stocks
        WHERE {field}=1
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows


def get_new(limit=20):
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT id, followers, country, audience, price, quality, status
        FROM stocks
        ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    con.close()
    return rows


def get_all_stocks():
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT id, followers, country, audience, price, quality, status
        FROM stocks
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    con.close()
    return rows


def update_stock_field(stock_id, field, value):
    allowed = {
        "followers", "country", "audience", "price", "quality",
        "description", "fb_link", "status", "featured", "promotion",
        "female_percent", "male_percent", "quality_percent",
        "real_followers", "organic_reach", "monetized", "no_violation",
        "ready_transfer", "business_ready",
    }
    if field not in allowed:
        return False
    con = connect()
    cur = con.cursor()
    if field == "followers":
        value = int(value)
    elif field in {"featured", "promotion"}:
        value = int(bool(value))
    cur.execute(f"UPDATE stocks SET {field}=? WHERE id=?", (value, stock_id))
    con.commit()
    con.close()
    return True


def toggle_stock_status(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT status FROM stocks WHERE id=?", (stock_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return None
    new_status = "sold" if row[0] == "available" else "available"
    cur.execute("UPDATE stocks SET status=? WHERE id=?", (new_status, stock_id))
    con.commit()
    con.close()
    return new_status


def toggle_stock_flag(stock_id, field):
    if field not in {"featured", "promotion"}:
        return None
    con = connect()
    cur = con.cursor()
    cur.execute(f"SELECT {field} FROM stocks WHERE id=?", (stock_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return None
    new_value = 0 if row[0] else 1
    cur.execute(f"UPDATE stocks SET {field}=? WHERE id=?", (new_value, stock_id))
    con.commit()
    con.close()
    return new_value


def delete_stock(stock_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM orders WHERE stock_id=? LIMIT 1", (stock_id,))
    if cur.fetchone():
        con.close()
        return False
    cur.execute("DELETE FROM favorites WHERE stock_id=?", (stock_id,))
    cur.execute("DELETE FROM stock_analytics WHERE stock_id=?", (stock_id,))
    cur.execute("DELETE FROM pending_stock_notifications WHERE stock_id=?", (stock_id,))
    cur.execute("DELETE FROM photo_upload_sessions WHERE stock_id=?", (stock_id,))
    cur.execute("DELETE FROM stock_photos WHERE stock_id=?", (stock_id,))
    cur.execute("DELETE FROM stocks WHERE id=?", (stock_id,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()
    return deleted


def get_stock_stats():
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(CASE WHEN status='available' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status='sold' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN featured=1 THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN promotion=1 THEN 1 ELSE 0 END), 0),
            (SELECT COUNT(*) FROM stock_photos)
        FROM stocks
    """)
    row = cur.fetchone()
    con.close()
    return row


def get_dashboard_stats():
    con = connect()
    cur = con.cursor()
    cur.execute("""
        SELECT
            COUNT(*),
            COALESCE(SUM(status='available'), 0),
            COALESCE(SUM(status='sold'), 0),
            COALESCE(SUM(featured=1), 0),
            COALESCE(SUM(promotion=1), 0),
            (SELECT COUNT(*) FROM stock_photos),
            COALESCE(SUM(followers BETWEEN 1 AND 5), 0),
            COALESCE(SUM(followers BETWEEN 6 AND 10), 0),
            COALESCE(SUM(followers BETWEEN 11 AND 20), 0),
            COALESCE(SUM(followers BETWEEN 21 AND 30), 0),
            COALESCE(SUM(followers BETWEEN 31 AND 50), 0),
            COALESCE(SUM(followers BETWEEN 51 AND 100), 0),
            COALESCE(SUM(LOWER(TRIM(country))='cambodia'), 0),
            COALESCE(SUM(LOWER(TRIM(country))='thailand'), 0),
            COALESCE(SUM(LOWER(TRIM(country))='vietnam'), 0),
            COALESCE(SUM(
                LOWER(TRIM(country)) NOT IN ('cambodia', 'thailand', 'vietnam')
            ), 0)
        FROM stocks
    """)
    row = cur.fetchone()

    cur.execute("""
        WITH cleaned_prices AS (
            SELECT TRIM(REPLACE(REPLACE(price, '$', ''), ',', '')) AS value
            FROM stocks
        ),
        numeric_prices AS (
            SELECT CAST(value AS REAL) AS amount
            FROM cleaned_prices
            WHERE value <> ''
              AND value GLOB '*[0-9]*'
              AND value NOT GLOB '*[^0-9.]*'
        )
        SELECT MIN(amount), MAX(amount), AVG(amount)
        FROM numeric_prices
    """)
    price_row = cur.fetchone()
    con.close()

    return {
        "total": row[0],
        "available": row[1],
        "sold": row[2],
        "featured": row[3],
        "promotion": row[4],
        "photos": row[5],
        "categories": {
            "1K–5K": row[6],
            "6K–10K": row[7],
            "11K–20K": row[8],
            "21K–30K": row[9],
            "31K–50K": row[10],
            "51K–100K": row[11],
        },
        "countries": {
            "Cambodia": row[12],
            "Thailand": row[13],
            "Vietnam": row[14],
            "Others": row[15],
        },
        "prices": {
            "lowest": price_row[0],
            "highest": price_row[1],
            "average": price_row[2],
        },
    }
