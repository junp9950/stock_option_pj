"""시험 C: V1.0 매수 신호 중 '예전 ▲진입도 같은 날 뜬' 것이 더 좋은가 — 신호 품질 + 계좌 (2026-10-13 KST).
사용: bash run.sh s7_entry.py dev   (2015.07~2022, 사전등록 전)
      bash run.sh s7_entry.py test  (2023~, PREREG_C.md 고정 뒤 한 번)
계좌 = v11 엔진 10칸·0.5%·RS 순, 구간마다 자본 1로 따로 시작."""
import sys
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
import common as CM

part = sys.argv[1]
A, B = {"dev": ("2015-07-01", "2022-12-31"), "test": ("2023-01-01", "2026-12-31")}[part]
c = pd.read_pickle(f"{CM.OUT}/cand_ent.pkl")
Cf = np.load(f"{CM.OUT}/Cf.npy", mmap_mode="r"); dates = np.load(f"{CM.OUT}/dates.npy")
f = CM.first_only(c)
f = f[(f.date >= A) & (f.date <= B)].copy(); f["yr"] = f.date.str[:4]
print(f"[{part}] {A}~{B} · V1.0 신호(겹침 뺌) {len(f)}건 · 진입 같이 뜸 {int(f.ent.sum())}건 ({100 * f.ent.mean():.0f}%)")
print("전체        ", CM.desc(f)); print("진입도 뜸   ", CM.desc(f[f.ent])); print("진입 안 뜸  ", CM.desc(f[~f.ent]))
for col in ("R", "net"):
    o, a, b = CM.boot_diff(f, "ent", col=col); print(f"  뜸−안뜸 {col}: {o:+.3f} [95% {a:+.3f}, {b:+.3f}] (날짜 묶음 5,000)")
print(f"  R 중앙값 뜸 {f[f.ent].R.median():+.2f} / 안뜸 {f[~f.ent].R.median():+.2f} · 상위 5% 자르면 뜸 {f[f.ent].R.clip(upper=f.R.quantile(.95)).mean():+.3f} / 안뜸 {f[~f.ent].R.clip(upper=f.R.quantile(.95)).mean():+.3f}")
better = yrs = 0
for y, g in f.groupby("yr"):
    s, ns = g[g.ent], g[~g.ent]
    if len(s) < 10 or len(ns) < 10: print(f"  {y} 표본 부족 ({len(s)}/{len(ns)})"); continue
    yrs += 1; better += s.R.mean() > ns.R.mean()
    print(f"  {y} 뜸 {s.R.mean():+.2f} / 안뜸 {ns.R.mean():+.2f} ({len(s)}/{len(ns)})")
print(f"  진입도 뜬 쪽이 나은 해: {better}/{yrs}")
S, E = CM.sidx(dates, A), min(CM.eidx(dates, B), len(dates) - 1)
cc = c[c.i >= S].reset_index(drop=True)
def run(cd, od, lab, size=None):
    eq, ent = CM.sim(cd, od, Cf, S, E, size=size); mt = CM.metr(eq); R = cd.R.values[ent]
    print(f"  {lab:30s} 연 {mt['cagr']:+6.1f}% 낙폭 {mt['mdd']:5.0f}% MAR {mt['mar']:5.2f} 샤프 {mt['sharpe']:.2f} · 진입 {len(ent)}건 R {R.mean():+.3f} · 진입도 뜬 비율 {100 * cd.ent.values[ent].mean():.0f}%")
    return mt
print("계좌 (10칸 · 거래당 0.5% · 종가 진입 · 구간 따로 시작):")
m1 = run(cc, CM.orders(cc), "(1) 기준 RS 순")
m2 = run(cc, CM.orders(cc, keys=[~cc.ent.values]), "(2) 진입도 뜬 것 먼저 → RS 순")
m3 = run(cc, CM.orders(cc), "(3) 진입도 뜬 것 1.5배 크기", size=np.where(cc.ent.values, 1.5, 1.0))
c4 = cc[cc.ent].reset_index(drop=True); m4 = run(c4, CM.orders(c4), "(4) 진입도 뜬 것만")
# 대조: (2)·(3)과 같은 수의 신호를 무작위로 골라 먼저/1.5배 — 200번
frac = cc.ent.mean(); rng = np.random.default_rng(20261013); r2, r3 = [], []
for k in range(200):
    pick = rng.random(len(cc)) < frac
    eq, _ = CM.sim(cc, CM.orders(cc, keys=[~pick]), Cf, S, E); r2.append(CM.metr(eq))
    eq, _ = CM.sim(cc, CM.orders(cc), Cf, S, E, size=np.where(pick, 1.5, 1.0)); r3.append(CM.metr(eq))
for lab, rr, mm in (("(2) 먼저", r2, m2), ("(3) 1.5배", r3, m3)):
    g = np.array([x["cagr"] for x in rr]); mr = np.array([x["mar"] for x in rr])
    print(f"  대조 {lab}: 무작위 같은 비율 200번 연 중앙 {np.median(g):+.1f}% · MAR 중앙 {np.median(mr):.2f} → 실제 백분위 연 {100 * np.mean(g < mm['cagr']):.0f} · MAR {100 * np.mean(mr < mm['mar']):.0f}")
