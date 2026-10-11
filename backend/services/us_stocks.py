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
_IDX: dict = {}
KO = {"BRK.B": "버크셔 해서웨이", "SPY": "S&P500 ETF", "QQQ": "나스닥100 ETF", "SOXX": "반도체 ETF(SOXX)", "SMH": "반도체 ETF(SMH)", "TQQQ": "나스닥 3배 ETF",
      "SOXL": "반도체 3배 ETF", "IONQ": "아이온큐", "RGTI": "리게티", "OKLO": "오클로", "SMR": "뉴스케일", "MSTR": "스트래티지", "HOOD": "로빈후드", "RKLB": "로켓랩",
      "ASTS": "AST 스페이스모바일", "TEM": "템퍼스 AI", "CRWV": "코어위브", "NBIS": "네비우스", "SNOW": "스노우플레이크", "CRWD": "크라우드스트라이크",
      "PANW": "팔로알토", "NET": "클라우드플레어", "SHOP": "쇼피파이", "ABNB": "에어비앤비", "AVAV": "에어로바이론먼트", "LLY": "일라이 릴리", "VST": "비스트라", "GOOG": "알파벳(구글) C", "TSM": "TSMC", "BRK.A": "버크셔 해서웨이 A"}
ETFS = [("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ"), ("SOXX", "iShares Semiconductor ETF"), ("SMH", "VanEck Semiconductor ETF"),
        ("TQQQ", "ProShares UltraPro QQQ"), ("SOXL", "Direxion Semiconductor Bull 3X"), ("DIA", "SPDR Dow Jones ETF"), ("IWM", "iShares Russell 2000 ETF")]


def is_us(code: str) -> bool:
    """미국 티커는 영문자로 시작. 한국 코드는 숫자로 시작(새 코드 0004V0·0080Y0처럼 중간에 영문이 들어가도 한국)."""
    return bool(re.match(r"[A-Za-z]", code or ""))


# ── 오늘 시세 덮어쓰기 (2026-10-11 점검: 스크리너는 하루 전 값이라 Nasdaq 관심종목 시세로 20개씩 받아 덮음) ──
_Q: dict = {"t": 0.0, "busy": False, "data": {}}
_DISK = __import__("pathlib").Path.home() / ".cache" / "stock_us_cache.json"      # 재시작 직후에도 바로 보이게 (시세·지수 마지막 값)


def _disk_load() -> None:
    if _Q.get("loaded"):
        return
    _Q["loaded"] = True
    try:
        import json  # noqa: PLC0415
        d = json.loads(_DISK.read_text())
        if d.get("q"):
            _Q["data"] = {k: tuple(v) for k, v in d["q"].items()}; _Q["t"] = d.get("qt", 0) - 1500      # 오래된 값 → 곧 새로 받음
        if d.get("idx"):
            _IDX["x"] = (d.get("it", 0) - 600, d["idx"])
    except Exception:  # noqa: BLE001
        pass


def _disk_save() -> None:
    try:
        import json  # noqa: PLC0415
        _DISK.parent.mkdir(parents=True, exist_ok=True)
        _DISK.write_text(json.dumps({"q": _Q["data"], "qt": _Q["t"], "idx": (_IDX.get("x") or (0, None))[1], "it": (_IDX.get("x") or (0, None))[0]}))
    except Exception:  # noqa: BLE001
        pass


def _refresh_quotes(syms: list[str]) -> None:
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    def one(chunk):
        q = "&".join("symbol=" + x.lower().replace(".", "%2F") + "%7cstocks" for x in chunk)
        for k in range(3):
            try:
                d = requests.get("https://api.nasdaq.com/api/quote/watchlist?" + q, headers=h, timeout=20).json().get("data") or []
                res = {}
                for r in d:
                    try:
                        res[(r.get("symbol") or "").upper().replace("/", ".")] = (float(str(r.get("lastSalePrice") or "0").replace("$", "").replace(",", "")),
                                                                                float(str(r.get("percentageChange") or "0").replace("%", "").replace("+", "") or 0),
                                                                                float(str(r.get("volume") or "0").replace(",", "") or 0))
                    except ValueError:
                        pass
                return res
            except Exception:  # noqa: BLE001
                time.sleep(1 + k)
        return {}
    try:
        chunks = [syms[i:i + 20] for i in range(0, len(syms), 20)]
        out = {}
        with ThreadPoolExecutor(4) as ex:
            for r in ex.map(one, chunks):
                out.update(r)
        if len(out) > len(syms) * 0.5:
            _Q.update(data=out, t=time.time()); _disk_save()
    finally:
        _Q["busy"] = False


