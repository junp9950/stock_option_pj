"""대량거래 관심종목: 최근 약 4개월 안에 몇 년 만의 최대 거래대금이 터진 종목과 지금 단계.

신기록일 = 그날 거래대금이 그 종목 데이터 전체(약 3년)에서 최대 + 직전 120일 중간값의 10배 이상 + 양봉 + 전날 대비 +5% 이상 + 30억 이상.
2023-09~2026-09 전종목 확인(1,113건): 신기록일 종가에 바로 사면 20일 뒤 중간값 -7.1%(플러스 34%)라 추격 매수 신호가 아니다.
대신 20일 안에 95%가 신기록일 종가보다 높은 가격을 찍어(중간값 +15%) 크게 움직이는 종목을 고르는 '관심 등록' 용도다.
진입은 그 뒤 숨고르기(거래가 마르면서 상승분을 지킴) 후 돌려세울 때 본다. 한양디지텍 9/17, 금호타이어 6~8월이 예.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

WINDOW = 80          # 신기록일을 찾는 기간 (거래일, 약 4개월)
PRE_MED_DAYS = 120   # '평소' 거래대금 = 직전 120거래일 중간값
MIN_HISTORY = 250    # 그 전 데이터가 최소 1년은 있어야 '몇 년 만'이라고 본다
X_MIN = 10           # 평소의 10배 이상
MIN_VALUE = 3e9      # 신기록일 거래대금 30억 이상
MIN_EVENT_CHG = 5.0  # 신기록일 전날 종가 대비 +5% 이상 (우리금융지주 10/1처럼 갭하락 뒤 대량 매도, 포스코인터 9/3처럼
                     # 주가는 안 움직인 대량 체결(블록딜·지수 편입 등)은 시세가 아니라 뺀다)
NEW_DAYS = 10        # 마지막 대량거래일 뒤 10거래일까지는 '신규'
DRY_MAX = 0.25       # 최근 5일 거래대금이 대량거래 최대일의 25% 이하면 말랐다고 본다
KEEP_MIN = 0.5       # 상승분의 절반 이상을 지켜야 숨고르기, 아니면 무너짐


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return {"trading_date": None, "items": []}
    days = [d for (d,) in db.execute(text(
        "select distinct trading_date from spot_daily_prices where trading_date <= :d order by trading_date desc limit :n"),
        {"d": latest, "n": WINDOW + PRE_MED_DAYS + 1})][::-1]
    win_start, load_start = days[-WINDOW], days[0]

    # 기간 시작 전까지의 종목별 최대 거래대금과 데이터 일수 (전체 3년치를 내려받지 않으려고 DB에서 집계)
    prior = {code: (float(mx or 0), int(n)) for code, mx, n in db.execute(text(
        "select stock_code, max(trading_value), count(*) from spot_daily_prices where trading_date < :w group by stock_code"),
        {"w": load_start})}
    by: dict[str, list] = defaultdict(list)
    for r in db.execute(text(
        "select stock_code, trading_date, open_price, high_price, low_price, close_price, trading_value "
        "from spot_daily_prices where trading_date >= :s order by stock_code, trading_date"), {"s": load_start}):
        by[r[0]].append(r)
    names = dict(db.execute(text("select code, name from stocks")).all())

    items = []
    for code, pl in by.items():
        if pl[-1][1] != latest:
            continue
        run_max, n_prior = prior.get(code, (0.0, 0))
        tv = [float(p[6] or 0) for p in pl]
        first = last_big = None
        big_max = 0.0
        for i, p in enumerate(pl):
            if p[1] >= win_start and n_prior + i >= MIN_HISTORY and i >= PRE_MED_DAYS // 2:
                med = statistics.median(tv[max(0, i - PRE_MED_DAYS):i]) or 1
                if tv[i] >= X_MIN * med:
                    last_big = i
                    big_max = max(big_max, tv[i])
                    if (first is None and tv[i] > run_max and p[5] > p[2] and tv[i] >= MIN_VALUE
                            and float(p[5]) >= float(pl[i - 1][5]) * (1 + MIN_EVENT_CHG / 100)):
                        first = (i, tv[i] / med)
            run_max = max(run_max, tv[i])
        if first is None:
            continue
        i, x = first
        ev = pl[i]
        base = float(pl[i - 1][5])                      # 신기록 전날 종가
        i_peak = max(range(i, len(pl)), key=lambda k: pl[k][3])
        peak, close = float(pl[i_peak][3]), float(pl[-1][5])
        kept = (close - base) / (peak - base) if peak > base else 0.0
        dry = (sum(tv[-5:]) / 5) / big_max if big_max else 1.0
        rest = len(pl) - 1 - last_big
        if close < base or kept < KEEP_MIN:
            stage = "무너짐"
        elif rest < NEW_DAYS:
            stage = "신규"
        elif dry <= DRY_MAX:
            stage = "숨고르기"
        else:
            stage = "진행 중"
        items.append({
            "code": code, "name": names.get(code, code),
            "event_date": ev[1].isoformat(), "event_change_pct": round((float(ev[5]) / base - 1) * 100, 1),
            "event_value": round(tv[i]), "event_x": round(x),
            "peak_date": pl[i_peak][1].isoformat(), "rise_pct": round((peak / base - 1) * 100, 1),
            "close_price": round(close), "change_pct": round((close / float(pl[-2][5]) - 1) * 100, 2),
            "off_peak_pct": round((close / peak - 1) * 100, 1), "kept_pct": round(kept * 100),
            "dry_pct": round(dry * 100), "rest_days": rest, "days_since": len(pl) - 1 - i,
            "stage": stage, "stop_price": round(base),
        })
    order = {"숨고르기": 0, "신규": 1, "진행 중": 2, "무너짐": 3}
    items.sort(key=lambda x: x["event_date"], reverse=True)   # 단계 안에서는 최근 신기록부터
    items.sort(key=lambda x: order[x["stage"]])
    return {"trading_date": latest.isoformat(), "window_start": win_start.isoformat(), "items": items}
