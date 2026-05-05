"""
user_handlers.py - User Interface (All text in Amharic)
Handles: Profile, Pay/Renew, Payment Schedule, Support & History
"""

import os
import logging
from datetime import datetime, date
from typing import Optional

from utils import (
    ETH_TZ,
    now_eth,
    to_ethiopian,
    eth_month_name,
    eth_days_in_month,
    format_eth_date,
    format_eth_date_storage,
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import database as db
from image_gen import generate_membership_card

logger = logging.getLogger(__name__)

CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# ── Conversation States ─────────────────────────────────────────────────────
(
    EDIT_NAME_INPUT,
    PAYMENT_AWAITING_SCREENSHOT,
    PAYMENT_CONFIRM,
    SUPPORT_MSG_INPUT,
) = range(4)


# ─────────────────────────────────────────────
#  MAIN MENU KEYBOARD
# ─────────────────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["👤 የእኔ መገለጫ", "💳 ክፈል / አድስ"],
            ["📅 የክፍያ መርሃ ግብር", "📝 ድጋፍ እና ታሪክ"],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ─────────────────────────────────────────────
#  START / WELCOME
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    user = db.register_user(tg_user.id, tg_user.full_name)
    await update.message.reply_text(
        f"👋 *እንኳን ደህና መጡ, {user.get('name', tg_user.full_name)}!*\n\n"
        "ይህ ቦት የደንበኝነት ክፍያዎን ለማስተዳደር ይረዳዎታል።\n"
        "ከታቹ ምናሌ ምርጫዎን ያድርጉ:",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


# ─────────────────────────────────────────────
#  👤 MY PROFILE
# ─────────────────────────────────────────────

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        user = db.register_user(update.effective_user.id, update.effective_user.full_name)

    status_icon = "✅ ተከፍሏል" if user["status"] == "paid" else "❌ አልተከፈለም"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ስም ቀይር", callback_data="profile_edit_name")],
        [InlineKeyboardButton("🪪 የደንበኝነት ካርድ", callback_data="profile_card")],
    ])
    # Show join date in Ethiopian calendar if available
    joined_raw = str(user.get("joined_at", ""))[:10]
    try:
        gd = datetime.strptime(joined_raw, "%Y-%m-%d")
        joined_display = format_eth_date(gd)
    except Exception:
        joined_display = joined_raw

    await update.message.reply_text(
        f"👤 *የእኔ መገለጫ*\n\n"
        f"📛 ስም: *{user['name']}*\n"
        f"🆔 Telegram ID: `{user['telegram_id']}`\n"
        f"📊 ሁኔታ: *{status_icon}*\n"
        f"📅 ተቀጥሮ: {joined_display} (ዓ.ም)",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "profile_edit_name":
        await query.edit_message_text(
            "✏️ *ስም ቀይር*\n\nአዲሱን ስምዎን ያስገቡ:",
            parse_mode="Markdown",
        )
        return EDIT_NAME_INPUT

    elif data == "profile_card":
        tg_id = query.from_user.id
        user = db.get_user(tg_id)
        if not user:
            await query.answer("❌ ፕሮፋይልዎ አልተገኘም።", show_alert=True)
            return
        await query.edit_message_text("⏳ ካርድ እየተዘጋጀ ነው...")
        card_io = generate_membership_card(tg_id, user["name"], user["status"])
        await query.message.reply_photo(
            photo=card_io,
            caption=f"🪪 *{user['name']} — የደንበኝነት ካርድ*",
            parse_mode="Markdown",
        )


async def receive_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    if len(new_name) < 2 or len(new_name) > 60:
        await update.message.reply_text("❌ ስሙ ከ 2 እስከ 60 ፊደላት መሆን አለበት። እንደገና ያስገቡ:")
        return EDIT_NAME_INPUT
    db.update_user_name(update.effective_user.id, new_name)
    await update.message.reply_text(
        f"✅ ስምዎ ወደ **{new_name}** ተቀይሯል!",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  💳 PAY / RENEW
# ─────────────────────────────────────────────

async def pay_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        user = db.register_user(update.effective_user.id, update.effective_user.full_name)

    if user["status"] == "paid":
        await update.message.reply_text(
            "✅ *ክፍያዎ ለዚህ ወር ጸድቋል!*\n\n"
            "ምንም ተጨማሪ ክፍያ አያስፈልግዎትም።",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    accounts = db.get_active_bank_accounts()
    if not accounts:
        await update.message.reply_text(
            "⚠️ *የባንክ ሒሳብ አልተገኘም*\n\n"
            "እባክዎ ቆይተው እንደገና ይሞክሩ። ወይም ድጋፍ ቡድኑን ያናግሩ።",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    bank_text = "🏦 *የክፍያ ሒሳቦች:*\n\n"
    for a in accounts:
        bank_text += (
            f"🏦 ባንክ: *{a['bank_name']}*\n"
            f"💳 ሒሳብ ቁጥር: `{a['account_number']}`\n"
            f"👤 ተቀባይ: *{a['account_holder']}*\n\n"
        )
    bank_text += (
        "━━━━━━━━━━━━━━━\n"
        "📸 *ክፍያ ፈጽመው ካበቁ, ደረሰኝ ፎቶ ያስቀምጡ።*\n"
        "_(ክፍያ ሳያደርጉ ለማቆም /cancel ያስገቡ)_"
    )
    await update.message.reply_text(
        bank_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PAYMENT_AWAITING_SCREENSHOT


async def receive_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "❌ *ፎቶ ብቻ ይቀበላሉ!*\n\nደረሰኝ ፎቶዎን ያስቀምጡ:",
            parse_mode="Markdown",
        )
        return PAYMENT_AWAITING_SCREENSHOT

    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("❌ ፕሮፋይልዎ አልተገኘም። /start ይጠቀሙ።")
        return ConversationHandler.END

    photo = update.message.photo[-1]
    context.user_data["receipt_file_id"] = photo.file_id
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ልኬዋለሁ, አረጋግጥ", callback_data="confirm_payment"),
            InlineKeyboardButton("❌ ሰርዝ", callback_data="cancel_payment"),
        ]
    ])
    await update.message.reply_text(
        "📸 *ደረሰኝ ደርሶናል!*\n\n"
        "ደረሰኙን ወደ አስተዳዳሪ ቡድን ልኬዋለሁ ማለት ይፈልጋሉ?",
        reply_markup=kb,
        parse_mode="Markdown",
    )
    return PAYMENT_CONFIRM


async def confirm_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    tg_id = query.from_user.id

    if data == "cancel_payment":
        await query.edit_message_text(
            "❌ *ክፍያ ተሰርዟል።*\n\nለማስቀጠል ዋናው ምናሌ ይጠቀሙ።",
            parse_mode="Markdown",
        )
        await query.message.reply_text("ወደ ዋናው ምናሌ ተመልሰዋል።", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if data == "confirm_payment":
        file_id = context.user_data.get("receipt_file_id")
        if not file_id:
            await query.edit_message_text("❌ ፎቶ አልተገኘም። እንደገና ይሞክሩ።")
            return ConversationHandler.END

        await query.edit_message_text("⏳ ደረሰኝ ወደ አስተዳዳሪ ቡድን እየተላከ ነው...")

        try:
            forwarded = await query.get_bot().send_photo(
                chat_id=CHANNEL_ID,
                photo=file_id,
                caption=(
                    f"📸 *አዲስ ደረሰኝ*\n\n"
                    f"👤 ተጠቃሚ: {db.get_user(tg_id)['name']}\n"
                    f"🆔 ID: `{tg_id}`\n"
                    f"📅 ቀን (ዓ.ም): {format_eth_date(now_eth())}"
                ),
                parse_mode="Markdown",
            )
            channel_msg_id = forwarded.message_id
        except Exception as e:
            logger.error(f"Failed to forward receipt to channel: {e}")
            await query.edit_message_text(
                "❌ *ደረሰኝ ወደ ቻናሉ መላክ አልተቻለም።*\n\n"
                "እባክዎ ቆይተው ወይም ድጋፍ ቡድኑን ያናግሩ።",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        now_dt = now_eth()
        eth_y, eth_m, eth_d = to_ethiopian(now_dt)
        db.create_payment_record(
            tg_id,
            channel_msg_id,
            eth_m,
            eth_y,
            eth_payment_date=format_eth_date_storage(now_dt),
        )

        await query.edit_message_text(
            "✅ *ደረሰኝዎ ተልኳል!*\n\n"
            "አስተዳዳሪዎቹ ካረጋገጡ ሁኔታዎ ይዘምናል።\n"
            "ትንሽ ቢጠብቁ ምስጋናዬ ነው! 🙏",
            parse_mode="Markdown",
        )
        await query.message.reply_text("ወደ ዋናው ምናሌ ተመልሰዋል።", reply_markup=main_menu_keyboard())
        return ConversationHandler.END


# ─────────────────────────────────────────────
#  📅 PAYMENT SCHEDULE
# ─────────────────────────────────────────────

async def payment_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cycle = db.get_billing_cycle()
    now_dt = now_eth()
    eth_year, eth_month, eth_day = to_ethiopian(now_dt)
    today = eth_day

    start = cycle["start"]
    end = cycle["end"]

    # Ethiopian months 1-12 always have 30 days; month 13 (Pagume) has 5 or 6
    days_in_eth_month = eth_days_in_month(eth_year, eth_month)

    in_billing_period = False
    days_remaining = 0
    next_event = ""

    if today >= start:
        in_billing_period = True
        if end < start:
            # End wraps into next Ethiopian month (e.g. start=25, end=5)
            days_remaining = (days_in_eth_month - today) + end
        else:
            days_remaining = end - today
        next_event = f"የክፍያ ጊዜ {end}ኛ ቀን ያበቃል"
    elif today <= end and end < start:
        # Carry-over window of the previous cycle
        in_billing_period = True
        days_remaining = end - today
        next_event = f"የክፍያ ጊዜ {end}ኛ ቀን ያበቃል"
    else:
        days_remaining = start - today
        next_event = f"ክፍያ {start}ኛ ቀን ይጀምራል"

    user = db.get_user(update.effective_user.id)
    user_status = "✅ ተከፍሏል" if user and user["status"] == "paid" else "❌ አልተከፈለም"

    if in_billing_period:
        if days_remaining > 1:
            countdown_text = f"⏳ {days_remaining} ቀናት ቀርተዋል"
        elif days_remaining == 1:
            countdown_text = "⚠️ ነገ የመጨረሻ ቀን ነው!"
        else:
            countdown_text = "🚨 ዛሬ የመጨረሻ ቀን ነው!"
    else:
        countdown_text = f"⏳ ክፍያ ለመጀመር {days_remaining} ቀናት ቀርተዋል"

    text = (
        f"📅 *የክፍያ መርሃ ግብር*\n\n"
        f"📆 ወር: *{eth_month_name(eth_month)} {eth_year} (ዓ.ም)*\n"
        f"📌 የክፍያ ዑደት: *{start}ኛ — {end}ኛ*\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{countdown_text}\n"
        f"🔔 ቀጣይ: _{next_event}_\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 የእርስዎ ሁኔታ: *{user_status}*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
#  📝 SUPPORT & HISTORY
# ─────────────────────────────────────────────

async def support_and_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 የክፍያ ታሪክ", callback_data="history_view")],
        [InlineKeyboardButton("💬 ድጋፍ ቡድን ያናግሩ", callback_data="support_contact")],
    ])
    await update.message.reply_text(
        "📝 *ድጋፍ እና ታሪክ*\nምርጫዎን ያድርጉ:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def support_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "history_view":
        tg_id = query.from_user.id
        history = db.get_user_payment_history(tg_id)
        if not history:
            await query.edit_message_text(
                "📋 *የክፍያ ታሪክ*\n\nምንም ታሪክ አልተገኘም።",
                parse_mode="Markdown",
            )
            return

        lines = ["📋 *የክፍያ ታሪክ:*\n"]
        for p in history[:10]:
            if p["status"] == "approved":
                icon = "✅"
                status_str = "ተቀብሏል"
            elif p["status"] == "rejected":
                icon = "❌"
                status_str = "ተቀባይነት አላገኘም"
            else:
                icon = "⏳"
                status_str = "በመጠባበቅ ላይ"

            # Prefer stored Ethiopian date; fall back to month/year fields
            eth_date = p.get("eth_payment_date", "")
            if eth_date:
                parts = eth_date.split("-")
                if len(parts) == 3:
                    date_display = f"{eth_month_name(int(parts[1]))} {parts[0]} (ዓ.ም)"
                else:
                    date_display = eth_date
            else:
                # month/year are now stored as Ethiopian values in new records
                date_display = f"{eth_month_name(p['month'])} {p['year']} (ዓ.ም)"

            lines.append(f"{icon} {date_display} — {status_str}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")

    elif data == "support_contact":
        await query.edit_message_text(
            "💬 *ድጋፍ ቡድን ያናግሩ*\n\n"
            "ጥያቄዎን ወይም አስተያየትዎን ያስገቡ:\n"
            "_(ለማቆም /cancel ያስገቡ)_",
            parse_mode="Markdown",
        )
        return SUPPORT_MSG_INPUT


async def receive_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    msg = update.message.text.strip()
    if len(msg) < 5:
        await update.message.reply_text("❌ መልዕክቱ በጣም አጭር ነው። ቢያንስ 5 ፊደላት ያስፈልጋሉ:")
        return SUPPORT_MSG_INPUT
    db.create_support_message(tg_id, msg)
    await update.message.reply_text(
        "✅ *ጥያቄዎ ተልኳል!*\n\n"
        "የድጋፍ ቡድናችን በቅርቡ ይመልሱዎታል። 🙏",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  CANCEL
# ─────────────────────────────────────────────

async def cancel_user_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ *ሂደቱ ተሰርዟል።*",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────
#  CONVERSATION HANDLER BUILDERS
# ─────────────────────────────────────────────

def build_profile_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(profile_callback, pattern=r"^profile_edit_name$"),
        ],
        states={
            EDIT_NAME_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel_user_conv)],
        allow_reentry=True,
    )


def build_payment_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^💳 ክፈል / አድስ$"), pay_renew),
        ],
        states={
            PAYMENT_AWAITING_SCREENSHOT: [
                MessageHandler(filters.PHOTO, receive_payment_screenshot),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_payment_screenshot),
            ],
            PAYMENT_CONFIRM: [
                CallbackQueryHandler(confirm_payment_callback, pattern=r"^(confirm_payment|cancel_payment)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_user_conv)],
        allow_reentry=True,
    )


def build_support_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(support_history_callback, pattern=r"^(history_view|support_contact)$"),
        ],
        states={
            SUPPORT_MSG_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_support_message),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_user_conv)],
        allow_reentry=True,
    )
