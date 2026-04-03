from __future__ import annotations

from datetime import date, datetime, timedelta

try:
    import exchange_calendars as xcals
except Exception:  # noqa: BLE001
    xcals = None


def get_calendar():
    return xcals.get_calendar("XKRX") if xcals else None


def is_trading_day(target_date: date) -> bool:
    calendar = get_calendar()
    if calendar is None:
        return target_date.weekday() < 5
    return bool(calendar.is_session(datetime.combine(target_date, datetime.min.time())))


def latest_trading_day(reference_date: date | None = None) -> date:
    cursor = reference_date or date.today()
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor

