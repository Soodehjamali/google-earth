"""Calendar utilities for consistent Gregorian to Jalali (Persian) date formatting.

Verifies:
- 2026-10-19 -> 27 Mehr 1405 (شب ۲۷ مهر)
- 2026-10-20 -> 28 Mehr 1405 (شب ۲۸ مهر)
- 2026-10-21 -> 29 Mehr 1405 (شب ۲۹ مهر)
- 2026-10-22 -> 30 Mehr 1405 (شب ۳۰ مهر)
"""

from datetime import date, datetime
from typing import Optional

PERSIAN_MONTHS = [
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def gregorian_to_jalali(d: date) -> tuple[int, int, int]:
    """Convert a Gregorian date to (j_year, j_month, j_day).

    Uses jdatetime if available, with mathematical Birashk/Khayyam fallback.
    """
    try:
        import jdatetime
        jd = jdatetime.date.fromgregorian(date=d)
        return jd.year, jd.month, jd.day
    except Exception:
        gy, gm, gd = d.year, d.month, d.day
        g_d_m = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0):
            g_d_m[2] = 29

        gy2 = gy - 1600 if gy > 1600 else gy - 621
        days = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80
        for i in range(1, gm):
            days += g_d_m[i]
        days += gd

        jy = 979 + 33 * (days // 12053)
        days %= 12053
        jy += 4 * (days // 1461)
        days %= 1461

        if days > 365:
            jy += (days - 1) // 365
            days = (days - 1) % 365

        if days < 186:
            jm = 1 + days // 31
            jd = 1 + days % 31
        else:
            jm = 7 + (days - 186) // 30
            jd = 1 + (days - 186) % 30
        return jy, jm, jd


EN_TO_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def format_night_display_fa(night_date_str: Optional[str]) -> str:
    """Format Gregorian YYYY-MM-DD into consistent Persian night label: e.g. 'شب ۲۷ مهر'.

    Standard Night Convention:
    The night labeled by its start date (evening of day D to morning of day D+1):
    - 2026-10-19 (18:00 to 09:00+1d) -> 'شب ۲۷ مهر'
    - 2026-10-20 (18:00 to 09:00+1d) -> 'شب ۲۸ مهر'
    - 2026-10-21 (18:00 to 09:00+1d) -> 'شب ۲۹ مهر'
    - 2026-10-22 (18:00 to 09:00+1d) -> 'شب ۳۰ مهر'
    """
    if not night_date_str:
        return "شب نامشخص"
    try:
        clean_str = night_date_str.strip()[:10]
        d = datetime.strptime(clean_str, "%Y-%m-%d").date()
        jy, jm, jd = gregorian_to_jalali(d)
        month_name = PERSIAN_MONTHS[jm] if 1 <= jm <= 12 else str(jm)
        res = f"شب {jd} {month_name}"
        return res.translate(EN_TO_FA_DIGITS)
    except Exception:
        return f"شب {night_date_str}"
