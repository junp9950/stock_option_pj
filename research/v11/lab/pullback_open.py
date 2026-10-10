"""prereg_pullback_open.md 실행 (2026-10-10 KST)."""
from lab_paths import APP_ROOT, DATA_DIR, LAB_DIR
import sys
sys.path.insert(0, str(LAB_DIR)); sys.path.insert(0, str(APP_ROOT))
import numpy as np, pandas as pd
import ma_lab as M
M.CACHE = str(DATA_DIR / 'ma_lab_cache_full.npz')
D = M.prep(M.load())
n, m = D["n"], D["m"]; O, H, L, C = D["o"], D["h"], D["l"], D["c"]
dates = np.array([str(d) for d in D["dates"]]); print("기간", dates[0], dates[-1], "종목", m)
CB, CS = M.COST_BUY, M.COST_SELL
# 분할 오류 표시 — 정리매매(마지막 10거래일)는 빼고
chg = D["chg"]; old = np.array([d < "2015-06-15" for d in dates])[:, None]
bad = np.nan_to_num(np.abs(chg)) > np.where(old, 0.155, 0.305)
fin = np.isfinite(C); li = np.where(fin.any(0), n - 1 - np.argmax(fin[::-1], axis=0), -1)
for j in range(m):
    if li[j] >= 0 and li[j] < n - 1:
        bad[max(li[j] - 9, 0):li[j] + 1, j] = False
badcum = np.cumsum(bad, axis=0)
e = {k: M.ema(C, k) for k in (8, 14, 20, 21, 55, 60)}
with np.errstate(invalid="ignore"):
    U = D["bull"][:, None] & (C > e[20]) & (e[20] > e[60]) & D["liq"] & (np.nan_to_num(D["RS"]) >= 95)
    stopA = L * 0.99; riskA = 1 - stopA / C
    pos = (C - L) / np.where(H - L == 0, np.nan, H - L)
    A_sig = U & (riskA <= 0.08) & (riskA > 0) & (C > O) & (np.nan_to_num(pos) >= 0.5)
    al = (e[8] > e[14]) & (e[14] > e[21]) & (e[21] > e[55])
    B_sig = U & al & (C < O) & (L <= e[14] * 1.005)
below21 = np.nan_to_num(C < e[21]).astype(bool)
start = int(np.searchsorted(dates, "2015-07-01"))

def run(j, t0, px0, st, same_day):
    """t0 = 산 날. same_day=True면 그날 저가·종가부터 판단(시가 매수)."""
    exit_next = False
    t = t0 if same_day else t0 + 1
    if not same_day and below21[t0, j]:
        exit_next = True
    while t <= min(li[j], n - 1):
        o, l = O[t, j], L[t, j]
        from backend.services.trading_rules import tradable_bar, locked_down
        bar = (t,o,H[t,j],l,C[t,j],D["chg"][t,j]*100)
        if not tradable_bar(bar):
            t += 1; continue
        if locked_down(bar):
            exit_next = exit_next or l <= st
            t += 1; continue
        if exit_next and not (same_day and t == t0):
            return t, o
        if np.isfinite(l) and l <= st:
            px = min(o, st) if (np.isfinite(o) and not (same_day and t == t0)) else st; return t, px
        if below21[t, j]:
            exit_next = True
        t += 1
    tl = min(li[j], n - 1)
    return tl, float(D["Cf"][tl, j]) if tl < n - 1 or li[j] < n - 1 else float(D["Cf"][tl, j])

rows = []
for j in range(m):
    u = U[:, j]
    if not u[start:].any():
        continue
    t = start; gap = 999; ep = None
    while t < n:
        if u[t]:
            if ep is None and gap >= 20:
                ep = {"s": t, "A": None, "B": None, "Bdone": False}
            gap = 0
        else:
            gap += 1
            if ep is not None and gap >= 10:
                ep["e"] = t; rows.append((j, ep)); ep = None
        if ep is not None:
            if ep["A"] is None and A_sig[t, j]:
                ep["A"] = t
            if not ep["Bdone"] and B_sig[t, j]:
                ep["Bdone"] = True; ep["B"] = t
        t += 1
    if ep is not None:
        ep["e"] = n - 1; rows.append((j, ep))
