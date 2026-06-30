# Stock Page Bot Pro

Version 1.0 — production Telegram stock-page catalog and administration bot.

## Requirements

- Python 3.14
- `python-telegram-bot==22.3`
- SQLite 3
- A Telegram bot token from BotFather

## Installation

Open PowerShell in the project folder:

```powershell
cd E:\RS_StockBot_Pro
python -m pip install -r StockPageBot_Part1\StockPageBot_Part1\requirements.txt
```

Configure `StockPageBot_Part1\StockPageBot_Part1\.env`:

```env
BOT_TOKEN=YOUR_BOT_TOKEN
ADMIN_IDS=619658883
TELEGRAM_CONTACT=https://t.me/your_username
FACEBOOK_CONTACT=https://facebook.com/your_page
```

The owner account is Telegram user ID `619658883`. Additional admins are
managed from Settings and stored in SQLite.

## Running the bot

From the repository root:

```powershell
python bot.py
```

Stop the bot with `Ctrl+C`. After code updates, stop and run it again.

## Customer guide

- Use `/start` to open the main menu.
- Switch between Khmer and English with `🌐 Language / ភាសា`.
- Browse Menu 1–6, New Stock, Featured, Promotion, and Available stock.
- Search by followers or use Advanced Search for country, price, quality,
  and status.
- Open stock details to view photos, contact the store, buy, share, save a
  favorite, or subscribe to new-stock notifications.
- Use Favorites and Trending from the main menu.

## Admin guide

The Admin Panel is hidden from customers. Admin functions include:

- Add Stock wizard and unlimited photo upload (`/done` to finish)
- Manage Stock and Quick Edit
- Photo Manager
- Featured and Promotion controls
- Statistics and customer analytics
- Backup and Restore
- Store Settings and Admin Manager

Use `/cancel` to safely leave an active admin wizard or edit operation.

## Backup

Open `Admin Panel → 💾 Backup`.

- `Create Backup` generates `backup_YYYYMMDD_HHMMSS.zip`.
- Each ZIP contains `database.db`, `settings.json`, and `backup_info.json`.
- `Export Database` sends a consistent raw SQLite snapshot.
- Backup History lists the latest 10 local backups.
- Auto Backup supports Off, Daily, Weekly, and Monthly schedules.

Local ZIP files are stored in the `backups` directory beside the database.

## Restore

1. Open `Admin Panel → 💾 Backup → Restore Database`.
2. Upload `database.db` or a backup ZIP.
3. Confirm the restore.

The bot validates SQLite integrity and required tables before confirmation.
It also creates a safety backup of the current database before replacement.
Existing data is never overwritten without explicit confirmation.

## Database and upgrades

The bot runs safe, idempotent migrations at startup. Existing stock and photo
records are preserved. SQLite uses WAL mode, foreign-key checks, busy timeouts,
and indexes for production reads.

## Testing

From the application directory:

```powershell
cd E:\RS_StockBot_Pro\StockPageBot_Part1\StockPageBot_Part1
python -m py_compile bot.py handlers\*.py keyboards\*.py database\*.py
python -m unittest discover -s tests -v
```

See [CHANGELOG.md](CHANGELOG.md) for release history.
