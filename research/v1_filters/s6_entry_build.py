"""시험 C 준비: V1.0 후보마다 '예전 ▲진입 신호도 같은 날 떴나'(ent) 표시 (2026-10-13 KST).
▲진입 = (박스 돌파 | 이평선 모였다 돌파 & 정배열60) & 추세 7조건 중 6↑ & 그날 +8% 미만 & 20일선 +15% 안 — stock_signals.signals()와 같은 식.
실행: bash run.sh s6_entry_build.py"""
import sys, time
sys.path.insert(0, "/home/junp/tmp_claude/lab_v11")
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
t0 = time.time()
import redteam_run as RR
import common as CM
D = RR.D
c = pd.read_pickle(f"{CM.OUT}/cand.pkl")
O, H, L, C, T = (pd.DataFrame(np.asarray(D[k], dtype="float64")) for k in "ohlct")
chg = C / C.shift(1) - 1
tvx = T / T.rolling(20).mean().shift(1)
e5, e10, e20, e60 = (C.ewm(span=k, adjust=False).mean() for k in (5, 10, 20, 60))
ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
gap_prev = ((ehi - elo) / C).shift(1)
ma20 = C.rolling(20).mean(); ma200 = C.rolling(200, min_periods=180).mean()
s50, s150 = C.rolling(50).mean(), C.rolling(150, min_periods=135).mean()
hi52, lo52 = H.rolling(250, min_periods=200).max(), L.rolling(250, min_periods=200).min()
tt7 = (((C > s150) & (C > ma200)).astype(int) + (s150 > ma200).astype(int) + (ma200 > ma200.shift(21)).astype(int)
       + ((s50 > s150) & (s50 > ma200)).astype(int) + (C > s50).astype(int) + (C >= lo52 * 1.3).astype(int) + (C >= hi52 * 0.75).astype(int))
hi20p, lo20p = H.shift(1).rolling(20).max(), L.shift(1).rolling(20).min()
hi10p = H.shift(1).rolling(10).max()
box = (hi20p / lo20p - 1 <= 0.20) & (C > hi20p) & (chg >= 0.05) & (tvx >= 2) & (C > ma200)
emab = (gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.29) & (tvx >= 1.5)
up60 = (C > e60) & (e20 > e60)
ENT = ((box | (emab & up60)) & (tt7 >= 6) & (chg < 0.08) & (C / ma20 - 1 < 0.15)).fillna(False).values
c["ent"] = ENT[c.signal_i.values, c.j.values]
c.to_pickle(f"{CM.OUT}/cand_ent.pkl")
print(f"후보 {len(c)} · 진입 같이 뜸 {int(c.ent.sum())} ({100 * c.ent.mean():.1f}%) · {(time.time() - t0) / 60:.1f}분")
