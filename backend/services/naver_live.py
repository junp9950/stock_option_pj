"""네이버 실시간 시세 — 전 종목 가격·거래량을 300개씩 한 번에 받는다 (2,400종목 1초 안).

토스 /prices는 거래량이 없어서 장중 섹터 수급(거래대금 배수)을 못 낸다 (2026-10-08).
오늘 체결된 종목만 돌려준다 — 휴장일·장 전에는 빈 dict.
"""
from __future__ import annotations

import re
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


_FCHART = "https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count=420&requestType=0"
_LEGACY = "https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"


def krx_day(code: str) -> dict | None:
    """오늘 정규장(15:30까지) 봉 — 시가·고가·저가·종가·거래량과 기준가(어제 정규장 종가).

    토스 일봉·DB 종가는 마지막 체결가라 넥스트레이드(20시까지)·시간외 단일가가 섞인다
    (2026-10-08 LS머트리얼즈: 어제 정규장 15,600인데 시간외 15,350이 종가로 잡혀 +5.5%가 +7.2%로 나옴).
    """
    today = datetime.now(_KST).strftime("%Y%m%d")
    try:
        r = requests.get(_LEGACY.format(code=code), timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        d = r.json()["result"]["areas"][0]["datas"][0]
        m = requests.get(_FCHART.format(code=code), timeout=6, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception:  # noqa: BLE001
        return None
    close = vol = None
    for x in re.findall(r'data="(\d{12})\|[^|]*\|[^|]*\|[^|]*\|(\d+)\|(\d+)"', m):
        if x[0][:8] == today and x[0][8:] <= "1530":
            close, vol = float(x[1]), float(x[2])
    if close is None or not d.get("sv"):
        return None
    return {"open": float(d.get("ov") or close), "high": float(d.get("hv") or close), "low": float(d.get("lv") or close),
            "close": close, "volume": vol, "base": float(d["sv"])}
