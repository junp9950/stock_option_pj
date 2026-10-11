"""시험 B: V1.0 신호 안에서 응축(신호일 포함 5일 안 볼린저 폭 좁음)이 도움이 되나 (2026-10-11 KST).
사용: bash run.sh s2_squeeze.py dev   (2015.07~2022, 사전등록 전)
      bash run.sh s2_squeeze.py test  (2023~2026.10.08, PREREG_B.md 고정 뒤 한 번)
신호 품질 = 같은 종목 겹친 신호 뺀 것(first_only). 계좌 = v11 엔진 10칸·0.5%·RS 순, 구간마다 자본 1로 따로 시작.
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
import common as CM

part = sys.argv[1]
A, B = {"dev": ("2015-07-01", "2022-12-31"), "test": ("2023-01-01", "2026-12-31")}[part]
c, Cf, dates = CM.load()
f = CM.first_only(c)
f = f[(f.date >= A) & (f.date <= B)].copy()
f["yr"] = f.date.str[:4]
print(f"[{part}] {A}~{B} · V1.0 신호(겹침 뺌) {len(f)}건 · 날짜 {f.date.nunique()}일 · 응축 있음 {int(f.sq5.sum())}건 ({100 * f.sq5.mean():.0f}%)")
print("기준(전체)      ", CM.desc(f))
print("응축 있음(5일)  ", CM.desc(f[f.sq5]))
print("응축 없음       ", CM.desc(f[~f.sq5]))
for col in ("R", "net"):
    o, a, b = CM.boot_diff(f, "sq5", col=col)
    print(f"  있음−없음 {col}: {o:+.3f} [95% {a:+.3f}, {b:+.3f}] (날짜 묶음 부트스트랩 5,000)")
f["win"] = (f.net > 0).astype(float)
o, a, b = CM.boot_diff(f, "sq5", col="win"); print(f"  있음−없음 이김 비율: {100 * o:+.1f}%p [{100 * a:+.1f}, {100 * b:+.1f}]")
print("참고 — 신호일 당일 응축:", CM.desc(f[f.sq0]), "| 아님", CM.desc(f[~f.sq0]))
# 중앙값·상위 의존도
print(f"  R 중앙값 있음 {f[f.sq5].R.median():+.2f} / 없음 {f[~f.sq5].R.median():+.2f} · 상위 5% 빼면 있음 {f[f.sq5].R.clip(upper=f.R.quantile(.95)).mean():+.3f} / 없음 {f[~f.sq5].R.clip(upper=f.R.quantile(.95)).mean():+.3f} (전체 95백분위로 자름)")
print("연도별 (있음 R / 없음 R / 건수):")
better = 0; yrs = 0
for y, g in f.groupby("yr"):
    s, ns = g[g.sq5], g[~g.sq5]
    if len(s) < 10 or len(ns) < 10:
        print(f"  {y} 표본 부족 ({len(s)}/{len(ns)})"); continue
    yrs += 1; better += s.R.mean() > ns.R.mean()
    print(f"  {y} {s.R.mean():+.2f} / {ns.R.mean():+.2f} ({len(s)}/{len(ns)}) 차이 {s.R.mean() - ns.R.mean():+.2f}")
print(f"  응축 있음이 나은 해: {better}/{yrs}")

# ── 계좌
S, E = CM.sidx(dates, A), min(CM.eidx(dates, B), len(dates) - 1)
cc = c[(c.i >= S)].copy()
def run(cd, od, lab):
    eq, ent = CM.sim(cd, od, Cf, S, E); mt = CM.metr(eq)
    R = cd.R.values[ent]
    print(f"  {lab:28s} 연 {mt['cagr']:+6.1f}% 낙폭 {mt['mdd']:5.0f}% MAR {mt['mar']:5.2f} 샤프 {mt['sharpe']:.2f} · 진입 {len(ent)}건 평균 R {R.mean():+.3f} · 응축 비율 {100 * cd.sq5.values[ent].mean():.0f}%")
    return mt, eq
print("계좌 (10칸 · 거래당 0.5% · 진입 신호일 종가 · 구간 따로 시작):")
m1, _ = run(cc, CM.orders(cc), "(1) 기준 RS 순")
m2, _ = run(cc, CM.orders(cc, keys=[~cc.sq5.values]), "(2) 응축 먼저, 그다음 RS 순")
c3 = cc[cc.sq5].reset_index(drop=True)
m3, _ = run(c3, CM.orders(c3), "(3) 응축 신호만")
# 대조: (3)과 같은 비율로 무작위로 남긴 계좌 200번 (신호 수가 줄어든 효과만)
frac = cc.sq5.mean(); rng = np.random.default_rng(20261011); rc = []
for k in range(200):
    keep = rng.random(len(cc)) < frac
    ck = cc[keep].reset_index(drop=True)
    eq, _ = CM.sim(ck, CM.orders(ck), Cf, S, E); rc.append(CM.metr(eq))
rcg = np.array([x["cagr"] for x in rc]); rmd = np.array([x["mdd"] for x in rc]); rmar = np.array([x["mar"] for x in rc])
print(f"  대조: 무작위 {100 * frac:.0f}%만 남김 200번 — 연 중앙 {np.median(rcg):+.1f}% (5~95% {np.percentile(rcg, 5):+.1f}~{np.percentile(rcg, 95):+.1f}) · 낙폭 중앙 {np.median(rmd):.0f}% · MAR 중앙 {np.median(rmar):.2f}"
      f" → (3) 백분위 연 {100 * np.mean(rcg < m3['cagr']):.0f} · MAR {100 * np.mean(rmar < m3['mar']):.0f}")
