"""순환매 모니터: 272개 테마를 이야기 줄기 16개로 묶어 매일 순위·확산·자금 흐름을 본다.

- 20일 상승: 줄기 소속 종목 20일 수익률 중간값, 순위는 16개 중
- 확산: 20일선 위 종목 비율
- 자금: 최근 5일 줄기 거래대금 평균 / 그 전 20거래일 평균
- 과열: 순위 1~2위 + 확산 90% 이상 + 자금이 최근 5일 정점보다 10% 이상 줄어듦
- 유입: 10거래일 전보다 순위 3계단 이상 상승 + 자금 1.05배 이상
3년 확인(상승·횡보장): 뜨거운 줄기 상위 3 + 그날 줄기 거래대금 1.2배 이상인 날의 거래 실린 양봉은 다음 날 평균 +0.94%(수익 71%),
줄기 밖은 +0.28%.
단 줄기 단위 '다음 10~20일 어느 줄기가 앞서나'는 거의 맞히지 못했다(같은 날 16개 평균 대비): 1~2위 -0.35%p/-0.47%p,
유입(순위 3계단↑+자금 1.05배) -0.20%p, 순위 하락 +0.17%p — 모두 1%p 미만. 그래서 이 화면은 '지금 어디에 돈이 붙었나'를 보는 용도다.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

FAMILIES: dict[str, str] = {
    "AI메모리·기판": r"HBM|CXL|소캠|SOCAMM|반도체 기판|FC-BGA|PCB|DDR|메모리|낸드|D램",
    "반도체 장비·재료": r"반도체 장비|반도체 재료|반도체 부품|시스템반도체|파운드리|온디바이스|AI반도체|NPU|칩렛|유리기판",
    "전력·전선": r"전선|전력|변압기|스마트그리드|ESS|초고압",
    "원전·에너지": r"원자력|원전|SMR|핵융합",
    "신재생": r"태양광|풍력|수소|연료전지|SOFC|신재생",
    "로봇": r"로봇|휴머노이드|피지컬 AI",
    "우주항공·방산": r"우주|위성|스페이스X|누리호|방산|드론|항공",
    "통신": r"통신장비|광통신|5G|6G|유심|USIM",
    "2차전지": r"2차전지|리튬|전고체|양극재|음극재|전해질|폐배터리",
    "바이오": r"제약|바이오|신약|항암|비만|치료제|백신|의료기기",
    "조선·해운": r"조선|해운|LNG",
    "자동차": r"자동차|전기차|자율주행|타이어",
    "화장품·소비": r"화장품|음식료|면세",
    "게임·엔터": r"게임|엔터|K-POP|웹툰|드라마",
    "금융·지주": r"증권|은행|보험|지주사|밸류업",
    "AI SW·플랫폼": r"인공지능|AI 챗봇|클라우드|데이터센터|소프트웨어|플랫폼|핀테크|전자결제|애플페이",
}


def family_members(db: Session) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {f: set() for f in FAMILIES}
    for code, theme in db.execute(text(
        "select ss.stock_code, s.sector_name from sector_stocks ss join sectors s on s.id = ss.sector_id where s.is_active"
    )):
        for f, pat in FAMILIES.items():
            if re.search(pat, theme or ""):
                out[f].add(code)
    return {f: sorted(m) for f, m in out.items()}


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return {"trading_date": None, "items": []}
    px = pd.read_sql(text("select stock_code, trading_date, close_price c, trading_value tv, change_pct ch from spot_daily_prices "
                          "where trading_date >= :d"), db.connection(), params={"d": latest - timedelta(days=110)})
    names = dict(db.execute(text("select code, name from stocks")).all())
    C = px.pivot(index="trading_date", columns="stock_code", values="c").sort_index()
    TV = px.pivot(index="trading_date", columns="stock_code", values="tv").sort_index()
    CH = px.pivot(index="trading_date", columns="stock_code", values="ch").sort_index()
    ret20 = C / C.shift(20) - 1
    above = C > C.rolling(20).mean()
    rows = {}
    for f, mem in family_members(db).items():
        m = [x for x in mem if x in C.columns]
        if len(m) < 5:
            continue
        tv = TV[m].sum(axis=1)
        rows[f] = {
            "ret20": ret20[m].median(axis=1), "breadth": above[m].mean(axis=1),
            "tv5": tv.rolling(5).mean() / tv.shift(5).rolling(20, min_periods=15).mean(),
            "tv1": tv / tv.shift(1).rolling(20, min_periods=15).mean(),
            "ret5": (C[m] / C[m].shift(5) - 1).median(axis=1), "chg": CH[m].median(axis=1), "members": m,
        }
    ret_df = pd.DataFrame({f: r["ret20"] for f, r in rows.items()})
    rank = ret_df.rank(axis=1, ascending=False)
    d, d10 = C.index[-1], C.index[-11]
    items = []
    for f, r in rows.items():
        tv5 = r["tv5"]
        overheat = (rank.at[d, f] <= 2 and r["breadth"].iloc[-1] >= 0.9 and tv5.iloc[-1] <= 0.9 * tv5.iloc[-6:].max())
        inflow = rank.at[d10, f] - rank.at[d, f] >= 3 and tv5.iloc[-1] >= 1.05
        m = r["members"]
        # 오늘 돈이 붙은 종목: 거래대금이 20일 평균의 2배 이상·30억 이상인 것 중 많이 오른 순 (대형주는 여러 줄기에 다 속해서 거래대금 순은 의미가 없다)
        avg20 = TV[m].iloc[-21:-1].mean()
        today = pd.DataFrame({"tv": TV.loc[d, m], "ch": CH.loc[d, m], "x": TV.loc[d, m] / avg20}).dropna()
        today = today[(today.x >= 2) & (today.tv >= 3e9)].sort_values("ch", ascending=False).head(3)
        items.append({
            "family": f, "count": len(m),
            "rank": int(rank.at[d, f]), "rank_10ago": int(rank.at[d10, f]),
            "ret20_pct": round(float(r["ret20"].iloc[-1]) * 100, 1), "ret5_pct": round(float(r["ret5"].iloc[-1]) * 100, 1),
            "chg_pct": round(float(r["chg"].iloc[-1]), 2),
            "breadth_pct": round(float(r["breadth"].iloc[-1]) * 100), "breadth_10ago": round(float(r["breadth"].loc[d10]) * 100),
            "tv5_x": round(float(tv5.iloc[-1]), 2), "tv5_peak5": round(float(tv5.iloc[-6:].max()), 2), "tv1_x": round(float(r["tv1"].iloc[-1]), 2),
            "status": "과열" if overheat else ("유입" if inflow else ""),
            "leaders": [{"code": c, "name": names.get(c, c), "change_pct": round(float(x.ch), 1), "tv_x": round(float(x.x), 1)} for c, x in today.iterrows()],
        })
    items.sort(key=lambda x: x["rank"])
    return {"trading_date": d.isoformat(), "items": items}
