# Payment Bot

Telegram subscription/payment management bot with Amharic-first admin and user flows.

## Features
- User onboarding (`/start`) and profile management
- Payment screenshot submission and admin review workflow
- Admin panel for:
  - Admin management
  - Billing cycle configuration
  - Reminder message templates and toggles
  - User management
  - Reports and inbox handling
- Automated reminders based on Ethiopian calendar
- Supabase-backed storage

## Repository Structure
- `bot/main.py` — app bootstrap, handlers, scheduler setup
- `bot/user_handlers.py` — user menu flows and payment submission
- `bot/admin_handlers.py` — admin panel and management workflows
- `bot/database.py` — Supabase data access layer
- `bot/utils.py` — Ethiopian date/time helpers

## Requirements
Dependencies are listed in `bot/requirements.txt`.

## Environment Variables
Set the following before running:
- `TELEGRAM_TOKEN` — bot token from BotFather
- `ADMIN_ID` — super admin Telegram numeric ID
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_KEY` — Supabase service key
- `CHANNEL_ID` — destination chat ID for payment receipts (e.g. `-100...`)

## Run Locally
```bash
cd bot
pip install -r requirements.txt
python main.py
```

## Deployment Notes
- `bot/Procfile` and `bot/runtime.txt` are included for platform deployment workflows.
- Ensure the bot is an admin in the target receipt channel/group.
