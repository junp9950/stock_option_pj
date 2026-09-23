"""거래량 비정상 감지 기반 세력 포착 스크리너.

달빛속삭임 방법론:
- 유통주식수 대비 / 평균 대비 비정상 거래량 발생일 = 세력 개입 신호
- 해당 구간 VWAP = 세력 평단가(코어라인)
- 현재가가 코어 하단 근처 + 거래량 수렴 = 매수 구간
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, Stock


# 비정상 거래량 감지 기준
_MIN_VOL_MULTIPLIER = 3.0      # 20일 평균 거래량 대비 N배 이상
_MIN_TRADING_VALUE = 5_000_000_000  # 50억 이상
_MIN_FLOAT_RATIO = 0.03         # 발행주식수의 3% 이상 거래
_MIN_MARKET_CAP = 300_000_000_000   # 시총 3,000억 이상
_LOOKBACK_DAYS = 90             # 최대 90일 이전 이벤트까지 탐지
_EVENT_WINDOW = 3               # 이벤트 발생 후 N일을 코어 구간으로 산정


def scan(db: Session, top_n_by_value: int | None = None) -> list[dict]:
    from_date = date.today() - timedelta(days=_LOOKBACK_DAYS + 30)

    rows = db.execute(
        select(
            SpotDailyPrice.stock_code,
            SpotDailyPrice.trading_date,
            SpotDailyPrice.open_price,
            SpotDailyPrice.high_price,
            SpotDailyPrice.low_price,
            SpotDailyPrice.close_price,
            SpotDailyPrice.volume,
            SpotDailyPrice.trading_value,
            SpotDailyPrice.change_pct,
            Stock.name,
            Stock.market,
            Stock.market_cap,
            Stock.shares_outstanding,
        )
        .join(Stock, Stock.code == SpotDailyPrice.stock_code)
        .where(SpotDailyPrice.trading_date >= from_date)
        .order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date)
    ).all()

    by_code: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}

    for r in rows:
        by_code[r.stock_code].append(r)
        meta[r.stock_code] = {
            "name": r.name,
            "market": r.market,
            "market_cap": r.market_cap,
            "shares_outstanding": r.shares_outstanding or 0,
        }

    # 거래대금 상위 N 필터: 최근 5일 평균 거래대금으로 랭킹
    if top_n_by_value:
        value_scores: dict[str, float] = {}
        for code, price_list in by_code.items():
            recent = price_list[-5:]
            vals = [p.trading_value for p in recent if p.trading_value]
            value_scores[code] = sum(vals) / len(vals) if vals else 0.0
        top_codes = set(sorted(value_scores, key=lambda c: -value_scores[c])[:top_n_by_value])
        by_code = {c: v for c, v in by_code.items() if c in top_codes}

    cutoff = date.today() - timedelta(days=_LOOKBACK_DAYS)
    results = []

    for code, price_list in by_code.items():
        if len(price_list) < 20:
            continue
        # top_n 모드에서는 거래대금으로 이미 상위 종목만 선별했으므로 시총 필터 제외
        if not top_n_by_value and meta[code]["market_cap"] < _MIN_MARKET_CAP:
            continue

        shares = meta[code]["shares_outstanding"]
        events = _find_events(price_list, cutoff, shares)

        if not events:
            continue

        latest_event = max(events, key=lambda e: e["date"])
        event_idx = latest_event["idx"]
        window = price_list[event_idx: event_idx + _EVENT_WINDOW]

        total_value = sum(p.trading_value for p in window if p.trading_value)
        total_vol = sum(p.volume for p in window if p.volume)
        core_vwap = total_value / total_vol if total_vol > 0 else price_list[event_idx].close_price
        core_low = min(p.low_price for p in window)
        core_high = max(p.high_price for p in window)
        event_close = price_list[event_idx].close_price

        latest = price_list[-1]
        current_price = latest.close_price

        core_range = core_high - core_low
        position = (current_price - core_low) / core_range if core_range > 0 else 0.5

        below_core = current_price < core_low * 0.97  # 3% 여유

        event_vol = price_list[event_idx].volume
        recent_vols = [p.volume for p in price_list[-5:] if p.volume]
        avg_recent_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 0
        vol_converging = avg_recent_vol < event_vol * 0.35 if event_vol > 0 else False

        # 구라하락 감지: 이벤트 종가 대비 현재가가 3% 이상 하락 + 거래량 수렴
        # = 가격은 내려왔지만 세력은 안 팔고 있음
        retrace_pct = (event_close - current_price) / event_close * 100 if event_close > 0 else 0
        fake_drop = retrace_pct >= 3.0 and vol_converging and not below_core

        days_since = (date.today() - latest_event["date"]).days
        float_ratio = (event_vol / shares * 100) if shares > 0 else 0

        score = _calc_score(
            position=position,
            below_core=below_core,
            vol_converging=vol_converging,
            fake_drop=fake_drop,
            float_ratio=float_ratio,
            vol_multiplier=latest_event["vol_multiplier"],
            days_since=days_since,
        )

        results.append({
            "code": code,
            "name": meta[code]["name"],
            "market": meta[code]["market"],
            "market_cap": meta[code]["market_cap"],
            "current_price": round(current_price),
            "change_pct": round(float(latest.change_pct or 0), 2),
            "event_date": str(latest_event["date"]),
            "event_close": round(event_close),
            "days_since_event": days_since,
            "vol_multiplier": round(latest_event["vol_multiplier"], 1),
            "trading_value_b": round(latest_event["trading_value"] / 1e8, 0),
            "float_ratio": round(float_ratio, 1),
            "core_vwap": round(core_vwap),
            "core_low": round(core_low),
            "core_high": round(core_high),
            "position": round(position, 2),
            "retrace_pct": round(retrace_pct, 1),
            "below_core": below_core,
            "vol_converging": vol_converging,
            "fake_drop": fake_drop,
            "signal_score": score,
        })

    results.sort(key=lambda x: (-x["signal_score"], x["days_since_event"]))
    return results


def _find_events(price_list: list, cutoff: date, shares: float) -> list[dict]:
    events = []
    for i, p in enumerate(price_list):
        if p.trading_date < cutoff:
            continue
        if i < 10:
            continue
        if not p.volume or not p.trading_value:
            continue

        # 흡수 조건: 양봉 + 등락률 양수여야 세력 매집 신호
        # 음봉(하락) 거래량 폭발은 분배/털기 — 제외
        if p.close_price <= p.open_price:
            continue
        change = float(p.change_pct or 0)
        if change <= 0:
            continue

        prev_vols = [price_list[j].volume for j in range(max(0, i - 20), i) if price_list[j].volume]
        if not prev_vols:
            continue
        avg_vol = sum(prev_vols) / len(prev_vols)
        if avg_vol == 0:
            continue

        vol_mult = p.volume / avg_vol
        float_ok = (p.volume / shares >= _MIN_FLOAT_RATIO) if shares > 0 else False

        if vol_mult >= _MIN_VOL_MULTIPLIER and p.trading_value >= _MIN_TRADING_VALUE:
            if shares == 0 or float_ok or vol_mult >= 5.0:
                events.append({
                    "date": p.trading_date,
                    "idx": i,
                    "vol_multiplier": vol_mult,
                    "trading_value": p.trading_value,
                    "change_pct": change,
                })
    return events


def _calc_score(
    position: float,
    below_core: bool,
    vol_converging: bool,
    fake_drop: bool,
    float_ratio: float,
    vol_multiplier: float,
    days_since: int,
) -> int:
    score = 0
    if not below_core:
        score += 2
    if 0 <= position <= 0.35:
        score += 3  # 코어 하단 근처 = 최적 매수 구간
    elif 0.35 < position <= 0.6:
        score += 1
    if vol_converging:
        score += 2  # 거래량 수렴 = 기간조정 중
    if fake_drop:
        score += 3  # 구라하락 = 핵심 패턴 (거래량 줄며 가격 하락)
    if float_ratio >= 10:
        score += 2
    elif float_ratio >= 5:
        score += 1
    if vol_multiplier >= 5:
        score += 2
    elif vol_multiplier >= 3:
        score += 1
    if days_since <= 15:
        score += 2
    elif days_since <= 30:
        score += 1
    return score
