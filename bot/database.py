"""
database.py - Supabase Integration Layer
All database operations for the Telegram Subscription Management Bot
"""

import os
import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from supabase import create_client, Client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_supabase: Optional[Client] = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


# ─────────────────────────────────────────────
#  SCHEMA BOOTSTRAP
# ─────────────────────────────────────────────

def init_tables():
    """
    Ensure all required tables exist.
    Run once at startup (uses Supabase RPC or REST DDL if needed).
    In production, run these SQL statements in the Supabase SQL editor.
    """
    sql_statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT 'ያልታወቀ',
            status TEXT NOT NULL DEFAULT 'unpaid',
            joined_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS admins (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            is_super BOOLEAN DEFAULT FALSE,
            added_by BIGINT,
            added_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS payments (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            month INT NOT NULL,
            year INT NOT NULL,
            receipt_channel_msg_id BIGINT,
            status TEXT NOT NULL DEFAULT 'pending',
            rejected_reason TEXT,
            eth_payment_date TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS support_messages (
            id BIGSERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            message TEXT NOT NULL,
            reply TEXT,
            replied_by BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            replied_at TIMESTAMPTZ
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS bank_accounts (
            id BIGSERIAL PRIMARY KEY,
            bank_name TEXT NOT NULL,
            account_number TEXT NOT NULL,
            account_holder TEXT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
    ]
    sb = get_supabase()
    for stmt in sql_statements:
        try:
            sb.rpc("exec_sql", {"query": stmt}).execute()
        except Exception:
            pass  # Tables may already exist

    _seed_default_settings()


def _seed_default_settings():
    """Insert default settings if they don't already exist."""
    defaults = {
        "billing_start_day": "25",
        "billing_end_day": "5",
        "msg_payment_start": (
            "📢 ውድ አባላት,\n\n"
            "የዚህ ወር የደንበኝነት ክፍያ ጊዜ ደርሷል! "
            "ከ{start_day} እስከ {end_day} ባለው ጊዜ ውስጥ ክፍያዎን እንዲፈጽሙ ጥሪ እናቀርባለን።\n\n"
            "💳 ለክፍያ መመሪያ ዋናውን ምናሌ ይጠቀሙ።"
        ),
        "msg_reminder_one_day": (
            "⚠️ ትዝታ!\n\n"
            "ነገ {end_day} የሚከፈለው የደንበኝነት ቀን ነው። "
            "ገና ካልከፈሉ፣ ዛሬ ክፍያዎን ፈጽሙ!\n\n"
            "💳 'ክፈል/አድስ' የሚለውን ምናሌ ይጠቀሙ።"
        ),
        "msg_final_day": (
            "🚨 የመጨረሻ ቀን!\n\n"
            "ዛሬ {end_day} — የደንበኝነት ክፍያ የመጨረሻ ቀን ነው። "
            "ገና ካልከፈሉ ወዲያውኑ ይፈጽሙ!\n\n"
            "⏳ ዛሬ ከፈሱ አገልግሎቱ ይቋረጣል።"
        ),
        "msg_approved": (
            "✅ ክፍያዎ ተቀብሏል!\n\n"
            "ስም: {name}\n"
            "ወር: {month}\n\n"
            "አመሰግናለሁ! አባልነትዎ ታድሷል። 🎉"
        ),
        "msg_rejected": (
            "❌ ክፍያዎ ተቀባይነት አላገኘም።\n\n"
            "ምክንያት: {reason}\n\n"
            "እባክዎ ትክክለኛ ደረሰኝ ፎቶ ልከው እንደገና ይሞክሩ።"
        ),
        "notify_payment_start": "true",
        "notify_one_day": "true",
        "notify_final_day": "true",
    }
    sb = get_supabase()
    for key, value in defaults.items():
        try:
            sb.table("settings").upsert(
                {"key": key, "value": value},
                on_conflict="key",
                ignore_duplicates=True,
            ).execute()
        except Exception as e:
            logger.warning(f"Setting seed warning for {key}: {e}")


# ─────────────────────────────────────────────
#  KEEP-ALIVE PING
# ─────────────────────────────────────────────

async def ping_supabase():
    """Ping Supabase every 48 hours to prevent free-tier sleep."""
    while True:
        try:
            get_supabase().table("settings").select("key").limit(1).execute()
            logger.info("✅ Supabase keep-alive ping successful.")
        except Exception as e:
            logger.error(f"Supabase keep-alive ping failed: {e}")
        await asyncio.sleep(48 * 3600)


# ─────────────────────────────────────────────
#  USER OPERATIONS
# ─────────────────────────────────────────────

def register_user(telegram_id: int, name: str) -> Dict[str, Any]:
    sb = get_supabase()
    existing = sb.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if existing.data:
        return existing.data[0]
    result = sb.table("users").insert({
        "telegram_id": telegram_id,
        "name": name,
        "status": "unpaid",
    }).execute()
    return result.data[0] if result.data else {}


def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return result.data[0] if result.data else None


def get_all_users() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("users").select("*").order("joined_at").execute()
    return result.data or []


def get_unpaid_users() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("users").select("*").eq("status", "unpaid").execute()
    return result.data or []


def get_paid_users() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("users").select("*").eq("status", "paid").execute()
    return result.data or []


def update_user_name(telegram_id: int, new_name: str) -> bool:
    sb = get_supabase()
    result = sb.table("users").update({
        "name": new_name,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("telegram_id", telegram_id).execute()
    return bool(result.data)


def update_user_status(telegram_id: int, status: str) -> bool:
    sb = get_supabase()
    result = sb.table("users").update({
        "status": status,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("telegram_id", telegram_id).execute()
    return bool(result.data)


def get_total_users_count() -> int:
    sb = get_supabase()
    result = sb.table("users").select("id", count="exact").execute()
    return result.count or 0


# ─────────────────────────────────────────────
#  ADMIN OPERATIONS
# ─────────────────────────────────────────────

def add_admin(telegram_id: int, added_by: int, is_super: bool = False) -> bool:
    sb = get_supabase()
    try:
        sb.table("admins").upsert({
            "telegram_id": telegram_id,
            "is_super": is_super,
            "added_by": added_by,
        }, on_conflict="telegram_id").execute()
        return True
    except Exception as e:
        logger.error(f"add_admin error: {e}")
        return False


def remove_admin(telegram_id: int) -> bool:
    sb = get_supabase()
    result = sb.table("admins").delete().eq("telegram_id", telegram_id).eq("is_super", False).execute()
    return bool(result.data)


def get_all_admins() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("admins").select("*").execute()
    return result.data or []


def is_admin(telegram_id: int) -> bool:
    sb = get_supabase()
    result = sb.table("admins").select("id").eq("telegram_id", telegram_id).execute()
    return bool(result.data)


def is_super_admin(telegram_id: int) -> bool:
    super_id = os.getenv("ADMIN_ID", "")
    if str(telegram_id) == str(super_id):
        return True
    sb = get_supabase()
    result = sb.table("admins").select("id").eq("telegram_id", telegram_id).eq("is_super", True).execute()
    return bool(result.data)


# ─────────────────────────────────────────────
#  PAYMENT OPERATIONS
# ─────────────────────────────────────────────

def create_payment_record(
    telegram_id: int,
    receipt_channel_msg_id: int,
    month: int,
    year: int,
    eth_payment_date: str = "",
) -> Dict[str, Any]:
    sb = get_supabase()
    result = sb.table("payments").insert({
        "telegram_id": telegram_id,
        "month": month,
        "year": year,
        "receipt_channel_msg_id": receipt_channel_msg_id,
        "status": "pending",
        "eth_payment_date": eth_payment_date,
    }).execute()
    return result.data[0] if result.data else {}


def get_pending_payments() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("payments").select("*").eq("status", "pending").order("created_at").execute()
    return result.data or []


def get_payment_by_id(payment_id: int) -> Optional[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("payments").select("*").eq("id", payment_id).execute()
    return result.data[0] if result.data else None


def approve_payment(payment_id: int) -> bool:
    sb = get_supabase()
    payment = get_payment_by_id(payment_id)
    if not payment:
        return False
    sb.table("payments").update({
        "status": "approved",
        "reviewed_at": datetime.utcnow().isoformat(),
    }).eq("id", payment_id).execute()
    update_user_status(payment["telegram_id"], "paid")
    return True


def reject_payment(payment_id: int, reason: str) -> bool:
    sb = get_supabase()
    result = sb.table("payments").update({
        "status": "rejected",
        "rejected_reason": reason,
        "reviewed_at": datetime.utcnow().isoformat(),
    }).eq("id", payment_id).execute()
    return bool(result.data)


def get_user_payment_history(telegram_id: int) -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("payments")
        .select("*")
        .eq("telegram_id", telegram_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def get_monthly_payments(month: int, year: int) -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("payments")
        .select("*")
        .eq("month", month)
        .eq("year", year)
        .eq("status", "approved")
        .execute()
    )
    return result.data or []


def get_total_paid_this_month() -> int:
    now = datetime.now()
    return len(get_monthly_payments(now.month, now.year))


def get_unpaid_users_for_month(month: int, year: int) -> List[Dict[str, Any]]:
    """
    Return all registered users who do NOT have an approved payment
    for the given Ethiopian month/year.
    """
    sb = get_supabase()
    all_users = get_all_users()
    approved = (
        sb.table("payments")
        .select("telegram_id")
        .eq("month", month)
        .eq("year", year)
        .eq("status", "approved")
        .execute()
    )
    paid_ids = {r["telegram_id"] for r in (approved.data or [])}
    return [u for u in all_users if u["telegram_id"] not in paid_ids]


def get_attendance_data(month: int, year: int) -> List[Dict[str, Any]]:
    """
    Build a per-user attendance record for one billing cycle.

    Timeliness classification (based on approved payment date vs billing end day):
      - ወቅቱን ጠብቆ  (On Time) — paid with >= 2 days to spare before end day
      - ዘግይቶ       (Late)    — paid on the last 1–2 days before / on the end day
      - አልከፈለም    (Unpaid)  — no approved payment found for this cycle

    Returns a list of dicts, one per registered user, sorted: paid first then unpaid.
    """
    from calendar import monthrange

    all_users = get_all_users()
    approved = get_monthly_payments(month, year)

    # Build lookup: telegram_id → payment record (most recent approved)
    payment_map: Dict[int, Dict[str, Any]] = {}
    for p in approved:
        tid = p["telegram_id"]
        if tid not in payment_map:
            payment_map[tid] = p
        else:
            # prefer the earlier approved payment
            if p["created_at"] < payment_map[tid]["created_at"]:
                payment_map[tid] = p

    # Billing end day for timeliness calculation
    end_day = int(get_setting("billing_end_day", "5"))
    _, days_in_month = monthrange(year, month)

    months_am = [
        "", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ",
        "ሐምሌ", "ነሐሴ", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ",
    ]
    month_name = months_am[month] if month <= 12 else str(month)

    rows = []
    for u in all_users:
        tid = u["telegram_id"]
        p = payment_map.get(tid)

        if p:
            paid_at_str = str(p.get("created_at", ""))[:10]  # "YYYY-MM-DD"
            paid_time_str = str(p.get("created_at", ""))[:16]  # "YYYY-MM-DD HH:MM"
            try:
                paid_day = int(paid_at_str[8:10])
            except (ValueError, IndexError):
                paid_day = end_day

            # Timeliness: if payment is in the billing month (>= start) or next month (carry-over)
            # We simplify: if paid on end_day or one day before → Late, else → On Time
            if paid_day >= end_day - 1:
                timeliness = "ዘግይቶ"
                timeliness_en = "Late"
            else:
                timeliness = "ወቅቱን ጠብቆ"
                timeliness_en = "On Time"

            rows.append({
                "ተ.ቁ": 0,  # filled in below
                "ስም": u["name"],
                "Telegram ID": tid,
                "ወር": f"{month_name} {year}",
                "ሁኔታ": "✅ ተከፍሏል",
                "ወቅታዊነት": timeliness,
                "Timeliness": timeliness_en,
                "የክፍያ ቀን": paid_time_str,
                "_sort": 0,  # paid first
                "_timeliness_sort": 0 if timeliness_en == "On Time" else 1,
            })
        else:
            rows.append({
                "ተ.ቁ": 0,
                "ስም": u["name"],
                "Telegram ID": tid,
                "ወር": f"{month_name} {year}",
                "ሁኔታ": "❌ አልተከፈለም",
                "ወቅታዊነት": "አልከፈለም",
                "Timeliness": "Unpaid",
                "የክፍያ ቀን": "—",
                "_sort": 1,  # unpaid last
                "_timeliness_sort": 2,
            })

    # Sort: on-time → late → unpaid
    rows.sort(key=lambda r: (r["_sort"], r["_timeliness_sort"], r["ስም"]))

    # Assign row numbers and strip internal sort keys
    for i, row in enumerate(rows, 1):
        row["ተ.ቁ"] = i
        del row["_sort"]
        del row["_timeliness_sort"]

    return rows


def reset_all_users_to_unpaid():
    sb = get_supabase()
    sb.table("users").update({"status": "unpaid"}).neq("status", "").execute()


def get_cycle_summary(month: int, year: int) -> Dict[str, Any]:
    """
    Return a full summary snapshot for a closing billing cycle.
    Call this BEFORE resetting statuses so the numbers are still accurate.
    """
    all_users = get_all_users()
    approved_payments = get_monthly_payments(month, year)
    paid_ids = {p["telegram_id"] for p in approved_payments}

    paid_users = [u for u in all_users if u["telegram_id"] in paid_ids]
    unpaid_users = [u for u in all_users if u["telegram_id"] not in paid_ids]

    # Pending (submitted but not yet reviewed)
    sb = get_supabase()
    pending = (
        sb.table("payments")
        .select("*")
        .eq("month", month)
        .eq("year", year)
        .eq("status", "pending")
        .execute()
    )
    pending_count = len(pending.data or [])

    # Rejected this cycle
    rejected = (
        sb.table("payments")
        .select("*")
        .eq("month", month)
        .eq("year", year)
        .eq("status", "rejected")
        .execute()
    )
    rejected_count = len(rejected.data or [])

    months_am = [
        "", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ",
        "ሐምሌ", "ነሐሴ", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ",
    ]
    month_name = months_am[month] if month <= 12 else str(month)

    return {
        "month": month,
        "year": year,
        "month_name": month_name,
        "total_users": len(all_users),
        "total_paid": len(paid_users),
        "total_unpaid": len(unpaid_users),
        "total_pending": pending_count,
        "total_rejected": rejected_count,
        "paid_users": paid_users,
        "unpaid_users": unpaid_users,
    }


# ─────────────────────────────────────────────
#  SETTINGS OPERATIONS
# ─────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    sb = get_supabase()
    result = sb.table("settings").select("value").eq("key", key).execute()
    if result.data:
        return result.data[0]["value"]
    return default


def set_setting(key: str, value: str) -> bool:
    sb = get_supabase()
    result = sb.table("settings").upsert(
        {"key": key, "value": value, "updated_at": datetime.utcnow().isoformat()},
        on_conflict="key",
    ).execute()
    return bool(result.data)


def get_all_settings() -> Dict[str, str]:
    sb = get_supabase()
    result = sb.table("settings").select("*").execute()
    return {row["key"]: row["value"] for row in (result.data or [])}


def get_billing_cycle() -> Dict[str, int]:
    start = int(get_setting("billing_start_day", "25"))
    end = int(get_setting("billing_end_day", "5"))
    return {"start": start, "end": end}


# ─────────────────────────────────────────────
#  BANK ACCOUNT OPERATIONS
# ─────────────────────────────────────────────

def get_active_bank_accounts() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("bank_accounts").select("*").eq("is_active", True).execute()
    return result.data or []


def add_bank_account(bank_name: str, account_number: str, account_holder: str) -> bool:
    sb = get_supabase()
    result = sb.table("bank_accounts").insert({
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder,
        "is_active": True,
    }).execute()
    return bool(result.data)


def deactivate_bank_account(account_id: int) -> bool:
    sb = get_supabase()
    result = sb.table("bank_accounts").update({"is_active": False}).eq("id", account_id).execute()
    return bool(result.data)


# ─────────────────────────────────────────────
#  SUPPORT MESSAGE OPERATIONS
# ─────────────────────────────────────────────

def create_support_message(telegram_id: int, message: str) -> Dict[str, Any]:
    sb = get_supabase()
    result = sb.table("support_messages").insert({
        "telegram_id": telegram_id,
        "message": message,
    }).execute()
    return result.data[0] if result.data else {}


def get_unanswered_support_messages() -> List[Dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("support_messages")
        .select("*")
        .is_("reply", "null")
        .order("created_at")
        .execute()
    )
    return result.data or []


def reply_to_support_message(msg_id: int, reply: str, replied_by: int) -> bool:
    sb = get_supabase()
    result = sb.table("support_messages").update({
        "reply": reply,
        "replied_by": replied_by,
        "replied_at": datetime.utcnow().isoformat(),
    }).eq("id", msg_id).execute()
    return bool(result.data)


def get_support_message_by_id(msg_id: int) -> Optional[Dict[str, Any]]:
    sb = get_supabase()
    result = sb.table("support_messages").select("*").eq("id", msg_id).execute()
    return result.data[0] if result.data else None
