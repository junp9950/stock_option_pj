"""거래량 비정상 감지 기반 세력 포착 스크리너.

달빛속삭임 방법론:
- 평균 대비 비정상 거래량 양봉일 = 세력 개입(흡수) 신호
- 이벤트 구간 VWAP = 세력 평단가(코어라인)
- 현재가가 VWAP 부근 + 거래량 수렴 + 몸통 하단 유지 = 매수 구간
결과는 0~100 종합 점수로 요약한다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, Stock


_MIN_VOL_MULTIPLIER = 3.0
_MIN_TRADING_VALUE = 5_000_000_000
_MIN_FLOAT_RATIO = 0.03
_MIN_AVG_TRADING_VALUE = 5_000_000_000  # 최근 5일 평균 거래대금 50억 미만은 유동성 부족
_LOOKBACK_DAYS = 40  # 이벤트 경과 상한(일). 오래된 이벤트는 눌림이 아니라 추세 하락이 섞임
_MAX_VWAP_GAP = 6.0  # VWAP 대비 +6% 초과 = 이미 오른 종목
_MIN_CLOSE_STRENGTH = 0.6  # 폭발일 종가가 고저 범위 상위 60% 이상 (윗꼬리 긴 캔들 제외)
_MAX_NEXT_DAY_DROP = -4.0  # 폭발 다음날 등락률이 이 이하면 분배로 판단
_DUMP_PCT = 8.0  # 시장 대비 이 % 이상 급락한 날을 급락일로 집계
_ROUND_TRIP = 0.90  # 이벤트 사이 종가가 이전 이벤트 종가의 90% 아래로 내려가면 되돌림(왕복)
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

    market_mult, market_chg = _market_stats(by_code)

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

        recent_tv = [p.trading_value for p in price_list[-5:] if p.trading_value]
        avg_tv = sum(recent_tv) / len(recent_tv) if recent_tv else 0.0
        if avg_tv < _MIN_AVG_TRADING_VALUE:
            continue

        shares = meta[code]["shares_outstanding"]
        events = _find_events(price_list, cutoff, shares, market_mult)
        if not events:
            continue

        latest_event = max(events, key=lambda e: e["date"])
        event_idx = latest_event["idx"]
        event_day = price_list[event_idx]
        bars_since = len(price_list) - 1 - event_idx
        if bars_since < 2:  # 이벤트 직후 1일 이내는 아직 눌림이 아님
            continue
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
        ev_sorted = sorted(events, key=lambda e: e["idx"])
        round_trips = 0
        for a, b in zip(ev_sorted, ev_sorted[1:]):
            seg = price_list[a["idx"] + 1: b["idx"]]
            if seg and min(x.close_price for x in seg) < price_list[a["idx"]].close_price * _ROUND_TRIP:
                round_trips += 1
        dump_days = sum(
            1 for p in price_list
            if p.trading_date >= cutoff
            and float(p.change_pct or 0) - market_chg.get(p.trading_date, 0.0) <= -_DUMP_PCT
        )
        # 손절선 이격도: 눌림 저점이 손절선에서 얼마나 떨어져 버텼는지 (백테스트 승/패 비교로 발견한 유의 지표)
        post_event = price_list[event_idx + 1:]
        post_low = min((p.low_price for p in post_event), default=current)
        low_touch_dist = (post_low - stop_price) / stop_price * 100 if stop_price > 0 else 10.0
        last2 = price_list[-2:]
        mixed_color = (
            len(last2) == 2
            and (last2[0].close_price > last2[0].open_price) != (last2[1].close_price > last2[1].open_price)
        )

        score, reasons = _calc_score(
            round_trips=round_trips,
            dump_days=dump_days,
            bars_since=bars_since,
            vwap_gap=vwap_gap,
            vol_ratio=vol_ratio,
            retrace_pct=retrace_pct,
            vol_multiplier=latest_event["vol_multiplier"],
            low_touch_dist=low_touch_dist,
            mixed_color=mixed_color,
            pre_event_vol_trend=_pre_event_vol_trend(price_list, event_idx),
        )

        if _is_squeezing(price_list[event_idx + 1:]):
            reasons.append("변동폭 축소")

        results.append({
            "code": code,
            "name": meta[code]["name"],
            "market": meta[code]["market"],
            "market_cap": mcap,
            "avg_tv_b": round(avg_tv / 1e8),
            "score": score,
            "grade": "강력" if score >= 75 else "관심" if score >= 60 else "관찰",
            "reasons": reasons,
            "current_price": round(current),
            "change_pct": round(float(price_list[-1].change_pct or 0), 2),
            "vwap": round(vwap),
            "vwap_gap_pct": round(vwap_gap, 1),
            "stop_price": round(stop_price),
            "event_date": str(latest_event["date"]),
            "event_change_pct": round(latest_event["change_pct"], 1),
            "days_since_event": days_since,
            "vol_multiplier": round(latest_event["vol_multiplier"], 1),
            "retrace_pct": round(retrace_pct, 1),
            "vol_ratio": round(vol_ratio, 2),
        })

    results.sort(key=lambda x: (-x["score"], x["days_since_event"]))
    return results


def _find_events(price_list: list, cutoff: date, shares: float, market_mult: dict) -> list[dict]:
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

        # 시장 전체 거래량 급증일(폭락/반등장)은 배수에서 제외해 종목 고유 급증만 본다
        vol_mult = p.volume / avg_vol / max(market_mult.get(p.trading_date, 1.0), 1.0)
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


def _pre_event_vol_trend(price_list: list, idx: int) -> float:
    """이벤트 직전 5일 평균 거래량 / 그 이전 15일 평균 거래량."""
    far = [price_list[j].volume for j in range(max(0, idx - 20), max(0, idx - 5)) if price_list[j].volume]
    near = [price_list[j].volume for j in range(max(0, idx - 5), idx) if price_list[j].volume]
    if not far or not near:
        return 1.0
    return (sum(near) / len(near)) / (sum(far) / len(far))


def _is_squeezing(post: list) -> bool:
    """이벤트 이후 구간의 후반부 등락 폭이 전반부의 75% 이하로 줄었는지."""
    if len(post) < 4:
        return False
    half = len(post) // 2
    first, second = post[:half], post[half:]
    r1 = max(p.high_price for p in first) - min(p.low_price for p in first)
    r2 = max(p.high_price for p in second) - min(p.low_price for p in second)
    return r1 > 0 and r2 / r1 <= 0.75


def _market_stats(by_code: dict) -> tuple[dict, dict]:
    """날짜별 시장 거래량 배수(직전 20일 평균 대비)와 평균 등락률."""
    vol_by_date: dict = defaultdict(float)
    chg_sum: dict = defaultdict(float)
    chg_cnt: dict = defaultdict(int)
    for price_list in by_code.values():
        for p in price_list:
            vol_by_date[p.trading_date] += p.volume or 0
            chg = float(p.change_pct or 0)
            if math.isfinite(chg):  # DB에 NaN 등락률 행이 있어 평균 전체가 NaN이 되는 것 방지
                chg_sum[p.trading_date] += chg
                chg_cnt[p.trading_date] += 1
    dates = sorted(vol_by_date)
    mult: dict = {}
    for i, d in enumerate(dates):
        prev = [vol_by_date[x] for x in dates[max(0, i - 20): i]]
        base = sum(prev) / len(prev) if len(prev) >= 10 else 0
        mult[d] = vol_by_date[d] / base if base > 0 else 1.0
    chg = {d: chg_sum[d] / chg_cnt[d] for d in dates if chg_cnt[d]}
    return mult, chg


def _calc_score(
    round_trips: int,
    dump_days: int,
    bars_since: int,
    vwap_gap: float,
    vol_ratio: float,
    retrace_pct: float,
    vol_multiplier: float,
    low_touch_dist: float = 10.0,
    mixed_color: bool = False,
    pre_event_vol_trend: float = 1.0,
) -> tuple[int, list[str]]:
    """0~100점. VWAP 30 + 거래량 수렴 22 + 눌림 깊이 17 + 손절선 이격 10 + 이벤트 강도 9 + 조정 2~4일 9 + 캔들 섞임 3.
    감점: 조정 10일+, 사전 예열, 손절선 근접, 왕복, 급락."""
    reasons: list[str] = []
    score = 0

    if -5 <= vwap_gap <= 3:
        score += 30
        reasons.append("VWAP 부근")
    elif 3 < vwap_gap <= 6:
        score += 21
    elif vwap_gap < -5:
        score += 17
        reasons.append("VWAP 하회")
    else:
        score += 8

    if vol_ratio <= 0.2:
        score += 22
        reasons.append("거래량 급감")
    elif vol_ratio <= 0.35:
        score += 16
        reasons.append("거래량 수렴")
    elif vol_ratio <= 0.5:
        score += 7

    if 3 <= retrace_pct <= 15:
        score += 17
        reasons.append(f"구라하락 -{retrace_pct:.0f}%")
    elif retrace_pct > 15:
        score += 9
    else:
        score += 7

    if vol_multiplier >= 5:
        score += 9
        reasons.append(f"거래량 {vol_multiplier:.0f}배")
    elif vol_multiplier >= 3:
        score += 5

    # 조정 기간: 백테스트상 2~4일째 진입만 플러스, 5일째부터 성과가 급격히 나빠짐
    if bars_since <= 4:
        score += 9
    elif bars_since >= 10:
        score -= 8
    reasons.append(f"조정 {bars_since}일째")

    # 터지기 전 5일 거래량이 이미 크게 붙어 있었으면 소문난 재료/추격 매수 가능성
    if pre_event_vol_trend >= 2.0:
        score -= 8
        reasons.append("사전 예열")

    if round_trips >= 2:
        score -= 25
        reasons.append(f"⚠ 왕복 {round_trips}회")
    elif round_trips == 1:
        score -= 15
        reasons.append("왕복 1회")
    if dump_days >= 2:
        score -= 10
        reasons.append(f"급락 {dump_days}일")

    # 손절선 이격도: 여유 있게 버틸수록 가점, 바짝 붙으면 감점 (백테스트 승/패 비교로 발견)
    if low_touch_dist >= 8:
        score += 10
        reasons.append("손절선 여유")
    elif low_touch_dist >= 5:
        score += 5
    elif low_touch_dist < 2:
        score -= 8
        reasons.append("손절선 근접 위험")

    if mixed_color:
        score += 3

    return max(score, 0), reasons
