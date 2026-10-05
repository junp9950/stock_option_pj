"""사용자 종베 채점 (2026-10-05 "매일 내가 종베 종목, 진입가격 알려줄 테니까 체크하고 비교해서 성공률을 높여 보자").

사용자가 텔레그램 /종베 로 그날 종베 종목·진입가를 남기면
  1) 장 마감 데이터가 들어온 뒤 그 종목이 종베 화면 후보였는지(A/B/🤖) · 아니면 어느 조건에서 빠졌는지
  2) 다음 날부터 결과: 다음 날 시가·고가·종가, 단순 규칙(갭 상승이면 시가, 아니면 종가 매도),
     분할 매도 규칙(다음 날 +2% 미만이면 전부, 이상이면 30%·다음 날 더 오르면 30%, 나머지는 최고 종가 -15% 또는 본전 이탈)
를 붙이고, 같은 날 화면 A등급·🤖 선택과 나란히 비교한다. 고르는 기준을 맞춰 가는 재료.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.db.models import JongbePick, Stock, UserJongbe

OWNER = "감사하모니카"


def today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _find(db: Session, q: str):
    q = q.strip()
    return db.execute(select(Stock.code, Stock.name).where((Stock.code == q) | (Stock.name == q))).first() or \
        db.execute(select(Stock.code, Stock.name).where(Stock.name.like(f"%{q}%")).order_by(Stock.market_cap.desc().nullslast()).limit(1)).first()


def add(db: Session, q: str, price: float, note: str = "", day: date | None = None, owner: str = OWNER) -> dict:
    row = _find(db, q)
    if not row:
        raise ValueError(f"종목을 못 찾았습니다: {q}")
    day = day or today_kst()
    x = db.scalar(select(UserJongbe).where(UserJongbe.owner == owner, UserJongbe.trading_date == day, UserJongbe.code == row.code))
    if x is None:
        x = UserJongbe(owner=owner, trading_date=day, code=row.code, name=row.name)
        db.add(x)
    x.entry_price, x.note = float(price), note.strip()[:200]
    db.commit()
    return {"code": row.code, "name": row.name, "date": day.isoformat(), "entry": x.entry_price}


def remove(db: Session, q: str, day: date | None = None, owner: str = OWNER) -> int:
    row = _find(db, q)
    if not row:
        return 0
    n = 0
    for x in db.scalars(select(UserJongbe).where(UserJongbe.owner == owner, UserJongbe.trading_date == (day or today_kst()), UserJongbe.code == row.code)):
        db.delete(x)
        n += 1
    db.commit()
    return n


# ── 그날 화면 후보였나 / 어디서 빠졌나 ─────────────────────────────
def diagnose(db: Session, day: date, code: str) -> dict:
    from backend.screener import jongbe as J  # noqa: PLC0415
    from backend.screener.rotation import family_members  # noqa: PLC0415
    pick = db.scalar(select(JongbePick).where(JongbePick.trading_date == day, JongbePick.code == code))
    out = {"grade": pick.grade if pick else None, "ai": bool(pick and pick.ai_pick), "why_not": [], "families": []}
    latest, P = J._load(db)
    if day not in P["c"].index or code not in P["c"].columns:
        out["why_not"].append("그날 가격 데이터 없음")
        return out
    Pd = {k: v.loc[:day] for k, v in P.items()}
    fam, order = J._families(Pd, family_members(db))
    hot = order[:J.HOT_TOP]
    v = J._stock_view(Pd, code)
    mine = [f for f in fam if code in fam[f]["members"]]
    out["families"] = [{"family": f, "rank": order.index(f) + 1, "money": fam[f]["tv_med"] >= J.MONEY_MED} for f in mine]
    if v:
        out.update(change_pct=round(v["change_pct"], 1), tv_x=round(v["tv_x"] or 0, 1), upper_pct=v.get("upper_pct"), gap20_pct=v.get("gap20_pct"))
    if pick:
        return out
    w = out["why_not"]
    in_hot = any(f in hot for f in mine)
    if not in_hot:
        best = min((order.index(f) + 1 for f in mine), default=None)
        w.append(f"뜨는 섹터(상위 {J.HOT_TOP}) 밖" + (f" — 속한 섹터 최고 {best}위" if best else " — 섹터 묶음에 없음"))
    if v:
        if not v["bull"]:
            w.append("음봉")
        if v["change_pct"] < J.MIN_CHG:
            w.append(f"+{J.MIN_CHG:.0f}% 미만 ({v['change_pct']:+.1f}%)")
        if not v["tv_x"] or v["tv_x"] < J.VOL_X:
            w.append(f"거래 {J.VOL_X:.0f}배 미만 ({(v['tv_x'] or 0):.1f}배)")
        if float(P["tv"][code].loc[day]) < J.MIN_TV:
            w.append("거래대금 30억 미만")
    if not w:     # 그날 후보 기록이 없는 날(기록 시작 전·수집 실패) — 조건으로 등급 추정
        money = any(fam[f]["tv_med"] >= J.MONEY_MED for f in mine if f in hot)
        out["grade"] = ("A" if money else "B") + "(추정)"
    return out


# ── 결과 ───────────────────────────────────────────────────────
def _scale_out(e: float, closes: list[float], trail: float = 0.15, hold: int = 40) -> tuple[float, int, bool]:
    """분할 매도 규칙 (scratchpad/scale3.py run2와 같은 계산, small_all=True, trail 15%). (수익률, 보유일, 끝났는지)"""
    if not closes:
        return 0.0, 0, False
    c1 = closes[0]
    d1 = c1 / e - 1
    if d1 < 0.02:
        return d1, 1, True
    pos, pnl = 0.7, 0.3 * d1
    if len(closes) < 2:
        return pnl + pos * d1, 1, False
    c2 = closes[1]
    if c2 > c1:
        pnl += 0.3 * (c2 / e - 1)
        pos -= 0.3
    peak, stop = max(c1, c2), e
    for k in range(2, min(len(closes), hold)):
        c = closes[k]
        peak = max(peak, c)
        stop = max(stop, peak * (1 - trail), e)
        if c < stop:
            return pnl + pos * (c / e - 1), k + 1, True
    last = closes[-1]
    return pnl + pos * (last / e - 1), len(closes), len(closes) >= hold


def result(db: Session, x) -> dict | None:
    rows = db.execute(text("select trading_date, open_price, high_price, close_price from spot_daily_prices "
                           "where stock_code = :c and trading_date > :d order by trading_date limit 40"),
                      {"c": x.code, "d": x.trading_date}).all()
    if not rows or not x.entry_price:
        return None
    e = x.entry_price
    nd, no, nh, nc = rows[0]
    r_rule = (no if no > e else nc) / e - 1
    so, held, done = _scale_out(e, [float(r[3]) for r in rows])
    return {"next_date": nd.isoformat(), "open": no / e - 1, "high": nh / e - 1, "close": nc / e - 1, "rule": r_rule,
            "scale": so, "held": held, "done": done}


def _pct(v: float) -> str:
    return f"{v * 100:+.1f}%"


def report(db: Session, days: int = 60, owner: str = OWNER) -> dict:
    """사용자 종베 결과와 같은 날 화면 A등급·🤖 선택 비교."""
    from backend.screener.jongbe import performance  # noqa: PLC0415
    xs = list(db.scalars(select(UserJongbe).where(UserJongbe.owner == owner).order_by(UserJongbe.trading_date.desc(), UserJongbe.id)))
    items, dates = [], set()
    for x in xs:
        r = result(db, x)
        items.append({"x": x, "r": r})
        if r:
            dates.add(x.trading_date.isoformat())
    perf = performance(db, days)["items"]
    same = [p for p in perf if p["date"] in dates]

    def agg(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return {"n": len(vals), "win": round(sum(v > 0 for v in vals) / len(vals) * 100), "avg": round(sum(vals) / len(vals) * 100, 2)}
    done = [i for i in items if i["r"]]
    return {
        "items": items,
        "me": agg([i["r"]["rule"] for i in done]),
        "me_scale": agg([i["r"]["scale"] for i in done if i["r"]["done"]]),
        "screen_a": agg([p["rule_pct"] / 100 for p in same if p["grade"] == "A"]),
        "ai": agg([p["rule_pct"] / 100 for p in same if p.get("ai_pick")]),
        "dates": len(dates),
    }


def daily_text(db: Session, day: date | None = None, owner: str = OWNER) -> str | None:
    """장 마감 뒤 보낼 채점: 오늘 남긴 종베 진단 + 결과 나온 지난 종베 + 누적 비교."""
    day = day or today_kst()
    xs = list(db.scalars(select(UserJongbe).where(UserJongbe.owner == owner).order_by(UserJongbe.trading_date.desc())))
    if not xs:
        return None
    lines = ["📒 <b>종베 채점</b>"]
    todays = [x for x in xs if x.trading_date == day]
    if todays:
        lines.append(f"\n<b>오늘({day.strftime('%m/%d')}) 남긴 종베</b>")
        for x in todays:
            d = diagnose(db, day, x.code)
            tag = (f"화면 {d['grade']}등급" + (" · 🤖도 고름" if d["ai"] else "")) if d["grade"] else "화면 후보 아님"
            lines.append(f"<b>{escape(x.name)}</b> {x.entry_price:,.0f}원 · {tag}")
            if d.get("change_pct") is not None:
                lines.append(f"   └ 오늘 {d['change_pct']:+.1f}% · 거래 {d['tv_x']}배" + (f" · 윗꼬리 {d['upper_pct']}%" if d.get("upper_pct") is not None else ""))
            if d["why_not"]:
                lines.append(f"   └ 빠진 이유: {', '.join(d['why_not'])}")
    prev = [x for x in xs if x.trading_date < day]
    fresh = []
    for x in prev:
        r = result(db, x)
        if r and r["next_date"] == day.isoformat():
            fresh.append((x, r))
    if fresh:
        lines.append("\n<b>어제 종베 결과</b> (진입가 대비)")
        for x, r in fresh:
            lines.append(f"<b>{escape(x.name)}</b> 시가 {_pct(r['open'])} · 고가 {_pct(r['high'])} · 종가 {_pct(r['close'])} → 규칙 {_pct(r['rule'])}"
                         + ("" if r["close"] >= 0.02 else " (분할 규칙: 전부 정리)"))
    rp = report(db, owner=owner)
    if rp["me"]:
        def s(a):
            return f"{a['n']}건 이김 {a['win']}% 평균 {a['avg']:+.2f}%" if a else "없음"
        lines.append(f"\n<b>누적</b> ({rp['dates']}일, 다음 날 갭이면 시가·아니면 종가)")
        lines.append(f"· 내 종베: {s(rp['me'])}")
        lines.append(f"· 같은 날 화면 A등급: {s(rp['screen_a'])}")
        lines.append(f"· 같은 날 🤖 선택: {s(rp['ai'])}")
        if rp["me_scale"]:
            lines.append(f"· 내 종베 분할 매도 규칙(끝난 것): {s(rp['me_scale'])}")
    return "\n".join(lines) if len(lines) > 1 else None
