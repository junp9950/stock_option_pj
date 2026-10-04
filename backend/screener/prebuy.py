"""선취매 후보: 뜨거운 섹터 안에서 거래가 터지기 전 조용한 종목 (사용자 선취매 근거 유형을 규칙으로).

A 저가 지킴 = 최근 5~60일 안 대량거래 양봉(거래 5배·+5%) 뒤 종가가 그 봉 저가를 한 번도 안 깸 (손절선 = 그 저가)
B 눌림     = 20일 고점 대비 -5~-15%, 20일선 위
D 버팀     = 소속 뜨거운 섹터가 그날 -1.5% 이하인데 종목은 0% 이상
공통: 오늘 조용(거래 1.3배 미만, 등락 ±4% 안), 20일선 이격 25% 미만, 최근 5일 평균 거래대금 10억 이상.

3년 확인(2023-12~2026-09, 상승·횡보장, 같은 날 시장 대비 20일 뒤): 조건 없는 뜨거운 섹터 조용한 종목 +1.7%p, A +1.3%p, B +2.2%p.
10일 안 거래 폭발(+10%·5배) 확률은 8~11%로 조건과 거의 무관 → 어느 종목이 터질지는 못 맞힌다. 고를 범위를 좁히는 용도.
사용자 실제 선취매: 세미파이브 2026-09-23·28(A+B), 하나마이크론 09-28(B)가 걸림.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

QUIET_X, QUIET_CHG, MAX_GAP, MIN_TV5 = 1.3, 4.0, 25.0, 1e9


def frames(P: dict) -> dict:
    """가격 피벗(o,h,l,c,tv,ch) → 날짜×종목 조건 표."""
    C, O, H, L, TV, CH = (P[k] for k in ("c", "o", "h", "l", "tv", "ch"))
    tv20 = TV.shift(1).rolling(20).mean()
    tvx = TV / tv20
    ma20 = C.rolling(20).mean()
    hi20 = H.rolling(20).max()
    spike = ((tvx >= 5) & (CH >= 5) & (C > O)).fillna(False)
    sp_low = L.where(spike).ffill(limit=60)
    idx = pd.DataFrame(np.arange(len(C))[:, None].repeat(C.shape[1], 1), index=C.index, columns=C.columns)
    sp_idx = idx.where(spike).ffill(limit=60)
    age = idx - sp_idx
    cv, spv = C.values, spike.values
    mn = np.full(cv.shape, np.nan)
    run = np.full(cv.shape[1], np.nan)
    for i in range(cv.shape[0]):   # 대량거래 봉 다음 날부터의 최저 종가
        run = np.where(spv[i], np.inf, np.fmin(run, cv[i]))
        mn[i] = run
    mn[np.isinf(mn)] = np.nan
    held = (pd.DataFrame(mn, index=C.index, columns=C.columns) >= sp_low) & (age >= 5) & (age <= 60)
    return {"held": held, "sp_low": sp_low, "age": age, "pull": ((C / hi20 - 1) <= -0.05) & ((C / hi20 - 1) >= -0.15) & (C > ma20),
            "off_hi": (C / hi20 - 1) * 100, "quiet": (tvx < QUIET_X) & (CH.abs() < QUIET_CHG), "gap": (C / ma20 - 1) * 100,
            "tvx": tvx, "tv5": TV.rolling(5).mean()}


def pick(P: dict, F: dict, d, hot_fams: list[str], members: dict[str, list[str]], skip=lambda code: False) -> list[dict]:
    """날짜 d의 선취매 후보. hot_fams = 그날 뜨거운 섹터, members = 섹터 → 종목코드."""
    C, CH = P["c"], P["ch"]
    if d not in C.index:
        return []
    out = {}
    for f in hot_fams:
        mem = [c for c in members.get(f, []) if c in C.columns]
        fam_chg = float(CH.loc[d, mem].mean()) if mem else 0.0
        for code in mem:
            c = C.at[d, code]
            if not (c == c and c >= 1000) or skip(code):
                continue
            if not (bool(F["quiet"].at[d, code]) and F["gap"].at[d, code] < MAX_GAP and F["tv5"].at[d, code] >= MIN_TV5):
                continue
            tags = []
            if bool(F["held"].at[d, code]):
                tags.append("저가 지킴")
            if bool(F["pull"].at[d, code]):
                tags.append("눌림")
            if fam_chg <= -1.5 and CH.at[d, code] >= 0:
                tags.append("버팀")
            if not tags:
                continue
            r = out.setdefault(code, {"code": code, "tags": tags, "families": [], "close": float(c), "change_pct": round(float(CH.at[d, code]), 2),
                                      "tv_x": round(float(F["tvx"].at[d, code]), 2), "gap20_pct": round(float(F["gap"].at[d, code]), 1),
                                      "off_high_pct": round(float(F["off_hi"].at[d, code]), 1),
                                      "stop_price": round(float(F["sp_low"].at[d, code])) if "저가 지킴" in tags else None})
            r["families"].append(f)
            if "버팀" in tags and "버팀" not in r["tags"]:
                r["tags"].append("버팀")
    return list(out.values())
