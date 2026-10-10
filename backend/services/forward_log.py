"""앞으로의 실전 기록 = 진짜 시험지 (2026-10-10 사용자 "다 해라" · GPT 교차검증 연구 3 설계).

규칙을 V1.0으로 동결하고, 사이트 매수 신호를 강도(RS) 높은 순 10칸으로 따라간 가상 계좌를 매일 기록한다.
- 15:12 스냅샷(snapshot_1512): 그 시각 실시간 점수로 매수 후보(S0) 전체 저장 — 조건 7개·점수·RS·손절·가격.
- 장 마감 뒤(record_close, 18:40): 확정 종가 후보 저장 + 가상 계좌 3개 하루 진행
    P 기본  = 15:12 신호 · RS 순 · 종가 체결 (실제로 할 수 있는 매매)
    S 보조  = 종가 신호 · RS 순 · 다음 날 시가 체결
    X 진단  = 종가 신호 · RS 순 · 같은 종가 체결 (백테스트 방식, 실제로는 불가능 — 비교용만)
  공통: 최대 10종목 · 거래당 위험 0.5%(손절폭 기준 크기) · 손절 = 산 날 저가 -1% 예약(시가가 아래면 시가) ·
        종가 < EMA21 → 다음 날 시가 정리 · 비용 매수 0.05% + 매도 0.25% · 하한가 잠김 날은 못 판 것으로 이월.
- 월간 보고(monthly_text): 15:12↔종가 일치율(Jaccard) · 상위 10 교체율 · 계좌별 거래 성적·낙폭 · 데이터 누락.
- 무작위 순서 10,000 그림자 계좌·백테스트 분포 비교는 저장된 후보로 나중에 한꺼번에 계산(시드 미리 고정: SHA256(prereg_gpt_redteam_dd 해시‖j)).
판정 기준(GPT 사전등록): 6개월 전 판정 금지 · 1차 = 12개월+100건+40 진입일 · 2차 = 24개월+200건+80 진입일 ·
자본 보호 = P 계좌 낙폭 15%↑면 위험 절반 검토, 25%↑면 신규 중단 검토(사용자 판단, 자동 매매 아님).
규칙을 바꾸면 VERSION을 올리고 기록을 새로 시작한다(섞지 않음).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
VERSION = "V1.0"
CONFIG = {"signal": "stock_signals._close_scores buy (S0)", "order": "RS desc", "slots": 10, "risk": 0.005,
          "stop": "entry-day low x0.99", "exit": "close<EMA21 -> next open", "cost_buy": 0.0005, "cost_sell": 0.0025,
          "market_filter": "bull (in S0)", "frozen": "2026-10-10", "next_open_cancel_if_open_le_stop": True}
CONFIG_HASH = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()[:12]
STATE_KEY = "fwd_v1_state"
KST = ZoneInfo("Asia/Seoul")


def _ensure(db: Session) -> None:
    db.execute(text("""create table if not exists forward_log (
        id serial primary key, trading_date date not null, kind varchar(16) not null, version varchar(16) not null,
        payload jsonb not null, created_at timestamptz default now(), unique (trading_date, kind, version))"""))
    db.commit()


def _save(db: Session, d, kind: str, payload: dict) -> None:
    _ensure(db)
    db.execute(text("""insert into forward_log (trading_date, kind, version, payload) values (:d, :k, :v, cast(:p as jsonb))
        on conflict (trading_date, kind, version) do update set payload = excluded.payload, created_at = now()"""),
               {"d": d, "k": kind, "v": VERSION, "p": json.dumps(payload, ensure_ascii=False, default=float)})
    db.commit()


def _load(db: Session, d, kind: str) -> dict | None:
    _ensure(db)
    r = db.execute(text("select payload from forward_log where trading_date = :d and kind = :k and version = :v"),
                   {"d": d, "k": kind, "v": VERSION}).scalar()
    return r if r is None or isinstance(r, dict) else json.loads(r)


def _cands(scores: dict, prices: dict | None = None) -> list[dict]:
    out = []
    for c, v in scores.items():
        if not v.get("buy"):
            continue
        px = (prices or {}).get(c)
        out.append({"code": c, "score": v["score"], "flags": [bool(x) for x in v["flags"]], "ema": bool(v.get("ema")),
                    "hot": bool(v.get("hot")), "semi": bool(v.get("semi")), "rs": v.get("rs"), "stop": round(float(v["stop"]), 2),
                    "risk": round(float(v["risk"]), 5), "price": px})
    out.sort(key=lambda x: -(x["rs"] or 0))
    for k, x in enumerate(out, 1):
        x["rs_rank"] = k
    return out


def snapshot_1512(db: Session) -> str:
    """15:12 장중 점수로 매수 후보 전체 저장 (close_entry_alert와 같은 2분 캐시를 씀)."""
    from backend.services.stock_signals import close_scores_now  # noqa: PLC0415
    sc = close_scores_now(db)
    if not sc.get("live"):
        return "장중 점수 없음"
    today = datetime.now(KST).date()
    codes = [c for c, v in sc["scores"].items() if v.get("buy")]
    prices = {}
    try:
        from backend.services.naver_live import snapshot  # noqa: PLC0415
        prices = {c: v["c"] for c, v in snapshot(codes, max_age=90).items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("15:12 가격 실패: %s", exc)
    cands = _cands(sc["scores"], prices)
    _save(db, today, "1512", {"at": sc.get("at"), "config": CONFIG_HASH, "universe": len(sc["scores"]), "cands": cands})
    return f"15:12 후보 {len(cands)}"


def _bars(db: Session, codes: list[str], upto) -> dict:
    """종목별 최근 130거래일 (날짜, 시, 고, 저, 종) — EMA21·청산 판단용."""
    if not codes:
        return {}
    rows = db.execute(text("""select stock_code, trading_date, open_price, high_price, low_price, close_price, change_pct
        from spot_daily_prices where stock_code = any(:c) and trading_date <= :d and trading_date >= :d - interval '200 days'
        order by stock_code, trading_date"""), {"c": codes, "d": upto}).all()
    out: dict = {}
    for c, d, o, h, l, cl, ch in rows:
        out.setdefault(c, []).append((d, float(o or 0), float(h or 0), float(l or 0), float(cl or 0), float(ch or 0)))
    return out


def _ema21(closes: list[float]) -> float:
    k = 2 / 22; e = closes[0]
    for x in closes[1:]:
        e = x * k + e * (1 - k)
    return e


def _new_acct() -> dict:
    return {"cash": 1.0, "pos": {}, "pending": [], "eq": [], "trades": [], "peak": 1.0}


def _equity(a: dict, bars: dict, d) -> float:
    mv = 0.0
    for c, p in a["pos"].items():
        b = [x for x in bars.get(c, []) if x[0] <= d]
        mv += p["sh"] * (b[-1][4] if b else p["px0"])
    return a["cash"] + mv


def _step(a: dict, name: str, d, bars: dict, cands: list[dict], entry: str) -> dict:
    """하루 진행. entry: 'close'(P·X) 또는 'next_open'(S: 오늘 시가에 어제 주문 체결, 오늘 후보는 내일 주문)."""
    cb, cs = CONFIG["cost_buy"], CONFIG["cost_sell"]
    notes = []
    today = {c: [x for x in bars.get(c, []) if x[0] == d] for c in set(a["pos"]) | {p["code"] for p in a["pending"]} | {x["code"] for x in cands}}
    # 1) S: 어제 주문을 오늘 시가에
    if entry == "next_open" and a["pending"]:
        E_ = _equity(a, bars, d)
        for o in a["pending"]:
            if len(a["pos"]) >= CONFIG["slots"]:
                notes.append(f"칸 없음 {o['code']}"); continue
            if o["code"] in a["pos"] or not today.get(o["code"]):
                continue
            op = today[o["code"]][0][1]
            if op <= 0:
                continue
            if op <= o["stop"]:                           # 시가가 이미 전날 정한 손절가 아래 = 손절 구조가 무효 → 진입 취소 (GPT 검토 10/10, 실행 정의)
                notes.append(f"시가가 손절 아래라 취소 {o['code']}"); continue
            rk = 1 - o["stop"] / op
            val = CONFIG["risk"] * E_ / rk
            a["cash"] -= val * (1 + cb)
            a["pos"][o["code"]] = {"sh": val / op, "px0": op, "d0": str(d), "stop": o["stop"], "risk0": rk, "rs": o.get("rs"), "hi": op, "lo": op, "exit_next": False}
        a["pending"] = []
    # 2) 청산: 어제 종가에 EMA21 아래였으면 오늘 시가 / 아니면 손절 예약
    for c in list(a["pos"]):
        p = a["pos"][c]; tb = today.get(c)
        if not tb or p["d0"] == str(d) and entry != "next_open":
            continue
        _, o, h, l, cl, ch = tb[0]
        locked = h == l and ch <= -29
        px = None; why = ""
        if p["exit_next"]:
            px, why = o, "21선"
        elif l > 0 and l <= p["stop"]:
            px, why = min(o, p["stop"]) if o > 0 else p["stop"], "손절"
        if px is not None and locked:
            notes.append(f"하한가 잠김 이월 {c}"); px = None
        p["hi"] = max(p["hi"], h); p["lo"] = min(p["lo"], l) if l > 0 else p["lo"]
        if px is not None:
            a["cash"] += p["sh"] * px * (1 - cs)
            net = px / p["px0"] - 1 - cb - cs
            a["trades"].append({"code": c, "d0": p["d0"], "px0": p["px0"], "d1": str(d), "px1": px, "why": why, "R": round(net / p["risk0"], 3),
                                "net": round(net, 4), "mfe": round(p["hi"] / p["px0"] - 1, 4), "mae": round(p["lo"] / p["px0"] - 1, 4), "rs": p.get("rs")})
            del a["pos"][c]
    # 3) 진입 (P·X: 오늘 종가)
    E_ = _equity(a, bars, d)
    selected, skipped = [], []
    if entry == "close":
        for x in cands:                                  # RS 순
            if x["code"] in a["pos"]:
                continue
            if len(a["pos"]) >= CONFIG["slots"]:
                skipped.append(x["code"]); continue
            tb = today.get(x["code"])
            if not tb:
                skipped.append(x["code"]); continue
            _, o, h, l, cl, ch = tb[0]
            stop_final = l * 0.99                         # 실제 손절 = 확정 저가 -1%
            rk_plan = x["risk"] if x.get("risk") else 1 - stop_final / cl     # 크기는 신호 시점 손절폭으로
            val = CONFIG["risk"] * E_ / max(rk_plan, 0.003)
            a["cash"] -= val * (1 + cb)
            rk_real = 1 - stop_final / cl
            a["pos"][x["code"]] = {"sh": val / cl, "px0": cl, "d0": str(d), "stop": stop_final, "risk0": rk_real, "rs": x.get("rs"), "hi": cl, "lo": cl,
                                   "exit_next": False, "risk_plan": rk_plan, "heat": round(val * rk_real / E_, 5)}
            selected.append(x["code"])
    else:
        a["pending"] = [{"code": x["code"], "stop": x["stop"], "rs": x.get("rs")} for x in cands if x["code"] not in a["pos"]]
    # 4) 오늘 종가로 EMA21 판단(다음 날 시가 정리) · 자본
    for c, p in a["pos"].items():
        b = [x[4] for x in bars.get(c, []) if x[0] <= d]
        if len(b) >= 30 and b[-1] < _ema21(b[-130:]):
            p["exit_next"] = True
    eq = _equity(a, bars, d); a["peak"] = max(a.get("peak", 1.0), eq)
    a["eq"].append([str(d), round(eq, 6)])
    heat = sum(p["sh"] * p["px0"] * p["risk0"] for p in a["pos"].values()) / eq if eq > 0 else 0
    return {"acct": name, "equity": round(eq, 6), "dd": round(eq / a["peak"] - 1, 4), "npos": len(a["pos"]), "heat": round(heat, 4),
            "selected": selected, "skipped": skipped[:30], "notes": notes}


def record_close(db: Session, asof: date | None = None) -> str:
    """장 마감 뒤: 확정 종가 후보 저장 + 가상 계좌 P·S·X 하루 진행. asof = 시험용 지난 날짜 다시 돌리기."""
    from backend.services.stock_signals import _close_scores  # noqa: PLC0415
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    today = asof or datetime.now(KST).date()
    latest = asof or db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest != today or not is_trading_day(today):
        return "오늘 시세 없음"
    sc = _close_scores(db, latest).get("scores", {})
    px = {r[0]: float(r[1]) for r in db.execute(text("select stock_code, close_price from spot_daily_prices where trading_date = :d"), {"d": latest}).all()}
    close_c = _cands(sc, px)
    snap = _load(db, latest, "1512")
    snap_c = (snap or {}).get("cands") or []
    _save(db, latest, "close", {"config": CONFIG_HASH, "universe": len(sc), "cands": close_c, "snapshot_missing": snap is None})
    st = _get(db, STATE_KEY, {}) or {}
    if st.get("last") == str(latest):
        return "이미 진행함"
    for k in ("P", "S", "X"):
        st.setdefault(k, _new_acct())
    codes = set()
    for k in ("P", "S", "X"):
        codes |= set(st[k]["pos"]) | {p["code"] for p in st[k]["pending"]}
    codes |= {x["code"] for x in close_c} | {x["code"] for x in snap_c}
    bars = _bars(db, sorted(codes), latest)
    rep = [_step(st["P"], "P", latest, bars, snap_c, "close"), _step(st["S"], "S", latest, bars, close_c, "next_open"), _step(st["X"], "X", latest, bars, close_c, "close")]
    for k in ("P", "S", "X"):
        st[k]["eq"] = st[k]["eq"][-800:]
    st["last"] = str(latest); st["version"] = VERSION; st["config"] = CONFIG_HASH
    _put(db, STATE_KEY, st)
    s1, s2 = {x["code"] for x in snap_c}, {x["code"] for x in close_c}
    jac = len(s1 & s2) / len(s1 | s2) if (s1 | s2) else None
    _save(db, latest, "acct", {"config": CONFIG_HASH, "jaccard": jac, "snapshot_missing": snap is None, "accounts": rep})
    return f"종가 후보 {len(close_c)} · 15:12 후보 {len(snap_c)}" + (f" · 일치 {jac:.2f}" if jac is not None else "") + " · " + " ".join(f"{r['acct']} {r['equity']:.4f}" for r in rep)


def monthly_text(db: Session, ym: str | None = None) -> str | None:
    """월간 보고 (규칙은 바꾸지 않고 보고만). ym 'YYYY-MM' (없으면 지난달)."""
    from backend.services.telegram import _get  # noqa: PLC0415
    _ensure(db)
    if ym is None:
        t = datetime.now(KST).date().replace(day=1)
        ym = f"{t.year - (t.month == 1)}-{12 if t.month == 1 else t.month - 1:02d}"
    rows = db.execute(text("select trading_date, kind, payload from forward_log where version = :v and to_char(trading_date, 'YYYY-MM') = :m order by trading_date"),
                      {"v": VERSION, "m": ym}).all()
    if not rows:
        return None
    by = {}
    for d, k, p in rows:
        by.setdefault(str(d), {})[k] = p if isinstance(p, dict) else json.loads(p)
    days = sorted(by)
    jac = [by[d]["acct"]["jaccard"] for d in days if "acct" in by[d] and by[d]["acct"].get("jaccard") is not None]
    miss = sum(1 for d in days if "1512" not in by[d])
    flips = []
    for d in days:
        acc = {r["acct"]: r for r in (by[d].get("acct") or {}).get("accounts", [])}
        if "P" in acc and "X" in acc:
            a, b = set(acc["P"]["selected"]), set(acc["X"]["selected"])
            if a | b:
                flips.append(1 - len(a & b) / len(a | b))
    st = _get(db, STATE_KEY, {}) or {}
    out = [f"📒 <b>실전 기록 {VERSION} — {ym}</b> (규칙 동결 · 보고만)",
           f"거래일 {len(days)} · 15:12 스냅샷 빠짐 {miss}일 · 15:12↔종가 후보 일치율 평균 {sum(jac) / len(jac):.2f}" if jac else f"거래일 {len(days)} · 15:12 스냅샷 빠짐 {miss}일",
           f"상위 10 교체율(P vs X 산 종목) 평균 {sum(flips) / len(flips):.2f}" if flips else ""]
    for k, nm in (("P", "P 기본(15:12 신호·종가)"), ("S", "S 보조(종가 신호·다음 날 시가)"), ("X", "X 진단(같은 종가)")):
        a = st.get(k) or {}
        tr = [t for t in a.get("trades", []) if t["d1"][:7] == ym]
        alltr = a.get("trades", [])
        eq = [e for e in a.get("eq", []) if e[0][:7] == ym]
        if not eq:
            continue
        mret = eq[-1][1] / (eq[0][1] or 1) - 1
        pk, mdd = 0, 0
        for _, v in a.get("eq", []):
            pk = max(pk, v); mdd = min(mdd, v / pk - 1)
        er = sum(t["R"] for t in alltr) / len(alltr) if alltr else None
        out.append(f"{nm}: 이번 달 {mret * 100:+.1f}% · 누적 {(a['eq'][-1][1] - 1) * 100:+.1f}% · 최대낙폭 {mdd * 100:.1f}% · 정리 {len(tr)}건(누적 {len(alltr)}건"
                   + (f", 평균 R {er:+.2f}" if er is not None else "") + f") · 보유 {len(a.get('pos', {}))}")
        if k == "P" and mdd <= -0.25:
            out.append("⛔ P 낙폭 25% 넘음 — 사전 기준상 신규 진입 중단 검토")
        elif k == "P" and mdd <= -0.15:
            out.append("⚠️ P 낙폭 15% 넘음 — 사전 기준상 위험 절반(0.25%) 검토")
    n_tr = len((st.get("P") or {}).get("trades", [])); n_days = len({t["d0"] for t in (st.get("P") or {}).get("trades", [])})
    out.append(f"판정 진행: P 정리 {n_tr}/100건 · 진입일 {n_days}/40 (1차 판정 = 12개월+100건+40일, 그 전엔 판정 안 함)")
    return "\n".join(x for x in out if x)
