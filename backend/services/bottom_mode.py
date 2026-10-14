"""바닥 모으기 모드 (2026-10-15 사용자 "그걸 감지해서 하따 모드로 니가 알아서 켜 주면 안 되나? 손절은 넓게 잡고 바닥에서 모아 가는 식으로").

켜짐: 200일선 위 종목 비율(거래대금 20일 평균 30억↑ 종목)이 35% 아래로 처음 내려간 날(앞 40거래일 동안 35% 아래가 없었을 때).
나눠 사기 (각각 그날 후보 10종목 같은 무게, 사장님이 직접 매수 — 자동 매수 아님):
  1차 = 켜진 날 · 2차 = 같은 무게 지수가 켜진 날보다 5% 더 빠진 날 · 3차 = 폭이 바닥에서 5%p 회복한 날 (정리일 전까지만)
후보: 거래대금 20일 평균 100억↑ 중 최근 20거래일 가장 많이 빠진 10종목 (바닥에선 '강한 종목'이 아니라 '많이 빠진 종목'이 튐).
손절: 산 값 −25% (메리츠 자동 손절 주문, stop_orders mode 'bottom') · 정리: 켜진 날부터 20거래일째 15:21 종가 시장가.
12년 검증(tmp_claude/bottom_test*.py, 10번): 강도 상위 10 = −2.5%(기각) · 많이 빠진 10 −25% 손절 20일 +7.3%(8/10, 최악 −18%) ·
  60일도 +7.4%로 비슷해 짧게(사용자가 올린 사이클 글 '1단계 반전은 빨리 정리') · 같은 무게 지수 60일 +12.5% — 이득은 종목보다 켜지는 시점. 표본 10번이라 '시험 중'.
상태: settings 'bottom_mode' = {cycle: {on, exit, idx0, low_b, tranches[{n, date, why, items}]} | None, history[]}
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
KEY = "bottom_mode"
ON_BELOW = 35.0
HOLD_DAYS = 20
STOP_PCT = 0.25


def _nth_after(d: date, n: int) -> date:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    k = 0
    while k < n:
        d += timedelta(days=1)
        if is_trading_day(d):
            k += 1
    return d


def _series(db: Session):
    """(날짜 목록, 200일선 위 비율 %, 같은 무게 지수, 종가 표, 거래대금 20일 평균 표) — 최근 ~320거래일."""
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    start = db.execute(text("select min(d) from (select distinct trading_date d from spot_daily_prices order by 1 desc limit 320) x")).scalar()
    rows = db.execute(text("select trading_date, stock_code, close_price, trading_value from spot_daily_prices where trading_date >= :s"), {"s": start}).all()
    df = pd.DataFrame(rows, columns=["d", "c", "close", "tv"])
    C = df.pivot(index="d", columns="c", values="close").sort_index().astype(float)
    T = df.pivot(index="d", columns="c", values="tv").sort_index().astype(float)
    tv20 = T.rolling(20, min_periods=15).mean()
    liq = tv20 >= 3e9
    s200 = C.rolling(200, min_periods=180).mean()
    ok = liq & s200.notna()
    b = ((C > s200) & ok).sum(axis=1) / ok.sum(axis=1).replace(0, np.nan) * 100
    ret = C.pct_change(fill_method=None).where(liq).clip(-.3, .3).mean(axis=1).fillna(0)
    idx = (1 + ret).cumprod()
    return b, idx, C, tv20


def _picks(db: Session, C, tv20, d) -> list[dict]:
    import numpy as np  # noqa: PLC0415
    i = C.index.get_loc(d)
    r20 = C.iloc[i] / C.iloc[i - 20] - 1
    cand = r20[(tv20.iloc[i] >= 1e10) & C.iloc[i].notna() & r20.notna()].sort_values()[:10]
    names = dict(db.execute(text("select code, name from stocks where code = any(:c)"), {"c": list(cand.index)}).all())
    from backend.utils.ticks import tick_floor  # noqa: PLC0415
    return [{"code": c, "name": names.get(c, c), "close": float(C.iloc[i][c]), "r20": round(float(v) * 100, 1),
             "stop": int(tick_floor(float(C.iloc[i][c]) * (1 - STOP_PCT)))} for c, v in cand.items() if np.isfinite(v)]


def _get(db: Session) -> dict:
    from backend.services.telegram import _get as g  # noqa: PLC0415
    s = g(db, KEY, None) or {}
    s.setdefault("cycle", None); s.setdefault("history", [])
    return s


def _put(db: Session, s: dict) -> None:
    from backend.services.telegram import _put as p  # noqa: PLC0415
    s["history"] = s["history"][-20:]
    p(db, KEY, s)


def _tranche_text(t: dict, cyc: dict) -> str:
    lines = [f"<b>{t['n']}차 매수</b> — {t['why']}", "최근 20일 가장 많이 빠진 거래대금 큰 10종목 (같은 금액씩):"]
    for x in t["items"]:
        lines.append(f"· {x['name']} {x['close']:,.0f} ({x['r20']:+.0f}%) · 손절 {x['stop']:,}")
    lines.append(f"손절 = 산 값 −25% (자동 주문) · 정리 = {date.fromisoformat(cyc['exit']).month}/{date.fromisoformat(cyc['exit']).day} 15:21 종가 자동 매도")
    lines.append("오늘 장 후(넥스트레이드 ~20:00)나 내일 아침에 사시면 됩니다")
    return "\n".join(lines)


def check(db: Session, send: bool = True, need_today: bool = True) -> str:
    """장 마감 뒤 하루 한 번. 켜짐·2차·3차·정리 하루 전 알림."""
    s = _get(db)
    b, idx, C, tv20 = _series(db)
    d = b.index[-1]
    today = str(d)
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    if need_today and today != str(datetime.now(ZoneInfo("Asia/Seoul")).date()):
        return f"오늘 일봉 아직 없음 (마지막 {today})"
    if s.get("last") == today:
        return f"{today} 이미 확인 · 폭 {b.iloc[-1]:.0f}%"
    s["last"] = today
    msgs = _step(db, s, b, idx, C, tv20)
    cyc = s["cycle"]
    _put(db, s)
    if send and msgs:
        from backend.services.telegram import owner_chats  # noqa: PLC0415
        from backend.services.telegram import send as tg  # noqa: PLC0415
        for c in owner_chats(db):
            for m in msgs:
                tg(db, m, c, html=True)
    return f"{today} 폭 {b.iloc[-1]:.0f}% · " + (f"켜짐({cyc['on']}~{cyc['exit']}, 매수 {len(cyc['tranches'])}번)" if cyc else "꺼짐") + (f" · 알림 {len(msgs)}" if msgs else "")


def _step(db: Session, s: dict, b, idx, C, tv20) -> list[str]:
    """마지막 날 기준 한 걸음 (켜짐·2차·3차·정리 전날). s를 바꾸고 알림 문장을 돌려준다."""
    d = b.index[-1]
    today = str(d)
    msgs = []
    cyc = s["cycle"]
    if cyc and today > cyc["exit"]:
        s["history"].append({k: cyc[k] for k in ("on", "exit")} | {"tranches": [{"n": t["n"], "date": t["date"]} for t in cyc["tranches"]]})
        s["cycle"] = cyc = None
    if cyc is None:
        prev = b.iloc[-41:-1]
        if b.iloc[-1] < ON_BELOW and len(prev) == 40 and (prev >= ON_BELOW).all():
            cyc = {"on": today, "exit": str(_nth_after(d, HOLD_DAYS)), "idx0": float(idx.iloc[-1]), "low_b": float(b.iloc[-1]), "tranches": []}
            t = {"n": 1, "date": today, "why": f"200일선 위 종목 {b.iloc[-1]:.0f}% (35% 아래로 처음)", "items": _picks(db, C, tv20, d)}
            cyc["tranches"].append(t)
            s["cycle"] = cyc
            msgs.append("🟣 <b>바닥 모으기 모드 켜짐 (시험 중)</b>\n" + _tranche_text(t, cyc)
                        + "\n\n2차 = 지수가 오늘보다 5% 더 빠지면 · 3차 = 폭이 바닥에서 5%p 회복하면 — 그때 다시 알려 드립니다")
    elif today > cyc["on"]:
        done = {t["n"] for t in cyc["tranches"]}
        cyc["low_b"] = min(cyc["low_b"], float(b.iloc[-1]))
        if today < cyc["exit"]:
            if 2 not in done and idx.iloc[-1] <= cyc["idx0"] * 0.95:
                t = {"n": 2, "date": today, "why": f"지수가 켜진 날보다 {(idx.iloc[-1] / cyc['idx0'] - 1) * 100:.1f}%", "items": _picks(db, C, tv20, d)}
                cyc["tranches"].append(t); msgs.append("🟣 바닥 모으기\n" + _tranche_text(t, cyc))
            if 3 not in done and b.iloc[-1] >= cyc["low_b"] + 5:
                t = {"n": 3, "date": today, "why": f"폭이 바닥 {cyc['low_b']:.0f}% → {b.iloc[-1]:.0f}% 회복 (돌아서는 신호)", "items": _picks(db, C, tv20, d)}
                cyc["tranches"].append(t); msgs.append("🟣 바닥 모으기\n" + _tranche_text(t, cyc))
        if str(_nth_after(d, 1)) == cyc["exit"]:
            msgs.append(f"🟣 바닥 모으기: 내일({cyc['exit'][5:]}) 15:21 종가에 이 모드로 산 종목 자동 매도 (20거래일 정리)")
    return msgs


_NOW: dict = {"key": None, "v": None}
STATS = {"n": 10, "avg": 7.3, "win": 8, "worst": -17.8, "best_idx60": 12.5}


def _trading_count(a: str, b: str) -> int:
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    d, e, k = date.fromisoformat(a), date.fromisoformat(b), 0
    while d < e:
        d += timedelta(days=1)
        k += is_trading_day(d)
    return k


def now(db: Session, demo: str | None = None) -> dict:
    """오늘 탭 '바닥 모으기' 화면용 (공개 — 계좌 정보 없음). demo='YYYY-MM-DD' = 그날까지 다시 돌려 본 상태(화면 시험용, 저장 안 함)."""
    from backend.services.stock_signals import _data_latest  # noqa: PLC0415
    latest = str(_data_latest(db))
    key = (latest, demo)
    if _NOW["key"] == key:
        return _NOW["v"]
    b, idx, C, tv20 = _series(db)
    if demo:
        end = date.fromisoformat(demo)
        st = {"cycle": None, "history": []}
        days = [d for d in b.index if d <= end][-45:]
        for d in days:
            _step(db, st, b[:d], idx[:d], C[:d], tv20[:d])
        b, idx = b[:end], idx[:end]
    else:
        st = _get(db)
    cyc = st["cycle"]
    if cyc and str(b.index[-1]) > cyc["exit"]:
        cyc = None
    bn = float(b.iloc[-1])
    v = {"date": str(b.index[-1]), "b200": round(bn, 1), "on_below": ON_BELOW, "hold": HOLD_DAYS, "stop_pct": int(STOP_PCT * 100),
         "recent": [{"d": str(d), "v": round(float(x), 1)} for d, x in b.iloc[-10:].items()], "stats": STATS, "demo": demo, "active": bool(cyc)}
    if cyc:
        done = {t["n"] for t in cyc["tranches"]}
        chg = (float(idx.iloc[-1]) / cyc["idx0"] - 1) * 100
        last = C.loc[b.index[-1]]
        trs = [{**t, "items": [{**x, "now": float(last[x["code"]]) if x["code"] in last and last[x["code"]] == last[x["code"]] else None} for x in t["items"]]}
               for t in cyc["tranches"]]
        for t in trs:
            for x in t["items"]:
                x["pnl"] = round((x["now"] / x["close"] - 1) * 100, 1) if x["now"] else None
        v.update(on=cyc["on"], exit=cyc["exit"], day=_trading_count(cyc["on"], str(b.index[-1])), tranches=trs,
                 next2={"done": 2 in done, "chg": round(chg, 1), "need": -5.0},
                 next3={"done": 3 in done, "low": round(cyc["low_b"], 1), "now": round(bn, 1), "need": round(cyc["low_b"] + 5, 1)})
    elif st["history"]:
        v["last"] = st["history"][-1]
    _NOW.update(key=key, v=v)
    return v


def lot_exit(db: Session, code: str, buy: date) -> str | None:
    """이 모드 후보로 산 것이면 정리일. 후보에 오른 날부터 정리일 사이에 산 것만."""
    s = _get(db)
    for cyc in [s["cycle"]] if s["cycle"] else []:
        for t in cyc["tranches"]:
            if t["date"] <= str(buy) <= cyc["exit"] and code in {x["code"] for x in t["items"]}:
                return cyc["exit"]
    return None


def status(db: Session) -> str:
    b, _, _, _ = _series(db)
    s = _get(db)
    cyc = s["cycle"]
    out = [f"200일선 위 종목 {b.iloc[-1]:.0f}% ({b.index[-1]} · 35% 아래로 처음 내려가면 켜짐)",
           "최근 5일: " + " · ".join(f"{d.month}/{d.day} {v:.0f}%" for d, v in b.iloc[-5:].items())]
    if cyc:
        out.insert(0, f"🟣 바닥 모으기 켜짐 {cyc['on']} ~ 정리 {cyc['exit']} · {', '.join(str(t['n']) + '차 ' + t['date'][5:] for t in cyc['tranches'])}")
        for t in cyc["tranches"]:
            out.append(f"{t['n']}차 후보: " + ", ".join(x["name"] for x in t["items"]))
    else:
        out.insert(0, "바닥 모으기: 꺼짐")
    if s["history"]:
        out.append("지난번: " + ", ".join(h["on"] for h in s["history"][-3:]))
    return "\n".join(out)
