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
import copy
import json
import logging
from backend.services import account_engine as engine
from backend.services.trading_rules import RULE_VERSION, size_multiplier
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
VERSION = "V1.1"
CONFIG = {"signal": "stock_signals._close_scores buy (S0)", "order": "RS desc", "slots": 10, "risk": 0.005,
          "stop": "signal snapshot low x0.99", "exit": "close<EMA21 -> next open", "cost_buy": 0.0005, "cost_sell": 0.0025,
          "market_filter": "P/L: previous completed session, frozen at snapshot; S/X: signal close", "frozen": "2026-10-11", "next_open_cancel_if_open_le_stop": True}
# 주도주 L (V1.0 아님, 이번 장 한정 별도 전략 · GPT 운영 규칙 10/10): 정배열·RS 95↑·손절폭 8%↓·양봉·종가 범위 위 절반
# 실제 L = 거래당 위험 0.25% · 최대 2종목 · 15:12 신호 → 종가. Lsh = 모든 주도주 신호 전수 기록(칸 제한 없음) → 꺼짐 판단용.
# 운영(10/10 GPT·사용자 합의 수정): 거래당 위험 0.10% · 최대 2종목. 상승장 아님 → 신규 중단. 실제 L 누적 R 고점 대비 −15R → 실매매 정지(계좌 약 −1.5%, 사용자 '/주도주 켜기' 전까지 기록만).
#   −8R · 최근 30건(Lsh) 평균 R ≤ −0.10 → 경고만(자동으로 끄지 않음 — 승률 18%라 성적 기반 켜고 끄기는 12년 검증에서 전부 엇갈림).
#   사용자가 직접 끄고 켜면(텔레그램 /주도주 끄기·켜기) 그때 30건 평균·낙폭과 함께 기록 → 나중에 사람 판단이 도움이 됐는지 평가.
# Z = 모멘텀 돌파 비교 규칙(종가가 직전 20일 고가 위 · 거래량 20일 평균 1.9배↑ · 그날 +5%↑ · 거래대금 30억↑), V1.0과 같은 체결·손절·정리로 종목 고르기만 비교.
LEAD = {"risk": 0.0010, "slots": 2, "roll": 30, "warn_mean": -0.10, "warn_R": -8.0, "stop_R": -15.0}
CONFIG_HASH = hashlib.sha256(json.dumps({"account": CONFIG, "lead": LEAD, "rules": RULE_VERSION}, sort_keys=True).encode()).hexdigest()[:12]
STATE_KEY = "fwd_v1_1_state"
KST = ZoneInfo("Asia/Seoul")


def _ensure(db: Session) -> None:
    db.execute(text("""create table if not exists forward_log (
        id serial primary key, trading_date date not null, kind varchar(16) not null, version varchar(16) not null,
        payload jsonb not null, created_at timestamptz default now(), unique (trading_date, kind, version))"""))
    db.commit()


def _save(db: Session, d, kind: str, payload: dict) -> None:
    _ensure(db)
    db.execute(text("""insert into forward_log (trading_date, kind, version, payload) values (:d, :k, :v, cast(:p as jsonb))
        on conflict (trading_date, kind, version) do nothing"""),
               {"d": d, "k": kind, "v": VERSION, "p": json.dumps(payload, ensure_ascii=False, default=float)})
    db.commit()


def _load(db: Session, d, kind: str) -> dict | None:
    _ensure(db)
    r = db.execute(text("select payload from forward_log where trading_date = :d and kind = :k and version = :v"),
                   {"d": d, "k": kind, "v": VERSION}).scalar()
    return r if r is None or isinstance(r, dict) else json.loads(r)


def _cands(scores: dict, prices: dict | None = None, lead: bool = False) -> list[dict]:
    out = []
    for c, v in scores.items():
        if (not v.get("lead") or v.get("buy")) if lead else not v.get("buy"):
            continue
        px = (prices or {}).get(c)
        out.append({"code": c, "score": v["score"], "flags": [bool(x) for x in v["flags"]], "ema": bool(v.get("ema")),
                    "hot": bool(v.get("hot")), "semi": bool(v.get("semi")), "rs": v.get("rs"), "stop": float(v["stop"]),
                    "risk": float(v["risk"]), "price": px if px is not None else v.get("price"), "size_mult": size_multiplier(v), "state": v.get("lead_state") or []})
    out.sort(key=lambda x: (-(x["rs"] or 0), x["code"]))
    for k, x in enumerate(out, 1):
        x["rs_rank"] = k
    return out


