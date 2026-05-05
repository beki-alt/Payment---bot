"""
main.py - Core Bot Initialization
Registers all handlers, schedules automated jobs, and starts the bot.
"""

import os
import asyncio
import logging
from datetime import time as dt_time

import pytz
from utils import ETH_TZ, now_eth, to_ethiopian, eth_days_in_month

from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import database as db
from keep_alive import keep_alive
from admin_handlers import (
    admin_panel,
    admin_panel_callback,
    admin_manage_callback,
    settings_callback,
    users_callback,
    inbox_callback,
    report_callback,
    build_admin_conversation,
    send_payment_start_reminder,
    send_one_day_reminder,
    send_final_day_reminder,
    monthly_cycle_reset_job,
)
from user_handlers import (
    start,
    my_profile,
    profile_callback,
    pay_renew,
    payment_schedule,
    support_and_history,
    support_history_callback,
    build_profile_conversation,
    build_payment_conversation,
    build_support_conversation,
)

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


async def post_init(application: Application):
    """Called after the application is initialized — seed DB and schedule jobs."""
    # ── Database initialization ──────────────────────────────────────────────
    try:
        db.init_tables()
        logger.info("✅ Database tables initialized.")
    except Exception as e:
        logger.error(f"DB init error: {e}")

    # ── Ensure super admin exists ────────────────────────────────────────────
    if ADMIN_ID:
        db.add_admin(ADMIN_ID, ADMIN_ID, is_super=True)
        logger.info(f"✅ Super admin ensured: {ADMIN_ID}")

    # ── Set bot commands ─────────────────────────────────────────────────────
    await application.bot.set_my_commands([
        BotCommand("start", "ቦቱን ጀምር"),
        BotCommand("admin", "የአስተዳዳሪ ፓነል"),
        BotCommand("cancel", "ሂደቱን ሰርዝ"),
    ])

    # ── Start Supabase keep-alive in background ──────────────────────────────
    asyncio.ensure_future(db.ping_supabase())
    logger.info("✅ Supabase keep-alive task scheduled.")

    # ── Schedule automated billing reminders ────────────────────────────────
    job_queue = application.job_queue
    if job_queue is None:
        logger.warning("JobQueue is not available. Reminders will not run.")
        return

    cycle = db.get_billing_cycle()
    start_day = cycle["start"]
    end_day = cycle["end"]

    # Payment start reminder — fires daily at 12:00 Ethiopian time; only sends on billing start day
    async def _payment_start_guard(ctx):
        _, __, eth_day = to_ethiopian(now_eth())
        if eth_day == start_day:
            await send_payment_start_reminder(ctx)

    async def _one_day_guard(ctx):
        eth_year, eth_month, eth_day = to_ethiopian(now_eth())
        # Ethiopian months 1-12 have 30 days; month 13 (Pagume) has 5 or 6
        days_in_eth_month = eth_days_in_month(eth_year, eth_month)
        one_day_before = end_day - 1 if end_day > 1 else days_in_eth_month
        if eth_day == one_day_before:
            await send_one_day_reminder(ctx)

    async def _final_day_guard(ctx):
        _, __, eth_day = to_ethiopian(now_eth())
        if eth_day == end_day:
            await send_final_day_reminder(ctx)

    # All reminders fire at 12:00 noon Ethiopian time (Africa/Addis_Ababa)
    job_queue.run_daily(_payment_start_guard, time=dt_time(12, 0, 0, tzinfo=ETH_TZ), name="payment_start")
    job_queue.run_daily(_one_day_guard,       time=dt_time(12, 0, 0, tzinfo=ETH_TZ), name="one_day_reminder")
    job_queue.run_daily(_final_day_guard,     time=dt_time(12, 0, 0, tzinfo=ETH_TZ), name="final_day_reminder")

    # ── Monthly cycle reset — fires at 00:05 Ethiopian time the day after end day ──
    async def _monthly_reset_guard(ctx):
        eth_year, eth_month, eth_day = to_ethiopian(now_eth())
        # Ethiopian months 1-12 always have 30 days, so reset is always end+1 or wraps to 1
        days_in_eth_month = eth_days_in_month(eth_year, eth_month)
        reset_day = end_day + 1 if end_day < days_in_eth_month else 1
        if eth_day == reset_day:
            await monthly_cycle_reset_job(ctx)

    job_queue.run_daily(_monthly_reset_guard, time=dt_time(0, 5, 0, tzinfo=ETH_TZ), name="monthly_cycle_reset")

    logger.info("✅ Automated reminder + monthly reset jobs scheduled.")


def build_application() -> Application:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN environment variable is not set!")

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    # ─── Admin conversation (includes inline callbacks for settings, users, inbox) ───
    admin_conv = build_admin_conversation()
    app.add_handler(admin_conv)

    # ─── User conversations ──────────────────────────────────────────────────
    app.add_handler(build_profile_conversation())
    app.add_handler(build_payment_conversation())
    app.add_handler(build_support_conversation())

    # ─── Core command handlers ───────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    # ─── Main-menu text button handlers ─────────────────────────────────────
    app.add_handler(MessageHandler(filters.Regex(r"^👤 የእኔ መገለጫ$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex(r"^📅 የክፍያ መርሃ ግብር$"), payment_schedule))
    app.add_handler(MessageHandler(filters.Regex(r"^📝 ድጋፍ እና ታሪክ$"), support_and_history))

    # ─── Inline callback fallback handlers ──────────────────────────────────
    app.add_handler(CallbackQueryHandler(profile_callback, pattern=r"^profile_card$"))
    app.add_handler(CallbackQueryHandler(support_history_callback, pattern=r"^history_view$"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^adm_"))
    app.add_handler(CallbackQueryHandler(inbox_callback, pattern=r"^inbox_|^approve_|^reject_|^reply_sup_"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern=r"^report_"))
    app.add_handler(CallbackQueryHandler(users_callback, pattern=r"^users_"))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^adm_settings$"))
    app.add_handler(CallbackQueryHandler(admin_manage_callback, pattern=r"^adm_manage$|^remove_adm_"))

    # ─── Unknown message fallback ────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _unknown_text))

    return app


async def _unknown_text(update, context):
    await update.message.reply_text(
        "❓ ምርጫዎን ከምናሌ ያድርጉ።\n/start ብለው ምናሌ ያሳዩ።"
    )


def main():
    logger.info("🚀 Starting Telegram Subscription Bot...")
    keep_alive()
    app = build_application()
    logger.info("✅ Bot is polling for updates...")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
