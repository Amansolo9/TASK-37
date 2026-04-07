"""Date formatting and parsing utilities.

Primary UI format: MM/DD/YYYY
Storage format: ISO 8601
"""

from datetime import datetime, date


def format_date_us(d: date | datetime | None) -> str:
    if d is None:
        return ""
    return d.strftime("%m/%d/%Y")


def format_datetime_us(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%m/%d/%Y %I:%M %p")


def parse_date_us(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_datetime_us(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
