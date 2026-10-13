"""미국 종목 일봉 쌓기 (2026-10-14 사용자 "미장도 추세추종 1단계 ㄱㄱ" — 국장 매수 규칙 그대로 신호·가상 기록, 주문 없음).
- 종목: Nasdaq 스크리너 거래소별(나스닥·뉴욕·아멕스) 시가총액 10억 달러↑ (약 2,700개). 일주일에 한 번 새로(표 us_symbols).
- 봉: 메리츠 Open API 해외 일봉(/market/v1/overseas/candles/days, 실시간 구분 '0'). 종목당 한 번에 2016년부터 받아짐.
  처음엔 2021-01-01부터, 매일은 최근 40개만 받아 덮음(표 us_daily_prices, 날짜 = 미국 거래일).
- 끝나지 않은 오늘 봉(미국 장중)은 넣지 않는다 — 미국 동부 16:30 전이면 그날 줄은 버림.
- 거래소 코드: 시세 OQ/NY/AX. 거래소를 잘못 넣으면 오류 없이 빈 목록이 와서 스크리너 거래소별 목록으로 정한다.
- 상장폐지 종목은 없음(살아 있는 종목만) → 긴 기간 검증엔 생존 편향. 1단계는 앞으로의 기록용.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
EXCH = {"nasdaq": "OQ", "nyse": "NY", "amex": "AX"}
MIN_CAP = 1e9
START = "20210101"


def _ensure(db: Session) -> None:
    db.execute(text("""create table if not exists us_symbols (symbol varchar(16) primary key, exch varchar(2) not null, name text,
        sector text, industry text, cap double precision, updated_at timestamptz default now(), active boolean default true)"""))
    db.execute(text("""create table if not exists us_daily_prices (symbol varchar(16) not null, trading_date date not null,
        open_price double precision, high_price double precision, low_price double precision, close_price double precision,
        volume double precision, primary key (symbol, trading_date))"""))
    db.execute(text("create index if not exists us_daily_prices_date on us_daily_prices (trading_date)"))
    db.commit()


def refresh_symbols(db: Session) -> int:
    """스크리너 거래소별 목록 → us_symbols. 목록에서 빠진 종목은 active = false (봉은 남김)."""
    _ensure(db)
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    rows = {}
    for ex, cd in EXCH.items():
        j = requests.get(f"https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0&download=true&exchange={ex}",
                         headers=h, timeout=40).json()
        for r in (j.get("data") or {}).get("rows") or []:
            sym = (r.get("symbol") or "").strip().upper().replace("/", ".")      # 스크리너 BRK/B → 메리츠 BRK.B
            try:
                cap = float(r.get("marketCap") or 0)
            except ValueError:
                cap = 0.0
            if cap < MIN_CAP or not sym or not sym.replace(".", "").isalnum():
                continue
            rows[sym] = {"s": sym, "e": cd, "n": (r.get("name") or "")[:200], "sec": r.get("sector") or "", "ind": r.get("industry") or "", "cap": cap}
    if len(rows) < 1500:            # 스크리너가 덜 왔으면 목록을 건드리지 않음
        raise RuntimeError(f"미국 종목 목록이 너무 적음 ({len(rows)})")
    db.execute(text("update us_symbols set active = false"))
    for x in rows.values():
        db.execute(text("""insert into us_symbols (symbol, exch, name, sector, industry, cap, updated_at, active) values (:s, :e, :n, :sec, :ind, :cap, now(), true)
            on conflict (symbol) do update set exch = excluded.exch, name = excluded.name, sector = excluded.sector, industry = excluded.industry,
            cap = excluded.cap, updated_at = now(), active = true"""), x)
    db.commit()
    return len(rows)


def _num(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def _fetch(sym: str, exch: str, full: bool) -> list[tuple]:
    from backend.services import meritz  # noqa: PLC0415
    q = {"mrkt_div_code": "OV", "mrkt_cls_code": exch, "iscd": sym, "dely_rltm_cls_code": "0", "mod_stpr_cls_code": "1"}
    if full:
        q.update({"from": START, "to": datetime.now(ET).strftime("%Y%m%d")})
    for k in range(3):
        res = meritz.call("GET", "/market/v1/overseas/candles/days", q)
        if res["ok"]:
            break
        if res["rsp_cd"] not in ("EGW00200", "NET"):
            return []
        time.sleep(1 + k)
    else:
        return []
    now = datetime.now(ET)
    unfinished = now.date() if (now.hour, now.minute) < (16, 30) else None
    out = []
    for r in res["data"] or []:
        try:
            d = date(int(r["date"][:4]), int(r["date"][4:6]), int(r["date"][6:8]))
        except (KeyError, ValueError, TypeError):
            continue
        if d == unfinished or d > now.date():
            continue
        o, hi, lo, c = _num(r.get("oprc")), _num(r.get("hprc")), _num(r.get("lprc")), _num(r.get("prpr"))
        if c is None:
            continue
        out.append((sym, d, o, hi, lo, c, float(r.get("acml_vol") or 0)))
    return out


def collect(db: Session, full: bool = False, symbols: list[str] | None = None) -> str:
    """full = 2021년부터 전부(처음 한 번 · 새 종목), 아니면 최근 40개. 새 종목(봉 없음)은 자동으로 full."""
    _ensure(db)
    if not db.execute(text("select 1 from us_symbols limit 1")).scalar():
        refresh_symbols(db)
    syms = db.execute(text("select symbol, exch from us_symbols where active" + (" and symbol = any(:x)" if symbols else "") + " order by cap desc"),
                      {"x": symbols} if symbols else {}).all()
    have = {r[0] for r in db.execute(text("select distinct symbol from us_daily_prices where trading_date >= current_date - 30")).all()}
    t0, n_rows, n_fail = time.time(), 0, 0

    def one(se):
        s, e = se
        return s, _fetch(s, e, full or s not in have)

    with ThreadPoolExecutor(4) as ex:      # 요청 사이 간격(0.12초)은 메리츠 Client가 지킴 — 기다리는 시간만 겹침
        for s, rows in ex.map(one, syms):
            if not rows:
                n_fail += 1
                continue
            db.execute(text("""insert into us_daily_prices (symbol, trading_date, open_price, high_price, low_price, close_price, volume)
                values (:s, :d, :o, :h, :l, :c, :v) on conflict (symbol, trading_date) do update set open_price = excluded.open_price,
                high_price = excluded.high_price, low_price = excluded.low_price, close_price = excluded.close_price, volume = excluded.volume"""),
                       [{"s": a, "d": b, "o": c, "h": d_, "l": e_, "c": f, "v": g} for a, b, c, d_, e_, f, g in rows])
            db.commit()
            n_rows += len(rows)
    latest = db.execute(text("select max(trading_date) from us_daily_prices")).scalar()
    return f"미국 일봉 {len(syms)}종목 · {n_rows:,}행 · 실패 {n_fail} · 마지막 {latest} · {time.time() - t0:.0f}초"