out = []
for j, ep in rows:
    rec = {"j": j, "s": ep["s"], "Ra": np.nan, "Rb": np.nan, "ia": -1, "ib": -1}
    if ep["A"] is not None and ep["A"] < n - 1:
        i = ep["A"]; px0 = float(C[i, j]); st = float(stopA[i, j])
        tx, px = run(j, i, px0, st, False)
        if badcum[tx,j] - badcum[i,j] != 0:
            raise ValueError("Unresolved price anomaly; repair source data")
        rec["Ra"] = (px / px0 * (1 - CS) - (1 + CB)) / (1 - st / px0); rec["ia"] = i
    if ep["B"] is not None and ep["B"] < n - 1 and ep["B"] + 1 <= li[j]:
        i = ep["B"] + 1; o = float(O[i, j]); st = float(L[ep["B"], j]) * 0.99
        if np.isfinite(o) and o > st and 1 - st / o <= 0.08:
            tx, px = run(j, i, o, st, True)
            if badcum[tx,j] - badcum[ep["B"],j] != 0:
                raise ValueError("Unresolved price anomaly; repair source data")
            rec["Rb"] = (px / o * (1 - CS) - (1 + CB)) / (1 - st / o); rec["ib"] = i
    out.append(rec)
df = pd.DataFrame(out); df["d"] = dates[df.s.values]
df.to_pickle(str(DATA_DIR / 'pullback_open.pkl'))
def per(d):
    return "2015.07~18" if d < "2019" else "2019~22" if d < "2023" else "2023~25.05" if d < "2025-06" else "2025.06~"
df["p"] = df.d.map(per)
pair = df.dropna(subset=["Ra", "Rb"]).copy(); pair["dR"] = pair.Rb - pair.Ra
pair["mon"] = [dates[min(a, b)][:7] for a, b in zip(pair.ia, pair.ib)]
rng = np.random.default_rng(20261010); g = pair.groupby("mon").dR.agg(["sum", "count"]).values
bs = []
for _ in range(10000):
    k = rng.integers(0, len(g), len(g)); s = g[k]; bs.append(s[:, 0].sum() / s[:, 1].sum())
lo, hi = np.percentile(bs, [2.5, 97.5])
print(f"구간 {len(df)} · A 거래 {df.Ra.notna().sum()} · B 거래 {df.Rb.notna().sum()} · 짝 {len(pair)}")
print(f"짝 ΔR 평균 {pair.dR.mean():+.3f} (95% CI {lo:+.3f} ~ {hi:+.3f})")
print(f"A 전체 평균 R {df.Ra.mean():+.3f} · B 전체 평균 R {df.Rb.mean():+.3f}")
print(f"못 한 비율 A {df.Ra.isna().mean()*100:.1f}% · B {df.Rb.isna().mean()*100:.1f}%")
for p in ["2015.07~18", "2019~22", "2023~25.05", "2025.06~"]:
    q = pair[pair.p == p]; r = df[df.p == p]
    print(f"  {p}: 짝 {len(q)} ΔR {q.dR.mean():+.3f} | A {r.Ra.notna().sum()}건 {r.Ra.mean():+.3f} · B {r.Rb.notna().sum()}건 {r.Rb.mean():+.3f}")
# 참고: 어느 쪽이 먼저 샀나, 짝 중 B가 더 싸게 산 비율
pair["b_first"] = pair.ib <= pair.ia
print(f"참고: 짝 중 B가 먼저 산 비율 {pair.b_first.mean()*100:.0f}% · B 먼저일 때 ΔR {pair[pair.b_first].dR.mean():+.3f} · A 먼저일 때 {pair[~pair.b_first].dR.mean():+.3f}")
