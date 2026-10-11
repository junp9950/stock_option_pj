"""호가 단위 (2023-01 코스피·코스닥 통일 기준). 손절가처럼 화면·알림에 보이는 가격은 실제 주문할 수 있는 값으로 내림 (2026-10-11)."""
from __future__ import annotations

import math


def tick_size(p: float) -> int:
    p = float(p)
    return 1 if p < 2000 else 5 if p < 5000 else 10 if p < 20000 else 50 if p < 50000 else 100 if p < 200000 else 500 if p < 500000 else 1000


def tick_floor(p: float) -> float:
    """호가 단위로 내림 (손절 예약가는 내려야 그 가격에 걸림)."""
    if p is None or p != p:      # None · NaN은 그대로
        return p
    t = tick_size(p)
    return float(math.floor(float(p) / t + 1e-9) * t)
