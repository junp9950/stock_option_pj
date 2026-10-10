"""주도주 신호(L) 전부를 자리 표시별로 12년 shadow R (2026-10-10 KST)."""
import sys
sys.path.insert(0, "/home/junp/tmp_claude"); sys.path.insert(0, "/home/junp/stock/futures-options-analyzer")
import numpy as np, pandas as pd
import ma_lab as M
M.CACHE = "/home/junp/tmp_claude/ma_lab_cache_full.npz"
D = M.prep(M.load())
n, m = D["n"], D["m"]; O, H, L, C = D["o"], D["h"], D["l"], D["c"]
dates = np.array([str(d) for d in D["dates"]])
chg = D["chg"]; old = np.array([d < "2015-06-15" for d in dates])[:, None]
bad = np.nan_to_num(np.abs(chg)) > np.where(old, 0.155, 0.305)
fin = np.isfinite(C); li = np.where(fin.any(0), n - 1 - np.argmax(fin[::-1], axis=0), -1)
for j in range(m):
    if 0 <= li[j] < n - 1:
        bad[max(li[j] - 9, 0):li[j] + 1, j] = False
D["badcum"] = np.cumsum(bad, axis=0).astype("int32")
e = {k: M.ema(C, k) for k in (8, 14, 20, 21, 55, 60)}
Cd = pd.DataFrame(C)
with np.errstate(invalid="ignore"):
    stop = (L * 0.99).astype("float32"); risk = 1 - stop / C
    pos = (C - L) / np.where(H - L == 0, np.nan, H - L)
    E = D["bull"][:, None] & (C > e[20]) & (e[20] > e[60]) & D["liq"] & (np.nan_to_num(D["RS"]) >= 95) & (risk <= 0.08) & (risk > 0) & (C > O) & (np.nan_to_num(pos) >= 0.5)
    al = (e[8] > e[14]) & (e[14] > e[21]) & (e[21] > e[55])
    pin = al & ((L <= e[14] * 1.005) | (L <= e[21] * 1.005)) & (C > e[14])
    warn = (Cd / Cd.rolling(20).mean() - 1).values >= 0.15
E = np.nan_to_num(E).astype(bool)
LEGS = [(np.nan_to_num((C < e[21]).astype(float)).astype(bool), 1.0)]
t = M.trades(D, E, LEGS, stop=stop, start=int(np.searchsorted(dates, "2015-07-01")))
t["R"] = (t.ret - M.COST_BUY - M.COST_SELL) / t.risk
t["d"] = dates[t.i.values]
pn = np.nan_to_num(pin[t.i.values, t.j.values]).astype(bool); wn = np.nan_to_num(warn[t.i.values, t.j.values]).astype(bool)
t["k"] = np.where(pn, "📍", np.where(wn, "⚠️만", "표시없음"))
t["p"] = [("2015.07~18" if d < "2019" else "2019~22" if d < "2023" else "2023~25.05" if d < "2025-06" else "2025.06~") for d in t.d]
t["open"] = t.exit >= n - 1
print("신호 전부", len(t), f"{t.R.mean():+.3f}")
for p in ["2015.07~18", "2019~22", "2023~25.05", "2025.06~", "전체"]:
    q = t if p == "전체" else t[t.p == p]
    s = " | ".join(f"{k} {len(g)}건 {g.R.mean():+.2f}R 이김 {(g.R>0).mean()*100:.0f}%" for k, g in q.groupby("k"))
    print(f"{p}: {s}")
q = t[t.d < "2026-07-30"]
print("7/30 이전만:", " | ".join(f"{k} {len(g)}건 {g.R.mean():+.2f}R" for k, g in q.groupby("k")))
q = t[t.d >= "2026-07-30"]
print("7/30~ 같은 엔진(겹침 포함):", " | ".join(f"{k} {len(g)}건 {g.R.mean():+.2f}R" for k, g in q.groupby("k")))
f = M.first_only(t)
for p in ["2015.07~18", "2019~22", "2023~25.05", "2025.06~", "전체"]:
    q = f if p == "전체" else f[f.p == p]
    print(f"겹침 제거 {p}:", " | ".join(f"{k} {len(g)}건 {g.R.mean():+.2f}R" for k, g in q.groupby("k")))
q = f[f.d >= "2026-07-30"]
print("겹침 제거 7/30~:", " | ".join(f"{k} {len(g)}건 {g.R.mean():+.2f}R" for k, g in q.groupby("k")))
# 2025.06~ ⚠️만이 몇 종목에 몰렸나
q = f[(f.p == "2025.06~") & (f.k == "⚠️만")].sort_values("R", ascending=False)
tot = q.R.sum(); top = q.R.head(10).sum()
print(f"2025.06~ ⚠️만(겹침 제거) 합 {tot:+.1f}R 중 상위 10건 {top:+.1f}R · 상위 10건 빼면 평균 {q.R.iloc[10:].mean():+.2f}R")
codes = D["codes"]
print("  상위:", [(codes[j], dates[i], round(r, 1)) for j, i, r in zip(q.j.head(10), q.i.head(10), q.R.head(10))])
for k in ("📍", "표시없음"):
    q = f[(f.p == "2025.06~") & (f.k == k)].sort_values("R", ascending=False)
    print(f"  {k}: 상위 10건 빼면 평균 {q.R.iloc[10:].mean():+.2f}R ({len(q)}건)")