def snapshot_1512(db: Session) -> str:
    """Freeze signal values and the last completed market filter; first write wins."""
    from backend.services.stock_signals import close_scores_now, _bull_days, _CSL
    today = datetime.now(KST).date()
    existing = _load(db, today, "1512")
    if existing is not None:
        return "이미 저장한 15:12 기록 유지"
    sc = close_scores_now(db)
    if not sc.get("live") or sc.get("date") != str(today):
        return "오늘 장중 점수 없음"
    latest = db.execute(text("select max(trading_date) from spot_daily_prices where trading_date < :d"), {"d": today}).scalar()
    bull = bool(_bull_days(db).get(latest, False))
    cands = _cands(sc["scores"])
    leads = _cands(sc["scores"], lead=True)
    lead_on = lead_state(db)["on"]
    plans = _plan_snapshot(db, today, _CSL.get("quotes", {}), cands, leads, bull, lead_on, latest)
    _save(db, today, "1512", {"at": sc.get("at"), "config": CONFIG_HASH,
          "market_asof": str(latest), "bull": bull, "lead_on": lead_on, "plans": plans,
          "universe": len(sc["scores"]), "cands": cands, "leads": leads})
    return f"15:12 후보 {len(cands)} · 주도주 {len(leads)}"


def _plan_snapshot(db, today, quotes, cands, leads, bull, lead_on, last_completed=None):
    """Freeze selected orders and quantities using the same 15:12 partial bars."""
    from backend.services.telegram import _get
    st = _get(db, STATE_KEY, {}) or {}
    if st.get("config", CONFIG_HASH) != CONFIG_HASH or st.get("version", VERSION) != VERSION:
        raise ValueError("계좌 규칙/버전 불일치")
    if st.get("last") and last_completed is not None and st["last"] != str(last_completed):
        raise ValueError("이전 거래일 계좌부터 복구한 후 스냅샷을 저장해야 합니다")
    specs = [("P", cands if bull else [], CONFIG["slots"], CONFIG["risk"]),
             ("L", leads if bull and lead_on else [], LEAD["slots"], LEAD["risk"]),
             ("Lsh", leads if bull else [], 999, .0005)]
    codes = {x["code"] for _, pool, _, _ in specs for x in pool}
    codes.update(c for name, _, _, _ in specs for c in st.get(name, {}).get("pos", {}))
    bars = _bars(db, sorted(codes), today)
    for code in codes:
        history = [b for b in bars.get(code, []) if b[0] < today]
        q = quotes.get(code)
        if q and all(q.get(k) for k in ("o", "h", "l", "c")):
            previous = history[-1][4] if history and history[-1][4] > 0 else q["o"]
            history.append((today,q["o"],q["h"],q["l"],q["c"],(q["c"]/previous-1)*100))
        bars[code] = history
    context = engine.day_context(bars, today)
    plans = {}
    for name, pool, slots, risk in specs:
        account = copy.deepcopy(st.get(name) or _new_acct())
        report = _step(account, name, today, bars, pool, "close", slots, risk, context)
        by_code = {x["code"]:x for x in pool}
        plans[name] = [{**by_code[code], "planned_shares": account["pos"][code]["sh"]}
                       for code in report["selected"]]
    return plans


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


def _ema21(closes):
    return engine.ema21(closes)


def _new_acct():
    return engine.new_account()


def _equity(a, bars, d):
    return engine.equity(a, engine.day_context(bars, d)["close"])


def _step(a, name, d, bars, cands, entry, slots=None, rp=None, context=None):
    return engine.advance(a, name, d, context if context is not None else engine.day_context(bars, d),
                          cands, entry, slots=CONFIG["slots"] if slots is None else slots,
                          risk=CONFIG["risk"] if rp is None else rp,
                          cost_buy=CONFIG["cost_buy"], cost_sell=CONFIG["cost_sell"])


