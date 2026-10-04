"""손절 짧은 자리 (사용자가 '맛있다'고 한 차트를 규칙으로, 2026-10-04).

A 추세선 지지 (전진건설로봇형): 저점을 높이는 추세선(50일, 저점 3번↑ 닿음, 8%↑ 상승) + 수평 저항(최근 30일 고점 근처 2번↑, 현재가 위 15% 안)
   + 60일 안 거래 터짐(3배·+8% 양봉) 뒤 거래 마름(최근 5일 / 60일 최대 0.35↓) + 지금 추세선 -1~+5%. 손절 = 추세선 -2% 아래 종가.
B 수평 지지 수렴 (SK이터닉스형): 120일 안 거래 터짐(박스 전) 뒤 20일 폭 15%↓, 거래 마르며 수렴(최근 10일 폭·거래 모두 그 전 20일의 70%↓),
   박스 하단을 60일 동안 3번↑ 닿음, 거래 바닥(5일 / 120일 최대 0.15↓), 1년 저점보다 15%↑ 위, 지금 하단 위 4% 안. 손절 = 하단 -2% 아래 종가.
3년(종가 매수, 손절선 종가 이탈 시 정리, +3R에 절반 익절 후 본전, 20일): A 578건 평균 +0.10R·이김 37%·손절 59%·+3R 23%,
B 619건 +0.05R·+3R 21%, B + 뜨거운 섹터(상위 5) 143건 +0.22R. 잃을 땐 작고(-1R) 4~5번에 1번 3배 이상 먹는 구조.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


def _trend(lo, hi, cl, tvv, tvx, chv, W=50):
    if np.isnan(lo[-W:]).any() or np.isnan(hi[-W:]).any() or cl[-1] < 1000 or np.nanmean(tvv[-5:]) < 1e9:
        return None
    lo, hi, c = lo[-W:], hi[-W:], cl[-1]
    a = int(np.argmin(lo[: W // 2]))
    xs = np.arange(a + 1, W - 1)
    if len(xs) < 10 or lo[a] <= 0:
        return None
    s = float(np.min((lo[xs] - lo[a]) / (xs - a)))
    if s <= 0:
        return None
    line = lo[a] + s * (np.arange(W) - a)
    if int(np.sum(lo[a:] <= line[a:] * 1.02)) < 3 or line[-1] / lo[a] - 1 < 0.08:
        return None
    seg = hi[-30:]
    res = float(np.max(seg))
    hit = np.where(seg >= res * 0.97)[0]
    if len(hit) < 2 or hit[-1] - hit[0] < 6 or c > res * 0.97 or res / c > 1.15:
        return None
    dist = c / line[-1] - 1
    if not -0.01 <= dist <= 0.05:
        return None
    sp = np.where((tvx[-60:] >= 3) & (chv[-60:] >= 8))[0]
    if len(sp) == 0:
        return None
    dry = np.nanmean(tvv[-5:]) / np.nanmax(tvv[-60:])
    if dry > 0.35:
        return None
    return {"type": "추세선 지지", "stop": round(line[-1] * 0.98), "support": round(line[-1]), "target": round(res),
            "dist_pct": round(dist * 100, 1), "dry": round(float(dry), 3), "since_burst": 59 - int(sp[-1])}


def _flat(lo, hi, cl, tvv, tvx, chv, low250, W=20):
    if np.isnan(lo[-W:]).any() or cl[-1] < 1000 or np.nanmean(tvv[-5:]) < 5e8:
        return None
    blo, bhi = float(np.min(lo[-W:])), float(np.max(hi[-W:]))
    if blo <= 0 or bhi / blo - 1 > 0.15:
        return None
    r_now = np.nanmax(hi[-10:]) / np.nanmin(lo[-10:]) - 1
    r_prev = np.nanmax(hi[-30:-10]) / np.nanmin(lo[-30:-10]) - 1
    if not (r_prev > 0 and r_now <= 0.7 * r_prev) or np.nanmean(tvv[-10:]) > 0.7 * np.nanmean(tvv[-30:-10]):
        return None
    dist = cl[-1] / blo - 1
    if dist > 0.04 or int(np.sum(np.abs(lo[-60:] / blo - 1) <= 0.02)) < 3:
        return None
    sp = np.where((tvx[-120:] >= 3) & (chv[-120:] >= 8))[0]
    if len(sp) == 0 or 119 - sp[-1] < W:
        return None
    dry = np.nanmean(tvv[-5:]) / np.nanmax(tvv[-120:])
    if dry > 0.15 or not (low250 == low250) or blo < low250 * 1.15:
        return None
    return {"type": "수평 지지 수렴", "stop": round(blo * 0.98), "support": round(blo), "target": round(bhi),
            "dist_pct": round(dist * 100, 1), "dry": round(float(dry), 3), "since_burst": 119 - int(sp[-1])}


def scan(db: Session) -> dict:
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = pd.read_sql(text("select stock_code, trading_date, high_price h, low_price l, close_price c, trading_value tv, change_pct ch "
                          "from spot_daily_prices where trading_date >= :d"), db.connection(), params={"d": latest - timedelta(days=420)})
    P = {k: px.pivot(index="trading_date", columns="stock_code", values=k).sort_index() for k in ("h", "l", "c", "tv", "ch")}
    C, H, L, TV, CH = (P[k] for k in ("c", "h", "l", "tv", "ch"))
    tvx = (TV / TV.shift(1).rolling(20).mean())
    low250 = L.rolling(250, min_periods=120).min().shift(20).iloc[-1]
    names, caps = {}, {}
    for code, name, cap in db.execute(text("select code, name, market_cap from stocks")):
        names[code], caps[code] = name, float(cap or 0)
    skip = ("리츠", "스팩", "ETF", "ETN")
    from backend.screener.rotation import family_members  # noqa: PLC0415
    fam_of: dict[str, list[str]] = {}
    for f, mem in family_members(db).items():
        for c in mem:
            fam_of.setdefault(c, []).append(f)
    tail = 130
    items = []
    for code in C.columns:
        nm = names.get(code, code)
        if any(k in nm for k in skip):
            continue
        lo, hi, cl = L[code].values[-tail:], H[code].values[-tail:], C[code].values[-tail:]
        tv, tx, ch = TV[code].values[-tail:], tvx[code].values[-tail:], CH[code].values[-tail:]
        if len(cl) < tail or np.isnan(cl[-1]):
            continue
        for r in (_trend(lo, hi, cl, tv, tx, ch), _flat(lo, hi, cl, tv, tx, ch, float(low250.get(code, np.nan)))):
            if r:
                c = float(cl[-1])
                r.update(code=code, name=nm, close=round(c), change_pct=round(float(ch[-1]), 2),
                         stop_pct=round((r["stop"] / c - 1) * 100, 1), target_pct=round((r["target"] / c - 1) * 100, 1),
                         families=fam_of.get(code, [])[:2], market_cap=caps.get(code, 0))
                items.append(r)
    items.sort(key=lambda x: x["stop_pct"], reverse=True)    # 손절이 가까운 순
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    fl = flags_get([x["code"] for x in items])
    for x in items:
        x["flags"] = fl.get(x["code"], {}).get("flags", [])
    return {"trading_date": C.index[-1].isoformat(), "items": items}
