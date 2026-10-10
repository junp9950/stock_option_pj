"""7/30~최근: 지금 사이트 규칙(V1.0 + 주도주 + 모멘텀 돌파 비교)을 날마다 그날까지 데이터로 다시 돌린 가상 계좌 (2026-10-10 KST). DB에 쓰지 않음."""
import sys, json, time
sys.path.insert(0, "/home/junp/stock/futures-options-analyzer")
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
ACC = {"X": F._new_acct(), "S": F._new_acct(), "L": F._new_acct(), "Lsh": F._new_acct(), "Z": F._new_acct()}
log = []
for d in days:
    t = time.time()
    sc = S._close_scores_cache = None
    S._CF["key"] = None
    sc = S._close_scores(db, d).get("scores", {})
    px = {c: b[-1][4] for c, b in ((c, [x for x in bars.get(c, []) if x[0] == d]) for c in sc) if b}
    cc, ll = F._cands(sc, px), F._cands(sc, px, lead=True)
    mm = F._momo_cands(db, d)
    bu = bool(bull.get(d, False))
    F._step(ACC["X"], "X", d, bars, cc if bu else [], "close")
    F._step(ACC["S"], "S", d, bars, cc if bu else [], "next_open")
    F._step(ACC["L"], "L", d, bars, ll if bu else [], "close", slots=F.LEAD["slots"], rp=F.LEAD["risk"])
    F._step(ACC["Lsh"], "Lsh", d, bars, ll if bu else [], "close", slots=999, rp=0.0005)
    F._step(ACC["Z"], "Z", d, bars, mm, "close")
    log.append({"d": str(d), "bull": bu, "cands": [(x["code"], x["rs"], x["hot"], x["semi"], x["ema"]) for x in cc],
                "leads": [(x["code"], x["rs"], x["state"]) for x in ll], "momo": [x["code"] for x in mm]})
    print(d, "상승장" if bu else "하락장", len(cc), len(ll), len(mm), {k: round(a["eq"][-1][1], 4) for k, a in ACC.items()}, f"{time.time()-t:.1f}s", flush=True)
# 끝날 때 보유는 마지막 종가로 평가(미실현)
last = days[-1]
for k, a in ACC.items():
    for c, p in a["pos"].items():
        cl = [x for x in bars[c] if x[0] <= last][-1][4]
        net = cl / p["px0"] - 1 - F.CONFIG["cost_buy"] - F.CONFIG["cost_sell"]
        a["trades"].append({"code": c, "d0": p["d0"], "px0": p["px0"], "d1": "보유중", "px1": cl, "why": "보유", "R": round(net / p["risk0"], 3), "net": round(net, 4), "rs": p.get("rs")})
json.dump({"acc": {k: {"eq": a["eq"], "trades": a["trades"]} for k, a in ACC.items()}, "log": log}, open("/home/junp/tmp_claude/replay_0730.json", "w"), ensure_ascii=False, default=str)