def _momo_cands(db: Session, latest) -> list[dict]:
    """모멘텀 돌파 비교 규칙: 종가 > 직전 20일 고가 · 거래량 ≥ 직전 20일 평균 × 1.9 · 그날 +5%↑ · 거래대금 20일 평균 30억↑. RS 순."""
    from backend.services.stock_signals import _close_frames  # noqa: PLC0415
    P = _close_frames(db, latest)
    C, H, L, V, TV = P["c"], P["h"], P["l"], P["v"], P["tv"]
    if str(C.index[-1]) != str(latest):
        return []
    c, l = C.iloc[-1], L.iloc[-1]
    ok = (c > H.iloc[-21:-1].max()) & (V.iloc[-1] >= 1.9 * V.iloc[-21:-1].mean()) & (c / C.iloc[-2] - 1 >= 0.05) & (TV.iloc[-20:].mean() >= 3e9)
    rs_raw = 0.4 * (C / C.shift(63) - 1) + 0.2 * (C / C.shift(126) - 1) + 0.2 * (C / C.shift(189) - 1) + 0.2 * (C / C.shift(252) - 1)
    RS = rs_raw.where(TV.rolling(20).mean() >= 3e9).rank(axis=1, pct=True).iloc[-1] * 98 + 1
    out = []
    for code in ok[ok.fillna(False).astype(bool)].index:
        st = float(l[code]) * 0.99
        out.append({"code": code, "rs": round(float(RS.get(code)), 1) if RS.get(code) == RS.get(code) else None, "stop": round(st, 2), "risk": round(1 - st / float(c[code]), 5)})
    out.sort(key=lambda x: (-(x["rs"] or 0), x["code"]))
    return out


def _lead_dd(st: dict) -> float:
    cum = pk = 0.0
    for t in (st.get("L") or {}).get("trades", []):
        cum += t["R"]; pk = max(pk, cum)
    return cum - pk


def lead_state(db: Session, st: dict | None = None) -> dict:
    """주도주 L 켜짐/꺼짐 + 경고 (화면·알림용). 꺼짐 = 사용자 수동 끔 · −15R 정지 · 하락장. 경고 = −8R · 최근 30건 평균 R ≤ −0.10."""
    from backend.services.stock_signals import _bull_days  # noqa: PLC0415
    from backend.services.telegram import _get  # noqa: PLC0415
    st = st if st is not None else (_get(db, STATE_KEY, {}) or {})
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    dd = _lead_dd(st); m30 = st.get("L_mean30")
    warn = []
    if dd <= LEAD["warn_R"]:
        warn.append(f"주도주 누적 {dd:+.1f}R")
    if m30 is not None and m30 <= LEAD["warn_mean"]:
        warn.append(f"최근 {LEAD['roll']}건 평균 R {m30:+.2f}")
    w = " · ".join(warn)
    man = st.get("L_manual") or {}
    if man.get("on") is False:
        return {"on": False, "why": f"사용자가 끔 ({man.get('at', '')}{' · ' + man['reason'] if man.get('reason') else ''})", "warn": w}
    if st.get("L_hard"):
        return {"on": False, "why": st["L_hard"], "warn": w}
    if not _bull_days(db).get(latest, False):
        return {"on": False, "why": "하락장 — 신규 중단", "warn": w}
    return {"on": True, "why": "", "warn": w}


def set_lead_manual(db: Session, on: bool, reason: str = "") -> str:
    """텔레그램 /주도주 끄기·켜기 — 사람 판단을 그때 숫자와 함께 남긴다. 켜기는 −15R 정지도 푼다."""
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    st = _get(db, STATE_KEY, {}) or {}
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    rec = {"at": now, "on": on, "reason": reason[:100], "mean30": st.get("L_mean30"), "dd": round(_lead_dd(st), 2), "hard": st.get("L_hard")}
    st.setdefault("L_manual_log", []).append(rec)
    st["L_manual"] = {"on": on, "at": now, "reason": reason[:100]}
    if on:
        st.pop("L_hard", None)
    _put(db, STATE_KEY, st)
    return (f"주도주 {'켬' if on else '끔'} ({now}) · 기록: 최근 30건 평균 R {rec['mean30'] if rec['mean30'] is not None else '-'} · 누적 낙폭 {rec['dd']:+.1f}R"
            + (" · −15R 정지 해제" if on and rec["hard"] else ""))


