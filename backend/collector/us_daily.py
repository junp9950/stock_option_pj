"""미국 종목 일봉 쌓기 (2026-10-14 사용자 "미장도 추세추종 1단계 ㄱㄱ" — 국장 매수 규칙 그대로 신호·가상 기록, 주문 없음).
- 종목: Nasdaq 스크리너 거래소별(나스닥·뉴욕·아멕스) 시가총액 10억 달러↑ (약 2,700개). 일주일에 한 번 새로(표 us_symbols).
- 봉: 메리츠 Open API 해외 일봉(/market/v1/overseas/candles/days, 실시간 구분 '0'). 종목당 한 번에 2016년부터 받아짐.
  처음엔 2021-01-01부터, 매일은 최근 40개만 받아 덮음(표 us_daily_prices, 날짜 = 미국 거래일).
- 끝나지 않은 오늘 봉(미국 장중)은 넣지 않는다 — 미국 동부 16:30 전이면 그날 줄은 버림.
- 거래소 코드: 시세 OQ/NY/AX. 거래소를 잘못 넣으면 오류 없이 빈 목록이 와서 스크리너 거래소별 목록으로 정한다.
- 상장폐지 종목은 없음(살아 있는 종목만) → 긴 기간 검증엔 생존 편향. 1단계는 앞으로의 기록용.
- **메리츠 해외 일봉은 액면분할을 반영하지 않는다**(수정주가 구분 값과 상관없이 같음 — NVDA 2024-06-07 1,208 → 다음 날 121).
  그래서 분할을 찾아(표 us_splits) 분할 전 가격 ÷ 비율, 거래량 × 비율로 저장한다. 매일 받을 때도 알려진 분할은 같은 비율로 맞춰 넣는다.
  찾는 법(detect_splits): 시가·종가가 표준 분할 비율만큼 뛰고 거래량은 그 비율 안팎(실제 급등락은 거래량이 10~30배) →
  토스(분할 반영) 자료가 있는 날짜면 토스로 확인, 없으면 위 조건만(3:2·2:3은 거래량 조건 엄격). 2026-10-14 토스 대조: 후보 186건 중 진짜 96건, 조건만으로 95건 맞힘·12건 오탐.
- 거래소를 옮긴 종목(ETSY 2025-10 나스닥→뉴욕)은 메리츠가 옮긴 날부터만 줘서, 앞쪽은 토스 일봉(약 3년, 분할 반영)으로 채운다(fill_history).
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
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
    db.execute(text("create table if not exists us_splits (symbol varchar(16) not null, ex_date date not null, ratio double precision not null, "
                    "source varchar(16), created_at timestamptz default now(), primary key (symbol, ex_date))"))
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
    splits = _splits(db)

    def one(se):
        s, e = se
        return s, _fetch(s, e, full or s not in have)

    with ThreadPoolExecutor(4) as ex:      # 요청 사이 간격(0.12초)은 메리츠 Client가 지킴 — 기다리는 시간만 겹침
        for s, rows in ex.map(one, syms):
            if not rows:
                n_fail += 1
                continue
            sp = splits.get(s) or []
            db.execute(text("""insert into us_daily_prices (symbol, trading_date, open_price, high_price, low_price, close_price, volume)
                values (:s, :d, :o, :h, :l, :c, :v) on conflict (symbol, trading_date) do update set open_price = excluded.open_price,
                high_price = excluded.high_price, low_price = excluded.low_price, close_price = excluded.close_price, volume = excluded.volume"""),
                       [_adj_row(r, sp) for r in rows])
            db.commit()
            n_rows += len(rows)
    latest = db.execute(text("select max(trading_date) from us_daily_prices")).scalar()
    msg = f"미국 일봉 {len(syms)}종목 · {n_rows:,}행 · 실패 {n_fail} · 마지막 {latest} · {time.time() - t0:.0f}초"
    try:      # 새 분할 찾기 (최근 60일) — 찾으면 그 앞 가격을 바로잡음
        msg += " · " + detect_splits(db, since=latest - timedelta(days=60) if latest else None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("미국 분할 찾기 실패: %s", exc)
    return msg


def _splits(db: Session) -> dict:
    out: dict = {}
    for s, d, k in db.execute(text("select symbol, ex_date, ratio from us_splits order by ex_date")).all():
        out.setdefault(s, []).append((d, float(k)))
    return out


def _adj_row(r, sp) -> dict:
    """메리츠 원래 가격 → 분할 반영(그 날짜 뒤에 있었던 분할 비율로 나눔)."""
    a, b, o, h, l, c, v = r
    f = 1.0
    for d, k in sp:
        if b < d:
            f *= k
    return {"s": a, "d": b, "o": o / f if o else o, "h": h / f if h else h, "l": l / f if l else l, "c": c / f, "v": v * f}


SPLIT_K = [1.5, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 35, 40, 50, 60, 100]


def _toss_closes(sym: str) -> dict:
    from backend.services import us_stocks  # noqa: PLC0415
    try:
        return {x["timestamp"][:10]: float(x["closePrice"]) for x in us_stocks.candles(sym, "1d")}
    except Exception:  # noqa: BLE001
        return {}


def detect_splits(db: Session, since=None, symbols: list[str] | None = None, apply: bool = True) -> str:
    """분할 찾기 → us_splits 저장 + 그 앞 가격 바로잡기. since = 이 날짜 뒤만 본다(매일은 최근 60일)."""
    import pandas as pd  # noqa: PLC0415
    _ensure(db)
    q = "select symbol, trading_date, open_price, close_price, volume from us_daily_prices where trading_date >= :a"
    prm = {"a": (since - timedelta(days=40)) if since else date(2000, 1, 1)}
    if symbols:
        q += " and symbol = any(:x)"; prm["x"] = symbols
    df = pd.DataFrame(db.execute(text(q + " order by symbol, trading_date"), prm).all(), columns=["s", "d", "o", "c", "v"])
    if df.empty:
        return "분할 0"
    df["pc"] = df.groupby("s").c.shift(1)
    df["pv"] = df.groupby("s").v.transform(lambda x: x.shift(1).rolling(20, min_periods=5).mean())
    r1, r2 = df.pc / df.o, df.pc / df.c
    done = {(s, d) for s, d in db.execute(text("select symbol, ex_date from us_splits")).all()}
    cands = {}
    for k in SPLIT_K + [1 / x for x in SPLIT_K]:
        m = ((r1 / k - 1).abs() < 0.04) & ((r2 / k - 1).abs() < 0.15)
        if since:
            m &= df.d > since
        for x in df[m].itertuples():
            if (x.s, x.d) not in done:
                cands[(x.s, x.d)] = (k, None if not x.pv else x.v / x.pv)
    found = []
    for (s, d), (k, vx) in sorted(cands.items()):
        t = _toss_closes(s)
        m_ = {str(a): float(b) for a, b in db.execute(text("select trading_date, close_price from us_daily_prices where symbol = :s and trading_date between :a and :b"),
                                                       {"s": s, "a": d - timedelta(days=10), "b": d + timedelta(days=10)}).all()}
        days = sorted(set(t) & set(m_))
        bef = [x for x in days if x < str(d)][-1:]; aft = [x for x in days if x >= str(d)][:1]
        if bef and aft:              # 토스(분할 반영)로 확인: 메리츠만 뛰고 토스는 안 뛰었으면 분할
            ok, src = abs((t[aft[0]] / m_[aft[0]]) / (t[bef[0]] / m_[bef[0]]) / k - 1) < 0.05, "toss"
        else:                        # 토스 자료 없는 옛날: 거래량이 분할 비율 안팎 (3:2·2:3은 더 좁게)
            lo, hi = (0.7, 1.6) if k in (1.5, 1 / 1.5) else (0.3, 4.0)
            ok, src = vx is None or lo * k <= vx <= hi * k, "rule"
        if ok:
            found.append((s, d, k, src))
    if apply:
        for s, d, k, src in found:
            db.execute(text("insert into us_splits (symbol, ex_date, ratio, source) values (:s, :d, :k, :src) on conflict do nothing"), {"s": s, "d": d, "k": k, "src": src})
            db.execute(text("update us_daily_prices set open_price = open_price / :k, high_price = high_price / :k, low_price = low_price / :k, "
                            "close_price = close_price / :k, volume = volume * :k where symbol = :s and trading_date < :d"), {"s": s, "d": d, "k": k})
            db.commit()
            logger.info("미국 분할 바로잡음 %s %s 비율 %.3f (%s)", s, d, k, src)
    return f"분할 {len(found)}건" + (f" ({', '.join(f'{s} {d}' for s, d, _, _ in found[:5])})" if found else "")


def fill_history(db: Session) -> str:
    """메리츠 자료가 2021년보다 늦게 시작하는 종목(거래소 옮김 · 새 상장)의 앞쪽을 토스 일봉(분할 반영)으로 채움 — 메리츠 행은 안 덮음."""
    import time as _t  # noqa: PLC0415
    from backend.services import us_stocks  # noqa: PLC0415
    rows = db.execute(text("select p.symbol, min(p.trading_date) from us_daily_prices p join us_symbols s on s.symbol = p.symbol and s.active "
                           "group by 1 having min(p.trading_date) > date '2021-02-01'")).all()
    n_sym = n_rows = 0
    for s, first in rows:
        try:
            cs = us_stocks.candles(s, "1d")
        except Exception:  # noqa: BLE001
            continue
        add = [{"s": s, "d": date.fromisoformat(x["timestamp"][:10]), "o": float(x["openPrice"]), "h": float(x["highPrice"]), "l": float(x["lowPrice"]),
                "c": float(x["closePrice"]), "v": float(x.get("volume") or 0)} for x in cs if x["timestamp"][:10] < str(first)]
        if add:
            db.execute(text("""insert into us_daily_prices (symbol, trading_date, open_price, high_price, low_price, close_price, volume)
                values (:s, :d, :o, :h, :l, :c, :v) on conflict (symbol, trading_date) do nothing"""), add)
            db.commit()
            n_sym += 1; n_rows += len(add)
        _t.sleep(0.15)
    return f"앞쪽 채움 {n_sym}종목 · {n_rows:,}행 (대상 {len(rows)})"
