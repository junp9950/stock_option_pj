"""오늘 거래대금이 '언제 이후 최고'인지: 6개월 넘게 이보다 큰 날이 없었던 종목 (사용자 요청 2026-10-04, '25년 3월 이후 최고 거래대금').
거래대금 30억 이상만. 상한가면 표시 (3년: 몇 년 만 최대 + 상한가 종가 매수 → 다음 날 시가 평균 +5.6%, 단 사기 어려움).
대량거래 관심종목(volume_record)의 신기록은 '평소 10배 + +5% 양봉'이라 더 좁다. 여기는 등락과 무관하게 다 보여 준다."""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_TV = 3e9
MIN_DAYS = 180


def scan(db: Session) -> dict:
    d = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    gmin = db.execute(text("select min(trading_date) from spot_daily_prices")).scalar()
    rows = db.execute(text("""
        with t as (select stock_code, trading_value tv, change_pct ch, close_price c from spot_daily_prices where trading_date = :d and trading_value >= :m)
        select t.stock_code, t.tv, t.ch, t.c,
          (select max(trading_date) from spot_daily_prices q where q.stock_code = t.stock_code and q.trading_date < :d and q.trading_value >= t.tv) last_big,
          (select min(trading_date) from spot_daily_prices q where q.stock_code = t.stock_code) first_d,
          (select avg(trading_value) from (select trading_value from spot_daily_prices q where q.stock_code = t.stock_code and q.trading_date < :d
                                           order by trading_date desc limit 20) z) avg20
        from t"""), {"d": d, "m": MIN_TV}).all()
    names, caps = {}, {}
    for code, name, cap, sh in db.execute(text("select code, name, market_cap, shares_outstanding from stocks")):
        names[code], caps[code] = name, (float(cap or 0), float(sh or 0))
    skip = ("리츠", "스팩", "ETF", "ETN")
    from backend.screener.rotation import family_members  # noqa: PLC0415
    fam_of: dict[str, list[str]] = {}
    for f, m in family_members(db).items():
        for c in m:
            fam_of.setdefault(c, []).append(f)
    out = []
    for code, tv, ch, c, last_big, first_d, avg20 in rows:
        nm = names.get(code, code)
        if any(k in nm for k in skip):
            continue
        if first_d and (d - first_d).days < MIN_DAYS:
            continue                     # 이력이 짧으면 '최고'가 의미 없음
        if last_big is not None and (d - last_big).days < MIN_DAYS:
            continue
        if last_big is None:
            label = "상장 이후 최고" if first_d > gmin else f"{gmin.year % 100}년 {gmin.month}월(데이터 시작) 이후 최고"
            since_days = (d - first_d).days
        else:
            label = f"{last_big.year % 100}년 {last_big.month}월 이후 최고"
            since_days = (d - last_big).days
        cap = caps.get(code, (0, 0))[0] or caps.get(code, (0, 0))[1] * float(c)
        out.append({"code": code, "name": nm, "label": label, "since_days": since_days, "last_big": last_big.isoformat() if last_big else None,
                    "value": round(float(tv)), "tv_x": round(float(tv) / float(avg20), 1) if avg20 else None,
                    "change_pct": round(float(ch), 2), "close": round(float(c)), "limit_up": float(ch) >= 29.5,
                    "families": fam_of.get(code, [])[:3], "market_cap": cap})
    out.sort(key=lambda x: (-x["since_days"], -x["value"]))
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    fl = flags_get([x["code"] for x in out])
    for x in out:
        x["flags"] = fl.get(x["code"], {}).get("flags", [])
    return {"trading_date": d.isoformat() if isinstance(d, date) else d, "items": out}