def record_close(db: Session, asof: date | None = None) -> str:
    """Advance every unprocessed trading date; historical replay uses this version only."""
    from backend.services.telegram import _get, _put
    from backend.utils.dates import is_trading_day
    target = asof or datetime.now(KST).date()
    latest = db.execute(text("select max(trading_date) from spot_daily_prices where trading_date <= :d"), {"d": target}).scalar()
    if latest != target or not is_trading_day(target):
        return "오늘 시세 없음"
    st = _get(db, STATE_KEY, {}) or {}
    if st.get("version", VERSION) != VERSION or st.get("config", CONFIG_HASH) != CONFIG_HASH:
        raise ValueError("계좌 규칙/버전 불일치: 기존 기록에 새 규칙을 섞을 수 없습니다")
    last = date.fromisoformat(st["last"]) if st.get("last") else None
    if last is not None and last > target:
        raise ValueError("과거 날짜로 운영 계좌를 되감을 수 없습니다")
    if last == target:
        if st.get("last_report"):
            _save(db, target, "acct", st["last_report"])
        return "이미 진행함"
    days = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_prices "
            "where trading_date > :a and trading_date <= :b order by 1"),
            {"a": last or target - timedelta(days=1), "b": target}).all()]
    if not days or days[-1] != target:
        raise ValueError("거래일 목록 불완전: 계좌 진행 중단")
    if last is not None:
        expected = {last + timedelta(days=i) for i in range(1, (target-last).days+1)
                    if is_trading_day(last + timedelta(days=i))}
        if not expected.issubset(days):
            raise ValueError("누락된 거래일 시세: 복구 전까지 계좌 진행 중단")
    for day in days:
        report, close_payload = _record_day(db, st, day)
        _save(db, day, "close", close_payload)
        st.update(last=str(day), version=VERSION, config=CONFIG_HASH, last_report=report)
        _put(db, STATE_KEY, st)
        _save(db, day, "acct", report)
    return f"{len(days)}거래일 처리 · " + " ".join(f"{r['acct']} {r['equity']:.4f}" for r in report["accounts"])


