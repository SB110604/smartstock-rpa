from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings

TZ = ZoneInfo(settings.TZ)


def now() -> datetime:
    """Timezone-aware current time in the business time zone (Asia/Kolkata)."""
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def local_date(dt: datetime) -> date:
    return dt.astimezone(TZ).date() if dt.tzinfo else dt.date()


def start_of_day(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=TZ)


def days_ago(n: int) -> date:
    return today() - timedelta(days=n)
