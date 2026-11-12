import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def norm_header(h):
    """Lower-case, trim, and collapse runs of _ or whitespace into one space."""
    return re.sub(r"[_\s]+", " ", h.strip().lower())


def norm_phone(raw):
    """Return +91XXXXXXXXXX, or None if invalid."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def _valid_ymd(y, m, d):
    """Return 'YYYY-MM-DD' if it is a real calendar date, else None."""
    from datetime import date
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def norm_date(raw):
    """Accept YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD-Mon-YYYY. Day-first."""
    s = (raw or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return _valid_ymd(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{2})[/-](\d{2})[/-](\d{4})", s)
    if m:
        return _valid_ymd(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{2})-([A-Za-z]{3})-(\d{4})", s)
    if m and m[2].lower() in MONTHS:
        return _valid_ymd(int(m[3]), MONTHS[m[2].lower()], int(m[1]))
    return None


def norm_decimal(raw):
    """Optional ₹ / Rs / Rs. / INR prefix, commas allowed, must be >= 0."""
    s = (raw or "").strip()
    s = re.sub(r"^(₹|rs\.?|inr)\s*", "", s, flags=re.I)
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None  # rejects '-', 'twelve thousand', negatives, NaN
    return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def norm_enum(raw, allowed):
    """Case-insensitive match against allowed values; stored lower-case."""
    s = (raw or "").strip().lower()
    return s if s in allowed else None
IST = timezone(timedelta(hours=5, minutes=30))


def parse_ts(raw):
    """Parse Z / +05:30 / naive (naive = IST). Return a fixed-width UTC string,
    e.g. '2026-10-05T13:20:21.000000Z', or None if it can't be parsed.
    Fixed width means plain string sorting is also time sorting."""
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")