"""오늘의 종베 후보: 시장 → 뜨거운 섹터 → 그날 섹터에 돈 몰림 → 거래 실린 양봉.

3년 확인(2023-12~2026-09, 상승·횡보장, 상한가 제외, 다음 날 '갭상승이면 시가·아니면 종가' 매도):
  기본(+3% 양봉·거래 2배) +0.42% / 뜨거운 섹터 상위 3 +0.74% / + 섹터 거래대금 1.2배 +0.94%(수익 71%) / 섹터 밖 +0.28%.
  하락장은 같은 조건 +0.12%. 다음 날 시가 매도는 -5% 넘는 손실 2%, 종가까지 보유 18%.
  사용자 실제 매매(2026-09-21~10-02): 손실 대부분이 거래 0.6배 이하·빠진 날·윗꼬리 긴 날의 매수.
등급: A = 뜨거운 섹터 + 섹터 돈 몰림(1.2배) + 거래 실린 양봉, B = 섹터는 뜨겁지만 돈 몰림 아님.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.screener.market_regime import current_regime
from backend.screener.rotation import FAMILIES, family_members, get_overrides

HOT_TOP = 3          # 20일 상승 순위 상위 몇 섹터를 뜨겁다고 볼지
MONEY_X = 1.2        # (참고 표시용) 그날 섹터 거래대금 합계 / 직전 20일 평균 — 대형주 몇 개가 좌우
MONEY_MED = 1.0      # A등급: 섹터 종목들 '그날 거래대금 / 자기 20일 평균'의 중간값 (절반 이상이 평소 이상 거래)
# 2026-10-04 3년 비교(종베 후보 6,991건, 다음 날 갭이면 시가·아니면 종가): 합계 1.2배↑ +0.86%(70%) vs 중간값 1.0↑ +1.20%(74%)·미만 +0.35%,
# 중간값 1.2↑ +1.46%(78%, 1,487건). 종목 자체가 5배↑ 터져도 섹터가 조용하면 +0.43% — 섹터 전체에 돈이 도는지가 중요.
MIN_CHG, VOL_X, MIN_TV = 3.0, 2.0, 3e9
LIMIT_UP = 29.5


def _load(db: Session):
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    px = pd.read_sql(text(
        "select stock_code, trading_date, open_price o, high_price h, low_price l, close_price c, trading_value tv, change_pct ch "
        "from spot_daily_prices where trading_date >= :d"), db.connection(), params={"d": latest - timedelta(days=160)})   # 선취매 후보의 60거래일 대량거래 이력까지
    P = {k: px.pivot(index="trading_date", columns="stock_code", values=k).sort_index() for k in ("o", "h", "l", "c", "tv", "ch")}
    return latest, P


def _families(P, members: dict[str, list[str]]):
    C, TV = P["c"], P["tv"]
    ret20 = C / C.shift(20) - 1
    ret5 = C / C.shift(5) - 1
    dchg = C / C.shift(1) - 1
    gap = C / C.rolling(20).mean() - 1
    d = C.index[-1]
    mkt5 = float(ret5.loc[d].median())
    fam = {}
    for f, mem in members.items():
        m = [x for x in mem if x in C.columns]
        if len(m) < 5:
            continue
        tv = TV[m].sum(axis=1)
        tvx = tv / tv.shift(1).rolling(20).mean()
        inflow = ((tvx >= 1.5) & (dchg[m].median(axis=1) >= 0.01)).iloc[-20:]   # 섹터 거래대금 1.5배 + 섹터 +1% 날
        fam[f] = {"ret20": float(ret20.loc[d, m].median()), "tv_x": float(tv.iloc[-1] / tv.iloc[-21:-1].mean()),
                  "tv_med": float((TV[m].iloc[-1] / TV[m].iloc[-21:-1].mean()).median()),
                  "stretch": float((gap.loc[d, m] >= 0.2).mean()), "members": m,
                  "ret5_rel": float(ret5.loc[d, m].median()) - mkt5, "inflow": int(inflow.sum()),
                  "ret20_prev": float(ret20.iloc[-6][m].median())}
    order = sorted(fam, key=lambda f: -fam[f]["ret20"])
    for i, f in enumerate(order):
        fam[f]["rank"] = i + 1
    for i, f in enumerate(sorted(fam, key=lambda f: -fam[f]["ret20_prev"])):
        fam[f]["rank_prev"] = i + 1
    return fam, order


def _stock_view(P, code: str) -> dict | None:
    O, H, L, C, TV, CH = (P[k] for k in ("o", "h", "l", "c", "tv", "ch"))
    if code not in C.columns or pd.isna(C[code].iloc[-1]):
        return None
    o, h, l, c, tv, ch = (float(x) for x in (O[code].iloc[-1], H[code].iloc[-1], L[code].iloc[-1], C[code].iloc[-1], TV[code].iloc[-1], CH[code].iloc[-1]))
    avg20 = float(TV[code].iloc[-21:-1].mean())
    ma20 = float(C[code].iloc[-20:].mean())
    return {"open": o, "close": c, "change_pct": round(ch, 2), "tv": tv, "tv_x": round(tv / avg20, 1) if avg20 else None,
            "upper_pct": round((h - c) / (h - l) * 100) if h > l else 0, "gap20_pct": round((c / ma20 - 1) * 100, 1) if ma20 else None,
            "bull": c > o}


def scan(db: Session) -> dict:
    latest, P = _load(db)
    members = family_members(db)
    fam, order = _families(P, members)
    hot = order[:HOT_TOP]
    regime = current_regime(db) or {}
    names, caps = {}, {}
    for code, name, cap, sh in db.execute(text("select code, name, market_cap, shares_outstanding from stocks")):
        names[code], caps[code] = name, (float(cap or 0), float(sh or 0))
    from backend.services.earnings_screen import read_snapshot  # noqa: PLC0415
    from backend.services.marcap_caps import caps as marcap_caps  # noqa: PLC0415
    snap = read_snapshot()
    earn_up = set(snap.get("up_codes") or [r["code"] for r in snap.get("rows", [])])
    mc = marcap_caps()
    skip = ("리츠", "스팩", "ETF", "ETN")
    TV = P["tv"]
    d = P["c"].index[-1]

    cands, limit = {}, []
    for f in hot:
        info = fam[f]
        money = info["tv_med"] >= MONEY_MED
        tv_rank = TV.loc[d, info["members"]].rank(ascending=False)
        for code in info["members"]:
            v = _stock_view(P, code)
            nm = names.get(code, code)
            if not v or any(k in nm for k in skip) or v["close"] < 1000 or v["tv"] < MIN_TV:
                continue
            kind, extra = "양봉", {}
            if not (v["bull"] and v["change_pct"] >= MIN_CHG and v["tv_x"] and v["tv_x"] >= VOL_X):
                # 두 번째 유형: 어제 큰 양봉(+5%·거래 3배·30억↑) → 오늘 밑꼬리 긴 도지 (사용자 PS일렉·LS머트리얼즈 직관, 2026-10-05)
                # 3년(상승·횡보장): 1,213건 다음 날(갭이면 시가) +0.50%(밑꼬리 짧은 도지 +0.16%), 뜨는 섹터 A 152건 +1.37%·이김 70%·분할 매도 +1.29%.
                o_, h_, l_, c_ = (float(P[k][code].iloc[-1]) for k in ("o", "h", "l", "c"))
                po, pc, ptv = float(P["o"][code].iloc[-2]), float(P["c"][code].iloc[-2]), float(P["tv"][code].iloc[-2])
                pch = float(P["ch"][code].iloc[-2])
                pavg = float(P["tv"][code].iloc[-22:-2].mean())
                rng = h_ - l_
                if not (rng > 0 and pc > po and pch >= 5 and pavg > 0 and ptv >= 3 * pavg and ptv >= 3e9):
                    continue
                low_wick = (min(o_, c_) - l_) / rng
                if not (abs(c_ - o_) / o_ <= 0.015 and rng / c_ >= 0.03 and low_wick >= 0.5 and c_ >= pc * 0.97):
                    continue
                kind, extra = "밑꼬리 도지", {"low_wick_pct": round(low_wick * 100), "prev_chg": round(pch, 1), "prev_tv_x": round(ptv / pavg, 1)}
            leader = bool(tv_rank.get(code, 99) <= 5)
            row = cands.setdefault(code, {"code": code, "name": nm, **{k: v[k] for k in ("close", "change_pct", "tv_x", "upper_pct", "gap20_pct")},
                                          "value": round(v["tv"]), "families": [], "money": False, "leader": False,
                                          "earn_up": code in earn_up,
                                          "market_cap": caps.get(code, (0, 0))[0] or caps.get(code, (0, 0))[1] * v["close"] or mc.get(code) or 0,
                                          "kind": kind, **extra})
            row["families"].append(f)
            row["money"] |= money
            top60 = float(P["c"][code].iloc[-61:-1].max())   # 종가 기준 (9/18 우리로처럼 장중 윗꼬리 고점에 끌려 반등형으로 잘못 보이지 않게)
            row["pos60_pct"] = round((v["close"] / top60 - 1) * 100, 1) if top60 == top60 and top60 else None
            wick60 = float(P["h"][code].iloc[-61:-1].max())
            row["under_wick"] = bool(wick60 == wick60 and v["close"] < wick60)   # 종가 신고가여도 전 고점 윗꼬리 아래면 매물 남음
            row["leader"] |= leader
    # 대량거래 관심종목과 연결: 오늘 몇 년 만의 최대 거래대금인지, 관심종목 단계(숨고르기·진입 신호 등)
    from backend.screener.volume_record import scan as vr_scan  # noqa: PLC0415
    vr = vr_scan(db)
    vr_stage = {x["code"]: x for x in vr["items"]}
    record_today = {x["code"] for x in vr["items"] if x["event_date"] == vr["trading_date"]} | {x["code"] for x in vr.get("limit_up", [])}
    rows = []
    for r in cands.values():
        v = vr_stage.get(r["code"])
        r["vr_stage"] = v["stage"] if v else ""
        r["vr_signal"] = bool(v and v["entry_signal"])
        r["record_today"] = r["code"] in record_today
        r["grade"] = "A" if r["money"] else "B"
        r["close"] = round(r["close"])
        (limit if r["change_pct"] >= LIMIT_UP else rows).append(r)
    rows.sort(key=lambda r: (r["grade"], r["upper_pct"]))

    # 스윙 후보: 뜨거운 섹터 안에서 60일 고점(박스 상단)에 -2% 이내로 붙었거나 0~+3% 막 넘은 종목 (10~20일 보유 기준)
    # 3년 확인(같은 날 전 종목 평균 대비 20일 뒤): 붙음+뜨거운 섹터 +2.39%p, 막 넘음+뜨거운 섹터 +2.87%p,
    # 거래 2배로 터지며 넘은 경우는 +0.78%p로 약했고, 이미 +3% 넘게 더 간 종목은 +0.72%p.
    C, H = P["c"], P["h"]
    hi60 = H.iloc[-61:-1].max()
    hot_members = {c for f in hot for c in fam[f]["members"]}
    swing = []
    for code in hot_members:
        v = _stock_view(P, code)
        nm = names.get(code, code)
        if not v or any(k in nm for k in skip) or v["close"] < 1000 or TV[code].iloc[-5:].mean() < 1e9:
            continue
        top = float(hi60.get(code, float("nan")))
        if not top or top != top:
            continue
        pos = v["close"] / top - 1
        if not -0.02 <= pos < 0.03:
            continue
        vr_v = vr_stage.get(code)
        swing.append({"code": code, "name": nm, "close": round(v["close"]), "change_pct": v["change_pct"], "box_top": round(top),
                      "pos_pct": round(pos * 100, 1), "state": "막 넘음" if pos >= 0 else "붙음", "tv_x": v["tv_x"],
                      "loud": bool(v["tv_x"] and v["tv_x"] >= VOL_X and pos >= 0), "gap20_pct": v["gap20_pct"],
                      "families": [f for f in hot if code in fam[f]["members"]], "earn_up": code in earn_up,
                      "vr_stage": vr_v["stage"] if vr_v else "",
                      "market_cap": caps.get(code, (0, 0))[0] or caps.get(code, (0, 0))[1] * v["close"] or mc.get(code) or 0})
    swing.sort(key=lambda x: (x["loud"], -(x["market_cap"] or 0)))

    # 선취매 후보 (backend/screener/prebuy.py): 거래 터지기 전 조용한 종목
    from backend.screener.prebuy import frames, pick  # noqa: PLC0415
    swing_codes = {x["code"] for x in swing}
    prebuy = []
    for x in pick(P, frames(P), d, hot, {f: fam[f]["members"] for f in hot}, skip=lambda c: any(k in names.get(c, "") for k in skip)):
        x.update(name=names.get(x["code"], x["code"]), close=round(x["close"]), earn_up=x["code"] in earn_up, in_swing=x["code"] in swing_codes,
                 market_cap=caps.get(x["code"], (0, 0))[0] or caps.get(x["code"], (0, 0))[1] * x["close"] or mc.get(x["code"]) or 0)
        prebuy.append(x)
    prebuy.sort(key=lambda x: (-len(x["tags"]), -(x["market_cap"] or 0)))

    # 투자주의·경고·위험, 단기과열, 관리종목, 신용불가 (KIS, 후보 종목만)
    from backend.services.stock_flags import get as flags_get  # noqa: PLC0415
    fl = flags_get([x["code"] for x in rows + limit + swing + prebuy])
    for x in rows + limit + swing + prebuy:
        x["flags"] = fl.get(x["code"], {}).get("flags", [])
    limit.sort(key=lambda r: -(r["market_cap"] or 0))
    return {
        "trading_date": d.isoformat(), "market": regime,
        "market_ok": regime.get("state") in ("상승", "횡보"),
        "families": [{"family": f, "rank": fam[f]["rank"], "ret20_pct": round(fam[f]["ret20"] * 100, 1),
                      "tv_x": round(fam[f]["tv_x"], 2), "tv_med": round(fam[f]["tv_med"], 2), "money": fam[f]["tv_med"] >= MONEY_MED,
                      "stretch_pct": round(fam[f]["stretch"] * 100),
                      "status": "과열" if fam[f]["stretch"] >= 0.2 else ("주의" if fam[f]["stretch"] >= 0.1 else "")}
                     for f in order[:6]],
        "movers": _movers(fam, order),
        "hot": hot, "items": rows, "limit_up": limit, "swing": swing, "prebuy": prebuy,
    }


def _movers(fam: dict, order: list[str]) -> list[dict]:
    """움직이기 시작한 섹터: 상위 3 밖인데 최근 5일 시장 대비 +2%p↑ · 20일 안 돈 유입(거래대금 1.5배 + 섹터 +1%) 2번↑ · 순위 5일 새 3계단↑ 중 하나."""
    out = []
    for f in order[HOT_TOP:]:
        x = fam[f]
        why = []
        if x["ret5_rel"] >= 0.02:
            why.append(f"5일 시장 대비 +{x['ret5_rel'] * 100:.1f}%p")
        if x["inflow"] >= 2:
            why.append(f"20일 안 돈 유입 {x['inflow']}번")
        if x["rank_prev"] - x["rank"] >= 3:
            why.append(f"순위 {x['rank_prev']}→{x['rank']}위")
        if why:
            out.append({"family": f, "rank": x["rank"], "rank_prev": x["rank_prev"], "ret5_rel_pct": round(x["ret5_rel"] * 100, 1),
                        "inflow": x["inflow"], "tv_x": round(x["tv_x"], 2), "why": why})
    return sorted(out, key=lambda r: -len(r["why"]))


def check(db: Session, queries: list[str]) -> dict:
    """보유·관심 종목이 종베 단계(시장·섹터·돈 몰림·봉·과열)를 통과하는지."""
    latest, P = _load(db)
    members = family_members(db)
    fam, order = _families(P, members)
    hot = set(order[:HOT_TOP])
    regime = current_regime(db) or {}
    by_name = {n: c for c, n in db.execute(text("select code, name from stocks"))}
    overrides = get_overrides(db)
    # 같이 움직인 섹터: 최근 60거래일, 시장 전체(전 종목 중간값) 움직임을 뺀 일별 등락의 상관
    CH = P["ch"].iloc[-60:].where(P["ch"].iloc[-60:].abs() < 30)
    mkt = CH.median(axis=1)
    fam_ret = {f: CH[[x for x in m if x in CH.columns]].median(axis=1) - mkt for f, m in members.items() if len(m) >= 5}
    fam_of: dict[str, list[str]] = {}
    for f, m in members.items():
        for c in m:
            fam_of.setdefault(c, []).append(f)
    out = []
    for q in queries:
        q = q.strip()
        if not q:
            continue
        code = q if q in P["c"].columns else by_name.get(q)
        v = _stock_view(P, code) if code else None
        if not v:
            out.append({"query": q, "found": False})
            continue
        fs = fam_of.get(code, [])
        hot_fs = [f for f in fs if f in hot]
        best = min((fam[f]["rank"] for f in fs if f in fam), default=None)
        out.append({
            "query": q, "found": True, "code": code, "name": next((n for n, c in by_name.items() if c == code), code),
            "close": round(v["close"]), "change_pct": v["change_pct"], "tv_x": v["tv_x"], "upper_pct": v["upper_pct"], "gap20_pct": v["gap20_pct"],
            "families": fs[:4], "best_rank": best, "override": overrides.get(code, ""),
            "comove": [{"family": f, "corr": round(float(v), 2)} for f, v in sorted(
                ((f, (CH[code] - mkt).corr(r)) for f, r in fam_ret.items()), key=lambda x: -(x[1] if x[1] == x[1] else -9))[:2]],
            "checks": {
                "시장 상승·횡보": regime.get("state") in ("상승", "횡보"),
                "뜨거운 섹터": bool(hot_fs),
                "섹터에 돈 몰림": any(fam[f]["tv_med"] >= MONEY_MED for f in hot_fs),
                "+3% 양봉": v["bull"] and v["change_pct"] >= MIN_CHG,
                "거래 2배 이상": bool(v["tv_x"] and v["tv_x"] >= VOL_X),
                "윗꼬리 30% 이하": v["upper_pct"] <= 30,
                "이격 +30% 미만": v["gap20_pct"] is None or v["gap20_pct"] < 30,
            },
        })
    return {"trading_date": P["c"].index[-1].isoformat(), "families": list(FAMILIES), "items": out}


# ── 실전 기록: 매일 후보를 저장하고 다음 날 결과를 붙인다 ──────────────────────
def record(db: Session) -> int:
    from backend.db.models import JongbePick  # noqa: PLC0415
    res = scan(db)
    d = pd.Timestamp(res["trading_date"]).date()
    db.query(JongbePick).filter(JongbePick.trading_date == d).delete()
    n = 0
    for r in res["items"] + res["limit_up"]:
        db.add(JongbePick(trading_date=d, code=r["code"], name=r["name"], grade="상한가" if r in res["limit_up"] else r["grade"],
                          close_price=r["close"], change_pct=r["change_pct"], market_ok=res["market_ok"]))
        n += 1
    db.commit()
    return n


def performance(db: Session, days: int = 60) -> dict:
    """저장된 후보의 다음 거래일 시가·고가·종가 결과."""
    rows = db.execute(text("""
        select p.trading_date, p.code, p.name, p.grade, p.close_price, p.market_ok,
               n.trading_date, n.open_price, n.high_price, n.close_price
        from jongbe_picks p
        join lateral (select trading_date, open_price, high_price, close_price from spot_daily_prices s
                      where s.stock_code = p.code and s.trading_date > p.trading_date order by trading_date limit 1) n on true
        where p.trading_date >= current_date - :days
        order by p.trading_date desc"""), {"days": days}).all()
    items, agg = [], {}
    for d, code, name, grade, c, ok, nd, no, nh, nc in rows:
        if not c or not no:
            continue
        r_open, r_high, r_close = no / c - 1, nh / c - 1, nc / c - 1
        r_rule = r_open if no > c else r_close
        items.append({"date": d.isoformat(), "next_date": nd.isoformat(), "code": code, "name": name, "grade": grade, "market_ok": ok,
                      "open_pct": round(r_open * 100, 1), "high_pct": round(r_high * 100, 1), "close_pct": round(r_close * 100, 1),
                      "rule_pct": round(r_rule * 100, 1)})
        a = agg.setdefault(grade, {"n": 0, "win": 0, "rule": 0.0, "high": 0.0})
        a["n"] += 1
        a["win"] += r_rule > 0
        a["rule"] += r_rule
        a["high"] += r_high
    summary = {g: {"count": a["n"], "win_pct": round(a["win"] / a["n"] * 100), "avg_rule_pct": round(a["rule"] / a["n"] * 100, 2),
                   "avg_high_pct": round(a["high"] / a["n"] * 100, 2)} for g, a in agg.items() if a["n"]}
    return {"summary": summary, "items": items[:200]}
