"""매일 마감 신호 기록 + 토요일 아침 주간 점검 (2026-10-09 사용자 "진행하고").

1) log_signals: 평일 저녁(18:30, 시세 다시 받은 뒤) 그날 ▲ 진입 · 종가 진입 점수 6↑ 종목을 settings 'signal_log'에 남긴다.
   차트 신호는 지금 규칙으로 과거를 다시 그린 것이라, "그날 실제로 뜬 신호"를 따로 쌓아 실전 성적을 본다
   (사용자 "과거 데이터 보고 후행하는 거 아니가").
2) weekly_text: 토요일 08:30 텔레그램 — 이번 주 규칙 어긴 매매 · 관심 종목 중 20일선 깨진 것 · 섹터 돈 들어온/빠진 곳 · 이번 주 신호 성적.
   금액은 쓰지 않고 % 만.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
LOG_KEY = "signal_log"
OWNER = "junp"


def log_signals(db: Session) -> str:
    from backend.services.stock_signals import _bull_days, _close_scores, _entry_today  # noqa: PLC0415
    from backend.services.telegram import _get, _put  # noqa: PLC0415
    from backend.utils.dates import is_trading_day  # noqa: PLC0415
    today = date.today()
    latest = db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    if latest != today or not is_trading_day(today):
        return "오늘 시세 없음"
    log = _get(db, LOG_KEY, {}) or {}
    entries = _entry_today(db, latest)          # 캐시를 거치지 않고 지금 DB로 바로 계산
    sc = _close_scores(db, latest).get("scores", {})
    names = dict(db.execute(text("select code, name from stocks")).all())
    log[str(latest)] = {
        "at": datetime.now().strftime("%H:%M"), "bull": bool(_bull_days(db).get(latest, False)),
        "entry": [{"code": x["code"], "name": x["name"], "kind": x["kind"], "close": x["close"], "stop": round(x["stop"])} for x in entries],
        "score": [{"code": c, "name": names.get(c, c), "score": v["score"], "stop": round(v["stop"])} for c, v in sc.items() if v["score"] >= 6],
    }
    try:      # 비교용 뒷기록 (화면·텔레그램엔 안 보임, 2026-10-09 사용자 "뒤로 백데이터로 · 어디에 뜨게는 하지 말고")
        log[str(latest)]["lazy"] = _lazy_today(db, latest)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Lazy식 신호 기록 실패: %s", exc)
    for k in sorted(log)[:-400]:                 # 400일만 들고 있는다
        log.pop(k)
    _put(db, LOG_KEY, log)
    return f"진입 {len(log[str(latest)]['entry'])} · 점수6↑ {len(log[str(latest)]['score'])}"


def _lazy_today(db: Session, latest) -> dict:
    """Lazy Alpha 툴팁 규칙을 역산한 진입·눌림 진입 (lazy_reentry.py와 같은 규칙) — 우리 신호와 앞으로의 데이터로 비교하려고 매일 남긴다.
    진입 = EMA8>14>21>55 정배열이 어제·오늘 유지 + (종가 21선 재돌파 또는 저가가 14·21선 0.5% 안 닿고 종가 14선 위 양봉).
    눌림 = 최근 10일 안 진입 뒤 저가가 8·14선 1% 안 + 양봉 + 거래량 전날보다 늘고 + 종가 14선 위. 거래대금 20일 평균 30억↑ · 상승·횡보장.
    3년 뒤돌아보기(같은 매도): 진입 R +0.10 · 눌림 +0.15 vs 우리 점수 6↑ +0.57."""
    import numpy as np  # noqa: PLC0415
    from backend.services.stock_signals import _bull_days  # noqa: PLC0415
    if not _bull_days(db).get(latest, False):
        return {"entry": [], "pull": [], "breakout": []}
    dates = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_prices where trading_date >= cast(:d as date) - 200 "
                                           "and trading_date <= :d order by 1"), {"d": latest}).all()]
    codes = [r[0] for r in db.execute(text("select distinct stock_code from spot_daily_prices where trading_date = :d"), {"d": latest}).all()]
    di, ci = {d: i for i, d in enumerate(dates)}, {c: i for i, c in enumerate(codes)}
    A = {k: np.full((len(dates), len(codes)), np.nan, dtype="float64") for k in ("o", "l", "c", "v", "t")}
    for s_, d_, o_, l_, c_, v_, t_ in db.execute(text("select stock_code, trading_date, open_price, low_price, close_price, volume, trading_value "
                                                      "from spot_daily_prices where trading_date >= cast(:d as date) - 200 and trading_date <= :d"), {"d": latest}):
        j = ci.get(s_)
        if j is None:
            continue
        i = di[d_]
        A["o"][i, j], A["l"][i, j], A["c"][i, j], A["v"][i, j], A["t"][i, j] = o_ or np.nan, l_ or np.nan, c_ or np.nan, v_ or np.nan, t_ or np.nan
    C = pd.DataFrame(A["c"])
    e8, e14, e21, e55 = (C.ewm(span=n, adjust=False).mean().values for n in (8, 14, 21, 55))
    O, L, Cn, V = A["o"], A["l"], A["c"], A["v"]
    liq = pd.DataFrame(A["t"]).rolling(20).mean().values >= 1e9      # Lazy Alpha는 작은 종목도 잡아서 10억까지 넓게 (2026-10-09 미래반도체 17억·대성에너지 29억)
    al = (e8 > e14) & (e14 > e21) & (e21 > e55)
    def ent(r):
        reclaim = al[r] & al[r - 1] & (Cn[r] > e21[r]) & (Cn[r - 1] <= e21[r - 1])
        sup = al[r] & al[r - 1] & ((L[r] <= e14[r] * 1.005) | (L[r] <= e21[r] * 1.005)) & (Cn[r] > e14[r]) & (Cn[r] > O[r])
        return (reclaim | sup) & liq[r]
    r = len(dates) - 1
    e_now = ent(r)
    recent = np.zeros(len(codes), bool)
    for k in range(1, 11):
        recent |= ent(r - k)
    pull = recent & al[r] & ((L[r] <= e8[r] * 1.01) | (L[r] <= e14[r] * 1.01)) & (Cn[r] > O[r]) & (V[r] > V[r - 1]) & (Cn[r] > e14[r]) & liq[r]
    # 돌파 진입 = 오늘 처음 EMA8>14>21>55 정배열 + 거래량 50일 평균(오늘 포함) 1.5배↑ + 양봉 (역산 7/7 일치, project_lazy_alpha)
    v50 = pd.DataFrame(V).rolling(50).mean().values
    brk = al[r] & ~al[r - 1] & (V[r] >= v50[r] * 1.5) & (Cn[r] > O[r]) & liq[r]
    pick = lambda m: [{"code": codes[j], "close": float(Cn[r, j]), "stop": round(float(L[r, j]) * 0.99)} for j in np.where(m)[0]]  # noqa: E731
    return {"entry": pick(e_now), "pull": pick(pull), "breakout": pick(brk)}


def _closes(db: Session, codes: list[str], since: date) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame()
    px = pd.read_sql(text("select stock_code s, trading_date d, close_price c from spot_daily_prices where trading_date >= :d and stock_code = any(:cs)"),
                     db.connection(), params={"d": since, "cs": codes})
    return px.pivot(index="d", columns="s", values="c").sort_index().astype(float)


def _week(db: Session, asof: date | None = None) -> list[date]:
    last = asof or db.execute(text("select max(trading_date) from spot_daily_prices")).scalar()
    mon = last - timedelta(days=last.weekday())
    return [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_prices where trading_date between :a and :b order by 1"),
                                     {"a": mon, "b": last}).all()]


def _rules_part(db: Session, days: list[date]) -> list[str]:
    from backend.services.trade_journal import analyze  # noqa: PLC0415
    a = analyze(db, OWNER)
    wk = [t for t in a.get("trips", []) if not t["excluded"] and t["sell_date"] >= str(days[0])]
    if not wk:
        return ["📒 <b>이번 주 매매</b>: 청산 기록 없음 (매매 일지에 넣으면 점검합니다)"]
    chk = [t for t in wk if t["rules"]]
    bad = [t for t in chk if t["rules"]["broke"]]
    avg = lambda ts: sum(t["pct"] for t in ts) / len(ts) if ts else 0.0  # noqa: E731
    ok = [t for t in chk if not t["rules"]["broke"]]
    out = [f"📒 <b>이번 주 매매 {len(wk)}건</b> (장중 매매 빼고 점검 {len(chk)}건)",
           f"✅ 지킴 {len(ok)}건 평균 {avg(ok):+.1f}%" + (f" · ⛔ 어김 {len(bad)}건 평균 {avg(bad):+.1f}%" if bad else " · 어긴 매매 없음 👍")]
    for t in bad[:8]:
        out.append(f"  ⛔ {t['name']} {t['pct']:+.1f}% — " + " · ".join(b.replace("⛔ ", "") for b in t["rules"]["broke"]))
    return out


def _watch_part(db: Session, days: list[date]) -> list[str]:
    from backend.services.watchlist import _items  # noqa: PLC0415
    items = _items(db)
    C = _closes(db, [x["code"] for x in items], days[0] - timedelta(days=120))
    if C.empty:
        return []
    e20 = C.ewm(span=20, adjust=False).mean()
    prev = C.index[C.index < days[0]]
    if not len(prev):
        return []
    p = prev[-1]
    broke, below = [], 0
    for x in items:
        c = x["code"]
        if c not in C.columns or pd.isna(C[c].iloc[-1]):
            continue
        now_below = C[c].iloc[-1] < e20[c].iloc[-1]
        below += bool(now_below)
        if now_below and C[c].get(p, float("nan")) >= e20[c].get(p, float("nan")):
            broke.append(f"  ⛔ {x['name']} 이번 주 {(C[c].iloc[-1] / C[c][p] - 1) * 100:+.1f}% · 20일선 아래로 마감")
    head = f"👀 <b>관심 종목 {len(items)}개</b> — 이번 주 20일선 깨진 것 {len(broke)}개 (지금 20일선 아래 {below}개)"
    return [head] + broke[:12]


def _sector_part(db: Session, days: list[date]) -> list[str]:
    from backend.screener.rotation import family_members  # noqa: PLC0415
    fam = family_members(db)
    codes = sorted({c for m in fam.values() for c in m})
    px = pd.read_sql(text("select stock_code s, trading_date d, close_price c, trading_value tv from spot_daily_prices "
                          "where trading_date >= :d and stock_code = any(:cs)"), db.connection(), params={"d": days[0] - timedelta(days=45), "cs": codes})
    C = px.pivot(index="d", columns="s", values="c").sort_index().astype(float)
    TV = px.pivot(index="d", columns="s", values="tv").sort_index().astype(float)
    prev = C.index[C.index < days[0]]
    if len(prev) < 20:
        return []
    ret = C.iloc[-1] / C.loc[prev[-1]] - 1
    tv_now = TV.loc[TV.index >= days[0]].mean()
    tv_before = TV.loc[prev[-20:]].mean()
    rows = []
    for f, m in fam.items():
        m = [c for c in m if c in C.columns and tv_before.get(c, 0) >= 1e9]
        if len(m) < 5:
            continue
        rows.append((f, float(ret[m].median()) * 100, float((tv_now[m] / tv_before[m]).median())))
    if not rows:
        return []
    rows.sort(key=lambda r: -r[1])
    out = ["💰 <b>섹터 이번 주</b> (종목 가운데값 · 거래대금은 지난 4주 평균 대비)"]
    out += ["  센 쪽: " + " · ".join(f"{f} {r:+.1f}%(거래 {x:.1f}배)" for f, r, x in rows[:3])]
    out += ["  약한 쪽: " + " · ".join(f"{f} {r:+.1f}%(거래 {x:.1f}배)" for f, r, x in rows[-3:][::-1])]
    return out


def _signal_part(db: Session, days: list[date]) -> list[str]:
    from backend.services.telegram import _get  # noqa: PLC0415
    log = _get(db, LOG_KEY, {}) or {}
    wk = {d: v for d, v in log.items() if d >= str(days[0])}
    if not wk:
        return []
    picks = [(d, x["code"], "entry") for d, v in wk.items() for x in v["entry"]] + [(d, x["code"], "score") for d, v in wk.items() for x in v["score"]]
    C = _closes(db, sorted({p[1] for p in picks}), days[0] - timedelta(days=7))
    res = {"entry": [], "score": []}
    for d, c, k in picks:
        dd = date.fromisoformat(d)
        if c in C.columns and dd in C.index and C[c][dd] > 0:
            res[k].append(C[c].iloc[-1] / C[c][dd] - 1)
    f = lambda xs: f"{len(xs)}개 · 지금까지 평균 {sum(xs) / len(xs) * 100:+.1f}% · 오른 비율 {sum(x > 0 for x in xs) / len(xs) * 100:.0f}%" if xs else "0개"  # noqa: E731
    return ["📡 <b>이번 주 사이트 신호 (그날 저녁 기록 기준)</b>", f"  ▲ 진입 {f(res['entry'])}", f"  종가 점수 6↑ {f(res['score'])}"]


def weekly_text(db: Session, asof: date | None = None) -> str | None:
    days = _week(db, asof)
    if not days:
        return None
    parts = [f"🗓 <b>주간 점검</b> {days[0].strftime('%m/%d')}~{days[-1].strftime('%m/%d')}"]
    for fn in (_rules_part, _watch_part, _sector_part, _signal_part):
        try:
            p = fn(db, days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("주간 점검 %s 실패: %s", fn.__name__, exc)
            p = []
        if p:
            parts.append("\n".join(p))
    return "\n\n".join(parts)


def send_weekly(db: Session, chat_id: str | None = None) -> None:
    from backend.services.telegram import _get, send  # noqa: PLC0415
    msg = weekly_text(db)
    if not msg:
        return
    chats = [chat_id] if chat_id else (_get(db, "user_watchlist_chats", []) or list(_get(db, "telegram_chats", {}).keys())[:1])
    for c in chats:
        send(db, msg, c, html=True)
