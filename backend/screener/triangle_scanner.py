from __future__ import annotations

from dataclasses import dataclass

from backend.db.models import SpotDailyPrice

# 박스권에서 저점을 계속 높여가며(상승 지지선) 좁혀지다가, 저항선을 대량거래로
# 돌파하는 "삼각수렴 돌파(ascending triangle breakout)" 패턴을 찾는다.
#
# 주의: backtest_triangle.py로 검증한 결과 이 정의 그대로는 실제로 마이너스
# 기대값을 보임(전체 T+5 평균 -1.61%, 강세장에서도 -1.35%, 승률 38% 안팎,
# 시간이 갈수록 더 나빠짐 - 2026-09-22 기준). 디아이 등 개별 사례는 잘 잡아내지만
# "돌파 당일/직후에 쫓아 사는" 성격이라 전체 모집단으로는 검증되지 않음.
# 따라서 API/UI에 연결하지 않은 상태 - 참고용/추가 개선용으로만 유지.
# (참고: detect_pullback과 조합해 "돌파 후 조용해질 때까지 대기" 용도로 쓰는 게
# 더 근거 있어 보임 - pullback_scanner.py 쪽이 이미 검증됨)
WINDOW = 20                # 삼각수렴 형성 구간(스파이크 이전) 일수
MIN_RESISTANCE_TOUCHES = 2  # 저항선 부근을 최소 몇 번 테스트했는지
RESISTANCE_BAND_PCT = 3.0   # 저항선으로 인정할 근접 범위(%)
MIN_LOW_RISE_PCT = 3.0      # 구간 전반부 대비 후반부 저점이 최소 이만큼은 높아야 함
MAX_RANGE_RATIO = 0.75      # 후반부 변동폭 / 전반부 변동폭 (좁혀짐 확인, 낮을수록 더 좁혀짐)
BREAKOUT_MAX_DAYS_AGO = 2   # 돌파 캔들이 오늘 기준 며칠 전까지 허용되는지 (0=당일)
MIN_BREAKOUT_VOLUME_RATIO = 2.0
MIN_BREAKOUT_CHANGE_PCT = 3.0


@dataclass
class TriangleCandidate:
    code: str
    name: str
    market: str
    sector: str
    market_cap: float
    close_price: float
    change_pct: float
    breakout_date: str
    breakout_change_pct: float
    breakout_volume_ratio: float
    days_since_breakout: int
    resistance_level: float
    low_rise_pct: float
    range_contraction: float
    quality_score: float


def detect_triangle_breakout(price_hist: list[SpotDailyPrice]) -> dict | None:
    """price_hist: 최신순(내림차순) 정렬. 최소 WINDOW+BREAKOUT_MAX_DAYS_AGO+5일 필요."""
    if len(price_hist) < WINDOW + BREAKOUT_MAX_DAYS_AGO + 25:
        return None

    # 1) 최근 며칠 내 돌파 캔들(거래량 급증+상승) 탐색
    breakout_idx = None
    for idx in range(0, BREAKOUT_MAX_DAYS_AGO + 1):
        p = price_hist[idx]
        window_vol = [x.volume for x in price_hist[idx + 1 : idx + 21] if x.volume and x.volume > 0]
        if len(window_vol) < 15 or not p.volume:
            continue
        avg_vol = sum(window_vol) / len(window_vol)
        if avg_vol <= 0:
            continue
        vol_ratio = p.volume / avg_vol
        chg = float(p.change_pct or 0)
        if vol_ratio >= MIN_BREAKOUT_VOLUME_RATIO and chg >= MIN_BREAKOUT_CHANGE_PCT:
            breakout_idx = idx
            breakout_vol_ratio = vol_ratio
            breakout_chg = chg
            break
    if breakout_idx is None:
        return None

    # 2) 돌파 이전 WINDOW일 구간에서 삼각수렴(상승 지지선 + 저항선 반복 테스트 + 좁혀짐) 확인
    triangle = price_hist[breakout_idx + 1 : breakout_idx + 1 + WINDOW]
    if len(triangle) < WINDOW:
        return None
    triangle_asc = list(reversed(triangle))  # 오래된 순

    half = len(triangle_asc) // 2
    first_half, second_half = triangle_asc[:half], triangle_asc[half:]

    first_low = min(p.low_price for p in first_half)
    second_low = min(p.low_price for p in second_half)
    if first_low <= 0:
        return None
    low_rise_pct = (second_low - first_low) / first_low * 100
    if low_rise_pct < MIN_LOW_RISE_PCT:
        return None  # 저점이 충분히 높아지지 않음 - 상승 지지선 아님

    resistance_level = max(p.high_price for p in triangle_asc)
    band = resistance_level * (1 - RESISTANCE_BAND_PCT / 100)
    touches = sum(1 for p in triangle_asc if p.high_price >= band)
    if touches < MIN_RESISTANCE_TOUCHES:
        return None  # 저항선을 충분히 테스트하지 않음(그냥 일회성 고점일 수 있음)

    first_range = max(p.high_price for p in first_half) - min(p.low_price for p in first_half)
    second_range = max(p.high_price for p in second_half) - min(p.low_price for p in second_half)
    if first_range <= 0:
        return None
    range_contraction = second_range / first_range
    if range_contraction > MAX_RANGE_RATIO:
        return None  # 변동폭이 충분히 좁혀지지 않음

    # 돌파가가 저항선을 실제로 넘었는지 확인 (그냥 박스 안에서의 급등이 아니라 진짜 돌파)
    breakout_day = price_hist[breakout_idx]
    if breakout_day.close_price < resistance_level * (1 - RESISTANCE_BAND_PCT / 100):
        return None

    low_rise_quality = min(low_rise_pct / 15.0, 1.0)
    contraction_quality = max(0.0, 1 - range_contraction / MAX_RANGE_RATIO)
    touch_quality = min((touches - MIN_RESISTANCE_TOUCHES + 1) / 4.0, 1.0)
    quality_score = round(low_rise_quality * 0.4 + contraction_quality * 0.35 + touch_quality * 0.25, 3)

    return {
        "breakout_date": breakout_day.trading_date.isoformat(),
        "breakout_change_pct": round(breakout_chg, 2),
        "breakout_volume_ratio": round(breakout_vol_ratio, 2),
        "days_since_breakout": breakout_idx,
        "resistance_level": round(resistance_level, 1),
        "low_rise_pct": round(low_rise_pct, 2),
        "range_contraction": round(range_contraction, 3),
        "quality_score": quality_score,
    }
