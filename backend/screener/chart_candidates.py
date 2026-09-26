"""차트 후보: 원하는 모양(불플래그 · 상승삼각형 · 기준봉 눌림)인 종목을 섹터 강도 순으로.

점수(0~100) = 종목의 대표 테마(주가가 가장 비슷하게 움직인 테마)의 최근 20일 수익률 백분위.
3년 백테스트: 강한 대표 테마(80+) + 차트 후보는 탐색·검증 두 기간 모두 같은 날 아무 종목보다 20일 +1.4~1.6%p
(상승삼각형이 가장 일관). 모양은 점수에 섞지 않고 목록에 올라오는 조건과 태그로만 쓴다. 점수는 '먼저 볼 순서'이다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db.models import SpotDailyPrice, Stock
from backend.screener.bull_flag import detect_bull_flag
from backend.screener.market_regime import current_regime

MIN_AVG_TRADING_VALUE = 5_000_000_000
RET_WIN = 20
STRONG_SECTOR = 80
CORR_WIN = 60        # 대표 테마를 고를 때 보는 기간 (거래일)
CORR_MIN_DAYS = 30
# 손절 깊이 구간. 3년 백테스트(종가 매수, 20일): 3~6%가 탐색·검증 모두 최고, 3% 미만은 흔들림에 거의 다 털려 모두 마이너스
STOP_GOOD = (3.0, 6.0)
STOP_DEEP = 10.0


def _stop_zone(dist: float | None) -> str | None:
    if dist is None:
        return None
    if dist < STOP_GOOD[0]:
        return "얕음"
    if dist < STOP_GOOD[1]:
        return "적정"
    return "보통" if dist < STOP_DEEP else "깊음"

# 상승삼각형 (와이씨형): 큰 상승 뒤 저점은 올라가고 위는 막힌 수렴
TRI_RISE_MIN = 0.40
TRI_WIN = 15
TRI_TOUCH_BAND = 0.03
TRI_MIN_TOUCHES = 3
TRI_LOW_RISE = 0.03
TRI_SHRINK = 0.75
TRI_NEAR_RES = 0.10


def detect_triangle(pl: list) -> dict | None:
    t = len(pl) - 1
    if t < 70:
        return None
    w = pl[t - TRI_WIN + 1: t + 1]
    body_top = [max(p.open_price, p.close_price) for p in w]
    res = max(body_top)
    touches = sum(1 for b in body_top if b >= res * (1 - TRI_TOUCH_BAND))
    if touches < TRI_MIN_TOUCHES:
        return None
    half = TRI_WIN // 2
    lo1, lo2 = min(p.low_price for p in w[:half]), min(p.low_price for p in w[half:])
    if lo1 <= 0 or lo2 < lo1 * (1 + TRI_LOW_RISE):
        return None
    r1 = max(p.high_price for p in w[:half]) - lo1
    r2 = max(p.high_price for p in w[half:]) - lo2
    if r1 <= 0 or r2 > TRI_SHRINK * r1:
        return None
    close = pl[t].close_price
    if not (res * (1 - TRI_NEAR_RES) <= close <= res * 1.02):
        return None
    base_low = min(p.low_price for p in pl[t - 60: t - TRI_WIN + 1])
    peak = max(p.high_price for p in pl[t - 60: t + 1])
    if base_low <= 0 or peak / base_low - 1 < TRI_RISE_MIN:
        return None
    return {"resistance": round(res), "support": round(lo2), "touches": touches,
            "rise_pct": round((peak / base_low - 1) * 100), "shrink": round(r2 / r1, 2)}


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < CORR_MIN_DAYS:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


def _sector_scores(db: Session, by_code: dict[str, list]) -> dict[str, tuple[int, str, float]]:
    """종목 → (섹터 점수 0~100, 대표 테마명, 대표 테마 20일 수익률 %).

    대표 테마 = 네이버에 등록된 여러 테마 중 최근 60일 일간 수익률이 그 종목과 가장 비슷하게 움직인 테마.
    '가장 강한 테마'로 고르면 곁가지 테마(예: 포스코인터내셔널의 리비안)가 뽑히고 테마가 많은 종목일수록 점수가 부풀려짐.
    테마 수익률은 모두 그 종목 자신을 뺀 나머지 종목 평균이다.
    """
    members: dict[int, set] = defaultdict(set)
    names: dict[int, str] = {}
    themes_of: dict[str, set] = defaultdict(set)
    for sid, name, code in db.execute(text(
        "select s.id, s.sector_name, ss.stock_code from sector_stocks ss join sectors s on s.id = ss.sector_id where s.is_active"
    )):
        members[sid].add(code)
        names[sid] = name
        themes_of[code].add(sid)

    all_dates = sorted({p.trading_date for pl in by_code.values() for p in pl[-(CORR_WIN + 1):]})[-(CORR_WIN + 1):]
    window = all_dates[1:]
    daily: dict[str, dict] = {}
    ret20: dict[str, float] = {}
    for code, pl in by_code.items():
        close = {p.trading_date: p.close_price for p in pl}
        daily[code] = {d: close[d] / close[prev] - 1 for prev, d in zip(all_dates, all_dates[1:])
                       if close.get(prev) and close.get(d)}
        if len(pl) > RET_WIN and pl[-1].trading_date == all_dates[-1] and pl[-1 - RET_WIN].close_price:
            ret20[code] = pl[-1].close_price / pl[-1 - RET_WIN].close_price - 1

    theme_day: dict[int, dict] = {}
    theme_r20: dict[int, tuple[float, int]] = {}
    for sid, mem in members.items():
        agg = {d: [0.0, 0] for d in window}
        for c in mem:
            for d, r in daily.get(c, {}).items():
                agg[d][0] += r
                agg[d][1] += 1
        theme_day[sid] = agg
        vals = [ret20[c] for c in mem if c in ret20]
        if len(vals) >= 3:
            theme_r20[sid] = (sum(vals), len(vals))
    ranked = sorted(s / n for s, n in theme_r20.values())
    if not ranked:
        return {}

    def pct(v: float) -> float:
        lo, hi = 0, len(ranked)
        while lo < hi:
            mid = (lo + hi) // 2
            if ranked[mid] < v:
                lo = mid + 1
            else:
                hi = mid
        return lo / len(ranked)

    out = {}
    for code, sids in themes_of.items():
        own_daily = daily.get(code, {})
        best = None
        for sid in sids:
            if sid not in theme_r20:
                continue
            xs, ys = [], []
            for d, (s, n) in theme_day[sid].items():
                r = own_daily.get(d)
                if r is None or n < 3:
                    continue
                xs.append(r)
                ys.append((s - r) / (n - 1))
            c = _corr(xs, ys)
            if c is not None and (best is None or c > best[0]):
                best = (c, sid)
        if best is None:
            continue
        sid = best[1]
        s, n = theme_r20[sid]
        own = ret20.get(code)
        if own is not None and n > 3:
            s, n = s - own, n - 1
        mean = s / n
        out[code] = (round(pct(mean) * 100), names[sid], round(mean * 100, 1))
    return out


def scan(db: Session) -> dict:
    latest = db.scalar(select(SpotDailyPrice.trading_date).order_by(SpotDailyPrice.trading_date.desc()).limit(1))
    if latest is None:
        return {"trading_date": None, "market": None, "items": []}
    rows = db.execute(
        select(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date, SpotDailyPrice.open_price,
               SpotDailyPrice.high_price, SpotDailyPrice.low_price, SpotDailyPrice.close_price,
               SpotDailyPrice.volume, SpotDailyPrice.trading_value, SpotDailyPrice.change_pct)
        .where(SpotDailyPrice.trading_date >= latest - timedelta(days=160))
        .order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date)
    ).all()
    by_code: dict[str, list] = defaultdict(list)
    for r in rows:
        by_code[r.stock_code].append(r)
    stocks = {s.code: s for s in db.scalars(select(Stock))}

    sectors = _sector_scores(db, by_code)

    found: dict[str, list[dict]] = defaultdict(list)
    for code, pl in by_code.items():
        if pl[-1].trading_date != latest or code not in stocks:
            continue
        tv = [p.trading_value for p in pl[-5:] if p.trading_value]
        if not tv or sum(tv) / len(tv) < MIN_AVG_TRADING_VALUE:
            continue
        flag = detect_bull_flag(pl)
        if flag:
            found[code].append({"type": "불플래그", "grade": flag["grade"], "stop": flag["flag_low"],
                                "detail": f"깃대 +{flag['pole_gain_pct']:.0f}% · 깃발 {flag['flag_days']}일 · 되돌림 {flag['retrace_pct']:.0f}%"
                                          + (" · 돌파" if flag["status"] == "돌파" else "")})
        tri = detect_triangle(pl)
        if tri:
            found[code].append({"type": "상승삼각형", "grade": None, "stop": tri["support"],
                                "detail": f"상승 +{tri['rise_pct']}% · 저항 {tri['resistance']:,}원 {tri['touches']}회 터치"})

    # 기준봉 눌림은 기존 세력 신호 스캐너 결과를 그대로 쓴다
    from backend.screener.volume_anomaly import scan as scan_signal  # noqa: PLC0415
    for sig in scan_signal(db):
        found[sig["code"]].append({"type": "기준봉 눌림", "grade": None, "stop": sig["stop_price"],
                                   "detail": f"{sig['event_date'][5:]} +{sig['event_change_pct']:.0f}% · 거래량 {sig['vol_multiplier']:.0f}배 · {sig['days_since_event']}일째"})

    items = []
    for code, patterns in found.items():
        pl = by_code.get(code)
        s = stocks.get(code)
        if not pl or s is None or pl[-1].trading_date != latest:
            continue
        close = pl[-1].close_price
        stops = [p["stop"] for p in patterns if p["stop"] and p["stop"] < close]
        stop = max(stops) if stops else None  # 여러 모양이면 가장 가까운 손절선
        sec = sectors.get(code)
        items.append({
            "code": code, "name": s.name, "market": s.market,
            "market_cap": s.market_cap or (s.shares_outstanding or 0) * close,
            "close_price": round(close), "change_pct": round(float(pl[-1].change_pct or 0), 2),
            "patterns": patterns,
            "sector_score": sec[0] if sec else None,
            "sector_name": sec[1] if sec else None,
            "sector_ret20": sec[2] if sec else None,
            "strong_sector": bool(sec and sec[0] >= STRONG_SECTOR),
            "stop_price": round(stop) if stop else None,
            "stop_dist_pct": round((close - stop) / close * 100, 1) if stop else None,
            "stop_zone": _stop_zone((close - stop) / close * 100 if stop else None),
        })
        # 백테스트에서 두 기간 모두 가장 좋았던 조합: 강한 대표 테마 + 손절 3~6%
        items[-1]["best_combo"] = items[-1]["strong_sector"] and items[-1]["stop_zone"] == "적정"
    items.sort(key=lambda x: (x["sector_score"] is None, -(x["sector_score"] or 0), -len(x["patterns"])))
    return {"trading_date": latest.isoformat(), "market": current_regime(db), "items": items}

