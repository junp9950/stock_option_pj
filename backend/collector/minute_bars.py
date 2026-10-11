"""분봉 길게 (2026-10-11 사용자 "분봉으로 줄일수록 짧아서 아쉽다").

네이버 분봉 API는 최근 약 6거래일만 준다. 토스 1분봉은 nextBefore로 몇 년 전까지 거슬러 받을 수 있어서(한 번에 200개)
종목을 처음 분봉으로 열면 뒤에서 약 석 달치 1분봉을 받아 표 stock_minute_bars에 쌓고, 3·5·10·15·30·60분봉은 여기서 묶어 만든다.
- 하루 = 08:00~20:00(NXT 포함) 약 720개 → 토스 3~4번. 석 달(63거래일) ≈ 230번 · 0.2초 쉼 → 종목당 1분 남짓, 한 번에 한 종목씩.
- 한 번 받은 종목은 이후 새 봉만 덧붙임(몇 번). 장 마감 뒤(20:15) 받은 종목 전부 덧붙이고 100일 넘은 봉은 지움.
시간은 한국 시간(timestamp without time zone).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
KEEP_DAYS = 92            # 달력 기준 약 석 달 (≈ 63거래일)
# 분봉마다 보여 줄 거래일 수 (차트는 끌어서 더 앞도 볼 수 있음)
SHOW_DAYS = {"1m": 10, "3m": 15, "5m": 20, "10m": 30, "15m": 40, "30m": 63, "60m": 63}
MIN_DAYS_READY = {"1m": 2, "3m": 5, "5m": 8, "10m": 12, "15m": 15, "30m": 25, "60m": 40}

_q: "queue.Queue[str]" = queue.Queue()
_pending: set[str] = set()
_lock = threading.Lock()
_worker: threading.Thread | None = None


def _ensure(db: Session) -> None:
    db.execute(text("create table if not exists stock_minute_bars (code varchar(12) not null, ts timestamp not null, "
                    "o real, h real, l real, c real, v bigint, primary key (code, ts))"))
    db.commit()


def _page(code: str, before: str | None):
    from backend.services import toss_client  # noqa: PLC0415
    params = {"symbol": code, "interval": "1m", "count": 200}
    if before:
        params["before"] = before
    for k in range(3):
        r = toss_client._get("/candles", params)  # noqa: SLF001
        if r is None:
            return [], None
        if r.status_code == 429:
            time.sleep(2 + 2 * k)
            continue
        if r.status_code != 200:
            return [], None
        res = r.json().get("result") or {}
        rows = []
        for x in res.get("candles") or []:
            try:
                # 토스 1분봉 시각 = 봉이 끝나는 시각 (토스 09:01 = 네이버 09:00 봉) → 1분 당겨 시작 시각으로
                rows.append({"code": code, "ts": datetime.fromisoformat(x["timestamp"]).astimezone(KST).replace(tzinfo=None) - timedelta(minutes=1),
                             "o": float(x["openPrice"]), "h": float(x["highPrice"]), "l": float(x["lowPrice"]),
                             "c": float(x["closePrice"]), "v": int(float(x.get("volume") or 0))})
            except (KeyError, ValueError):
                continue
        return rows, res.get("nextBefore")
    return [], None


def _save(db: Session, rows: list[dict]) -> None:
    if rows:
        db.execute(text("insert into stock_minute_bars (code, ts, o, h, l, c, v) values (:code, :ts, :o, :h, :l, :c, :v) "
                        "on conflict (code, ts) do update set o = excluded.o, h = excluded.h, l = excluded.l, c = excluded.c, v = excluded.v"), rows)
        db.commit()


def fill(db: Session, code: str, max_pages: int = 400) -> int:
    """새 봉 덧붙이기 + 석 달까지 앞쪽 채우기. 받은 페이지 수."""
    _ensure(db)
    newest, oldest = db.execute(text("select max(ts), min(ts) from stock_minute_bars where code = :c"), {"c": code}).one()
    cutoff = datetime.now(KST).replace(tzinfo=None) - timedelta(days=KEEP_DAYS)
    pages = 0
    # 1) 지금부터 거꾸로, DB에 있는 가장 새 봉까지
    before = None
    while pages < 40:
        rows, nb = _page(code, before); pages += 1
        _save(db, rows)
        if not rows or not nb or (newest and min(r["ts"] for r in rows) <= newest) or min(r["ts"] for r in rows) < cutoff:
            break
        before = nb
        time.sleep(0.2)
    if newest is None:      # 처음 받는 종목: 위에서 이어서 내려온 만큼이 oldest
        oldest = db.execute(text("select min(ts) from stock_minute_bars where code = :c"), {"c": code}).scalar()
    # 2) 가장 오래된 봉에서 더 앞으로 석 달까지
    if oldest and oldest > cutoff:
        before = (oldest + timedelta(minutes=1)).replace(tzinfo=KST).isoformat()
        while pages < max_pages:
            time.sleep(0.2)
            rows, nb = _page(code, before); pages += 1
            _save(db, rows)
            if not rows or not nb or min(r["ts"] for r in rows) < cutoff:
                break
            before = nb
    return pages


def _run() -> None:
    from backend.db.database import SessionLocal  # noqa: PLC0415
    while True:
        code = _q.get()
        db = SessionLocal()
        try:
            t0 = time.time()
            n = fill(db, code)
            logger.info("분봉 채움 %s: %d번 %.0f초", code, n, time.time() - t0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("분봉 채움 실패 %s: %s", code, type(exc).__name__)
        finally:
            db.close()
            with _lock:
                _pending.discard(code)


def request_fill(code: str) -> None:
    """뒤에서 채우기 (같은 종목 중복 X, 대기 40종목까지)."""
    global _worker
    with _lock:
        if code in _pending or len(_pending) >= 40:
            return
        _pending.add(code)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="minute-bars", daemon=True)
            _worker.start()
    _q.put(code)


def filling(code: str) -> bool:
    with _lock:
        return code in _pending


def load(db: Session, code: str, tf: str, ext: bool = False) -> tuple[list[dict], int]:
    """묶은 분봉 (차트 형식) · DB에 있는 거래일 수. ext=False면 정규장(09:00~15:30, 15:30 종가 체결은 앞 봉에 합침)만 — 시간외(NXT)는 거래가 얇아 화면만 차지."""
    _ensure(db)
    mins = int(tf[:-1])
    days = [r[0] for r in db.execute(text("select distinct ts::date from stock_minute_bars where code = :c order by 1 desc limit :n"),
                                     {"c": code, "n": SHOW_DAYS[tf]}).all()]
    if not days:
        return [], 0
    n_all = db.execute(text("select count(distinct ts::date) from stock_minute_bars where code = :c"), {"c": code}).scalar() or 0
    rows = db.execute(text(
        "select date_bin(make_interval(mins => :m), case when ts::time = time '15:30' then ts - interval '1 minute' else ts end, timestamp '2000-01-01 09:00') b, (array_agg(o order by ts))[1], max(h), min(l), "
        "(array_agg(c order by ts desc))[1], sum(v) from stock_minute_bars where code = :c and ts >= :d "
        + ("" if ext else "and ts::time between time '09:00' and time '15:30' ") + "group by 1 order by 1"),
        {"m": mins, "c": code, "d": min(days)}).all()
    import calendar  # noqa: PLC0415
    out = [{"t": calendar.timegm(b.timetuple()), "timestamp": b.strftime("%Y-%m-%dT%H:%M:00+09:00"), "openPrice": o, "highPrice": h,
            "lowPrice": l, "closePrice": c, "volume": int(v or 0)} for b, o, h, l, c, v in rows]
    return out, n_all


def ready(n_days: int, tf: str) -> bool:
    return n_days >= MIN_DAYS_READY.get(tf, 5)


def refresh_all(db: Session) -> str:
    """장 마감 뒤: 받아 둔 종목 전부 새 봉 덧붙이기 + 오래된 봉 지우기."""
    _ensure(db)
    codes = [r[0] for r in db.execute(text("select distinct code from stock_minute_bars")).all()]
    for c in codes:
        try:
            fill(db, c, max_pages=60)
        except Exception as exc:  # noqa: BLE001
            logger.warning("분봉 덧붙이기 실패 %s: %s", c, type(exc).__name__)
        time.sleep(0.2)
    db.execute(text("delete from stock_minute_bars where ts < now() - interval '100 days'"))
    db.commit()
    return f"분봉 {len(codes)}종목 덧붙임"