def _record_day(db, st, day):
    from backend.services.stock_signals import _close_scores, _bull_days
    sc = _close_scores(db, day).get("scores", {})
    close_c, close_l = _cands(sc), _cands(sc, lead=True)
    bull = bool(_bull_days(db).get(day, False))
    snap = _load(db, day, "1512")
    if snap is not None and snap.get("config") != CONFIG_HASH:
        raise ValueError("스냅샷 규칙 불일치")
    snap_c, snap_l = (snap or {}).get("cands", []), (snap or {}).get("leads", [])
    snapshot_bull = bool((snap or {}).get("bull", False))
    lead_on = bool((snap or {}).get("lead_on", False)) and not st.get("L_hard")
    plans = (snap or {}).get("plans", {})
    momo = _momo_cands(db, day)
    account_specs = [
        ("P", plans.get("P", []) if snapshot_bull else [], "close", CONFIG["slots"], CONFIG["risk"]),
        ("S", close_c if bull else [], "next_open", CONFIG["slots"], CONFIG["risk"]),
        ("X", close_c if bull else [], "close", CONFIG["slots"], CONFIG["risk"]),
        ("L", plans.get("L", []) if snapshot_bull and lead_on else [], "close", LEAD["slots"], LEAD["risk"]),
        ("Lsh", plans.get("Lsh", []) if snapshot_bull else [], "close", 999, .0005),
        ("Z", momo, "close", CONFIG["slots"], CONFIG["risk"])]
    codes = set()
    for name, cands, _, _, _ in account_specs:
        a = st.setdefault(name, _new_acct())
        codes.update(a["pos"])
        codes.update(x["code"] for x in a["pending"] + cands)
    bars = _bars(db, sorted(codes), day)
    context = engine.day_context(bars, day)
    reports = [_step(st[name], name, day, bars, cands, entry, slots, risk, context)
               for name, cands, entry, slots, risk in account_specs]
    tr = st["Lsh"]["trades"][-LEAD["roll"]:]
    if len(tr) >= LEAD["roll"]:
        st["L_mean30"] = round(sum(t["R"] for t in tr) / len(tr), 3)
    dd = _lead_dd(st)
    if dd <= LEAD["stop_R"] and not st.get("L_hard"):
        st["L_hard"] = f"주도주 누적 {dd:+.1f}R — 신규 중단"
    s1, s2 = {x["code"] for x in snap_c}, {x["code"] for x in close_c}
    report = {"config": CONFIG_HASH, "jaccard": len(s1 & s2) / len(s1 | s2) if s1 | s2 else None,
              "snapshot_missing": snap is None, "accounts": reports}
    payload = {"config": CONFIG_HASH, "universe": len(sc), "bull": bull, "cands": close_c,
               "leads": close_l, "momo": momo, "snapshot_missing": snap is None}
    return report, payload


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
    for k, nm in (("P", "P 기본(15:12 신호·종가)"), ("S", "S 보조(종가 신호·다음 날 시가)"), ("X", "X 진단(같은 종가)"),
                  ("L", "L 주도주 실제(0.10%·2종목)"), ("Lsh", "L 주도주 전수 기록"), ("Z", "Z 모멘텀 돌파 비교(20일 고점 돌파·거래 1.9배·+5% · 같은 체결)")):
        a = st.get(k) or {}
        tr = [t for t in a.get("trades", []) if t["d1"][:7] == ym]
        alltr = [t for t in a.get("trades", []) if t["d1"][:7] <= ym]
        eq = [e for e in a.get("eq", []) if e[0][:7] == ym]
        if not eq:
            continue
        prior = [e for e in a.get("eq", []) if e[0][:7] < ym]
        base = prior[-1][1] if prior else 1.0
        mret = eq[-1][1] / base - 1 if base > 0 else 0.0
        pk, mdd = 1.0, 0
        for eq_date, v in a.get("eq", []):
            if eq_date[:7] > ym:
                continue
            pk = max(pk, v); mdd = min(mdd, v / pk - 1)
        er = sum(t["R"] for t in alltr) / len(alltr) if alltr else None
        month_reports = [r for d in days for r in by[d].get("acct", {}).get("accounts", []) if r["acct"] == k]
        held = month_reports[-1]["npos"] if month_reports else "기록 없음"
        out.append(f"{nm}: 이번 달 {mret * 100:+.1f}% · 누적 {(eq[-1][1] - 1) * 100:+.1f}% · 최대낙폭 {mdd * 100:.1f}% · 정리 {len(tr)}건(누적 {len(alltr)}건"
                   + (f", 평균 R {er:+.2f}" if er is not None else "") + f") · 월말 보유 {held}")
        if len(alltr) >= 10:      # 추세추종은 소수 큰 수익이 전체를 만든다 — 승률보다 이 숫자들 (GPT 권고 10/10)
            rs_ = sorted(t["R"] for t in alltr); wins = [r for r in rs_ if r > 0]; loss = [r for r in rs_ if r <= 0]
            top = rs_[-max(1, len(rs_) // 10):]; tot = sum(rs_)
            out.append(f"   중앙 R {rs_[len(rs_) // 2]:+.2f} · 이긴 비율 {100 * len(wins) / len(rs_):.0f}% · 손익비 {(sum(wins) / len(wins)) / abs(sum(loss) / len(loss)) if wins and loss else 0:.1f}"
                       + (f" · 상위 10% 거래가 전체 R의 {100 * sum(top) / tot:.0f}%" if tot > 0 else " · 누적 R 0 이하"))
        if k == "P" and mdd <= -0.25:
            out.append("⛔ P 낙폭 25% 넘음 — 사전 기준상 신규 진입 중단 검토")
        elif k == "P" and mdd <= -0.15:
            out.append("⚠️ P 낙폭 15% 넘음 — 사전 기준상 위험 절반(0.25%) 검토")
    try:
        ls_ = lead_state(db, st)
        out.append("현재 주도주 상태: " + ("켜짐" if ls_["on"] else "꺼짐 — " + ls_["why"]) + (f" · ⚠️ {ls_['warn']}" if ls_.get("warn") else ""))
        for r_ in (st.get("L_manual_log") or [])[-5:]:
            out.append(f"  사용자 {'켬' if r_['on'] else '끔'} {r_['at']} · {r_.get('reason') or ''} · 30건 평균 {r_.get('mean30')} · 낙폭 {r_.get('dd')}R")
    except Exception:  # noqa: BLE001
        pass
    primary_trades = [t for t in (st.get("P") or {}).get("trades", []) if t["d1"][:7] <= ym]
    n_tr = len(primary_trades); n_days = len({t["d0"] for t in primary_trades})
    out.append(f"판정 진행: P 정리 {n_tr}/100건 · 진입일 {n_days}/40 (1차 판정 = 12개월+100건+40일, 그 전엔 판정 안 함)")
    return "\n".join(x for x in out if x)
