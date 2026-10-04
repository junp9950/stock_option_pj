"""매매 일지: 체결 내역을 붙여넣으면 매수·매도를 짝지어(선입선출) 성과를 내고, 산 날의 상태별로 나눠 본다.

사람마다 이름 + 비밀번호로 기록을 나눈다 (사이트에 로그인이 없어 금액이 보이는 이 화면만 잠금).
유형: 같은 날 = 장중, 다음 거래일 = 종베, 2~10거래일 = 스윙, 그 이상 = 장기, 산 기록이 없으면 = 이전 보유.
산 날의 상태(자동 근거)는 그날 장 마감 시세로 계산한다: 거래 실린 양봉, 조용한 날, 빠진 날, 윗꼬리, 박스 상단,
과열(20일선 이격 +20%), 뜨거운 섹터(20일 상승 상위 3)와 섹터 돈 몰림(거래대금 1.2배), 시장 국면.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db.models import Setting, Stock, TradeExecution
from backend.screener.market_regime import regime_series
from backend.screener.rotation import family_members

USER_TAGS = ["박스 돌파", "상대강도", "눌림", "수렴", "섹터 순환", "대량거래", "뉴스·재료", "장투", "기타"]
KINDS = ["장중", "종베", "스윙", "장기"]


# ── 잠금 ────────────────────────────────────────────────────────
def _pin_key(owner: str) -> str:
    return f"journal_pin:{owner}"


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


def owners(db: Session) -> list[str]:
    rows = db.scalars(select(Setting.key).where(Setting.key.like("journal_pin:%"))).all()
    return sorted(k.split(":", 1)[1] for k in rows)


def auth(db: Session, owner: str, pin: str, create: bool = False) -> str:
    """'ok' / 'created' / 'bad' / 'none'(없는 이름, create=False)."""
    owner, pin = owner.strip()[:20], pin.strip()
    if not owner or len(pin) < 4:
        return "bad"
    row = db.scalar(select(Setting).where(Setting.key == _pin_key(owner)))
    if row is None:
        if not create:
            return "none"
        salt = secrets.token_hex(8)
        db.add(Setting(key=_pin_key(owner), value=f"{salt}${_hash(pin, salt)}"))
        db.commit()
        return "created"
    salt, h = row.value.split("$", 1)
    return "ok" if secrets.compare_digest(_hash(pin, salt), h) else "bad"


def get_cfg(db: Session, owner: str) -> dict:
    row = db.scalar(select(Setting).where(Setting.key == f"journal_cfg:{owner}"))
    return json.loads(row.value) if row else {"exclude": []}


def set_cfg(db: Session, owner: str, cfg: dict) -> dict:
    row = db.scalar(select(Setting).where(Setting.key == f"journal_cfg:{owner}"))
    if row is None:
        db.add(Setting(key=f"journal_cfg:{owner}", value=json.dumps(cfg, ensure_ascii=False)))
    else:
        row.value = json.dumps(cfg, ensure_ascii=False)
    db.commit()
    return cfg


# ── 붙여넣기 해석 ───────────────────────────────────────────────
def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("원", "").replace("주", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(s: str, today: date) -> date | None:
    s = s.strip()
    m = re.fullmatch(r"(20\d\d)[-./](\d{1,2})[-./](\d{1,2})\.?", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})\.?", s) or re.fullmatch(r"(\d{1,2})월(\d{1,2})일", s)
    if m:
        d = date(today.year, int(m[1]), int(m[2]))
        return d.replace(year=d.year - 1) if d > today + timedelta(days=7) else d
    return None


def parse(db: Session, raw: str, default_date: date) -> tuple[list[dict], list[str], int]:
    """증권사 체결 내역(탭 구분) 또는 '10/5 한양디지텍 매수 100 21500' 같은 자유 형식 줄 → 체결 목록, 못 읽은 줄, 날짜 보정(거래일 수)."""
    by_code, by_name = {}, {}
    for code, name in db.execute(select(Stock.code, Stock.name)):
        by_code[code], by_name[name.replace(" ", "")] = name, code
    out, bad = [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        cells = [c.strip() for c in re.split(r"\t|\s{2,}", line)]
        # 증권사 형식: 일자, 월, 번호, 매수/매도, A종목코드, 종목명, 수량, 단가, 금액, -, 수수료·세금, 매입금액, 손익, 수익률
        if len(cells) >= 9 and cells[3] in ("매수", "매도") and re.fullmatch(r"A?\d{6}|A?\d{5}[A-Z]", cells[4]):
            d = _date(cells[0], default_date)
            qty, px, amt = _num(cells[6]), _num(cells[7]), _num(cells[8])
            if d and qty and px:
                fee = _num(cells[10]) if len(cells) > 10 else None
                cost = _num(cells[11]) if len(cells) > 11 else None
                pnl = _num(cells[12]) if len(cells) > 12 else None
                code = cells[4].lstrip("A")
                out.append({"trade_date": d, "seq": cells[2], "side": cells[3], "code": code, "name": cells[5] or by_code.get(code, code),
                            "qty": int(qty), "price": px, "amount": amt or qty * px, "fee": fee or 0.0,
                            "broker_cost": cost, "broker_pnl": pnl})
                continue
        # 자유 형식
        toks = line.replace(",", "").split()
        d, side, code, nums = default_date, None, None, []
        for t in toks:
            if _date(t, default_date):
                d = _date(t, default_date)
            elif t in ("매수", "샀음", "삼", "buy") or t.startswith("매수"):
                side = "매수"
            elif t in ("매도", "팜", "팔았음", "sell") or t.startswith("매도"):
                side = "매도"
            elif re.fullmatch(r"A?\d{6}", t) and t.lstrip("A") in by_code:
                code = t.lstrip("A")
            elif t.replace(" ", "") in by_name:
                code = by_name[t]
            elif _num(t) is not None:
                nums.append((t, _num(t)))
            elif t.endswith("주") and _num(t[:-1]) is not None:
                nums.insert(0, ("주", _num(t[:-1])))
        if code is None:  # 띄어쓰기 있는 종목명
            for nm, c in by_name.items():
                if len(nm) >= 2 and nm in line.replace(" ", ""):
                    code = c if code is None or len(nm) > len(by_code[code]) else code
        if not (side and code and len(nums) >= 2):
            bad.append(line)
            continue
        qty, px = nums[0][1], nums[1][1]
        if qty > px:  # '가격 수량' 순서로 쓴 경우
            qty, px = px, qty
        out.append({"trade_date": d, "seq": "", "side": side, "code": code, "name": by_code[code], "qty": int(qty), "price": px,
                    "amount": qty * px, "fee": 0.0, "broker_cost": None, "broker_pnl": None})
    return out, bad, _settle_shift(db, out)


def _settle_shift(db: Session, rows: list[dict]) -> int:
    """증권사 내역의 '일자'가 결제일(체결 +2거래일)인 경우가 있다 (2026-10 사용자 내역: 201건 중 200건이 2거래일 전 시세 범위).
    체결가가 그날 고가~저가 안에 드는지로 0~2거래일 중 가장 잘 맞는 쪽을 골라 체결일로 옮긴다."""
    br = [r for r in rows if r["seq"]]
    if len(br) < 3:
        return 0
    lo_d, hi_d = min(r["trade_date"] for r in br), max(r["trade_date"] for r in br)
    days = [d for (d,) in db.execute(text("select distinct trading_date from spot_daily_prices where trading_date between :a and :b order by 1"),
                                       {"a": lo_d - timedelta(days=14), "b": hi_d})]
    d = days[-1] if days else lo_d - timedelta(days=14)
    while d < hi_d:   # 아직 시세가 없는 미래 결제일은 평일로 채운다
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in days:
            days.append(d)
    rng = {(c, dd): (lo, hi) for c, dd, lo, hi in db.execute(text(
        "select stock_code, trading_date, low_price, high_price from spot_daily_prices where trading_date between :a and :b and stock_code = any(:c)"),
        {"a": days[0], "b": hi_d, "c": list({r["code"] for r in br})})}

    def back(dd: date, k: int) -> date | None:
        prev = [x for x in days if x <= dd]
        return prev[-1 - k] if len(prev) > k else None

    fit = {}
    for k in (0, 1, 2):
        n = 0
        for r in br:
            dd = back(r["trade_date"], k)
            lohi = rng.get((r["code"], dd))
            n += bool(lohi and lohi[0] * 0.995 <= r["price"] <= lohi[1] * 1.005)
        fit[k] = n
    best = max(fit, key=lambda k: (fit[k], -k))
    if best == 0 or fit[best] < fit[0] + max(2, 0.2 * len(br)):
        return 0
    for r in br:
        r["trade_date"] = back(r["trade_date"], best) or r["trade_date"]
    return best


def _key(owner: str, e: dict) -> str:
    return f"{owner}|{e['trade_date']}|{e['seq']}|{e['side']}|{e['code']}|{e['qty']}|{e['price']:g}"


def add(db: Session, owner: str, rows: list[dict]) -> dict:
    have = set(db.scalars(select(TradeExecution.dedup_key).where(TradeExecution.owner == owner)).all())
    n = 0
    for e in rows:
        k = _key(owner, e)
        if k in have:
            continue
        have.add(k)
        db.add(TradeExecution(owner=owner, dedup_key=k, **e))
        n += 1
    db.commit()
    return {"added": n, "skipped": len(rows) - n}


# ── 산 날의 상태 ────────────────────────────────────────────────
_ctx_cache: dict = {}   # (start, latest, n_overrides) → 계산 결과


def _context(db: Session, start: date):
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    members = family_members(db)
    key = (start, latest, sum(len(v) for v in members.values()))
    if key in _ctx_cache:
        return _ctx_cache[key]
    px = pd.read_sql(text(
        "select stock_code, trading_date, open_price o, high_price h, low_price l, close_price c, trading_value tv, change_pct ch "
        "from spot_daily_prices where trading_date >= :d"), db.connection(), params={"d": start - timedelta(days=130)})
    P = {k: px.pivot(index="trading_date", columns="stock_code", values=k).sort_index() for k in ("o", "h", "l", "c", "tv", "ch")}
    C, TV = P["c"], P["tv"]
    ret20 = C / C.shift(20) - 1
    fam_ret, fam_tvx = {}, {}
    for f, mem in members.items():
        m = [x for x in mem if x in C.columns]
        if len(m) < 5:
            continue
        fam_ret[f] = ret20[m].median(axis=1)
        tv = TV[m].sum(axis=1)
        fam_tvx[f] = tv / tv.shift(1).rolling(20).mean()
    fam_rank = pd.DataFrame(fam_ret).rank(axis=1, ascending=False)
    chg = P["ch"].clip(-30, 30).mean(axis=1)
    regime = regime_series({d: float(v) for d, v in chg.items()})
    code_fams = defaultdict(list)
    for f, mem in members.items():
        for c in mem:
            code_fams[c].append(f)
    ctx = {"P": P, "fam_rank": fam_rank, "fam_tvx": pd.DataFrame(fam_tvx), "regime": regime, "code_fams": code_fams,
           "tv20": TV.shift(1).rolling(20).mean(), "ma20": C.rolling(20).mean(), "hi60": P["h"].shift(1).rolling(60).max(),
           "dates": list(C.index)}
    _ctx_cache.clear()
    _ctx_cache[key] = ctx
    return ctx


def _state(ctx, code: str, d: date, buy_px: float) -> dict | None:
    P = ctx["P"]
    C = P["c"]
    if code not in C.columns or d not in C.index or pd.isna(C.at[d, code]):
        return None
    o, h, l, c, tv, ch = (float(P[k].at[d, code]) for k in ("o", "h", "l", "c", "tv", "ch"))
    tv20, ma20, hi60 = (float(ctx[k].at[d, code]) for k in ("tv20", "ma20", "hi60"))
    tv_x = tv / tv20 if tv20 == tv20 and tv20 > 0 else None
    upper = (h - c) / (h - l) * 100 if h > l else 0.0
    gap = (c / ma20 - 1) * 100 if ma20 == ma20 and ma20 else None
    pos = (c / hi60 - 1) * 100 if hi60 == hi60 and hi60 else None
    fams = ctx["code_fams"].get(code, [])
    ranks = {f: int(ctx["fam_rank"].at[d, f]) for f in fams if f in ctx["fam_rank"].columns and ctx["fam_rank"].at[d, f] == ctx["fam_rank"].at[d, f]}
    hot = [f for f, r in ranks.items() if r <= 3]
    money = any(float(ctx["fam_tvx"].at[d, f]) >= 1.2 for f in hot)
    reg = ctx["regime"].get(d, {}).get("state", "")
    tags = []
    if c > o and ch >= 3 and tv_x and tv_x >= 2:
        tags.append("거래 실린 양봉")
    if tv_x is not None and tv_x <= 0.6:
        tags.append("조용한 날")
    if ch <= -2:
        tags.append("빠진 날")
    if upper >= 60 and h > l and (h / l - 1) >= 0.04:
        tags.append("윗꼬리 긴 날")
    if pos is not None and -2 <= pos < 3:
        tags.append("박스 상단")
    if gap is not None and gap >= 20:
        tags.append("과열(이격 20%↑)")
    tags.append("뜨거운 섹터" if hot else "섹터 밖")
    if money:
        tags.append("섹터 돈 몰림")
    if reg == "하락":
        tags.append("하락장")
    return {"change_pct": round(ch, 2), "tv_x": round(tv_x, 2) if tv_x else None, "upper_pct": round(upper),
            "gap20_pct": round(gap, 1) if gap is not None else None, "box_pos_pct": round(pos, 1) if pos is not None else None,
            "vs_close_pct": round((buy_px / c - 1) * 100, 2), "families": sorted(fams, key=lambda f: ranks.get(f, 99))[:3],
            "hot": hot, "regime": reg, "tags": tags}


# ── 짝 맞추기·분석 ──────────────────────────────────────────────
def _kind(days: int | None) -> str:
    if days is None:
        return "이전 보유"
    return "장중" if days == 0 else "종베" if days == 1 else "스윙" if days <= 10 else "장기"


def _stats(trips: list[dict]) -> dict:
    n = len(trips)
    if not n:
        return {"count": 0}
    cost = sum(t["buy_amount"] for t in trips)
    pnl = sum(t["pnl"] for t in trips)
    wins = [t for t in trips if t["pnl"] > 0]
    loss = [t for t in trips if t["pnl"] <= 0]
    return {"count": n, "win_pct": round(len(wins) / n * 100), "avg_pct": round(sum(t["pct"] for t in trips) / n, 2),
            "pnl": round(pnl), "ret_on_cost_pct": round(pnl / cost * 100, 2) if cost else 0,
            "avg_win_pct": round(sum(t["pct"] for t in wins) / len(wins), 2) if wins else None,
            "avg_loss_pct": round(sum(t["pct"] for t in loss) / len(loss), 2) if loss else None,
            "worst_pct": round(min(t["pct"] for t in trips), 2), "best_pct": round(max(t["pct"] for t in trips), 2)}


def analyze(db: Session, owner: str) -> dict:
    ex = db.scalars(select(TradeExecution).where(TradeExecution.owner == owner)
                    .order_by(TradeExecution.trade_date, TradeExecution.id)).all()
    cfg = get_cfg(db, owner)
    excl = set(cfg.get("exclude") or [])
    execs = [{"id": e.id, "date": e.trade_date.isoformat(), "seq": e.seq, "side": e.side, "code": e.code, "name": e.name,
              "qty": e.qty, "price": e.price, "amount": e.amount, "fee": e.fee, "tag": e.tag, "memo": e.memo, "kind": e.kind}
             for e in ex]
    if not ex:
        return {"executions": [], "trips": [], "summary": {}, "insights": [], "cfg": cfg, "user_tags": USER_TAGS, "kinds": KINDS}

    ctx = _context(db, min(e.trade_date for e in ex))
    # 입력 점검: 체결가가 그날 시세 범위(고가~저가, 시간외 감안 ±3%) 밖이면 날짜나 가격이 잘못 들어온 것
    Hh, Ll = ctx["P"]["h"], ctx["P"]["l"]
    warn = []
    for x in execs:
        d = date.fromisoformat(x["date"])
        if x["code"] in Hh.columns and d in Hh.index and Hh.at[d, x["code"]] == Hh.at[d, x["code"]]:
            hi, lo = float(Hh.at[d, x["code"]]), float(Ll.at[d, x["code"]])
            if not lo * 0.97 <= x["price"] <= hi * 1.03:
                x["price_warn"] = f"그날 시세 {lo:,.0f}~{hi:,.0f}원 밖"
                warn.append(x)
    tdays = ctx["dates"]
    tidx = {d: i for i, d in enumerate(tdays)}

    def ndays(a: date, b: date) -> int:
        if a in tidx and b in tidx:
            return tidx[b] - tidx[a]
        return sum(1 for d in tdays if a < d <= b)

    # 같은 날 체결 순서: 증권사 번호가 있으면 번호 순, 없으면 입력 순 (같은 날 매수 → 매도로 짝지음)
    def order(e):
        return (e.trade_date, int(e.seq) if e.seq.isdigit() else 10**9 + e.id)

    lots = defaultdict(list)    # code → [[date, qty, price, exec]]
    raw_trips = []
    for e in sorted(ex, key=order):
        if e.side == "매수":
            lots[e.code].append([e.trade_date, e.qty, e.price, e])
            continue
        left = e.qty
        while left > 0 and lots[e.code]:
            lot = lots[e.code][0]
            q = min(left, lot[1])
            raw_trips.append((lot[3], e, q, lot[2]))
            lot[1] -= q
            left -= q
            if lot[1] == 0:
                lots[e.code].pop(0)
        if left > 0:   # 기록 전부터 갖고 있던 물량: 증권사 매입금액이 있으면 그 평균가를 쓴다
            px = e.broker_cost / e.qty if e.broker_cost else None
            if px:
                raw_trips.append((None, e, left, px))

    groups = {}
    for b, s, q, bpx in raw_trips:
        k = (s.code, b.trade_date if b else None, s.trade_date, b.id if b and b.kind else None)
        g = groups.setdefault(k, {"code": s.code, "name": s.name, "buy_date": b.trade_date if b else None, "sell_date": s.trade_date,
                                  "qty": 0, "buy_amount": 0.0, "sell_amount": 0.0, "fee": 0.0, "buys": [], "kind_set": ""})
        g["qty"] += q
        g["buy_amount"] += q * bpx
        g["sell_amount"] += q * s.price
        g["fee"] += (s.fee or 0) * q / s.qty if s.qty else 0
        if b is not None:
            g["buys"].append(b)
            g["kind_set"] = g["kind_set"] or b.kind
    trips = []
    for g in groups.values():
        days = ndays(g["buy_date"], g["sell_date"]) if g["buy_date"] else None
        buy_px = g["buy_amount"] / g["qty"]
        pnl = g["sell_amount"] - g["buy_amount"] - g["fee"]
        user_tags = sorted({b.tag for b in g["buys"] if b.tag})
        st = _state(ctx, g["code"], g["buy_date"], buy_px) if g["buy_date"] else None
        trips.append({"code": g["code"], "name": g["name"], "buy_date": g["buy_date"].isoformat() if g["buy_date"] else None,
                      "sell_date": g["sell_date"].isoformat(), "days": days, "kind": g["kind_set"] or _kind(days),
                      "qty": g["qty"], "buy_px": round(buy_px, 1), "sell_px": round(g["sell_amount"] / g["qty"], 1),
                      "buy_amount": round(g["buy_amount"]), "pnl": round(pnl), "pct": round(pnl / g["buy_amount"] * 100, 2),
                      "user_tags": user_tags, "state": st, "excluded": g["code"] in excl or "장투" in user_tags})
    trips.sort(key=lambda t: (t["sell_date"], t["buy_date"] or ""), reverse=True)

    # 아직 들고 있는 물량
    holding = []
    for code, ls in lots.items():
        for d, q, px, b in ls:
            if q > 0:
                holding.append({"code": code, "name": b.name, "buy_date": d.isoformat(), "qty": q, "price": px, "tag": b.tag,
                                "state": _state(ctx, code, d, px)})
    last = ctx["dates"][-1]
    for h in holding:
        c = ctx["P"]["c"]
        cur = float(c.at[last, h["code"]]) if h["code"] in c.columns and c.at[last, h["code"]] == c.at[last, h["code"]] else None
        h["close"], h["eval_pct"] = cur, round((cur / h["price"] - 1) * 100, 2) if cur else None

    use = [t for t in trips if not t["excluded"]]
    by = lambda key: {k: _stats(v) for k, v in key.items()}  # noqa: E731
    g_kind, g_tag, g_user, g_month, g_fam = (defaultdict(list) for _ in range(5))
    for t in use:
        g_kind[t["kind"]].append(t)
        g_month[t["sell_date"][:7]].append(t)
        for u in t["user_tags"] or ["(근거 안 적음)"]:
            g_user[u].append(t)
        if t["state"]:
            for a in t["state"]["tags"]:
                g_tag[a].append(t)
            for f in t["state"]["families"][:1] or ["섹터 없음"]:
                g_fam[f].append(t)
    summary = {"all": _stats(use), "by_kind": by(g_kind), "by_state": by(g_tag), "by_user_tag": by(g_user),
               "by_month": by(g_month), "by_family": by(g_fam)}
    return {"executions": list(reversed(execs)), "trips": trips, "holding": holding, "summary": summary,
            "insights": ([f"⚠️ 체결가가 그날 시세 범위 밖인 기록 {len(warn)}건 — 날짜나 가격을 확인해 주세요 (체결 내역 보기에 표시)"] if warn else []) + _insights(use, g_tag, g_kind), "cfg": cfg, "user_tags": USER_TAGS, "kinds": KINDS,
            "as_of": last.isoformat()}


def _insights(use: list[dict], g_tag: dict, g_kind: dict) -> list[str]:
    """숫자로 보이는 차이만 짧게. 건수가 적으면 말하지 않는다."""
    out = []
    if len(use) < 5:
        return ["아직 기록이 적어서 경향을 말하기 이릅니다 (청산 5건 이상부터)."]
    base = _stats(use)
    pairs = [("거래 실린 양봉", "조용한 날"), ("뜨거운 섹터", "섹터 밖")]
    for a, b in pairs:
        sa, sb = _stats(g_tag.get(a, [])), _stats(g_tag.get(b, []))
        if sa["count"] >= 3 and sb["count"] >= 3:
            out.append(f"{a}에 산 것 평균 {sa['avg_pct']:+.2f}%({sa['count']}건, 이긴 비율 {sa['win_pct']}%) vs {b} {sb['avg_pct']:+.2f}%({sb['count']}건, {sb['win_pct']}%)")
    for t in ("빠진 날", "윗꼬리 긴 날", "과열(이격 20%↑)", "박스 상단", "섹터 돈 몰림", "하락장"):
        s = _stats(g_tag.get(t, []))
        if s["count"] >= 3 and abs(s["avg_pct"] - base["avg_pct"]) >= 0.5:
            out.append(f"{t}에 산 것 평균 {s['avg_pct']:+.2f}%({s['count']}건) — 전체 평균 {base['avg_pct']:+.2f}%보다 {'좋음' if s['avg_pct'] > base['avg_pct'] else '나쁨'}")
    ks = {k: _stats(v) for k, v in g_kind.items() if len(v) >= 3}
    if len(ks) >= 2:
        best = max(ks, key=lambda k: ks[k]["pnl"])
        worst = min(ks, key=lambda k: ks[k]["pnl"])
        if best != worst:
            out.append(f"가장 많이 번 유형: {best}({ks[best]['pnl']:+,}원) · 가장 나쁜 유형: {worst}({ks[worst]['pnl']:+,}원)")
    loss = sorted(use, key=lambda t: t["pnl"])[:3]
    if loss and loss[0]["pnl"] < 0:
        out.append("가장 큰 손실: " + ", ".join(f"{t['name']} {t['pct']:+.1f}%({t['pnl']:+,}원, {t['kind']})" for t in loss if t["pnl"] < 0))
    return out


def update_exec(db: Session, owner: str, ex_id: int, fields: dict) -> bool:
    e = db.get(TradeExecution, ex_id)
    if not e or e.owner != owner:
        return False
    for k in ("tag", "memo", "kind"):
        if k in fields and fields[k] is not None:
            setattr(e, k, str(fields[k])[:200])
    e.updated_at = datetime.utcnow()
    db.commit()
    return True


def delete_exec(db: Session, owner: str, ex_id: int) -> bool:
    e = db.get(TradeExecution, ex_id)
    if not e or e.owner != owner:
        return False
    db.delete(e)
    db.commit()
    return True
