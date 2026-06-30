import sqlite3
from datetime import datetime
from config import DB_PATH


def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


def init_db():
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
    cur.execute(
        "INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)",
        (619658883, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
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
        "CREATE INDEX IF NOT EXISTS idx_stock_photos_stock ON stock_photos(stock_id, id)"
    )

    con.commit()
    con.close()


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
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key=?", (key,))
    row = cur.fetchone()
    con.close()
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


def get_all_settings():
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT key, value FROM app_settings ORDER BY key")
    settings = dict(cur.fetchall())
    con.close()
    return settings


def is_admin_user(user_id):
    con = connect()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM admins WHERE user_id=?", (int(user_id),))
    exists = cur.fetchone() is not None
    con.close()
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
