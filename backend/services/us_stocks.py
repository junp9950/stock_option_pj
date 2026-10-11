"""미국 주식 차트 보기 (2026-10-11 사용자 "실시간 필요 없고 차트 확인 정도만").
- 종목 목록: Nasdaq 스크리너(미국 상장 전체) 중 시가총액 10억 달러↑, 일주일에 한 번 새로. 한글 이름은 아는 것만.
- 봉: 토스 API (일봉 200개씩 거슬러 약 3년, 1분봉 200개씩 — 분봉은 최근 며칠). 시세는 지연이어도 됨, 30분 캐시.
- 한국 종목 코드는 숫자 6자리라 영문이 들어가면 미국으로 본다.
"""
from __future__ import annotations

import calendar
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from backend.utils.logger import get_logger

logger = get_logger(__name__)
KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")
_LIST: dict = {}
_CANDLE: dict = {}
KO = {"BRK.B": "버크셔 해서웨이", "SPY": "S&P500 ETF", "QQQ": "나스닥100 ETF", "SOXX": "반도체 ETF(SOXX)", "SMH": "반도체 ETF(SMH)", "TQQQ": "나스닥 3배 ETF",
      "SOXL": "반도체 3배 ETF", "IONQ": "아이온큐", "RGTI": "리게티", "OKLO": "오클로", "SMR": "뉴스케일", "MSTR": "스트래티지", "HOOD": "로빈후드", "RKLB": "로켓랩",
      "ASTS": "AST 스페이스모바일", "TEM": "템퍼스 AI", "CRWV": "코어위브", "NBIS": "네비우스", "SNOW": "스노우플레이크", "CRWD": "크라우드스트라이크",
      "PANW": "팔로알토", "NET": "클라우드플레어", "SHOP": "쇼피파이", "ABNB": "에어비앤비", "AVAV": "에어로바이론먼트", "LLY": "일라이 릴리", "VST": "비스트라"}
ETFS = [("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ"), ("SOXX", "iShares Semiconductor ETF"), ("SMH", "VanEck Semiconductor ETF"),
        ("TQQQ", "ProShares UltraPro QQQ"), ("SOXL", "Direxion Semiconductor Bull 3X"), ("DIA", "SPDR Dow Jones ETF"), ("IWM", "iShares Russell 2000 ETF")]


def is_us(code: str) -> bool:
    return bool(re.search(r"[A-Za-z]", code or ""))


