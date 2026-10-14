"""전종목 동일가중 지수로 본 시장 국면 (상승/횡보/하락).

하락 = 지수가 20일 이동평균 아래. 레이더 상단 표시와 백테스트 진입 보류가 같은 규칙을 쓴다.
"""
from __future__ import annotations

import math
from sqlalchemy.orm import Session



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
    from sqlalchemy import text
    from backend.services.stock_signals import _close_frames
    from backend.services.trading_rules import market_returns
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest is None:
        return None
    frames = _close_frames(db, latest)
    series = regime_series((market_returns(frames["c"],frames["tv"]) * 100).to_dict())
    if not series:
        return None
    last = max(series)
    return {**series[last], "as_of": last.isoformat()}


# 시장 사이클 위치 (2026-10-15 사용자가 올린 올리버 켈 '가격 움직임 사이클' → "어케 하면 좋겠는데?" → 시장 카드에 단계 + 12년 그 뒤 성적).
# 같은 무게 지수(시장 국면과 같은 것) · 20일선(SMA) · 50일선 이격 · 200일선 위 종목 비율. 그날까지 정보만.
# 12년(tmp_claude/cycle_test.py, 2015-07~2026-10) 단계별 뒤 20일 평균 · 오른 비율 (전체 +1.5% · 62%):
#   ② 웨지 팝 +2.8% 73% (앞 6년 +3.1 · 뒤 6년 +2.5 — 둘 다 좋음) · ① 반전 확장 +4.2% 70% (앞 +7.8 · 뒤 +1.4) · ⑧ 하락 추세 +2.8% 73% (지수는 평균회귀)
#   ③ 크로스백 +0.1% 55% · ④ 상승 추세 +0.5% 56% · ⑥ 웨지 드롭 +0.2% 56% (셋 다 앞뒤 모두 평소 이하) · ⑤ 과열 +1.8% 64% (앞 +3.6 · 뒤 −0.5 엇갈림)
#   지수 단위 숫자라 종목 매수 규칙(하락장 쉼)과는 따로 봄 — 우리 추세 매수는 하락장에서 손해(12년), 지수는 빠진 뒤 평균으로 돌아옴.
CYCLE = {
    "①": ("① 반전 확장", "투매 · 바닥 모으기 자리", 4.2, 70),
    "②": ("② 웨지 팝", "20일선 위로 막 올라섬", 2.8, 73),
    "③": ("③ 크로스백", "20일선까지 되돌림", 0.1, 55),
    "④": ("④ 상승 추세", "20일선 위 · 오름", 0.5, 56),
    "⑤": ("⑤ 과열", "50일선 +8%↑ · 소진 주의", 1.8, 64),
    "⑥": ("⑥ 웨지 드롭", "20일선 아래로 막 꺾임", 0.2, 56),
    "⑧": ("⑧ 하락 추세", "20일선 아래 이어짐", 2.8, 73),
    "횡보": ("횡보", "20일선 위 · 평평", 2.7, 62),
}
CYCLE_BASE = (1.5, 62)


def cycle_stage(lvl, b200: float | None) -> dict | None:
    """lvl = 같은 무게 지수(pandas Series, 최근 80거래일 이상) · b200 = 오늘 200일선 위 종목 비율(%)."""
    import numpy as np  # noqa: PLC0415
    if len(lvl) < 60:
        return None
    ma20 = lvl.rolling(20).mean(); ma50 = lvl.rolling(50).mean()
    above = (lvl > ma20).to_numpy()
    i = len(lvl) - 1
    last_up = last_dn = -999
    for j in range(20, len(lvl)):
        if above[j] and not above[j - 1]:
            last_up = j
        if not above[j] and above[j - 1]:
            last_dn = j
    rising = bool(ma20.iloc[-1] > ma20.iloc[-6])
    ext = float(lvl.iloc[-1] / ma50.iloc[-1] - 1); dd20 = float(lvl.iloc[-1] / lvl.iloc[-21] - 1)
    if not above[i]:
        prior = float(np.mean(above[max(0, last_dn - 20):last_dn])) if last_dn > 0 else 0
        if (b200 is not None and b200 < 35) or dd20 <= -0.08:
            k = "①"
        elif i - last_dn <= 10 and prior >= 0.6:
            k = "⑥"
        else:
            k = "⑧"
    else:
        prior = 1 - float(np.mean(above[max(0, last_up - 20):last_up])) if last_up > 0 else 0
        if ext >= 0.08:
            k = "⑤"
        elif i - last_up <= 10 and prior >= 0.6:
            k = "②"
        elif rising and lvl.iloc[-1] <= ma20.iloc[-1] * 1.01:
            k = "③"
        elif rising:
            k = "④"
        else:
            k = "횡보"
    name, say, r20, up = CYCLE[k]
    return {"key": k, "name": name, "say": say, "r20": r20, "up": up, "base_r20": CYCLE_BASE[0], "base_up": CYCLE_BASE[1],
            "b200": None if b200 is None else round(b200), "ext50": round(ext * 100, 1), "dd20": round(dd20 * 100, 1)}
