"""네이버 실시간 시세 — 전 종목 가격·거래량을 300개씩 한 번에 받는다 (2,400종목 1초 안).

토스 /prices는 거래량이 없어서 장중 섹터 수급(거래대금 배수)을 못 낸다 (2026-10-08).
오늘 체결된 종목만 돌려준다 — 휴장일·장 전에는 빈 dict.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

_URL = "https://polling.finance.naver.com/api/realtime/domestic/stock/"
_KST = ZoneInfo("Asia/Seoul")
_cache: dict = {"t": 0.0, "key": None, "v": {}}
_lock = threading.Lock()


def _num(x) -> float | None:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def snapshot(codes: list[str], max_age: float = 60) -> dict[str, dict]:
    """{code: {c, o, h, l, v, chg}} — 오늘 체결분만. 같은 목록은 max_age초 캐시."""
    key = hash(tuple(codes))
    with _lock:
        if _cache["key"] == key and time.time() - _cache["t"] < max_age:
            return _cache["v"]
    today = datetime.now(_KST).strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    for i in range(0, len(codes), 300):
        try:
            r = requests.get(_URL + ",".join(codes[i:i + 300]), timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            datas = r.json().get("datas", []) if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            datas = []
        for x in datas:
            if not str(x.get("localTradedAt", "")).startswith(today):
                continue
            c, v = _num(x.get("closePriceRaw")), _num(x.get("accumulatedTradingVolumeRaw"))
            if not c or v is None:
                continue
            out[x["itemCode"]] = {"c": c, "o": _num(x.get("openPriceRaw")), "h": _num(x.get("highPriceRaw")),
                                  "l": _num(x.get("lowPriceRaw")), "v": v, "chg": _num(x.get("fluctuationsRatioRaw"))}
        time.sleep(0.05)
    with _lock:
        _cache.update(t=time.time(), key=key, v=out)
    return out
