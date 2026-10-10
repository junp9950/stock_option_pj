"""7/30~최근: 지금 사이트 규칙(V1.0 + 주도주 + 모멘텀 돌파 비교)을 날마다 그날까지 데이터로 다시 돌린 가상 계좌 (2026-10-10 KST). DB에 쓰지 않음."""
from lab_paths import APP_ROOT, DATA_DIR, LAB_DIR
import sys, json, time
sys.path.insert(0, str(APP_ROOT))
from datetime import date
from sqlalchemy import text
from backend.db.database import SessionLocal
from backend.services import forward_log as F
from backend.services import stock_signals as S

db = SessionLocal()
START = date(2026, 7, 30)
days = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_prices where trading_date >= :s order by 1"), {"s": START}).all()]
bull = S._bull_days(db)
rows = db.execute(text("""select stock_code, trading_date, open_price, high_price, low_price, close_price, change_pct from spot_daily_prices
    where trading_date >= :s order by stock_code, trading_date"""), {"s": date(2026, 1, 1)}).all()
bars = {}
for c, d, o, h, l, cl, ch in rows:
    bars.setdefault(c, []).append((d, float(o or 0), float(h or 0), float(l or 0), float(cl or 0), float(ch or 0)))
VAR = ["L", "L_pin_first", "L_no_warn_only", "L_pin_only", "L5_pin_first", "L5"]
ACC = {k: F._new_acct() for k in VAR}
CANDS = {}
log = []
for d in days:
    t = time.time()
    sc = S._close_scores_cache = None
    S._CF["key"] = None
    sc = S._close_scores(db, d).get("scores", {})
    px = {c: b[-1][4] for c, b in ((c, [x for x in bars.get(c, []) if x[0] == d]) for c in sc) if b}
    cc, ll = F._cands(sc, px), F._cands(sc, px, lead=True)
    mm = []
    bu = bool(bull.get(d, False))
    if not bu: ll = []
    has = lambda x, t: any(t in y for y in x["state"])
    pin_first = sorted(ll, key=lambda x: (0 if has(x, "📍") else (2 if has(x, "⚠️") else 1), -(x["rs"] or 0)))
    nowarn = [x for x in pin_first if not (has(x, "⚠️") and not has(x, "📍"))]
    pin = [x for x in ll if has(x, "📍")]
    rp = F.LEAD["risk"]
    F._step(ACC["L"], "L", d, bars, ll, "close", slots=2, rp=rp)
    F._step(ACC["L_pin_first"], "a", d, bars, pin_first, "close", slots=2, rp=rp)
    F._step(ACC["L_no_warn_only"], "b", d, bars, nowarn, "close", slots=2, rp=rp)
    F._step(ACC["L_pin_only"], "c", d, bars, pin, "close", slots=2, rp=rp)
    F._step(ACC["L5_pin_first"], "e", d, bars, pin_first, "close", slots=5, rp=rp)
    F._step(ACC["L5"], "f", d, bars, ll, "close", slots=5, rp=rp)
    CANDS[str(d)] = {"bull": bu, "cands": cc, "leads": ll}
    log.append({"d": str(d), "bull": bu, "cands": [(x["code"], x["rs"], x["hot"], x["semi"], x["ema"]) for x in cc],
                "leads": [(x["code"], x["rs"], x["state"]) for x in ll], "momo": [x["code"] for x in mm]})
    print(d, "상승장" if bu else "하락장", len(cc), len(ll), len(mm), {k: round(a["eq"][-1][1], 4) for k, a in ACC.items()}, f"{time.time()-t:.1f}s", flush=True)
# 끝날 때 보유는 마지막 종가로 평가(미실현)
last = days[-1]
for k, a in ACC.items():
    for c, p in a["pos"].items():
        cl = [x for x in bars[c] if x[0] <= last][-1][4]
        net = cl / p["px0"] * (1 - F.CONFIG["cost_sell"]) - (1 + F.CONFIG["cost_buy"])
        a["trades"].append({"code": c, "d0": p["d0"], "px0": p["px0"], "d1": "보유중", "px1": cl, "why": "보유", "R": round(net / p["risk0"], 3), "net": round(net, 4), "rs": p.get("rs")})
json.dump({"acc": {k: {"eq": a["eq"], "trades": a["trades"]} for k, a in ACC.items()}, "log": log, "cands": CANDS}, open(str(DATA_DIR / 'replay_0730_L.json'), "w"), ensure_ascii=False, default=str)
