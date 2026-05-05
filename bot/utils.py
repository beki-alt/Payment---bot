"""
utils.py - Ethiopian Calendar & Timezone Utilities

Provides Ethiopian date conversion (Gregorian → Ethiopian) and
Africa/Addis_Ababa timezone helpers used across the entire bot.

Algorithm note:
  Pure-Python Gregorian → Ethiopian via Julian Day Number.
  Epoch: JDN 1724420 (verified: Sep 11 2023 → Meskerem 1, 2016 EC ✓)
  Ethiopian leap year: every 4th year (year % 4 == 3, i.e. 3, 7, 11 ... 2015, 2019 ...)

  Also attempts to use the `ethiopian-date` library if installed.
"""

import logging
from datetime import datetime
from typing import Tuple

import pytz

logger = logging.getLogger(__name__)

# ── Timezone ────────────────────────────────────────────────────────────────
ETH_TZ = pytz.timezone("Africa/Addis_Ababa")

# ── Ethiopian month names (Amharic) ─────────────────────────────────────────
ETH_MONTHS = [
    "",           # index 0 — unused
    "መስከረም",    # 1  Meskerem   (Sep–Oct)
    "ጥቅምት",     # 2  Tikimt     (Oct–Nov)
    "ህዳር",      # 3  Hidar      (Nov–Dec)
    "ታህሳስ",     # 4  Tahsas     (Dec–Jan)
    "ጥር",        # 5  Tir        (Jan–Feb)
    "የካቲት",     # 6  Yekatit    (Feb–Mar)
    "መጋቢት",     # 7  Megabit    (Mar–Apr)
    "ሚያዝያ",     # 8  Miyazia    (Apr–May)
    "ግንቦት",     # 9  Ginbot     (May–Jun)
    "ሰኔ",        # 10 Senie      (Jun–Jul)
    "ሐምሌ",      # 11 Hamle      (Jul–Aug)
    "ነሐሴ",      # 12 Nehase     (Aug–Sep)
    "ጳጉሜ",      # 13 Pagume     (Sep, short month)
]

# ── JDN epoch (verified against multiple known dates) ───────────────────────
_ETH_EPOCH_JDN = 1724420


def _greg_to_jdn(year: int, month: int, day: int) -> int:
    """Convert a Gregorian date to its Julian Day Number."""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return (
        day
        + (153 * m + 2) // 5
        + 365 * y
        + y // 4
        - y // 100
        + y // 400
        - 32045
    )


def _jdn_to_ethiopian(jdn: int) -> Tuple[int, int, int]:
    """Convert a Julian Day Number to an Ethiopian calendar date."""
    era = jdn - _ETH_EPOCH_JDN
    quad, remainder = divmod(era, 1461)      # 1461 = 4 × 365 + 1
    year_base = quad * 4

    if remainder == 0:
        # Exact start of a 4-year cycle
        return year_base, 1, 1

    # Which year within the 4-year cycle?
    year_in_quad, day_in_year = divmod(remainder - 1, 365)
    eth_year  = year_base + year_in_quad + 1
    eth_month = day_in_year // 30 + 1
    eth_day   = day_in_year % 30 + 1
    return eth_year, eth_month, eth_day


def to_ethiopian(dt: datetime) -> Tuple[int, int, int]:
    """
    Convert a datetime (any timezone) to an Ethiopian calendar tuple
    (eth_year, eth_month, eth_day).

    Tries the `ethiopian-date` library first; falls back to the
    built-in JDN algorithm if unavailable.
    """
    # Ensure we work in Ethiopian local date
    if dt.tzinfo is None:
        dt = ETH_TZ.localize(dt)
    else:
        dt = dt.astimezone(ETH_TZ)

    g_year, g_month, g_day = dt.year, dt.month, dt.day

    # ── Try third-party library first ───────────────────────────────────────
    try:
        from ethiopian_date import EthiopianDateConverter
        return EthiopianDateConverter.to_ethiopian(g_year, g_month, g_day)
    except Exception:
        pass  # Fall through to built-in algorithm

    # ── Built-in JDN algorithm ───────────────────────────────────────────────
    jdn = _greg_to_jdn(g_year, g_month, g_day)
    return _jdn_to_ethiopian(jdn)


def now_eth() -> datetime:
    """Return the current datetime in Africa/Addis_Ababa timezone."""
    return datetime.now(tz=ETH_TZ)


def eth_month_name(month: int) -> str:
    """Return the Amharic name for an Ethiopian month number (1–13)."""
    if 1 <= month <= 13:
        return ETH_MONTHS[month]
    return str(month)


def eth_days_in_month(eth_year: int, eth_month: int) -> int:
    """
    Return the number of days in an Ethiopian month.
    Months 1–12 always have 30 days.
    Month 13 (Pagume) has 6 days in a leap year, 5 otherwise.
    Ethiopian leap year: eth_year % 4 == 3.
    """
    if eth_month < 13:
        return 30
    return 6 if eth_year % 4 == 3 else 5


def prev_eth_months(n: int = 6):
    """
    Return a list of (eth_year, eth_month) tuples for the last n Ethiopian
    months, most recent first. The current month is included as the first item.
    """
    eth_year, eth_month, _ = to_ethiopian(now_eth())
    months = []
    y, m = eth_year, eth_month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 13
            y -= 1
    return months


def format_eth_date(dt: datetime) -> str:
    """
    Return a human-readable Ethiopian date string.
    Example: "25 መስከረም 2016"
    """
    y, m, d = to_ethiopian(dt)
    return f"{d} {eth_month_name(m)} {y}"


def format_eth_datetime(dt: datetime) -> str:
    """
    Return Ethiopian date + local time string.
    Example: "25 መስከረም 2016 — 12:35"
    """
    if dt.tzinfo is None:
        dt = ETH_TZ.localize(dt)
    else:
        dt = dt.astimezone(ETH_TZ)
    y, m, d = to_ethiopian(dt)
    return f"{d} {eth_month_name(m)} {y} — {dt.strftime('%H:%M')}"


def format_eth_date_storage(dt: datetime) -> str:
    """
    Return Ethiopian date in ISO-like storage format.
    Example: "2016-01-25"
    """
    y, m, d = to_ethiopian(dt)
    return f"{y}-{m:02d}-{d:02d}"


def parse_eth_date_storage(eth_str: str) -> Tuple[int, int, int]:
    """
    Parse a stored Ethiopian date string "2016-01-25"
    and return (eth_year, eth_month, eth_day).
    Returns (0, 0, 0) on parse failure.
    """
    try:
        parts = eth_str.split("-")
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return 0, 0, 0
