"""차트 후보: 원하는 모양(불플래그 · 상승삼각형 · 기준봉 눌림 · 장대음봉도지 · VCP)인 종목을 섹터 강도 순으로.

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

from backend.db.models import Sector, SectorStock, SpotDailyPrice, Stock
from backend.screener.bull_flag import detect_bull_flag
from backend.screener.market_regime import current_regime

MIN_AVG_TRADING_VALUE = 500_000_000   # 5일 평균 거래대금 5억: 거래가 사실상 없는 종목만 뺀다
BREAKOUT_KEEP = 0                     # 돌파 후 며칠까지 목록에 남길지 (0 = 이미 돌파해 출발한 종목은 제외)
MAX_TODAY_CHANGE = 7.0                # 오늘 이만큼 이상 오른 종목은 이미 쏜 것으로 보고 제외
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
TRI_POLE_DAYS = 15     # 깃대는 15거래일 안의 급등 (두 달 걸친 완만한 반등은 깃대가 아니다)
TRI_NEAR_HI90 = 0.75   # 지금 가격이 90일 고점의 75% 이상 (폭락 뒤 바닥 반등 제외)


def detect_triangle(pl: list, market: dict | None = None) -> dict | None:
    """market: 날짜 → 전종목 동일가중 지수. 주면 깃대 상승을 시장 대비로 잰다 (7/30 폭락 뒤 시장 전체 반등을 깃대로 오인하지 않게)."""
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
    # 깃대: 삼각형 시작 전 저점에서 15거래일 안에 '그 뒤' 고점까지 +40% 이상 (시장 대비). 예전엔 60일 안 아무 고점/저점으로
    # 재서 넥스트칩처럼 빠지기만 한 종목, 미래에셋벤처투자처럼 두 달 완만한 반등, 7/30 폭락 뒤 시장 전체 반등이 다 깃대로 잡혔다.
    w0 = t - TRI_WIN + 1
    if t < 90 or close < TRI_NEAR_HI90 * max(p.high_price for p in pl[t - 90: t + 1]):
        return None
    best = None
    for i in range(t - 60, w0):
        if pl[i].low_price <= 0:
            continue
        top = max(range(i + 1, min(i + TRI_POLE_DAYS + 1, t + 1)), key=lambda k: pl[k].high_price)
        gain = pl[top].high_price / pl[i].low_price
        if market:
            m0, m1 = market.get(pl[i].trading_date), market.get(pl[top].trading_date)
            if m0 and m1:
                gain /= m1 / m0
        if gain - 1 >= TRI_RISE_MIN and (best is None or gain > best[0]):
            best = (gain, i, top)
    if best is None:
        return None
    gain, i_low, i_top = best
    base_low, peak = pl[i_low].low_price, pl[i_top].high_price
    if lo1 < base_low + 0.5 * (peak - base_low):   # 삼각형은 깃대 위쪽 절반에
        return None
    return {"resistance": round(res), "support": round(lo2), "touches": touches,
            "rise_pct": round((gain - 1) * 100), "shrink": round(r2 / r1, 2)}


VCP_SEG = 15     # 수축 구간 길이(거래일) — 10일보다 15일이 3년 확인에서 일관됨


def _vcp_core(pl: list) -> dict | None:
    """마지막 날 기준 VCP 성립 여부: 상승 추세 + 최근 45일을 15일씩 세 구간으로 나눴을 때
    눌림 폭(구간 고가 대비 저가)이 차례로 줄고 마지막 폭 12% 이하, 첫 폭이 마지막의 1.8배 이상, 거래대금도 줄어듦."""
    if len(pl) < 200:
        return None
    c = [p.close_price for p in pl]
    h = [p.high_price for p in pl]
    lo = [p.low_price for p in pl]
    v = [float(p.trading_value or 0) for p in pl]
    close = c[-1]
    ma50, ma150 = sum(c[-50:]) / 50, sum(c[-150:]) / 150
    hi, low = max(h[-250:]), min(x for x in lo[-250:] if x)
    if not (close > ma50 > ma150 and close >= hi * 0.8 and close >= low * 1.3):
        return None
    segs = []
    n = len(pl)
    for k in (2, 1, 0):
        a, b = n - VCP_SEG * (k + 1), n - VCP_SEG * k
        hh, ll = max(h[a:b]), min(lo[a:b])
        if not hh or not ll:
            return None
        segs.append(((1 - ll / hh) * 100, sum(v[a:b]) / VCP_SEG))
    (r1, v1), (r2, v2), (r3, v3) = segs
    if not (r1 > r2 > r3 and r3 <= 12 and r1 >= r3 * 1.8 and v3 < v1):
        return None
    return {"r": [round(r1), round(r2), round(r3)], "v": [v1, v2, v3], "low": min(lo[-VCP_SEG:])}


def detect_vcp(pl: list) -> dict | None:
    """VCP(변동성 축소 패턴, 사용자 정의 "박스 돌파하기 위해 거래량 죽이면서 변동성 압축하는 그림") — 2026-10-05.
    매수선 = 직전 15일 고가. 상태: 매수선 -5~0% 안(돌파 대기) 또는 어제까지 VCP였고 오늘 매수선 0~+5% 돌파.
    3년(상승·횡보장, 같은 날 전 종목 평균 대비 20일): 성립 275건 +2.93%p(중간 +0.3, 이김 51%), 매수선 -5% 안 +3.29,
    뜨는 섹터 + 매수선 -5% 안 60건 +7.19%p(중간 +3.3, 이김 60%), 돌파일 +2.77(뜨는 섹터 +4.59). 기준 전 종목 +0.32.
    손절 = 마지막 수축 구간 저점."""
    if len(pl) < 201:
        return None
    close = pl[-1].close_price
    pivot = max(p.high_price for p in pl[-VCP_SEG - 1:-1])
    core = _vcp_core(pl)
    if core and pivot * 0.95 <= close <= pivot:
        return {**core, "pivot": pivot, "state": "돌파 대기", "pos": round((close / pivot - 1) * 100, 1)}
    if pivot < close <= pivot * 1.05:
        y = _vcp_core(pl[:-1])
        if y:
            return {**y, "pivot": pivot, "state": "돌파", "pos": round((close / pivot - 1) * 100, 1)}
    return None


def detect_big_doji(pl: list) -> dict | None:
    """장대음봉도지: 그저께 장대양봉(몸통 +7%↑, 몸통이 변동폭 60%↑, 거래량 20일 평균 2~15배, 종가가 60일 고점 98%↑)
    다음 어제·오늘 연속 도지(몸통 ±3% 이내, 종가가 양봉 몸통 절반 위).
    최근 9개월 확인(185건, 두 번째 도지 종가 매수): 5일 평균 +4.5% · 중간값 +2.2% · 플러스 55%,
    도지 1개(5일 중간값 -0.1%)나 3개(+0.5%)보다 나았다. 20일 중간값은 마이너스라 짧게 보고 양봉 시가 이탈 시 손절."""
    if len(pl) < 63:
        return None
    big = pl[-3]
    if not big.open_price or not big.close_price or not big.volume:
        return None
    body = (big.close_price - big.open_price) / big.open_price * 100
    rng = big.high_price - big.low_price
    if body < 7 or rng <= 0 or (big.close_price - big.open_price) / rng < 0.6:
        return None
    vols = [x.volume for x in pl[-23:-3] if x.volume]
    if not vols:
        return None
    vol_x = big.volume / (sum(vols) / len(vols))
    if not 2 <= vol_x <= 15:   # 30배 넘게 터진 날은 재료 한 번에 튄 경우가 많아 제외
        return None
    if big.close_price < max(x.high_price for x in pl[-63:-3]) * 0.98:
        return None            # 앞 매물대(60일 고점)를 넘은 장대양봉만
    mid = (big.open_price + big.close_price) / 2
    for dj in pl[-2:]:
        if not dj.open_price or abs(dj.close_price - dj.open_price) / dj.open_price * 100 > 3 or dj.close_price < mid:
            return None
    return {"body_pct": round(body, 1), "vol_x": round(vol_x, 1),
            "vs_big": round((pl[-1].close_price / big.close_price - 1) * 100, 1),
            "big_date": big.trading_date.isoformat(), "stop": big.open_price}


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
        .where(SpotDailyPrice.trading_date >= latest - timedelta(days=380))   # VCP 추세 확인에 250거래일
        .order_by(SpotDailyPrice.stock_code, SpotDailyPrice.trading_date)
    ).all()
    by_code: dict[str, list] = defaultdict(list)
    for r in rows:
        by_code[r.stock_code].append(r)
    stocks = {s.code: s for s in db.scalars(select(Stock))}

    sectors = _sector_scores(db, by_code)

    # 전종목 동일가중 지수 (상승삼각형 깃대를 시장 대비로 재는 데 쓴다)
    day_chg: dict = defaultdict(list)
    for pl in by_code.values():
        for p in pl:
            if p.change_pct is not None and abs(p.change_pct) < 30:
                day_chg[p.trading_date].append(float(p.change_pct))
    market, level = {}, 100.0
    for d in sorted(day_chg):
        level *= 1 + sum(day_chg[d]) / len(day_chg[d]) / 100
        market[d] = level

    found: dict[str, list[dict]] = defaultdict(list)
    for code, pl in by_code.items():
        if pl[-1].trading_date != latest or code not in stocks:
            continue
        if float(pl[-1].change_pct or 0) >= MAX_TODAY_CHANGE:
            continue  # 이미 쏜 종목 (추격 매수 구간)
        tv = [p.trading_value for p in pl[-5:] if p.trading_value]
        if not tv or sum(tv) / len(tv) < MIN_AVG_TRADING_VALUE:
            continue
        flag, after = detect_bull_flag(pl), 0
        if not flag:   # 돌파 후 BREAKOUT_KEEP일까지: 며칠 전에는 깃발이었고 오늘 종가가 깃대 고점 위
            for k in range(1, BREAKOUT_KEEP + 1):
                f = detect_bull_flag(pl[:-k])
                if f and pl[-1].close_price > f["pole_top"]:
                    flag, after = f, k
                    break
        if flag:
            state = f" · 돌파 후 {after}일" if after else (" · 돌파" if flag["status"] == "돌파" else "")
            found[code].append({"type": "불플래그", "grade": flag["grade"], "stop": flag["flag_low"],
                                "detail": f"깃대 +{flag['pole_gain_pct']:.0f}% · 깃발 {flag['flag_days']}일 · 되돌림 {flag['retrace_pct']:.0f}%" + state})
        tri, after = detect_triangle(pl, market), 0
        if not tri:
            for k in range(1, BREAKOUT_KEEP + 1):
                tr = detect_triangle(pl[:-k], market)
                if tr and pl[-1].close_price > tr["resistance"]:
                    tri, after = tr, k
                    break
        if tri:
            found[code].append({"type": "상승삼각형", "grade": None, "stop": tri["support"],
                                "detail": f"깃대 +{tri['rise_pct']}%(시장 대비) · 저항 {tri['resistance']:,}원 {tri['touches']}회 터치"
                                          + (f" · 돌파 후 {after}일" if after else "")})
        vc = detect_vcp(pl)
        if vc:
            found[code].append({"type": "VCP", "grade": None, "stop": vc["low"],
                                "detail": f"눌림 {vc['r'][0]}%→{vc['r'][1]}%→{vc['r'][2]}% · 거래 {vc['v'][0] / 1e8:.0f}→{vc['v'][2] / 1e8:.0f}억 · "
                                          f"매수선 {vc['pivot']:,.0f}원 {vc['pos']:+.1f}% ({vc['state']})"})
        dj = detect_big_doji(pl)
        if dj:
            found[code].append({"type": "장대음봉도지", "grade": None, "stop": dj["stop"],
                                "detail": f"{dj['big_date'][5:]} 장대양봉 +{dj['body_pct']:.0f}% · 거래량 {dj['vol_x']:.0f}배 · 도지 2개 · 양봉 종가 대비 {dj['vs_big']:+.1f}%"})

    # 기준봉 눌림은 기존 세력 신호 스캐너 결과를 그대로 쓴다
    from backend.screener.volume_anomaly import scan as scan_signal  # noqa: PLC0415
    for sig in scan_signal(db):
        found[sig["code"]].append({"type": "기준봉 눌림", "grade": None, "stop": sig["stop_price"],
                                   "detail": f"{sig['event_date'][5:]} +{sig['event_change_pct']:.0f}% · 거래량 {sig['vol_multiplier']:.0f}배 · {sig['days_since_event']}일째"})

    from backend.services.marcap_caps import caps as marcap_caps  # noqa: PLC0415
    marcap = marcap_caps()   # stocks에 시총·주식 수가 없는 종목(유니버스 밖)을 채운다
    from backend.services.industry_map import industries  # noqa: PLC0415
    from backend.services.earnings_screen import read_snapshot  # noqa: PLC0415
    industry = industries()
    snap = read_snapshot()
    earn_up = set(snap.get("up_codes") or [r["code"] for r in snap.get("rows", [])])   # 실적 개선(영업이익 +30%·매출 +10%)
    themes: dict[str, list[str]] = defaultdict(list)   # 업종 필터에서 테마 이름으로도 찾을 수 있게
    for code, name in db.execute(select(SectorStock.stock_code, Sector.sector_name)
                                 .join(Sector, Sector.id == SectorStock.sector_id).where(Sector.is_active)):
        themes[code].append(name)
    items = []
    for code, patterns in found.items():
        pl = by_code.get(code)
        s = stocks.get(code)
        if not pl or s is None or pl[-1].trading_date != latest:
            continue
        if float(pl[-1].change_pct or 0) >= MAX_TODAY_CHANGE:
            continue  # 기준봉 눌림 경로로 들어온 종목도 오늘 이미 쏜 건 제외
        close = pl[-1].close_price
        stops = [p["stop"] for p in patterns if p["stop"] and p["stop"] < close]
        stop = max(stops) if stops else None  # 여러 모양이면 가장 가까운 손절선
        sec = sectors.get(code)
        cap = s.market_cap or (s.shares_outstanding or 0) * close or marcap.get(code) or 0
        tv_today = float(pl[-1].trading_value or 0)
        items.append({
            "code": code, "name": s.name, "market": s.market,
            "market_cap": cap,
            "trading_value": round(tv_today),
            "turnover_pct": round(tv_today / cap * 100, 2) if cap else None,
            "industry": industry.get(code),
            "earn_up": code in earn_up,
            # 20일선 이격도: 3년 확인 +20~30% 구간부터 20일 뒤 시장 대비 마이너스, +30%↑는 절반 넘게 -15% 이상 하락
            "gap20_pct": round((close / (sum(p.close_price for p in pl[-20:]) / 20) - 1) * 100, 1),
            "themes": themes.get(code, []),
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
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    fl = flags_get([x["code"] for x in items])
    for x in items:
        x["flags"] = fl.get(x["code"], {}).get("flags", [])
    return {"trading_date": latest.isoformat(), "market": current_regime(db), "items": items}

