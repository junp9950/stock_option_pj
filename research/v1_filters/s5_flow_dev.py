"""시험 A 연습 구간만: 2026-01-02 ~ 2026-07-31 신호 (6~7월은 하락장이라 신호 없음 → 사실상 1~5월).
같은 종목 겹친 신호는 뺌(first_only, 전체 후보 기준). 시험 구간(8월~)은 여기서 보지 않는다.
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
import common as CM

DEV_END = "2026-07-31"
c, Cf, dates = CM.load()
keep = set(CM.first_only(c).index)
f = pd.read_pickle(f"{CM.OUT}/flowfeat.pkl")
f = f[f.index.isin(keep) & (f.date <= DEV_END)].copy()
print(f"연습 구간 V1.0 신호(겹침 뺌) {len(f)}건 · 그중 수급 특징 있음 {int(f.has.sum())}건 · 날짜 {f.date.nunique()}일 · 시장 1~4월은 큰 종목 ~200개만 수급 자료")
print("기준(전체):", CM.desc(f), "| 수급 있는 것:", CM.desc(f[f.has]))
g = f[f.has].copy()
FEATS = ["fo1", "fo5", "fo20", "ins1", "ins5", "ins20", "fi1", "fi5", "fi20", "fo5p", "ins5p", "fi5p"]
cuts = {}
print("\n세 묶음(연습 구간 신호 안에서 나눈 경계) — 아래/가운데/위 · 위−아래 R 차이 [날짜 묶음 부트스트랩 95%]")
for k in FEATS:
    x = g[g[k].notna()].copy()
    q1, q2 = np.percentile(x[k], [100 / 3, 200 / 3]); cuts[k] = (q1, q2)
    lo, mid, hi = x[x[k] <= q1], x[(x[k] > q1) & (x[k] <= q2)], x[x[k] > q2]
    sub = pd.concat([lo.assign(top=False), hi.assign(top=True)])
    obs, a, b = CM.boot_diff(sub, "top")
    print(f"  {k:6s} 경계 {q1:+.3f}/{q2:+.3f} | 아래 {CM.desc(lo)} | 가운데 {CM.desc(mid)} | 위 {CM.desc(hi)} | 위−아래 {obs:+.3f} [{a:+.3f},{b:+.3f}]")
print("\n방향 묶음 (순매수 > 0 vs < 0)")
for k in FEATS:
    x = g[g[k].notna()].copy(); x["buy"] = x[k] > 0
    obs, a, b = CM.boot_diff(x, "buy")
    print(f"  {k:6s} 매수 {CM.desc(x[x.buy])} | 매도 {CM.desc(x[~x.buy])} | 차이 {obs:+.3f} [{a:+.3f},{b:+.3f}]")
print("\n외국인·기관 함께 (1·5·20일)")
for k in ("1", "5", "20", "5p"):
    x = g[g[f"fo{k}"].notna() & g[f"ins{k}"].notna()].copy()
    bb = (x[f"fo{k}"] > 0) & (x[f"ins{k}"] > 0); ss = (x[f"fo{k}"] < 0) & (x[f"ins{k}"] < 0)
    x["ss"] = ss; o1 = CM.boot_diff(x, "ss"); x["bb"] = bb; o2 = CM.boot_diff(x, "bb")
    print(f"  {k:3s}일 둘 다 매수 {CM.desc(x[bb])} | 엇갈림 {CM.desc(x[~bb & ~ss])} | 둘 다 매도 {CM.desc(x[ss])}"
          f" | 둘다매도−나머지 {o1[0]:+.3f} [{o1[1]:+.3f},{o1[2]:+.3f}] · 둘다매수−나머지 {o2[0]:+.3f} [{o2[1]:+.3f},{o2[2]:+.3f}]")
print("\n월별 (수급 있는 신호):", " · ".join(f"{m} {len(x)}건 R {x.R.mean():+.2f}" for m, x in g.groupby(g.date.str[:7])))
pd.to_pickle(cuts, f"{CM.OUT}/flow_cuts_dev.pkl")
