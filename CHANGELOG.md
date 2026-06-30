# Changelog

## Stock Page Bot Pro 1.0 Stable — 2026-06-30

Final production release covering Modules 1–22.

### Core platform

- Professional admin panel with database-backed permissions
- Guided stock creation, editing, flags, promotions, and photo management
- Khmer/English customer catalog, favorites, notifications, and sharing
- Order, payment receipt, Facebook transfer, and status-history workflows
- Customer CRM, VIP/ban controls, private notes, and targeted broadcasts

### Administration and insight

- Statistics and analytics dashboards with exports
- Backup, validated restore, history, retention, and automatic schedules
- Store settings, Menu Editor, Theme Editor, payment QR, and announcements
- Admin audit logs with filters, search, pagination, and CSV export
- Global and advanced stock/customer/order search with smart and saved filters

### Automation

- Persistent scheduled announcements and reminders
- Daily, weekly, and monthly recurring jobs restored after restart
- Automatic backup and cleanup
- Daily optimize, vacuum, analytics refresh, and database health checks

### Final production hardening

- Added safe runtime caches for repeated settings and permission lookups
- Added workload indexes for search, order, customer, and scheduler queries
- Added startup integrity, foreign-key, schema, migration, and index validation
- Hardened update and background-task error boundaries with admin diagnostics
- Removed the tracked environment-secret file and added safe deployment samples
- Added Render Blueprint configuration with persistent SQLite storage
- Updated installation, deployment, backup, editor, scheduler, CRM, analytics,
  and Order Manager documentation

All migrations are idempotent and preserve existing customer, stock, order,
settings, audit, scheduler, and backup data.
