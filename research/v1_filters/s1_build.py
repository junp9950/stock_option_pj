"""1단계: v11 엔진(상폐 포함 정정판)으로 V1.0 후보 다시 만들기 + 기준 숫자 재현 + 응축 표시 계산 (2026-10-11 KST).
실행: bash run.sh s1_build.py
"""
import sys, time
sys.path.insert(0, "/home/junp/tmp_claude/lab_v11")
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
t0 = time.time()
import redteam_run as RR          # 모듈 수준에서 W = RT.build("full")
import redteam_lab as RT
import common as CM

W, D = RR.W, RR.D
dates = W["dates"]; n, m = W["n"], W["m"]
c, info = RR.cand_variant("primary", "close")
print(f"후보 {len(c)}개 · 강제 정리 {info['merger_open']}건 · 걸린 시간 {(time.time() - t0) / 60:.1f}분", flush=True)

# ── 기준 재현 (RESULTS.md 9절: RS 순 상폐 포함 정정판 연 +23.4% 낙폭 -51% · A 따로 시작 연 +6.9%)
S, E = RT.sidx(W, "2015-07-01"), n - 1
eq, _, _, _ = RR.sim2(c, RR.orders_rs(c), S, E); mt = RT.metr(eq)
print(f"[재현 sim2] 12년 RS 순: 연 {mt['cagr']:+.1f}% 낙폭 {mt['mdd']:.0f}% MAR {mt['mar']:.2f} 샤프 {mt['sharpe']:.2f}  (기대 +23.4% / -51% / 0.46 / 0.73)")
eqa, _, _, _ = RR.sim2(c, RR.orders_rs(c), S, RT.eidx(W, "2022-12-31")); ma = RT.metr(eqa)
print(f"[재현 sim2] A 2015.07~22 따로 시작: 연 {ma['cagr']:+.1f}% 낙폭 {ma['mdd']:.0f}%  (기대 +6.9%)")

# 저장 (가벼운 시뮬용)
c = c.copy()
c["date"] = dates[c.signal_i.values]
c["code"] = np.array(D["codes"])[c.j.values]
c["net"] = c.R * c.risk
np.save(f"{CM.OUT}/Cf.npy", D["Cf"].astype("float32"))
np.save(f"{CM.OUT}/dates.npy", dates)
np.save(f"{CM.OUT}/codes.npy", np.array(D["codes"]))

# ── 응축: BB(20, 2σ, 모집단 표준편차) 폭 4·std/mean ≤ 최근 120봉(오늘 포함, 유효 60개↑) 폭의 아래 20% (사이트 chartPatterns·pattern_val과 같음)
C = D["c"].astype("float64")
Cd = pd.DataFrame(C)
mu = Cd.rolling(20, min_periods=20).mean(); sd = Cd.rolling(20, min_periods=20).std(ddof=0)
bw = (4 * sd / mu).values
SQ = np.zeros((n, m), bool)
pad = np.full((119, m), np.nan)
B = np.vstack([pad, bw])
from numpy.lib.stride_tricks import sliding_window_view
for a in range(0, m, 150):
    win = sliding_window_view(B[:, a:a + 150], 120, axis=0)          # (n, k, 120), 마지막 = 오늘
    x = bw[:, a:a + 150]
    k = np.isfinite(win).sum(-1)
    with np.errstate(invalid="ignore"):
        less = (win < x[..., None]).sum(-1)
    SQ[:, a:a + 150] = np.isfinite(x) & (k >= 60) & (less <= np.floor(k * 0.2))
SQ[:60] = False
sq5 = pd.DataFrame(SQ.astype(float)).rolling(5, min_periods=1).max().fillna(0).values > 0     # t-4..t (오늘 포함, t까지만)
c["sq5"] = sq5[c.signal_i.values, c.j.values]
c["sq0"] = SQ[c.signal_i.values, c.j.values]
np.save(f"{CM.OUT}/SQ.npy", SQ)
c.to_pickle(f"{CM.OUT}/cand.pkl")

# 내 시뮬(common.sim)이 sim2와 같은지
eq2, _ = CM.sim(c, CM.orders(c), D["Cf"], S, E); m2 = CM.metr(eq2)
print(f"[재현 common.sim] 12년 RS 순: 연 {m2['cagr']:+.1f}% 낙폭 {m2['mdd']:.0f}% · sim2와 최대 차이 {np.max(np.abs(eq2 / eq - 1)):.2e}")
print(f"응축(신호 전 5일 안) 비율: 전체 후보 {100 * c.sq5.mean():.1f}% · 끝 {(time.time() - t0) / 60:.1f}분")
