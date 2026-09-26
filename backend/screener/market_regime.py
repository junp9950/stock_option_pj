"""전종목 동일가중 지수로 본 시장 국면 (상승/횡보/하락).

하락 = 지수가 20일 이동평균 아래. 레이더 상단 표시와 백테스트 진입 보류가 같은 규칙을 쓴다.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, Stock


def regime_series(market_chg: dict) -> dict:
    """날짜별 평균 등락률 → 날짜별 국면. 각 날짜의 판정은 그날 장 마감까지의 정보만 쓴다."""
    dates = sorted(d for d in market_chg if math.isfinite(market_chg[d]))
    level, index = 100.0, {}
    for d in dates:
        level *= 1 + market_chg[d] / 100
        index[d] = level

    ma20: dict = {}
    out: dict = {}
    for i, d in enumerate(dates):
        window = [index[dates[j]] for j in range(max(0, i - 19), i + 1)]
        ma20[d] = sum(window) / len(window)
        ma20_5ago = ma20[dates[i - 5]] if i >= 5 else ma20[d]
        if index[d] < ma20[d]:
            state = "하락"
        elif ma20[d] > ma20_5ago:
            state = "상승"
        else:
            state = "횡보"
        out[d] = {
            "state": state,
            "vs_ma20_pct": round((index[d] / ma20[d] - 1) * 100, 2),
            "cum20_pct": round((index[d] / index[dates[max(0, i - 20)]] - 1) * 100, 2),
        }
    return out


def current_regime(db: Session) -> dict | None:
    rows = db.execute(
        select(SpotDailyPrice.trading_date, func.avg(func.coalesce(SpotDailyPrice.change_pct, 0)))
        .join(Stock, Stock.code == SpotDailyPrice.stock_code)
        .where(SpotDailyPrice.trading_date >= date.today() - timedelta(days=90))
        .where(SpotDailyPrice.change_pct != float("nan"))  # Postgres: NaN = NaN 이 참이라 NaN 행만 빠진다
        .group_by(SpotDailyPrice.trading_date)
    ).all()
    series = regime_series({d: float(avg) for d, avg in rows})
    if not series:
        return None
    last = max(series)
    return {**series[last], "as_of": last.isoformat()}
