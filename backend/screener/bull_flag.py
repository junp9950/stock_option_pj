"""불플래그(깃발형) 탐지: 깃대(단기 급등) → 깃발(짧고 좁은 평행/하향 채널, 거래량 감소) → (선택) 상단 돌파.

차트 후보 페이지(chart_candidates.py)에서 모양 판별에 쓴다.
"""
from __future__ import annotations


POLE_MIN_GAIN = 0.20        # 깃대 상승률 (깃대 시작 저가 → 깃대 끝 고가)
POLE_MAX_DAYS = 10          # 깃대 길이 상한 (1일짜리 장대양봉도 허용)
POLE_VOL_MULT = 1.5         # 깃대 구간 평균 거래량 / 깃대 이전 20일 평균
FLAG_DAYS = (3, 15)         # 깃발 길이 (깃대 끝 다음날 ~ 오늘)
FLAG_MAX_RETRACE = 0.50     # 깃발 최저가가 깃대 길이의 몇 %까지 되돌려도 되는지
# 이 이하면 "선명", 초과는 "애매". 첫 판정(2026-09-23)에서 확실하다고 한 3개는 23~32%, 애매 4개는 44~48%였음
CLEAR_MAX_RETRACE = 0.35
FLAG_MAX_OVERSHOOT = 0.02   # 깃발 중 깃대 고점을 이만큼 넘으면 깃발이 아니라 계속 상승
FLAG_MAX_WIDTH = 0.60       # 깃발 전체 폭 / 깃대 길이
FLAG_SLOPE_MAX = 0.3        # 깃발 고점선·저점선 기울기 상한 (%/일) — 옆이나 아래로
FLAG_SLOPE_MIN = -2.0       # 기울기 하한 (%/일) — 너무 가파르면 깃발이 아니라 하락
FLAG_PARALLEL = 1.0         # 고점선과 저점선 기울기 차이 상한 (%/일)
# 깃발 평균 거래량 / 깃대 중 최대 거래량일. 깃대 평균과 비교하면 폭발일 하루가 조용한 날들과 희석돼
# 급등 직후 거래량이 조금 남은 전형적인 깃발(예: 한선엔지니어링 2026-09)이 빠진다
FLAG_VOL_RATIO = 0.35
BREAKOUT_VOL = 1.5          # 돌파일 거래량 / 깃발 평균 거래량


def _slope_pct(values: list[float]) -> tuple[float, float]:
    """최소제곱 직선의 (기울기 %/일, 마지막 날 추정값). 기울기는 평균값 대비 %."""
    n = len(values)
    xs = range(n)
    mx, my = (n - 1) / 2, sum(values) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / sxx if sxx else 0.0
    return slope / my * 100 if my else 0.0, my + slope * (n - 1 - mx)


def detect_bull_flag(pl: list) -> dict | None:
    """pl: 오래된 순 일봉. 마지막 날 장 마감 기준으로 불플래그면 세부 지표, 아니면 None."""
    t = len(pl) - 1
    if t < 45:
        return None
    lo, hi = t - FLAG_DAYS[1], t - FLAG_DAYS[0]
    top = max(range(lo, hi + 1), key=lambda i: pl[i].high_price)
    pole_top = pl[top].high_price
    start = min(range(top - POLE_MAX_DAYS, top), key=lambda i: pl[i].low_price)
    pole_low = pl[start].low_price
    if pole_low <= 0:
        return None
    pole_gain = pole_top / pole_low - 1
    if pole_gain < POLE_MIN_GAIN:
        return None
    pole_height = pole_top - pole_low

    pole_vols = [p.volume for p in pl[start + 1: top + 1] if p.volume]
    pre_vols = [p.volume for p in pl[start - 20: start] if p.volume]
    if not pole_vols or not pre_vols:
        return None
    pole_vol = sum(pole_vols) / len(pole_vols)
    if pole_vol < POLE_VOL_MULT * sum(pre_vols) / len(pre_vols):
        return None

    flag = pl[top + 1: t + 1]
    if not (FLAG_DAYS[0] <= len(flag) <= FLAG_DAYS[1]):
        return None
    flag_low = min(p.low_price for p in flag)
    flag_high = max(p.high_price for p in flag)
    if flag_high > pole_top * (1 + FLAG_MAX_OVERSHOOT):
        return None
    retrace = (pole_top - flag_low) / pole_height
    if retrace > FLAG_MAX_RETRACE:
        return None
    width = (flag_high - flag_low) / pole_height
    if width > FLAG_MAX_WIDTH:
        return None

    # 돌파일(오늘)은 채널 계산에서 빼야 돌파가 채널을 왜곡하지 않는다
    body = flag[:-1] if len(flag) > FLAG_DAYS[0] else flag
    slope_hi, upper_now = _slope_pct([p.high_price for p in body])
    slope_lo, _ = _slope_pct([p.low_price for p in body])
    if not (FLAG_SLOPE_MIN <= slope_hi <= FLAG_SLOPE_MAX and FLAG_SLOPE_MIN <= slope_lo <= FLAG_SLOPE_MAX):
        return None
    if abs(slope_hi - slope_lo) > FLAG_PARALLEL:
        return None

    flag_vols = [p.volume for p in body if p.volume]
    flag_vol = sum(flag_vols) / len(flag_vols) if flag_vols else 0
    pole_peak_vol = max(pole_vols)
    vol_ratio = flag_vol / pole_peak_vol if pole_peak_vol else 1.0
    if vol_ratio > FLAG_VOL_RATIO:
        return None

    today = pl[t]
    upper_today = upper_now + upper_now * slope_hi / 100  # 채널 상단을 오늘까지 연장
    breakout = today.close_price > upper_today and flag_vol > 0 and (today.volume or 0) >= BREAKOUT_VOL * flag_vol
    if today.close_price < flag_low:
        return None

    # 정렬용: 되돌림 얕고, 거래량 많이 줄고, 폭 좁을수록 높게
    quality = round((1 - retrace / FLAG_MAX_RETRACE) * 0.35 + (1 - vol_ratio / FLAG_VOL_RATIO) * 0.35
                    + (1 - width / FLAG_MAX_WIDTH) * 0.30, 3)
    return {
        "pole_start": pl[start].trading_date.isoformat(),
        "pole_top_date": pl[top].trading_date.isoformat(),
        "pole_days": top - start,
        "pole_gain_pct": round(pole_gain * 100, 1),
        "pole_vol_mult": round(pole_vol / (sum(pre_vols) / len(pre_vols)), 1),
        "flag_days": len(flag),
        "retrace_pct": round(retrace * 100, 1),
        "width_pct": round(width * 100, 1),
        "slope_high": round(slope_hi, 2),
        "slope_low": round(slope_lo, 2),
        "vol_ratio": round(vol_ratio, 2),
        "flag_low": round(flag_low),
        "pole_top": round(pole_top),
        "status": "돌파" if breakout else "깃발 형성중",
        "grade": "선명" if retrace <= CLEAR_MAX_RETRACE else "애매",
        "quality": quality,
    }

