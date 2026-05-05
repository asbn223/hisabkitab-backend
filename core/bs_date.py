# apps/core/bs_date.py
"""
Bikram Sambat (Nepali calendar) utilities.
Reference: 2000 AD = 2056 BS (approximate conversion)
"""
from datetime import datetime, date

# BS month days (regular year)
BS_MONTHS_DAYS = [31, 31, 32, 32, 31, 30, 30, 30, 29, 29, 30, 30]

# Reference: AD date and corresponding BS date
REFERENCE_AD_YEAR = 2000
REFERENCE_BS_YEAR = 2056
REFERENCE_AD_MONTH = 9  # September
REFERENCE_AD_DAY = 17
REFERENCE_BS_MONTH = 3  # Ashwin (6th month, 0-indexed as 3 for calculation)

NEPALI_DIGITS = ["०", "१", "२", "३", "४", "५", "६", "७", "८", "९"]

NEPALI_MONTHS = [
    "बैशाख",  # 1 - April/May
    "जेठ",  # 2 - May/June
    "असार",  # 3 - June/July
    "श्रावण",  # 4 - July/August
    "भाद्र",  # 5 - August/September
    "आश्विन",  # 6 - September/October
    "कार्तिक",  # 7 - October/November
    "मंसिर",  # 8 - November/December
    "पौष",  # 9 - December/January
    "माघ",  # 10 - January/February
    "फाल्गुन",  # 11 - February/March
    "चैत्र",  # 12 - March/April
]

NEPALI_MONTHS_EN = [
    "Baishakh", "Jestha", "Ashadh", "Shrawan",
    "Bhadra", "Ashwin", "Kartik", "Mangsir",
    "Poush", "Magh", "Falgun", "Chaitra"
]