def universe() -> list[dict]:
    hit = _LIST.get("u")
    if hit and time.time() - hit[0] < 7 * 86400:
        return hit[1]
    try:
        from backend.collector.market_events import US_EARNINGS  # noqa: PLC0415
        ko = {k: v[0] for k, v in US_EARNINGS.items()} | KO
    except Exception:  # noqa: BLE001
        ko = dict(KO)
    out = []
    try:
        j = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0&download=true",
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=30).json()
        for r in (j.get("data") or {}).get("rows") or []:
            try:
                cap = float(r.get("marketCap") or 0)
            except ValueError:
                cap = 0
            sym = (r.get("symbol") or "").strip().replace("/", ".")
            if cap < 1e9 or not sym or "^" in sym:
                continue
            nm = re.sub(r"\s+(Common Stock|Class [A-C] Common Stock|Ordinary Shares|American Depositary Shares.*|Inc\.?|Corporation|Corp\.?)(\s.*)?$", "",
                        (r.get("name") or "").strip()).strip() or sym
            out.append({"code": sym, "name": ko.get(sym, nm), "en": nm, "cap": cap, "sector": r.get("sector") or "", "industry": r.get("industry") or "",
                        "close": float(str(r.get("lastsale") or "0").replace("$", "") or 0), "chg": float(str(r.get("pctchange") or "0").replace("%", "") or 0)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("미국 종목 목록 실패: %s", type(exc).__name__)
        if hit:
            return hit[1]
    have = {x["code"] for x in out}
    out += [{"code": s, "name": ko.get(s, n), "en": n, "cap": 0, "sector": "ETF", "industry": "ETF", "close": 0, "chg": 0} for s, n in ETFS if s not in have]
    out.sort(key=lambda x: -x["cap"])
    if out:
        _LIST["u"] = (time.time(), out)
    return out


def info(code: str) -> dict | None:
    return next((x for x in universe() if x["code"] == code.upper()), None)


def _pages(code: str, interval: str, n_pages: int) -> list[dict]:
    from backend.services import toss_client  # noqa: PLC0415
    out, before = [], None
    for _ in range(n_pages):
        p = {"symbol": code, "interval": interval, "count": 200}
        if before:
            p["before"] = before
        r = toss_client._get("/candles", p)  # noqa: SLF001
        if r is None or r.status_code != 200:
            break
        res = r.json().get("result") or {}
        c = res.get("candles") or []
        out += c
        before = res.get("nextBefore")
        if not c or not before:
            break
        time.sleep(0.15)
    return out


def candles(code: str, tf: str = "1d", ext: bool = False) -> list[dict]:
    """차트 형식 봉. 일봉 timestamp = 미국 날짜, 분봉 t = 한국 시각(차트 축이 한국 시간으로 보이게)."""
    code = code.upper()
    key = (code, tf, ext)
    hit = _CANDLE.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    if tf in ("1d", "1w"):
        raw = sorted(_pages(code, "1d", 4), key=lambda c: c["timestamp"])
        day = []
        for c in raw:
            d = datetime.fromisoformat(c["timestamp"]).astimezone(ET).date()      # 토스 미국 일봉은 한국 13시(= 미국 0시) 표시 → 미국 날짜
            day.append({"timestamp": f"{d}T00:00:00.000+09:00", "openPrice": c["openPrice"], "highPrice": c["highPrice"], "lowPrice": c["lowPrice"],
                        "closePrice": c["closePrice"], "volume": c.get("volume") or "0"})
        if tf == "1d":
            out = day
        else:
            wk: dict = {}
            for c in day:
                d = datetime.fromisoformat(c["timestamp"][:10])
                k = (d - timedelta(days=d.weekday())).date()
                w = wk.get(k)
                if not w:
                    wk[k] = w = {**c, "timestamp": f"{k}T00:00:00.000+09:00", "volume": 0}
                else:
                    w["highPrice"] = str(max(float(w["highPrice"]), float(c["highPrice"])))
                    w["lowPrice"] = str(min(float(w["lowPrice"]), float(c["lowPrice"])))
                    w["closePrice"] = c["closePrice"]
                w["volume"] = float(w["volume"]) + float(c["volume"] or 0)
            out = [wk[k] for k in sorted(wk)]
    else:
        mins = int(tf[:-1])
        pages = {1: 5, 3: 10, 5: 14, 15: 20, 30: 25, 60: 25}.get(mins, 10)      # 1분봉 200개씩 — 많을수록 첫 표시가 느림(한 번 받으면 30분 저장)
        raw = sorted(_pages(code, "1m", pages), key=lambda c: c["timestamp"])
        buckets: dict = {}
        for c in raw:
            t_end = datetime.fromisoformat(c["timestamp"])                   # 토스 1분봉 시각 = 봉 끝 → 1분 당겨 시작 시각
            t0 = (t_end - timedelta(minutes=1)).astimezone(ET)
            reg = (9, 30) <= (t0.hour, t0.minute) < (16, 0)
            if not ext and not reg:
                continue
            base = t0.replace(hour=9, minute=30, second=0, microsecond=0)
            k = base + timedelta(minutes=((t0 - base).total_seconds() // 60 // mins) * mins) if t0 >= base else t0.replace(second=0, microsecond=0)
            b = buckets.get(k)
            v = float(c.get("volume") or 0)
            if not b:
                buckets[k] = {"o": c["openPrice"], "h": float(c["highPrice"]), "l": float(c["lowPrice"]), "c": c["closePrice"], "v": v}
            else:
                b["h"] = max(b["h"], float(c["highPrice"])); b["l"] = min(b["l"], float(c["lowPrice"])); b["c"] = c["closePrice"]; b["v"] += v
        out = []
        for k in sorted(buckets):
            b, kst = buckets[k], k.astimezone(KST)
            out.append({"t": calendar.timegm(kst.replace(tzinfo=None).timetuple()), "timestamp": kst.strftime("%Y-%m-%dT%H:%M:00+09:00"),
                        "openPrice": b["o"], "highPrice": b["h"], "lowPrice": b["l"], "closePrice": b["c"], "volume": b["v"]})
    _CANDLE[key] = (time.time(), out)
    if len(_CANDLE) > 300:
        _CANDLE.clear()
    return out
