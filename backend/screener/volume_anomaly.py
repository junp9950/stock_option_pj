"""거래량 비정상 감지 기반 세력 포착 스크리너.

달빛속삭임 방법론:
- 평균 대비 비정상 거래량 양봉일 = 세력 개입(흡수) 신호
- 이벤트 구간 VWAP = 세력 평단가(코어라인)
- 현재가가 VWAP 부근 + 거래량 수렴 + 몸통 하단 유지 = 매수 구간
결과는 0~100 종합 점수로 요약한다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, Stock


_MIN_VOL_MULTIPLIER = 3.0
_MIN_TRADING_VALUE = 5_000_000_000
_MIN_FLOAT_RATIO = 0.03
_MIN_MARKET_CAP = 300_000_000_000
_LOOKBACK_DAYS = 40  # 이벤트 경과 상한(일). 오래된 이벤트는 눌림이 아니라 추세 하락이 섞임
_MAX_VWAP_GAP = 6.0  # VWAP 대비 +6% 초과 = 이미 오른 종목
_MIN_CLOSE_STRENGTH = 0.6  # 폭발일 종가가 고저 범위 상위 60% 이상 (윗꼬리 긴 캔들 제외)
_MAX_NEXT_DAY_DROP = -4.0  # 폭발 다음날 등락률이 이 이하면 분배로 판단
_MAX_REBOUND = 6.0  # 이벤트 이후 종가 저점 대비 회복률 상한(%)


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

    if top_n_by_value:
        value_scores: dict[str, float] = {}
        for code, price_list in by_code.items():
            vals = [p.trading_value for p in price_list[-5:] if p.trading_value]
            value_scores[code] = sum(vals) / len(vals) if vals else 0.0
        top_codes = set(sorted(value_scores, key=lambda c: -value_scores[c])[:top_n_by_value])
        by_code = {c: v for c, v in by_code.items() if c in top_codes}

    cutoff = date.today() - timedelta(days=_LOOKBACK_DAYS)
    results = []

    for code, price_list in by_code.items():
        if len(price_list) < 20:
            continue
        mcap = meta[code]["market_cap"] or meta[code]["shares_outstanding"] * price_list[-1].close_price
        if not top_n_by_value and mcap < _MIN_MARKET_CAP:
            continue

        shares = meta[code]["shares_outstanding"]
        events = _find_events(price_list, cutoff, shares)
        if not events:
            continue

        latest_event = max(events, key=lambda e: e["date"])
        event_idx = latest_event["idx"]
        event_day = price_list[event_idx]
        # 폭발 다음날 큰 음봉 = 분배 신호
        after = price_list[event_idx + 1: event_idx + 2]
        if after and float(after[0].change_pct or 0) <= _MAX_NEXT_DAY_DROP:
            continue

        # 세력 평단 = 폭발일 하루의 실제 체결 평균가 (이후 하락일이 섞이지 않게)
        vwap = (
            event_day.trading_value / event_day.volume
            if event_day.volume and event_day.trading_value
            else event_day.close_price
        )
        event_close = event_day.close_price
        stop_price = min(event_day.open_price, event_day.close_price)  # 폭발일 몸통 하단

        current = price_list[-1].close_price
        vwap_gap = (current - vwap) / vwap * 100 if vwap > 0 else 0.0
        retrace_pct = (event_close - current) / event_close * 100 if event_close > 0 else 0.0

        # 손절선 이탈(매집 무효) 또는 VWAP 대비 과열은 제외. 이벤트 종가 위 횡보는 허용
        if current < stop_price or vwap_gap > _MAX_VWAP_GAP:
            continue

        # 이미 반등 중: 3일 연속 상승이거나 이벤트 이후 종가 저점 대비 크게 회복
        recent3 = price_list[-3:]
        if len(recent3) == 3 and all(float(p.change_pct or 0) > 0 for p in recent3):
            continue
        post_low = min(p.close_price for p in price_list[event_idx + 1:] or [price_list[-1]])
        if post_low > 0 and (current - post_low) / post_low * 100 > _MAX_REBOUND:
            continue

        event_vol = event_day.volume
        recent_vols = [p.volume for p in price_list[-5:] if p.volume]
        avg_recent = sum(recent_vols) / len(recent_vols) if recent_vols else 0
        vol_ratio = avg_recent / event_vol if event_vol > 0 else 1.0

        days_since = (date.today() - latest_event["date"]).days
        score, reasons = _calc_score(
            vwap_gap=vwap_gap,
            vol_ratio=vol_ratio,
            retrace_pct=retrace_pct,
            vol_multiplier=latest_event["vol_multiplier"],
            days_since=days_since,
        )

        results.append({
            "code": code,
            "name": meta[code]["name"],
            "market": meta[code]["market"],
            "market_cap": mcap,
            "score": score,
            "grade": "강력" if score >= 75 else "관심" if score >= 60 else "관찰",
            "reasons": reasons,
            "current_price": round(current),
            "change_pct": round(float(price_list[-1].change_pct or 0), 2),
            "vwap": round(vwap),
            "vwap_gap_pct": round(vwap_gap, 1),
            "stop_price": round(stop_price),
            "event_date": str(latest_event["date"]),
            "days_since_event": days_since,
            "vol_multiplier": round(latest_event["vol_multiplier"], 1),
            "retrace_pct": round(retrace_pct, 1),
            "vol_ratio": round(vol_ratio, 2),
        })

    results.sort(key=lambda x: (-x["score"], x["days_since_event"]))
    return results


def _find_events(price_list: list, cutoff: date, shares: float) -> list[dict]:
    events = []
    for i, p in enumerate(price_list):
        if p.trading_date < cutoff or i < 10:
            continue
        if not p.volume or not p.trading_value:
            continue
        # 흡수 조건: 양봉 + 등락률 양수 (음봉 폭발은 분배/털기)
        if p.close_price <= p.open_price:
            continue
        change = float(p.change_pct or 0)
        if change <= 0:
            continue
        day_range = p.high_price - p.low_price
        if day_range > 0 and (p.close_price - p.low_price) / day_range < _MIN_CLOSE_STRENGTH:
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
    vwap_gap: float,
    vol_ratio: float,
    retrace_pct: float,
    vol_multiplier: float,
    days_since: int,
) -> tuple[int, list[str]]:
    """0~100점. VWAP 근접 35 + 거래량 수렴 25 + 눌림 깊이 20 + 이벤트 강도 10 + 신선도 10."""
    reasons: list[str] = []
    score = 0

    if -5 <= vwap_gap <= 3:
        score += 35
        reasons.append("VWAP 부근")
    elif 3 < vwap_gap <= 6:
        score += 25
    elif vwap_gap < -5:
        score += 20
        reasons.append("VWAP 하회")
    else:
        score += 10

    if vol_ratio <= 0.2:
        score += 25
        reasons.append("거래량 급감")
    elif vol_ratio <= 0.35:
        score += 18
        reasons.append("거래량 수렴")
    elif vol_ratio <= 0.5:
        score += 8

    if 3 <= retrace_pct <= 15:
        score += 20
        reasons.append(f"구라하락 -{retrace_pct:.0f}%")
    elif retrace_pct > 15:
        score += 10
    else:
        score += 8

    if vol_multiplier >= 5:
        score += 10
        reasons.append(f"거래량 {vol_multiplier:.0f}배")
    elif vol_multiplier >= 3:
        score += 6

    if days_since <= 10:
        score += 10
    elif days_since <= 20:
        score += 7
    elif days_since <= 40:
        score += 4

    return score, reasons