def is_leap_year(year: int) -> bool:
    """Check if AD year is leap year."""
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def ad_to_bs(ad_date_str: str) -> str:
    """
    Convert AD date (YYYY-MM-DD) to BS date (YYYY-MM-DD).

    Uses simplified algorithm accurate for years 2000-2030.
    For production, consider using nepali-datetime library.

    Args:
        ad_date_str: AD date string in YYYY-MM-DD format

    Returns:
        BS date string in YYYY-MM-DD format
    """
    if isinstance(ad_date_str, date):
        ad_date_str = ad_date_str.isoformat()

    try:
        ad_date = datetime.strptime(ad_date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format: {ad_date_str}. Expected YYYY-MM-DD.")

    year, month, day = ad_date.year, ad_date.month, ad_date.day

    # Simplified conversion: AD + 56 years, 8 months offset
    # This is approximate and works for most fiscal purposes

    # Calculate days since reference
    ref_ad = date(REFERENCE_AD_YEAR, REFERENCE_AD_MONTH, REFERENCE_AD_DAY)
    days_diff = (ad_date - ref_ad).days

    # Start from reference BS date
    bs_year = REFERENCE_BS_YEAR
    bs_month = REFERENCE_BS_MONTH  # 0-indexed
    bs_day = 1

    # Add days
    remaining_days = days_diff

    while remaining_days > 0:
        days_in_month = BS_MONTHS_DAYS[bs_month]

        if remaining_days >= days_in_month:
            remaining_days -= days_in_month
            bs_month += 1
            if bs_month >= 12:
                bs_month = 0
                bs_year += 1
        else:
            bs_day += remaining_days
            remaining_days = 0

    # Adjust for month boundaries
    while bs_day > BS_MONTHS_DAYS[bs_month]:
        bs_day -= BS_MONTHS_DAYS[bs_month]
        bs_month += 1
        if bs_month >= 12:
            bs_month = 0
            bs_year += 1

    # Convert to 1-indexed month for output
    return f"{bs_year}-{str(bs_month + 1).zfill(2)}-{str(bs_day).zfill(2)}"


def bs_to_ad(bs_date_str: str) -> str:
    """
    Convert BS date to AD date (approximate).

    Args:
        bs_date_str: BS date in YYYY-MM-DD format

    Returns:
        AD date in YYYY-MM-DD format
    """
    year, month, day = map(int, bs_date_str.split('-'))

    # Reverse calculation (approximate)
    ad_year = year - 56
    ad_month = month - 8
    ad_day = day

    if ad_month <= 0:
        ad_month += 12
        ad_year -= 1

    # Adjust for month length differences
    try:
        ad_date = date(ad_year, ad_month, ad_day)
        return ad_date.isoformat()
    except ValueError:
        # Adjust day if invalid
        from calendar import monthrange
        _, last_day = monthrange(ad_year, ad_month)
        ad_day = min(ad_day, last_day)
        ad_date = date(ad_year, ad_month, ad_day)
        return ad_date.isoformat()


def to_nepali_digits(num: str | int | float) -> str:
    """
    Convert Arabic numerals to Nepali (Devanagari) numerals.

    Args:
        num: Number to convert

    Returns:
        String with Nepali digits
    """
    return "".join([
        NEPALI_DIGITS[int(c)] if c.isdigit() else c
        for c in str(num)
    ])


def format_bs_date(bs_date: str, use_nepali_digits: bool = False,
                   format_type: str = 'full') -> str:
    """
    Format BS date to human readable string.

    Args:
        bs_date: BS date string (YYYY-MM-DD)
        use_nepali_digits: Whether to use Nepali digits
        format_type: 'full', 'short', or 'month_year'

    Returns:
        Formatted date string
    """
    try:
        year, month, day = bs_date.split("-")
        month_idx = int(month) - 1
        month_name = NEPALI_MONTHS[month_idx]

        if use_nepali_digits:
            y, m, d = to_nepali_digits(year), month_name, to_nepali_digits(day)
        else:
            y, m, d = year, month_name, day

        if format_type == 'full':
            return f"{d} {m} {y}"
        elif format_type == 'short':
            return f"{d} {m[:3]} {y}"
        elif format_type == 'month_year':
            return f"{m} {y}"
        else:
            return bs_date
    except (ValueError, IndexError):
        return bs_date


def get_current_bs_date() -> str:
    """Get current date in BS format."""
    return ad_to_bs(date.today().isoformat())


def get_current_bs_datetime() -> str:
    """Get current datetime in BS format."""
    now = datetime.now()
    bs_date = ad_to_bs(now.date().isoformat())
    return f"{bs_date} {now.strftime('%H:%M:%S')}"


def get_fiscal_year(bs_date: str = None, fiscal_start_month: int = 4) -> dict:
    """
    Get fiscal year details for a given BS date.

    Nepali fiscal year starts in Shrawan (month 4).

    Args:
        bs_date: BS date string (default: current date)
        fiscal_start_month: Month number when fiscal year starts (default: 4)

    Returns:
        Dict with start_date, end_date, year_name
    """
    if bs_date is None:
        bs_date = get_current_bs_date()

    year, month, _ = map(int, bs_date.split('-'))

    # Determine fiscal year
    if month >= fiscal_start_month:
        start_year = year
        end_year = year + 1
    else:
        start_year = year - 1
        end_year = year

    start_month = fiscal_start_month
    end_month = fiscal_start_month - 1

    start_date = f"{start_year}-{str(start_month).zfill(2)}-01"
    end_date = f"{end_year}-{str(end_month).zfill(2)}-30"

    return {
        'start_date': start_date,
        'end_date': end_date,
        'start_year': start_year,
        'end_year': end_year,
        'year_name': f"{start_year}/{str(end_year)[-2:]}",
        'start_month': start_month,
        'end_month': end_month,
    }


def get_month_name(month_number: int, nepali: bool = True) -> str:
    """Get month name from month number (1-12)."""
    if not 1 <= month_number <= 12:
        raise ValueError("Month must be between 1 and 12")

    if nepali:
        return NEPALI_MONTHS[month_number - 1]
    return NEPALI_MONTHS_EN[month_number - 1]


def get_month_range(year: int, month: int) -> tuple:
    """
    Get start and end dates for a BS month.

    Returns:
        Tuple of (start_date, end_date) in BS format
    """
    days = BS_MONTHS_DAYS[month - 1]
    start = f"{year}-{str(month).zfill(2)}-01"
    end = f"{year}-{str(month).zfill(2)}-{days}"
    return start, end


def add_days_to_bs_date(bs_date: str, days: int) -> str:
    """Add days to a BS date."""
    # Convert to AD, add days, convert back
    ad_date_str = bs_to_ad(bs_date)
    ad_date = datetime.strptime(ad_date_str, "%Y-%m-%d").date()
    from datetime import timedelta
    new_ad_date = ad_date + timedelta(days=days)
    return ad_to_bs(new_ad_date.isoformat())


def days_between_bs_dates(start_date: str, end_date: str) -> int:
    """Calculate days between two BS dates."""
    start_ad = bs_to_ad(start_date)
    end_ad = bs_to_ad(end_date)
    start = datetime.strptime(start_ad, "%Y-%m-%d").date()
    end = datetime.strptime(end_ad, "%Y-%m-%d").date()
    return (end - start).days