def _quotes_kick(syms: list[str]) -> None:
    if time.time() - _Q["t"] < 1200 or _Q["busy"]:
        return
    _Q["busy"] = True
    import threading  # noqa: PLC0415
    threading.Thread(target=_refresh_quotes, args=(syms,), daemon=True).start()


def universe() -> list[dict]:
    """종목 목록(스크리너, 6시간) + 오늘 시세(Nasdaq 관심종목 시세, 20분, 뒤에서 받음)를 덮은 것."""
    _disk_load()
    base = _universe_base()
    _quotes_kick([x["code"] for x in base if x["cap"] > 0])
    q = _Q["data"]
    if not q:
        return base
    return [({**x, "close": q[x["code"]][0], "chg": q[x["code"]][1], "vol": q[x["code"]][2] or x["vol"]} if x["code"] in q else x) for x in base]


def quotes_age() -> float | None:
    return time.time() - _Q["t"] if _Q["t"] else None


def _universe_base() -> list[dict]:
    hit = _LIST.get("u")
    if hit and time.time() - hit[0] < 6 * 3600:      # 종목·시총은 자주 안 바뀜 (시세는 위에서 따로)
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
                        "close": float(str(r.get("lastsale") or "0").replace("$", "") or 0), "chg": float(str(r.get("pctchange") or "0").replace("%", "") or 0),
                        "vol": float(r.get("volume") or 0)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("미국 종목 목록 실패: %s", type(exc).__name__)
        if hit:
            return hit[1]
    have = {x["code"] for x in out}
    out += [{"code": s, "name": ko.get(s, n), "en": n, "cap": 0, "sector": "ETF", "industry": "ETF", "close": 0, "chg": 0, "vol": 0} for s, n in ETFS if s not in have]
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
        r = None
        for k in range(3):
            r = toss_client._get("/candles", p)  # noqa: SLF001
            if r is not None and r.status_code == 429:
                time.sleep(2 + 3 * k); continue
            break
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
    if tf == "1w":
        day = candles(code, "1d")
    if tf == "1d":
        raw = sorted(_pages(code, "1d", 4), key=lambda c: c["timestamp"])
        day = []
        for c in raw:
            d = datetime.fromisoformat(c["timestamp"]).astimezone(ET).date()      # 토스 미국 일봉은 한국 13시(= 미국 0시) 표시 → 미국 날짜
            day.append({"timestamp": f"{d}T00:00:00.000+09:00", "openPrice": c["openPrice"], "highPrice": c["highPrice"], "lowPrice": c["lowPrice"],
                        "closePrice": c["closePrice"], "volume": c.get("volume") or "0"})
        out = day
    if tf == "1w":
        if True:      # 주봉 = 일봉 캐시를 월요일 기준으로 묶음
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
    elif tf != "1d":
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
            if t0 >= base:
                k = base + timedelta(minutes=((t0 - base).total_seconds() // 60 // mins) * mins)
            else:      # 장 전: 자정 기준으로 같은 간격
                mm = t0.hour * 60 + t0.minute
                k = t0.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=(mm // mins) * mins)
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
    if out:      # 못 받았으면 저장 안 함 (다음에 다시)
        _CANDLE[key] = (time.time(), out)
    if len(_CANDLE) > 300:
        _CANDLE.clear()
    return out


SECTOR_KO = {"Technology": "기술", "Finance": "금융", "Health Care": "헬스케어", "Consumer Discretionary": "경기소비재", "Industrials": "산업재",
             "Energy": "에너지", "Utilities": "유틸리티", "Real Estate": "부동산", "Basic Materials": "소재", "Consumer Staples": "필수소비재",
             "Telecommunications": "통신", "Miscellaneous": "기타", "ETF": "ETF", "": "기타"}
INDEX = [("SPY", "S&P500"), ("QQQ", "나스닥100"), ("DIA", "다우"), ("SOXX", "반도체(SOX)"), ("IWM", "러셀2000")]


def overview(db=None) -> dict:
    """미장 오늘: 지수(ETF로 대신) · 섹터 등락(시총 가중) · 대형주 많이 오른/내린 · 거래대금 많은 · 이번 주 미국 일정."""
    L = [x for x in universe() if x["cap"] > 0]
    idx = []      # 지수는 indices() (2026-10-11 느려서 뺌 — ETF 일봉 5개를 토스에서 받느라 첫 화면이 늦었음)
    sec: dict = {}
    for x in L:
        k = SECTOR_KO.get(x["sector"], x["sector"] or "기타")
        d = sec.setdefault(k, {"name": k, "cap": 0.0, "w": 0.0, "n": 0, "up": 0, "lead": []})
        d["cap"] += x["cap"]; d["w"] += x["cap"] * x["chg"]; d["n"] += 1; d["up"] += x["chg"] > 0
        d["lead"].append(x)
    sectors = []
    for d in sec.values():
        if d["n"] < 5:
            continue
        top = sorted(d["lead"], key=lambda x: -x["cap"])[:4]
        sectors.append({"name": d["name"], "chg": round(d["w"] / d["cap"], 2) if d["cap"] else 0, "n": d["n"], "up_pct": round(d["up"] / d["n"] * 100),
                        "leaders": [{"code": x["code"], "name": x["name"], "chg": x["chg"]} for x in top]})
    sectors.sort(key=lambda x: -x["chg"])
    big = [x for x in L if x["cap"] >= 1e10]
    pick = lambda arr: [{"code": x["code"], "name": x["name"], "close": x["close"], "chg": x["chg"], "cap": x["cap"], "dv": x["close"] * x["vol"]} for x in arr]
    out = {"index": idx, "sectors": sectors, "gainers": pick(sorted(big, key=lambda x: -x["chg"])[:10]), "losers": pick(sorted(big, key=lambda x: x["chg"])[:10]),
           "active": pick(sorted(L, key=lambda x: -(x["close"] * x["vol"]))[:15]), "breadth": {"up": sum(x["chg"] > 0 for x in L), "down": sum(x["chg"] < 0 for x in L), "n": len(L)}}
    if db is not None:
        try:
            from datetime import date  # noqa: PLC0415
            from backend.collector.market_events import events  # noqa: PLC0415
            out["events"] = [e for e in events(db, date.today(), date.today() + timedelta(days=7)) if e["country"] == "US" and e["importance"] >= 1][:30]
        except Exception:  # noqa: BLE001
            out["events"] = []
    return out


def heat_items(limit: int = 300) -> list[dict]:
    L = sorted([x for x in universe() if x["cap"] > 0], key=lambda x: -x["cap"])[:limit]
    return [{"code": x["code"], "name": x["name"], "sector": SECTOR_KO.get(x["sector"], x["sector"] or "기타"), "market_cap": x["cap"], "change_pct": x["chg"]} for x in L]


def rank(sort: str = "dv", limit: int = 100, min_cap: float = 1e9) -> list[dict]:
    L = [x for x in universe() if x["cap"] >= min_cap]
    key = {"dv": lambda x: -(x["close"] * x["vol"]), "cap": lambda x: -x["cap"], "up": lambda x: -x["chg"], "down": lambda x: x["chg"]}.get(sort)
    L = sorted(L, key=key)[:limit]
    return [{"code": x["code"], "name": x["name"], "en": x["en"], "close": x["close"], "chg": x["chg"], "cap": x["cap"], "dv": x["close"] * x["vol"],
             "sector": SECTOR_KO.get(x["sector"], x["sector"] or "기타"), "industry": x["industry"]} for x in L]


# ── 미장 오늘 위 카드: 나스닥 · 나스닥100 선물 · S&P500 (국장 코스피 · 코200선물 · 코스닥 자리) ──
IDX3 = [(".IXIC", "index", "나스닥", "QQQ", False), ("NQcv1", "futures", "나스닥100 선물", "QQQ", True), (".INX", "index", "S&P500", "SPY", False)]


def _etf_prev(etf: str, pts: list) -> float | None:
    """선 그래프 기준선 = 그 세션 전날 ETF 종가."""
    if not pts:
        return None
    first_us = datetime.fromtimestamp(pts[0]["t"], tz=ZoneInfo("UTC")).replace(tzinfo=KST).astimezone(ET).date().isoformat()
    d = [x for x in candles(etf, "1d") if x["timestamp"][:10] < first_us]
    return float(d[-1]["closePrice"]) if d else None


def _spark(etf: str, ext: bool) -> list[dict]:
    """장중 선용 5분 간격 — 1분봉을 최근 세션만큼만 (정규장 3쪽 = 600분, 장 전·후 포함 6쪽)."""
    key = ("spark", etf, ext)
    hit = _CANDLE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    raw = sorted(_pages(etf, "1m", 6 if ext else 3), key=lambda c: c["timestamp"])
    b: dict = {}
    for c in raw:
        t0 = (datetime.fromisoformat(c["timestamp"]) - timedelta(minutes=1)).astimezone(ET)
        if not ext and not ((9, 30) <= (t0.hour, t0.minute) < (16, 0)):
            continue
        k = t0.replace(minute=t0.minute - t0.minute % 5, second=0, microsecond=0)
        b[k] = c["closePrice"]
    out = []
    for k in sorted(b):
        kst = k.astimezone(KST)
        out.append({"t": calendar.timegm(kst.replace(tzinfo=None).timetuple()), "timestamp": kst.strftime("%Y-%m-%dT%H:%M:00+09:00"), "closePrice": b[k], "openPrice": b[k]})
    if out:
        _CANDLE[key] = (time.time(), out)
    return out


def indices() -> dict:
    """5분 지나면 저장해 둔 값을 바로 주고 뒤에서 새로 받음 (화면이 기다리지 않게)."""
    _disk_load()
    hit = _IDX.get("x")
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    if hit:
        if not _IDX.get("busy"):
            _IDX["busy"] = True
            import threading  # noqa: PLC0415
            def _bg():
                try:
                    _indices_calc()
                finally:
                    _IDX["busy"] = False
            threading.Thread(target=_bg, daemon=True).start()
        return hit[1]
    return _indices_calc()


def _nget(url: str, h: dict):
    """네이버 해외 API — 가끔 응답이 늦어 끊기므로 한 번 더 (2026-10-11 20:54 ReadTimeout)."""
    for k in range(2):
        try:
            return requests.get(url, headers=h, timeout=8).json()
        except (requests.Timeout, requests.ConnectionError):
            if k:
                raise
            time.sleep(1.5)


def _indices_calc() -> dict:
    h = {"User-Agent": "Mozilla/5.0"}
    out = []
    old = {x["code"]: x for x in ((_IDX.get("x") or (0, {}))[1].get("items") or [])}
    for code, kind, nm, etf, ext in IDX3:
        try:
            b = _nget(f"https://api.stock.naver.com/{kind}/{code}/basic", h)
            d = _nget(f"https://api.stock.naver.com/chart/foreign/{kind}/{code}?periodType=dayCandle", h).get("priceInfos") or []
            close = float(str(b.get("closePrice")).replace(",", ""))
            pct = float(b.get("fluctuationsRatio") or 0)
            prev = round(close / (1 + pct / 100), 2)
            cl = [float(x["closePrice"]) for x in d]
            ma20 = sum(cl[-20:]) / 20 if len(cl) >= 20 else None
            # 장중 선: 지수 분봉은 못 받아서 같은 방향 ETF 1분봉으로 (선물 자리는 장 전·후 포함)
            m = _spark(etf, ext)
            last_day = m[-1]["timestamp"][:10] if m else ""
            if m and not ext:      # 마지막 한 세션 (한국 시각으로 22:30~05:00이라 날짜가 걸쳐서, 마지막 봉에서 8시간 안)
                t_end = m[-1]["t"]; pts = [x for x in m if t_end - x["t"] <= 7 * 3600]
            else:
                t_end = m[-1]["t"] if m else 0; pts = [x for x in m if t_end - x["t"] <= 20 * 3600]
            out.append({"code": code, "name": nm, "close": close, "pct": pct, "prev": prev, "ma20": ma20, "date": (b.get("localTradedAt") or "")[:10],
                        "delay": b.get("delayTimeName"), "etf": etf, "points": [[x["timestamp"][11:16], float(x["closePrice"])] for x in pts],
                        "etf_prev": _etf_prev(etf, pts), "daily": cl[-60:]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("미국 지수 실패 %s: %s", code, type(exc).__name__)
            if code in old:      # 하나 실패해도 화면에서 그 지수가 빠지지 않게 지난 값 그대로 (2026-10-11)
                out.append(old[code])
    # 시장 판단(국장과 같은 생각): S&P500이 20일선 위 + 20일선이 오르는 중이면 상승, 아래 + 내리는 중이면 하락
    verdict = None
    try:
        sp = _nget("https://api.stock.naver.com/chart/foreign/index/.INX?periodType=dayCandle", h).get("priceInfos") or []
        cl = [float(x["closePrice"]) for x in sp]
        if len(cl) >= 30:
            ma, ma_prev = sum(cl[-20:]) / 20, sum(cl[-25:-5]) / 20
            above, up = cl[-1] > ma, ma > ma_prev
            verdict = {"state": "상승" if above and up else "하락" if not above and not up else "횡보", "vs_ma20_pct": round((cl[-1] / ma - 1) * 100, 2),
                       "cum20_pct": round((cl[-1] / cl[-21] - 1) * 100, 2)}
    except Exception:  # noqa: BLE001
        pass
    res = {"items": out, "verdict": verdict or (_IDX.get("x") or (0, {}))[1].get("verdict")}
    if out:
        _IDX["x"] = (time.time(), res); _disk_save()
    return res
