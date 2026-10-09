from __future__ import annotations

from datetime import date, datetime, timedelta

try:
    import exchange_calendars as xcals
except Exception:  # noqa: BLE001
    xcals = None


_CAL: list = []
_DAYS: dict = {}


_SESS_FILE = None


def _sessions() -> set | None:
    """거래일 목록을 파일로 저장해 두고 씀 — 달력 객체를 만드는 데 7초씩 걸려서 재시작마다 느리던 것 (2026-10-09)."""
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    f = Path.home() / ".cache" / "krx_sessions.json"
    try:
        d = json.loads(f.read_text())
        if d.get("end", "") >= (date.today() + timedelta(days=30)).isoformat():
            return set(d["days"])
    except Exception:  # noqa: BLE001
        pass
    cal = get_calendar()
    if cal is None:
        return None
    try:
        days = [x.strftime("%Y-%m-%d") for x in cal.sessions]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"end": days[-1], "days": days}))
        return set(days)
    except Exception:  # noqa: BLE001
        return None


def get_calendar():
    """휴장일 달력 — 만드는 데 수 초 걸려서 한 번만 만든다 (2026-10-09 매번 새로 만들어 모든 탭이 느리던 것)."""
    if _CAL:
        return _CAL[0]
    cal = None
    if xcals:
        try:
            cal = xcals.get_calendar("XKRX", start=(date.today() - timedelta(days=1200)).isoformat())   # 기간을 줄여 만드는 시간 단축
        except Exception:  # noqa: BLE001
            cal = None
    _CAL.append(cal)
    return cal


def is_trading_day(target_date: date) -> bool:
    if target_date in _DAYS:
        return _DAYS[target_date]
    if "sess" not in _DAYS:
        _DAYS["sess"] = _sessions()
    sess = _DAYS["sess"]
    if sess is not None and min(sess) <= target_date.isoformat() <= max(sess):
        v = target_date.isoformat() in sess
    else:
        calendar = get_calendar()
        try:
            v = bool(calendar.is_session(datetime.combine(target_date, datetime.min.time()))) if calendar else target_date.weekday() < 5
        except Exception:  # noqa: BLE001
            v = target_date.weekday() < 5
    _DAYS[target_date] = v
    return v


def latest_trading_day(reference_date: date | None = None) -> date:
    cursor = reference_date or date.today()
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor

