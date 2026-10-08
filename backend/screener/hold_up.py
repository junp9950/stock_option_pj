"""버틴 종목 종베 — 사용자 원칙 (2026-10-08 본인 글): "종베는 장이 안 좋음에도 꾸역꾸역 버티는 종목 위주, 최근 돈이 들어왔던 종목 위주".

조건: 하루 거래대금 20일 평균 50억↑ · 20일선 위 & 20일선 > 60일선 · 20일선 이격 20% 미만 · 오늘 +12% 미만
      · 최근 10일 안 기준봉(거래 3배·+5% 양봉) · 오늘 시장(종목 평균)보다 +2%p 이상 · 고가 쪽 마감(하루 폭의 60% 위)
점수 = 시장 대비 등락 (+ 고가 근처 약간) → 상위 3개.
3년 확인 (2023~, /home/junp/tmp_claude/jb3.py):
  매일 상위 3개 전체 1,785건 · 다음 날 종가 -0.12% · 5일 -0.08% → 평소에는 의미 없음
  **시장 -1%↓ 날의 상위 3개 272건 · 다음 날 시가 +0.23% · 고가 +5.11% · 종가 +0.66% · 5일 +2.38%** → 빠진 날에만 쓴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

STAT = "3년: 시장 -1%↓ 날 상위 3개 → 다음 날 고가 평균 +5.1% · 종가 +0.7% · 5일 +2.4%"


def picks(db: Session, k: int = 3) -> dict:
    px = pd.read_sql(text("select stock_code s, trading_date d, high_price h, low_price l, close_price c, trading_value tv "
                          "from spot_daily_prices where trading_date >= (select max(trading_date) from spot_daily_prices) - 130"),
                     db.connection())
    if px.empty:
        return {"date": None, "market": 0.0, "items": []}
    P = {k_: px.pivot(index="d", columns="s", values=k_).sort_index().astype(float) for k_ in ("h", "l", "c", "tv")}
    H, L, C, TV = P["h"], P["l"], P["c"], P["tv"]
    chg = (C / C.shift(1) - 1).clip(-.3, .3)
    avg20 = TV.rolling(20).mean().shift(1)
    mk = chg.where(TV.rolling(20).mean() >= 1e9).mean(axis=1)
    d = C.index[-1]
    m = float(mk.iloc[-1])
    rel = chg.iloc[-1] - m
    pos = ((C - L) / (H - L).replace(0, np.nan)).iloc[-1]
    spike = (TV / avg20 >= 3) & (chg >= 0.05)
    recent = spike.iloc[-11:-1]
    ma20, ma60 = C.rolling(20).mean().iloc[-1], C.rolling(60).mean().iloc[-1]
    c = C.iloc[-1]
    ok = ((avg20.iloc[-1] >= 5e9) & (c > ma20) & (ma20 > ma60) & (c / ma20 - 1 < 0.20) & (chg.iloc[-1] < 0.12)
          & recent.any() & (rel >= 0.02) & (pos >= 0.6))
    score = (rel + 0.02 * pos)[ok.fillna(False)].sort_values(ascending=False)
    names = dict(db.execute(text("select code, name from stocks")).all())
    items = []
    for code in score.index[:k]:
        r = recent[code]
        items.append({"code": code, "name": names.get(code, code), "close": float(c[code]), "chg": float(chg[code].iloc[-1]) * 100,
                      "rel": float(rel[code]) * 100, "low": float(L[code].iloc[-1]), "gap20": float(c[code] / ma20[code] - 1) * 100,
                      "spike": str(r[r].index[-1])[5:].replace("-", "/") if r.any() else "", "tv": float(TV[code].iloc[-1])})
    try:      # 보여 주는 숫자는 정규장 15:30 기준 (DB 종가엔 넥스트레이드·시간외가 섞인다)
        from backend.services.naver_live import krx_day  # noqa: PLC0415
        for x in items:
            kd = krx_day(x["code"])
            if kd and kd["base"]:
                x["close"], x["low"] = kd["close"], kd["low"]
                x["rel"] += (kd["close"] / kd["base"] - 1) * 100 - x["chg"]
                x["chg"] = (kd["close"] / kd["base"] - 1) * 100
    except Exception:  # noqa: BLE001
        pass
    return {"date": str(d), "market": m * 100, "down_day": m <= -0.01, "items": items}
