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


_FCHART = "https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count=1100&requestType=0"
_LEGACY = "https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"


def krx_day(code: str) -> dict | None:
    """가장 최근 거래일의 정규장(15:30까지) 봉 — 시가·고가·저가·종가·거래량과 기준가(그 전 거래일 정규장 종가).

    토스 일봉·DB 종가는 마지막 체결가라 넥스트레이드(20시까지)·시간외 단일가가 섞인다
    (2026-10-08 LS머트리얼즈: 어제 정규장 15,600인데 시간외 15,350이 종가로 잡혀 +5.5%가 +7.2%로 나옴).
    분봉 1,100개(약 2거래일)로 날짜별 15:30 종가를 잡아서, 휴장일·다음 날 아침에도 직전 거래일 기준으로 보여 준다.
    """
    today = datetime.now(_KST).strftime("%Y%m%d")
    try:
        m = requests.get(_FCHART.format(code=code), timeout=6, headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception:  # noqa: BLE001
        return None
    days: dict[str, list] = {}
    for x in re.findall(r'data="(\d{12})\|[^|]*\|[^|]*\|[^|]*\|(\d+)\|(\d+)"', m):
        if "0900" <= x[0][8:] <= "1530":
            days.setdefault(x[0][:8], []).append((float(x[1]), float(x[2])))
    if not days:
        return None
    ds = sorted(days)
    d = ds[-1]
    rows = days[d]
    close, vol = rows[-1]
    prices = [r[0] for r in rows]
    base = days[ds[-2]][-1][0] if len(ds) >= 2 else None
    o = h = l = None
    if d == today or base is None:      # 오늘 장이면 옛 polling API가 시가·고가·저가·기준가를 정확히 준다
        try:
            r = requests.get(_LEGACY.format(code=code), timeout=6, headers={"User-Agent": "Mozilla/5.0"})
            j = r.json()["result"]["areas"][0]["datas"][0]
            if d == today:
                o, h, l = float(j.get("ov") or 0) or None, float(j.get("hv") or 0) or None, float(j.get("lv") or 0) or None
                base = float(j["sv"]) if j.get("sv") else base
        except Exception:  # noqa: BLE001
            pass
    if not base:
        return None
    return {"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "open": o or prices[0], "high": max(h or 0, max(prices)), "low": min(l or 1e18, min(prices)),
            "close": close, "volume": vol, "base": base}
