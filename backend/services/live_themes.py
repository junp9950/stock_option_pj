"""오늘 강한 테마 (실시간): 토스 현재가로 테마별 오늘 등락을 계산한다.

등락 = 토스 현재가 / DB의 직전 거래일 종가. 테마 등락은 상·하위 1종목씩 뺀 평균(5종목 이상일 때)이라
한 종목 상한가가 테마 전체를 끌어올리지 못한다. 상승 비율은 테마 종목 중 오른 종목의 비율(쏠림이 아니라 테마 전체가 오르는지).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.toss_client import _get
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_BATCH = 200          # 토스 /prices 한 번에 조회할 종목 수 (200까지 확인)
_TTL = 60             # 초. 여러 사람이 탭을 열어도 토스 호출은 1분에 한 번
_MIN_MEMBERS = 3
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}


def _prices(codes: list[str]) -> dict[str, tuple[float, str]]:
    out: dict[str, tuple[float, str]] = {}
    for i in range(0, len(codes), _BATCH):
        resp = _get("/prices", {"symbols": ",".join(codes[i:i + _BATCH])})
        if resp is None or resp.status_code != 200:
            logger.warning("Toss prices 실패: %s", resp.status_code if resp is not None else "no token")
            continue
        for r in resp.json().get("result", []):
            if not r.get("timestamp") or not r.get("lastPrice"):
                continue
            try:
                out[r["symbol"]] = (float(r["lastPrice"]), r["timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _build(db: Session) -> dict:
    members: dict[int, list[str]] = defaultdict(list)
    names: dict[int, str] = {}
    for sid, name, code in db.execute(text(
        "select s.id, s.sector_name, ss.stock_code from sector_stocks ss join sectors s on s.id = ss.sector_id where s.is_active"
    )):
        members[sid].append(code)
        names[sid] = name
    codes = sorted({c for m in members.values() for c in m})
    prices = _prices(codes)
    if not prices:
        return {"as_of": None, "items": []}

    # 시세 시각의 날짜(장 마감 후·주말이면 마지막 거래일) 직전 거래일 종가가 기준
    as_of = max(ts for _, ts in prices.values())
    today = date.fromisoformat(as_of[:10])
    prev = {code: close for code, close in db.execute(text(
        "select distinct on (stock_code) stock_code, close_price from spot_daily_prices "
        "where trading_date < :d and trading_date >= :lo order by stock_code, trading_date desc"
    ), {"d": today, "lo": today - timedelta(days=14)})}
    stock_names = dict(db.execute(text("select code, name from stocks")).all())

    # 테마 거래대금 배수: DB의 가장 최근 거래일 테마 합계 / 그 전 20거래일 평균 (토스 현재가에는 거래대금이 없다)
    tdays = [d for (d,) in db.execute(text(
        "select distinct trading_date from spot_daily_prices where trading_date <= :d order by 1 desc limit 21"), {"d": today})]
    tv_by_day: dict = defaultdict(dict)
    if len(tdays) >= 6:
        for code, d, tv in db.execute(text(
            "select stock_code, trading_date, trading_value from spot_daily_prices where trading_date between :a and :b"),
            {"a": tdays[-1], "b": tdays[0]}):
            tv_by_day[code][d] = float(tv or 0)

    chg: dict[str, float] = {}
    for code, (px, ts) in prices.items():
        pc = prev.get(code)
        if pc and ts[:10] == as_of[:10]:   # 오늘 체결이 없는(거래정지 등) 종목은 뺀다
            r = (px / pc - 1) * 100
            if abs(r) <= 30.5:   # 상하한가 밖 = 액면분할·병합 등으로 기준가가 바뀐 것
                chg[code] = r

    items = []
    for sid, mem in members.items():
        vals = sorted((chg[c], c) for c in mem if c in chg)
        if len(vals) < _MIN_MEMBERS:
            continue
        core = vals[1:-1] if len(vals) >= 5 else vals
        tv_x = None
        if tv_by_day:
            last = sum(tv_by_day.get(c, {}).get(tdays[0], 0) for c in mem)
            prev = [sum(tv_by_day.get(c, {}).get(d, 0) for c in mem) for d in tdays[1:]]
            base = sum(prev) / len(prev) if prev else 0
            tv_x = round(last / base, 2) if base else None
        items.append({
            "sector_id": sid,
            "sector_name": names[sid],
            "avg_change_pct": round(sum(v for v, _ in core) / len(core), 2),
            "up_ratio": round(sum(1 for v, _ in vals if v > 0) / len(vals) * 100),
            "count": len(vals),
            "tv_x": tv_x,
            "leaders": [{"code": c, "name": stock_names.get(c, c), "change_pct": round(v, 2)} for v, c in vals[::-1][:3]],
        })
    items.sort(key=lambda x: -x["avg_change_pct"])
    return {"as_of": as_of, "tv_date": tdays[0].isoformat() if tdays else None, "items": items}


def live_themes(db: Session) -> dict:
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["at"] < _TTL:
            return _cache["data"]
        data = _build(db)
        _cache.update(at=time.time(), data=data)
        return data
