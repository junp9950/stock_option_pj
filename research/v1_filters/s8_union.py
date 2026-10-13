"""시험 D: 매수(V1.0) ∪ 예전 ▲진입 — 계좌 (PREREG_D.md). 실행: bash run.sh s8_union.py"""
import sys, time
sys.path.insert(0, "/home/junp/tmp_claude/lab_v11"); sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
t0 = time.time()
import redteam_run as RR
import redteam_lab as RT
import ma_lab as M
import common as CM
W, D = RR.W, RR.D
n, m = W["n"], W["m"]; dates = W["dates"]
O, H, L, C, T = (pd.DataFrame(np.asarray(D[k], dtype="float64")) for k in "ohlct")
chg = C / C.shift(1) - 1; tvx = T / T.rolling(20).mean().shift(1)
e5, e10, e20, e60 = (C.ewm(span=k, adjust=False).mean() for k in (5, 10, 20, 60))
ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
gap_prev = ((ehi - elo) / C).shift(1)
ma20 = C.rolling(20).mean(); ma200 = C.rolling(200, min_periods=180).mean()
s50, s150 = C.rolling(50).mean(), C.rolling(150, min_periods=135).mean()
hi52, lo52 = H.rolling(250, min_periods=200).max(), L.rolling(250, min_periods=200).min()
tt7 = (((C > s150) & (C > ma200)).astype(int) + (s150 > ma200).astype(int) + (ma200 > ma200.shift(21)).astype(int)
       + ((s50 > s150) & (s50 > ma200)).astype(int) + (C > s50).astype(int) + (C >= lo52 * 1.3).astype(int) + (C >= hi52 * 0.75).astype(int))
hi20p, lo20p = H.shift(1).rolling(20).max(), L.shift(1).rolling(20).min(); hi10p = H.shift(1).rolling(10).max()
box = (hi20p / lo20p - 1 <= 0.20) & (C > hi20p) & (chg >= 0.05) & (tvx >= 2) & (C > ma200)
emab = (gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.29) & (tvx >= 1.5)
up60 = (C > e60) & (e20 > e60)
ENT = ((box | (emab & up60)) & (tt7 >= 6) & (chg < 0.08) & (C / ma20 - 1 < 0.15)).fillna(False).values & D["bull"][:, None] & D["liq"]
E0 = W["E0"]
li = RT.last_idx(D["c"])
def cands(mask):
    t = M.trades(D, mask, [(D["c"] < M.ema(D["c"], 21), 1.)], stop=W["stop"], start=260)
    c = RT.make_cand(W, t)
    over = (c.xday.values > li[c.j.values]) & (li[c.j.values] < n - 1)
    if over.any():
        jj = c.j.values[over]; lx = li[jj]
        c.loc[over, "xday"] = lx; c.loc[over, "xpx"] = D["Cf"][lx, jj]
        c["R"] = (c.xpx / c.px0 * (1 - RR.CS) - (1 + RR.CB)) / c.risk
    c["date"] = dates[c.signal_i.values]; c["net"] = c.R * c.risk
    c["e0"] = E0[c.signal_i.values, c.j.values]; c["ent"] = ENT[c.signal_i.values, c.j.values]
    return c
cb = cands(E0); cu = cands(E0 | ENT)
print(f"후보: 기준 {len(cb)} · 합집합 {len(cu)} (진입만 {int((~cu.e0).sum())}) · {(time.time()-t0)/60:.1f}분", flush=True)
Cf = D["Cf"]
for part, (A, B) in {"연습 2015.07~22": ("2015-07-01", "2022-12-31"), "시험 2023~": ("2023-01-01", "2026-12-31")}.items():
    S, E = RT.sidx(W, A), min(RT.eidx(W, B), n - 1)
    print(f"[{part}]")
    for lab, c, keys in (("기준 (지금 매수만)", cb, None), ("합집합 (둘 중 하나)", cu, None), ("(b) 매수 먼저 → 남는 칸 진입", cu, "e0first")):
        cc = c[c.i >= S].reset_index(drop=True)
        od = CM.orders(cc, keys=[~cc.e0.values]) if keys else CM.orders(cc)
        eq, ent = CM.sim(cc, od, Cf, S, E); mt = CM.metr(eq); R = cc.R.values[ent]
        print(f"  {lab:26s} 연 {mt['cagr']:+6.1f}% 낙폭 {mt['mdd']:5.0f}% MAR {mt['mar']:5.2f} 샤프 {mt['sharpe']:.2f} · 진입 {len(ent)}건 R {R.mean():+.3f} · 진입만 신호 {100*(~cc.e0.values[ent]).mean():.0f}%", flush=True)
    f = CM.first_only(cu[(cu.date >= A) & (cu.date <= B)])
    print(f"  신호(겹침 뺌): 매수 {CM.desc(f[f.e0])} | 진입만 {CM.desc(f[~f.e0])}")
print("끝")
