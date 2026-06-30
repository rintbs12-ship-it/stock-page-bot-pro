# Stock Page Bot Pro

Version 1.0 Stable — production Telegram stock catalog, order management, CRM,
analytics, automation, and administration bot.

## Requirements

- Python 3.14
- SQLite 3
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

The bot initializes and migrates SQLite automatically, verifies database
integrity and foreign keys, starts its health server, restores persistent jobs,
and begins Telegram polling.

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `BOT_TOKEN` | Yes | Secret token issued by BotFather |
| `ADMIN_IDS` | Yes | Comma-separated bootstrap admin Telegram IDs |
| `TELEGRAM_CONTACT` | No | Public Telegram contact URL |
| `FACEBOOK_CONTACT` | No | Public Facebook page URL |
| `DB_PATH` | No | SQLite path; defaults to `database.db` |
| `IMAGE_DIR` | No | Optional local image directory |
| `PORT` | On Render | Health server port; defaults to `10000` |

Never commit `.env` or a real bot token. Configure secrets in the hosting
provider. If a token has ever appeared in Git history, revoke and regenerate it
with BotFather before deployment.

## Render deployment

The included `render.yaml` creates a Python web service with a persistent disk.

1. Push the repository to a private Git provider.
2. In Render, create a Blueprint from `render.yaml`.
3. Set `BOT_TOKEN`, `ADMIN_IDS`, `TELEGRAM_CONTACT`, and `FACEBOOK_CONTACT`.
4. Keep `DB_PATH=/var/data/database.db`.
5. Deploy and confirm the `/` health check returns `OK`.

A persistent disk is required. Without it, SQLite data and local backups are
lost during redeployment. Run only one polling instance against a bot token.

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

- SQLite uses WAL, foreign keys, busy timeout, parameterized queries, and
  workload indexes.
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
