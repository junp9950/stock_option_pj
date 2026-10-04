"""바닥 박스 감시 (한선엔지니어링형): 120일 고점 -40%↓ 빠진 뒤 15일 폭 13%↓ 박스 + 거래 평소(그 전 60일) 0.6배↓.
3년(632건): 사 두면 20일 -0.7%p·40일 -2.8%p로 손해, 20일 안 터질 확률 18%(아무 종목 15%) → 매수 신호가 아니라 감시용.
'터짐' = 어제까지 박스였는데 오늘 +8%↑·거래 3배↑ 양봉 (한선 9/16 +24%). 그날 섹터·시장이 받쳐 주면 들어갈 후보."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

N, MAX_BAND, MAX_DD, MAX_DRY = 15, 0.13, -0.40, 0.6


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = pd.read_sql(text("select stock_code, trading_date, open_price o, high_price h, low_price l, close_price c, trading_value tv, change_pct ch "
                          "from spot_daily_prices where trading_date >= :d"), db.connection(), params={"d": latest - timedelta(days=300)})
    P = {k: px.pivot(index="trading_date", columns="stock_code", values=k).sort_index() for k in ("o", "h", "l", "c", "tv", "ch")}
    C, O, H, L, TV, CH = (P[k] for k in ("c", "o", "h", "l", "tv", "ch"))
    band = H.rolling(N).max() / L.rolling(N).min() - 1
    dd = C / C.rolling(120).max() - 1
    dry = TV.rolling(N).mean() / TV.shift(N).rolling(60).mean()
    box = (band <= MAX_BAND) & (dd <= MAX_DD) & (dry <= MAX_DRY) & (TV.rolling(5).mean() >= 3e8) & (C >= 1000)
    tvx = TV / TV.shift(1).rolling(20).mean()
    names, caps = {}, {}
    for code, name, cap in db.execute(text("select code, name, market_cap from stocks")):
        names[code], caps[code] = name, float(cap or 0)
    skip = ("리츠", "스팩", "ETF", "ETN")
    from backend.screener.rotation import family_members  # noqa: PLC0415
    fam_of: dict[str, list[str]] = {}
    for f, m in family_members(db).items():
        for c in m:
            fam_of.setdefault(c, []).append(f)
    d, prev = C.index[-1], C.index[-2]
    items, burst = [], []
    for code in C.columns:
        nm = names.get(code, code)
        if any(k in nm for k in skip):
            continue
        on_now, on_prev = bool(box.at[d, code]), bool(box.at[prev, code])
        is_burst = on_prev and CH.at[d, code] >= 8 and tvx.at[d, code] >= 3 and C.at[d, code] > O.at[d, code]
        if not (on_now or is_burst):
            continue
        k = 0          # 박스가 며칠째인지
        for v in box[code].values[::-1][int(is_burst):]:
            if not v:
                break
            k += 1
        x = {"code": code, "name": nm, "days": k + N - 1, "band_pct": round(float(band.at[prev if is_burst else d, code]) * 100, 1),
             "dd_pct": round(float(dd.at[d, code]) * 100), "dry_x": round(float(dry.at[prev if is_burst else d, code]), 2),
             "close": round(float(C.at[d, code])), "change_pct": round(float(CH.at[d, code]), 2),
             "box_low": round(float(L[code].iloc[-N - int(is_burst):len(L) - int(is_burst)].min())),
             "families": fam_of.get(code, [])[:2], "market_cap": caps.get(code, 0)}
        (burst if is_burst else items).append(x)
    items.sort(key=lambda x: (-x["days"], x["band_pct"]))
    return {"trading_date": d.isoformat(), "items": items, "burst": burst}
