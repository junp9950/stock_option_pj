"""미장 매수 신호 + 가상 계좌 기록 (2026-10-14 사용자 "1단계는 일단 ㄱㄱ, 2단계(자동 주문)는 나중에 할 생각 있다").

국장 매수 규칙(stock_signals._close_scores · V1.0 + 돌파 매수 + 주도주)을 미국 일봉(us_daily_prices)에 그대로 돌린다. 주문은 없다.
- 거래대금은 원화로 환산(1달러 = 1,400원 고정)해서 국장 기준(20일 평균 30억↑, 시장 국면 10억↑)을 그대로 쓴다.
  종목이 시총 10억 달러↑라 거의 다 통과 — 사실상 시총 10억 달러↑ 전체.
- 반도체·AI 특별(국장 테마 묶음)은 미장엔 없음. 손절가 = 신호 날 저가 × 0.99, 센트 아래 버림.
- 시장 국면 = 국장과 같은 정의(같은 무게 평균 등락 → 20일선·기울기), 미국 종목으로 계산.

가상 계좌(표 forward_log, version 'US1.0', 상태 settings us_fwd_v1_state) — 앞으로의 기록, 지난 날짜를 채우지 않는다:
  UC = 종가 신호 → 같은 종가 (2단계에서 장 마감 15분 전 신호 + 장 마감 시장가(MOC)로 할 자리 · 지금 규칙 먼저 10칸, 남는 칸 돌파 매수)
  UO = 같은 후보 → 다음 날 시가
  UL = 주도주 소량 (0.10% · 2종목)
  공통: 거래당 위험 0.5% · 손절 = 신호 날 저가 −1%(시가가 아래면 시가) · 종가 < EMA21 → 다음 날 시가 정리 ·
        비용 매수 0.1% + 매도 0.1%(수수료 어림, 환전 비용 뺌) · 시장 하락이면 신규 없음.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import threading
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services import account_engine as engine

logger = logging.getLogger(__name__)
KRW_PER_USD = 1400.0
VERSION = "US1.0"
STATE_KEY = "us_fwd_v1_state"
CONFIG = {"slots": 10, "risk": 0.005, "lead_slots": 2, "lead_risk": 0.0010, "cost_buy": 0.001, "cost_sell": 0.001}
_LOCK = threading.Lock()
_C: dict = {"key": None, "frames": None, "bull": None, "reg": None, "scores": {}}


def _cent(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def data_latest(db: Session):
    """봉이 '거의 다' 들어온 마지막 미국 거래일 (전 거래일 행 수의 80%↑) — 수집 중간에 반쪽 날짜로 계산하지 않게."""
    rows = db.execute(text("select trading_date, count(*) from us_daily_prices where trading_date >= "
                           "(select max(trading_date) from us_daily_prices) - 10 group by 1 order by 1 desc limit 2")).all()
    if not rows:
        return None
    if len(rows) == 2 and rows[0][1] < rows[1][1] * 0.8:
        return rows[1][0]
    return rows[0][0]


def _frames(db: Session, latest) -> dict:
    if _C["key"] == latest and _C["frames"] is not None:
        return _C["frames"]
    rows = db.execute(text("""select p.symbol, p.trading_date, p.open_price, p.high_price, p.low_price, p.close_price, p.volume
        from us_daily_prices p join us_symbols s on s.symbol = p.symbol and s.active
        where p.trading_date >= cast(:d as date) - 800 and p.trading_date <= :d"""), {"d": latest}).all()
    df = pd.DataFrame(rows, columns=["s", "d", "o", "h", "l", "c", "v"])
    piv = {k: df.pivot(index="d", columns="s", values=k).sort_index().astype("float32") for k in ("o", "h", "l", "c", "v")}
    piv["tv"] = (piv["c"] * piv["v"] * KRW_PER_USD).astype("float32")
    from backend.screener.market_regime import regime_series  # noqa: PLC0415
    from backend.services.trading_rules import market_returns  # noqa: PLC0415
    reg = regime_series((market_returns(piv["c"], piv["tv"]) * 100).to_dict())
    _C.update(key=latest, frames=piv, reg=reg, bull={d: r["state"] in ("상승", "횡보") for d, r in reg.items()}, scores={}, rsh=None)
    return piv


def scores(db: Session, day=None) -> dict:
    """그날(없으면 마지막 날) 종가 기준 점수 — stock_signals._close_scores 그대로."""
    from backend.services.stock_signals import _close_scores  # noqa: PLC0415
    latest = data_latest(db)
    if latest is None:
        return {"date": None, "scores": {}, "brk": {}}
    with _LOCK:
        P = _frames(db, latest)
        day = day or latest
        if day in _C["scores"]:
            return _C["scores"][day]
        cut = {k: v.loc[:day] for k, v in P.items()}
        if str(cut["c"].index[-1]) != str(day):
            return {"date": str(day), "scores": {}, "brk": {}}
        out = _close_scores(db, day, frames=cut, semi=frozenset(), stop_round=_cent)
        _C["scores"][day] = out
        return out


def regime(db: Session, day=None) -> dict | None:
    latest = data_latest(db)
    if latest is None:
        return None
    with _LOCK:
        _frames(db, latest)
        return (_C["reg"] or {}).get(day or latest)


def bull_days(db: Session) -> dict:
    """날짜별 상승·횡보 여부 (차트 신호용 — stock_signals._bull_days와 같은 모양)."""
    latest = data_latest(db)
    if latest is None:
        return {}
    with _LOCK:
        _frames(db, latest)
        return _C["bull"] or {}


def rs_hist(db: Session) -> dict:
    """날짜별 RS (stock_signals.rs_hist와 같은 모양: {"dates": [...], "rs": {code: 배열}}) — 차트에 지난 날짜 매수를 찍으려면 그날의 전 종목 순위가 필요."""
    from backend.services.trading_rules import relative_strength  # noqa: PLC0415
    latest = data_latest(db)
    if latest is None:
        return {}
    with _LOCK:
        P = _frames(db, latest)
        if _C.get("rsh") is None:
            RS = relative_strength(P["c"], P["tv"]).iloc[-270:]
            _C["rsh"] = {"date": str(latest), "dates": [str(d) for d in RS.index],
                         "rs": {c: RS[c].to_numpy(dtype="float32") for c in RS.columns if RS[c].notna().any()}}
        return _C["rsh"]


def _names(db: Session) -> dict:
    try:      # 한글 이름은 미장 탭 목록과 같게 (아는 것만)
        from backend.services.us_stocks import _universe_base  # noqa: PLC0415
        ko = {x["code"]: x["name"] for x in _universe_base() if x["name"] != x["en"]}
    except Exception:  # noqa: BLE001
        ko = {}
    return {s: (ko.get(s) or n or s, sec or "") for s, n, sec in db.execute(text("select symbol, name, sector from us_symbols")).all()}


def _short(nm: str) -> str:
    import re  # noqa: PLC0415
    return re.sub(r"\s+(Common Stock|Class [A-C].*|Ordinary Shares.*|American Depositary.*|Inc\.?|Corporation|Corp\.?|Holdings?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|ASA|SE|AG|Co\.)(\s.*)?$", "", nm or "").strip(" ,") or nm


def signal_list(db: Session) -> dict:
    """화면·알림용: 매수(V1.0) · 돌파 매수 · 주도주, RS 높은 순."""
    from backend.services.forward_log import _cands  # noqa: PLC0415
    sc = scores(db)
    if not sc.get("date"):
        return {"date": None, "items": [], "brk": [], "leads": [], "regime": None}
    nm = _names(db)
    rg = regime(db) or {}

    def deco(xs, kind):
        out = []
        for x in xs:
            n, sec = nm.get(x["code"], (x["code"], ""))
            out.append({"code": x["code"], "name": _short(n), "sector": sec, "price": round(float(x["price"]), 2), "stop": x["stop"],
                        "risk": round(x["risk"] * 100, 1), "rs": round(x["rs"], 0) if x.get("rs") is not None else None, "score": x["score"],
                        "kind": kind, "half": x["size_mult"] < 1, "state": x.get("state") or []})
        return out
    s = sc["scores"]
    buy = _cands(s)
    brk = _cands({c: {**v, "buy": True} for c, v in (sc.get("brk") or {}).items()})
    leads = _cands(s, lead=True)
    return {"date": sc["date"], "regime": rg.get("state"), "vs_ma20": rg.get("vs_ma20_pct"), "universe": len(s),
            "items": deco(buy, "매수"), "brk": deco(brk, "돌파 매수"), "leads": deco(leads, "주도주")}


# ── 가상 계좌 ─────────────────────────────────────────────

def _bars(db: Session, codes: list[str], upto) -> dict:
    if not codes:
        return {}
    rows = db.execute(text("""select symbol, trading_date, open_price, high_price, low_price, close_price from us_daily_prices
        where symbol = any(:c) and trading_date <= :d and trading_date >= cast(:d as date) - 200 order by symbol, trading_date"""),
                      {"c": codes, "d": upto}).all()
    out: dict = {}
    for c, d, o, h, l, cl in rows:
        lst = out.setdefault(c, [])
        prev = lst[-1][4] if lst else None
        lst.append((d, float(o or 0), float(h or 0), float(l or 0), float(cl or 0), (float(cl) / prev - 1) * 100 if prev else 0.0))
    return out


def _save(db: Session, d, kind: str, payload: dict) -> None:
    from backend.services.forward_log import _ensure  # noqa: PLC0415
    _ensure(db)
    db.execute(text("""insert into forward_log (trading_date, kind, version, payload) values (:d, :k, :v, cast(:p as jsonb))
        on conflict (trading_date, kind, version) do update set payload = excluded.payload"""),
               {"d": d, "k": kind, "v": VERSION, "p": json.dumps(payload, ensure_ascii=False, default=float)})
    db.commit()


def record(db: Session) -> dict:
    """새로 들어온 미국 거래일마다 가상 계좌를 하루씩 진행. 처음 실행이면 마지막 날 하루만(지난 날짜를 채우지 않음)."""
    from backend.services.forward_log import _cands  # noqa: PLC0415
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    latest = data_latest(db)
    if latest is None:
        return {"days": [], "msg": "미국 일봉 없음"}
    st = _get(db, STATE_KEY, {}) or {}
    last = date.fromisoformat(st["last"]) if st.get("last") else None
    if last is not None and last >= latest:
        return {"days": [], "msg": "새 거래일 없음", "last": str(last)}
    days = [r[0] for r in db.execute(text("select distinct trading_date from us_daily_prices where trading_date > :a and trading_date <= :b order by 1"),
                                     {"a": last or latest - timedelta(days=1), "b": latest}).all()]
    if not days:
        days = [latest]
    reports = []
    for day in days:
        sc = scores(db, day)
        s = sc.get("scores") or {}
        if not s:
            continue
        bull = bool((_C["bull"] or {}).get(day, False))
        main = _cands(s) + _cands({c: {**v, "buy": True} for c, v in (sc.get("brk") or {}).items()})
        leads = _cands(s, lead=True)
        specs = [("UC", main if bull else [], "close", CONFIG["slots"], CONFIG["risk"]),
                 ("UO", main if bull else [], "next_open", CONFIG["slots"], CONFIG["risk"]),
                 ("UL", leads if bull else [], "close", CONFIG["lead_slots"], CONFIG["lead_risk"])]
        codes = set()
        for name, cands, *_ in specs:
            a = st.setdefault(name, engine.new_account())
            codes.update(a["pos"]); codes.update(x["code"] for x in a["pending"] + cands)
        bars = _bars(db, sorted(codes), day)
        ctx = engine.day_context(bars, day)
        before = {name: len(st[name]["trades"]) for name, *_ in specs}
        rep = [engine.advance(st[name], name, day, ctx, cands, entry, slots=slots, risk=risk,
                              cost_buy=CONFIG["cost_buy"], cost_sell=CONFIG["cost_sell"]) for name, cands, entry, slots, risk in specs]
        for r in rep:
            r["closed"] = st[r["acct"]]["trades"][before[r["acct"]]:]
            r["exit_next"] = [c for c, p in st[r["acct"]]["pos"].items() if p.get("exit_next")]
        report = {"bull": bull, "accounts": rep, "n_main": len(main), "n_leads": len(leads)}
        _save(db, day, "close", {"bull": bull, "universe": len(s), "cands": main, "leads": leads})
        _save(db, day, "acct", report)
        st.update(last=str(day), version=VERSION, last_report=report)
        _put(db, STATE_KEY, st)
        reports.append((day, report))
    return {"days": [str(d) for d, _ in reports], "report": reports[-1][1] if reports else None, "msg": f"{len(reports)}거래일 진행"}


def state(db: Session) -> dict:
    """화면용 가상 계좌 요약."""
    from backend.services.telegram import _get  # noqa: PLC0415
    st = _get(db, STATE_KEY, {}) or {}
    nm = _names(db)
    out = {"last": st.get("last"), "accounts": []}
    for k, lab in (("UC", "종가 진입"), ("UO", "다음 날 시가 진입"), ("UL", "주도주 소량")):
        a = st.get(k)
        if not a:
            continue
        eq = a["eq"][-1][1] if a.get("eq") else 1.0
        out["accounts"].append({"acct": k, "label": lab, "ret": round((eq - 1) * 100, 2), "start": a["eq"][0][0] if a.get("eq") else None,
                                "pos": [{"code": c, "name": _short(nm.get(c, (c, ""))[0]), "d0": p["d0"], "px0": round(p["px0"], 2), "stop": round(p["stop"], 2),
                                         "exit_next": bool(p.get("exit_next"))} for c, p in a["pos"].items()],
                                "trades": [{**t, "name": _short(nm.get(t["code"], (t["code"], ""))[0])} for t in a["trades"][-20:]]})
    return out


def morning_text(db: Session, rec: dict) -> str | None:
    """아침 텔레그램 (사장님 방). 새 거래일이 없으면 None."""
    if not rec.get("days"):
        return None
    L = signal_list(db)
    rep = rec.get("report") or {}
    d = date.fromisoformat(L["date"])
    wd = "월화수목금토일"[d.weekday()]
    g = {"상승": "▲ 상승 · 매매 가능", "횡보": "■ 횡보 · 매매 가능", "하락": "▼ 하락 · 쉬기"}.get(L["regime"] or "", "-")
    out = [f"🇺🇸 <b>미장 신호 — {d.month}/{d.day}({wd}) 미국 종가</b>",
           "국장과 같은 규칙 · 기록만 (주문 없음)",
           f"시장: {g}" + (f" (20일선 {L['vs_ma20']:+.1f}%)" if L.get("vs_ma20") is not None else ""),
           "  └ 국장과 같은 계산: 시총 10억 달러↑ 종목 같은 무게 평균 (S&P500과 다를 수 있음)"]

    def line(i, x):
        nm_ = "" if x["name"].upper() == x["code"] else " " + x["name"][:18]
        return (f"{i}. {x['code']}{nm_} ${x['price']:,.2f} · 손절 ${x['stop']:,.2f} (−{x['risk']}%) · RS {x['rs']:.0f}"
                + (" · 수량 절반" if x["half"] else ""))
    if L["items"]:
        out.append(f"\n<b>매수 신호 {len(L['items'])}개</b> (RS 높은 순)")
        out += [line(i, x) for i, x in enumerate(L["items"][:10], 1)]
    else:
        out.append("\n매수 신호 없음")
    room = max(0, 10 - len(L["items"]))
    if L["brk"] and room:
        out.append(f"\n<b>돌파 매수 {len(L['brk'])}개</b> (남는 칸 {room})")
        out += [line(i, x) for i, x in enumerate(L["brk"][:room], 1)]
    if L["leads"]:
        out.append(f"\n🔥 주도주 {len(L['leads'])}개: " + " · ".join(f"{x['code']}" for x in L["leads"][:5]))
    if L["regime"] == "하락":
        out.append("\n시장 하락이라 가상 계좌는 새로 사지 않음")
    acc = {r["acct"]: r for r in rep.get("accounts", [])}
    uc = acc.get("UC")
    if uc:
        out.append(f"\n가상 계좌(종가 진입): {(uc['equity'] - 1) * 100:+.2f}% · 보유 {uc['npos']}"
                   + (f" · 오늘 산 것 {', '.join(uc['selected'])}" if uc["selected"] else ""))
        for t in uc.get("closed") or []:
            out.append(f"  정리 {t['code']} {t['why']} {t['R']:+.2f}R")
        if uc.get("exit_next"):
            out.append("  ⚠ 다음 장 시가 정리(21일선 아래): " + ", ".join(uc["exit_next"]))
    return "\n".join(out)
