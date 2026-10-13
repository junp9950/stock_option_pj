"""매일 데이터 점검 — 이상 있을 때만 사장님 텔레그램으로 (2026-10-13 사용자 "이상 있을 때만").
① 08:30·17:05 지난 거래일 시세가 KRX 공식 정규장 값과 맞는지 (08:20 바로잡기 뒤). 수정주가(시·고·저·종 같은 비율)는 정상으로 봄.
② 16:15 오늘 15:41 수집이 다 들어왔는지 (종목 수가 전날의 90% 이상).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _tell(db: Session, msg: str) -> None:
    try:
        from backend.services.telegram import owner_chats, send  # noqa: PLC0415
        for c in owner_chats(db):
            send(db, msg, c)
    except Exception as exc:  # noqa: BLE001
        logger.warning("데이터 점검 알림 실패: %s", type(exc).__name__)


def _prev_trading_day(d: date) -> date:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def check_prices(db: Session, final: bool = False) -> str:
    """지난 거래일 DB 시세 vs KRX 공식. final=True(17:05)면 KRX 자료가 아직 없을 때도 알림."""
    from backend.collector.krx_daily import fetch  # noqa: PLC0415
    day = _prev_trading_day(datetime.now(KST).date())
    k = fetch(day)
    if not k:
        msg = f"KRX 공식 시세 {day} 아직 없음"
        if final:
            _tell(db, f"⚠ 데이터 점검: {day} KRX 공식 시세를 오늘 하루 못 받았습니다 — 그날 시세가 장 후 값이 섞인 임시값 그대로입니다.")
        return msg
    rows = db.execute(text("select stock_code, open_price, high_price, low_price, close_price from spot_daily_prices where trading_date = :d"), {"d": day}).all()
    bad, cover = [], 0
    for s, o, h, l, c in rows:
        x = k.get(s)
        if not x:
            continue
        cover += 1
        old = [float(v or 0) for v in (o, h, l, c)]
        if all(abs(a - b) <= 0.5 for a, b in zip(old, x[:4])):
            continue
        rat = [a / b for a, b in zip(old, x[:4]) if a > 0 and b > 0]
        if len(rat) == 4 and (max(rat) - min(rat)) / max(rat) < 1e-4:
            continue      # 수정주가 (같은 비율) — 정상
        bad.append(s)
    missing = len(k) - cover
    problems = []
    if len(bad) > 3:
        problems.append(f"KRX 공식값과 다른 종목 {len(bad)}개 (예: {', '.join(bad[:5])})")
    if missing > max(50, len(k) * 0.05):
        problems.append(f"KRX엔 있는데 DB에 없는 종목 {missing}개 (KRX {len(k)} · DB {cover})")
    if problems:
        _tell(db, f"⚠ 데이터 점검 ({day}): " + " · ".join(problems) + "\n자동 바로잡기(07:30·08:20·11:30·17:00)가 다시 돌고, 그래도 남으면 확인이 필요합니다.")
        return "이상: " + " · ".join(problems)
    return f"{day} 정상 (KRX {len(k)} · 대조 {cover})"


def check_collection(db: Session) -> str:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    today = datetime.now(KST).date()
    if not is_trading_day(today):
        return "장 없는 날"
    prev = _prev_trading_day(today)
    n_today = db.execute(text("select count(*) from spot_daily_prices where trading_date = :d"), {"d": today}).scalar() or 0
    n_prev = db.execute(text("select count(*) from spot_daily_prices where trading_date = :d"), {"d": prev}).scalar() or 0
    if n_prev and n_today < n_prev * 0.9:
        _tell(db, f"⚠ 데이터 점검: 오늘 시세가 덜 들어왔습니다 — {n_today}종목 (어제 {n_prev}). 15:41 수집이 중간에 끊겼을 수 있습니다.")
        return f"이상: 오늘 {n_today} / 어제 {n_prev}"
    return f"정상: 오늘 {n_today} / 어제 {n_prev}"
