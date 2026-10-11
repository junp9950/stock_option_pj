"""시험 A 시험 구간 한 번: 2026-08-01 ~ 2026-10-08 (PREREG_A.md 고정 뒤). 10/8에 열린 거래는 10/8 종가로 평가."""
import sys
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
import common as CM

A = "2026-08-01"
c, Cf, dates = CM.load()
keep = set(CM.first_only(c).index)
F = pd.read_pickle(f"{CM.OUT}/flowfeat.pkl")
f = F[F.index.isin(keep) & (F.date >= A)].copy()
f["open"] = f.xday >= len(dates)
print(f"시험 구간 V1.0 신호(겹침 뺌) {len(f)}건 · 수급 있음 {int(f.has.sum())}건 · 날짜 {f.date.nunique()}일 · 10/8에 아직 열린 거래 {int(f.open.sum())}건")
print("기준(전체):", CM.desc(f), "| 수급 있는 것:", CM.desc(f[f.has]))
g = f[f.has].copy()
# H-A1
x = g[g.fo20.notna() & g.ins20.notna()].copy(); x["ss"] = (x.fo20 < 0) & (x.ins20 < 0)
o, a, b = CM.boot_diff(x, "ss")
ok1 = "판단 불가(15건 미만)" if x.ss.sum() < 15 else ("통과" if (o < 0 and b < 0) else "실패")
print(f"H-A1 20일 둘 다 순매도 {CM.desc(x[x.ss])} | 나머지 {CM.desc(x[~x.ss])} | 차이 {o:+.3f} [95% {a:+.3f}, {b:+.3f}] → {ok1}")
# H-A2
q1, q2 = pd.read_pickle(f"{CM.OUT}/flow_cuts_dev.pkl")["ins20"]
y = g[g.ins20.notna()].copy(); lo, hi = y[y.ins20 <= q1], y[y.ins20 > q2]
sub = pd.concat([lo.assign(top=False), hi.assign(top=True)]); o2, a2, b2 = CM.boot_diff(sub, "top")
ok2 = "판단 불가(15건 미만)" if min(len(lo), len(hi)) < 15 else ("통과" if (o2 > 0 and a2 > 0) else "실패")
print(f"H-A2 기관 20일 위 1/3(>{q2:+.3f}) {CM.desc(hi)} | 아래 1/3(≤{q1:+.3f}) {CM.desc(lo)} | 가운데 {CM.desc(y[(y.ins20 > q1) & (y.ins20 <= q2)])} | 위−아래 {o2:+.3f} [95% {a2:+.3f}, {b2:+.3f}] → {ok2}")
print("참고 — 이미 닫힌 거래만: H-A1 둘 다 매도", CM.desc(x[x.ss & ~x.open]), "| 나머지", CM.desc(x[~x.ss & ~x.open]))

# 보조: 시험 구간 10칸 계좌 (8/1부터 따로 시작, 열린 건 10/8 종가)
S, E = CM.sidx(dates, A), len(dates) - 1
cc = c[c.i >= S].copy()
fl = F.reindex(cc.index)
ss_all = ((fl.fo20 < 0) & (fl.ins20 < 0)).fillna(False).values
def show(lab, cd, od, size=None):
    eq, ent = CM.sim(cd, od, Cf, S, E, size=size); mt = CM.metr(eq)
    print(f"  {lab:24s} 기간 수익 {100 * (eq[-1] - 1):+.1f}% · 낙폭 {mt['mdd']:.1f}% · 진입 {len(ent)}건")
print(f"보조 계좌 ({dates[S]}~{dates[E]}, {E - S + 1}거래일 — 너무 짧아 참고만):")
show("기준", cc, CM.orders(cc))
c2 = cc[~ss_all].reset_index(drop=True); show("H-A1 신호 빼기", c2, CM.orders(c2))
show("H-A1 신호 절반 크기", cc, CM.orders(cc), size=np.where(ss_all, 0.5, 1.0))
