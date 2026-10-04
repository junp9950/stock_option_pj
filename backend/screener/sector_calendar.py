"""강한 섹터 캘린더: 날짜마다 그날 가장 강했던 섹터(16개)와 테마(272개)를 모아 둔다 (우라늄 건의 2026-10-04).
테마 강도 = 소속 종목 그날 등락률 평균(±30% 자름). 종목 5개 이상 + 테마 거래대금 합 100억 이상만."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.screener.rotation import family_members

DAYS = 130          # 약 6개월
TOP_THEMES, TOP_FAMS = 5, 3
MIN_MEMBERS, MIN_TV = 5, 1e10


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = pd.read_sql(text("select stock_code, trading_date, change_pct ch, trading_value tv from spot_daily_prices where trading_date >= :d"),
                     db.connection(), params={"d": latest - timedelta(days=int(DAYS * 1.5))})
    CH = px.pivot(index="trading_date", columns="stock_code", values="ch").sort_index().clip(-30, 30).iloc[-DAYS:]
    TV = px.pivot(index="trading_date", columns="stock_code", values="tv").reindex_like(CH)
    names = dict(db.execute(text("select code, name from stocks")).all())
    th = pd.read_sql(text("select s.id, s.sector_name, ss.stock_code from sector_stocks ss join sectors s on s.id = ss.sector_id where s.is_active"),
                     db.connection())
    th = th[th.stock_code.isin(CH.columns)]
    t_chg, t_up, t_tv, t_mem = {}, {}, {}, {}
    for (sid, name), g in th.groupby(["id", "sector_name"]):
        mem = list(g.stock_code)
        if len(mem) < MIN_MEMBERS:
            continue
        key = (int(sid), name)
        t_chg[key] = CH[mem].mean(axis=1)
        t_up[key] = (CH[mem] > 0).sum(axis=1) / CH[mem].notna().sum(axis=1).clip(lower=1)
        t_tv[key] = TV[mem].sum(axis=1)
        t_mem[key] = mem
    TC, TU, TT = pd.DataFrame(t_chg), pd.DataFrame(t_up), pd.DataFrame(t_tv)
    fams = {f: [c for c in m if c in CH.columns] for f, m in family_members(db).items()}
    FC = pd.DataFrame({f: CH[m].mean(axis=1) for f, m in fams.items() if len(m) >= MIN_MEMBERS})
    days = []
    for d in CH.index:
        row = TC.loc[d].where(TT.loc[d] >= MIN_TV).dropna().sort_values(ascending=False)
        themes = []
        for key in row.index[:TOP_THEMES]:
            mem = t_mem[key]
            lead = CH.loc[d, mem].dropna().sort_values(ascending=False).index[:3]
            themes.append({"id": key[0], "name": key[1], "chg": round(float(row[key]), 2), "up_pct": round(float(TU.at[d, key]) * 100),
                           "leaders": [{"name": names.get(c, c), "chg": round(float(CH.at[d, c]), 1)} for c in lead]})
        fr = FC.loc[d].dropna().sort_values(ascending=False)
        days.append({"date": d.isoformat(), "market_chg": round(float(CH.loc[d].mean()), 2), "themes": themes,
                     "families": [{"name": f, "chg": round(float(fr[f]), 2)} for f in fr.index[:TOP_FAMS]]})
    return {"trading_date": latest.isoformat(), "days": days}
