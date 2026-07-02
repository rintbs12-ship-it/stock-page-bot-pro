# Stock Page Bot Pro

Version 1.0 Stable — production Telegram stock catalog, order management, CRM,
analytics, automation, and administration bot.

## Requirements

- Python 3.14
- PostgreSQL (Neon recommended) or SQLite 3 for local development
- Telegram bot token from BotFather
- `python-telegram-bot==22.3`

## Local installation

```powershell
cd E:\RS_StockBot_Pro\StockPageBot_Part1\StockPageBot_Part1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, then start the application:

```powershell
python bot.py
```

When `DATABASE_URL` is set, the bot uses PostgreSQL. Otherwise it falls back to
local SQLite. Schema creation and safe additive migrations run at startup.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | Yes | Secret token issued by BotFather |
| `ADMIN_IDS` | Yes | Comma-separated bootstrap admin Telegram IDs |
| `TELEGRAM_CONTACT` | No | Public Telegram contact URL |
| `FACEBOOK_CONTACT` | No | Public Facebook page URL |
| `DATABASE_URL` | Production | PostgreSQL URL; enables persistent PostgreSQL |
| `DB_PATH` | Render SQLite | Must be `/var/data/database.db`; local development defaults to `database.db` |
| `IMAGE_DIR` | No | Optional local image directory |
| `PORT` | On Render | Health server port; defaults to `10000` |

Never commit `.env` or a real bot token. Configure secrets in the hosting
provider. If a token has ever appeared in Git history, revoke and regenerate it
with BotFather before deployment.

## Neon PostgreSQL and Render deployment

1. Create a project at [Neon](https://neon.tech/).
2. Copy its pooled PostgreSQL connection string (`postgresql://...`). Keep
   `sslmode=require` in the URL.
3. In Render, open **Web Service → Environment** and add
   `DATABASE_URL=<your Neon connection string>`.
4. Set `BOT_TOKEN`, `ADMIN_IDS`, `TELEGRAM_CONTACT`, `FACEBOOK_CONTACT`, and
   `PORT`.
5. Deploy and confirm the `/` health check returns `OK`.

`DATABASE_URL` takes priority over `DB_PATH`. `DB_PATH` remains the local
SQLite fallback. Run only one polling instance for each Telegram bot token.

### Render SQLite persistent disk

When `DATABASE_URL` is not configured, attach a Render Persistent Disk at
`/var/data` and set:

```text
DB_PATH=/var/data/database.db
```

The bot also detects Render's `RENDER=true` environment and forces SQLite to
`/var/data/database.db`, so it can never silently fall back to the ephemeral
application path `./database.db` on Render. **Deploy latest commit is safe only
when the persistent disk is mounted and `DB_PATH=/var/data/database.db`.**
Startup logs report the selected backend, exact SQLite path, file existence,
and row counts for stocks, settings, users, orders, and photos. Production
startup never copies a bundled database or inserts demo stocks.

### Migrating existing SQLite data

Stop the bot and make a copy of `database.db`. Deploy once with `DATABASE_URL`
so the PostgreSQL schema is initialized, then migrate from a machine that can
access the SQLite file and Neon:

```bash
pgloader --with "data only" --with "reset sequences" --on-error-stop \
  sqlite:///absolute/path/database.db "$DATABASE_URL"
```

Use Neon's direct (non-pooled) connection string for this one-time import.
The flags preserve the schema initialized by the bot, copy rows, and reset
PostgreSQL sequences. Verify row counts for `stocks`,
`orders`, `telegram_users`, `customer_profiles`, `payment_logs`,
`stock_photos`, `app_settings`, and all remaining tables before switching
production traffic. Retain the original SQLite backup until verification is
complete.

## Customer workflow

Customers can browse and filter stock, search by followers, open localized
Khmer/English stock cards, save favorites, subscribe to notifications, place an
order, upload payment receipts, submit Facebook transfer details, and monitor
order history. Customer callbacks never expose admin actions.

## Admin Panel

The Admin Panel is protected by a database-backed permission check. It includes
stock creation and editing, photo management, orders, customers, analytics,
notifications, settings, audit logs, advanced search, scheduler controls,
backup/restore, and maintenance.

Use `/cancel` to leave an active wizard safely.

### Order Manager

Order Manager handles waiting, paid, processing, completed, and cancelled
orders. Payment approval is guarded against duplicate transitions. Receipt
history, customer notifications, timestamps, status history, and automatic
stock completion are persisted.

### CRM

The Customers section supports customer lookup, profiles, order history, VIP
and ban controls, private notes, spending totals, and targeted communications.

### Analytics

Statistics and Analytics Dashboard report stock activity, order conversion,
revenue, payment results, customer rankings, and trends. Reports can be
filtered and exported.

### Menu Editor

Open `Admin Panel → Settings → Menu Editor`. The owner can edit button text and
emoji, enable or disable customer menu items, reorder entries, and restore
defaults. Changes are stored in SQLite and apply immediately.

### Theme Editor

Open `Admin Panel → Settings → Theme Editor` to configure the welcome emoji,
store title, welcome and footer text, menu style, separators, message icons,
and stock-card template. Template placeholders are validated before saving.

### Scheduler

Scheduler & Auto Tasks restores active jobs from SQLite after every restart.
It supports:

- Daily, weekly, and monthly backups with retention cleanup
- One-time, daily, weekly, and monthly announcements
- Pending-payment, pending-order, follow-up, and custom reminders
- Log, temporary-file, and old-backup cleanup
- Daily optimize, vacuum, analytics refresh, and health checks

### Audit logs and search

Audit Logs records sensitive admin actions with admin, target, details, and
timestamp. Logs support filtering, search, pagination, and CSV export.
Advanced Search covers stock, customers, orders, smart filters, saved filters,
recent searches, pagination, and CSV export.

## Backup and restore

Open `Admin Panel → Backup Manager`.

The in-bot ZIP restore workflow is for SQLite fallback databases. With
PostgreSQL, use Neon point-in-time restore/branches or `pg_dump` and
`pg_restore`; never upload a SQLite ZIP over PostgreSQL.

- Create Backup writes `backup_YYYYMMDD_HHMMSS.zip`.
- ZIP files contain `database.db`, `settings.json`, and `backup_info.json`.
- Export Database creates a consistent SQLite snapshot.
- Auto Backup supports Off, Daily, Weekly, and Monthly.
- Retention keeps the configured latest N backups and removes older archives.

To restore, select a local backup or upload `database.db`/a backup ZIP, review
the confirmation, and approve. The bot validates SQLite before replacement and
creates a safety backup first. Migrations and runtime caches are refreshed after
restore.

## Production behavior

- PostgreSQL uses `DATABASE_URL`, parameterized queries, foreign keys, and
  workload indexes. SQLite fallback uses WAL and busy timeout.
- Startup runs idempotent migrations plus integrity, schema, index, and foreign
  key verification.
- Unexpected update errors receive a reference number, are logged in detail,
  persisted to maintenance history when possible, and reported to admins.
- Background schedulers isolate failures and continue running.
- The health server binds to `0.0.0.0:$PORT`.

## Validation

From the application directory:

```powershell
python -c "import bot, database.db, handlers.menu, handlers.scheduler"
python -m unittest discover -s tests -v
```

For syntax validation:

```powershell
python -m compileall -q bot.py database handlers keyboards tests
```
