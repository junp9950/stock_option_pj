"""시험 E: 14일선 절반 매도 (PREREG_E.md). 실행: bash run.sh s9_half14.py"""
import sys, time
sys.path.insert(0, "/home/junp/tmp_claude/lab_v11"); sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import numpy as np, pandas as pd
t0 = time.time()
import redteam_run as RR
import redteam_lab as RT
import ma_lab as M
W, D = RR.W, RR.D
n = W["n"]; C = D["c"]; Cf = D["Cf"]
li = RT.last_idx(C)
CB, CS = RR.CB, RR.CS
def build(legs):
    t = M.trades(D, W["E0"], legs, stop=W["stop"], start=260)
    rows = []
    for r in t.itertuples(index=False):
        si = int(r.signal_i) if hasattr(r, "signal_i") else int(r.i)
        L = []
        for lg in r.legs:
            d, px, w = int(lg[0]), float(lg[1]), float(lg[2])
            if d > li[r.j] and li[r.j] < n - 1:          # 폐지까지 보유 → 마지막 종가 (공식과 같은 가정)
                d, px = int(li[r.j]), float(Cf[li[r.j], r.j])
            L.append((d, px, w))
        rows.append((si, int(r.i), int(r.j), float(r.px0), float(r.risk), L))
    c = pd.DataFrame(rows, columns=["signal_i", "i", "j", "px0", "risk", "legs"])
    c = c[np.isfinite(c.px0) & (c.px0 > 0) & (c.risk > 0)].reset_index(drop=True)
    c["rs"] = np.nan_to_num(D["RS"][c.signal_i.values, c.j.values], nan=-1)
    size = D.get("size_mult"); c["size_mult"] = size[c.signal_i.values, c.j.values] if size is not None else 1.
    return c
def orders(c):
    o = np.lexsort((c.j.values, -c.rs.values, c.i.values)); od = {}
    for r in o: od.setdefault(int(c.i.values[r]), []).append(r)
    return od
def sim(c, od, S, E, rp=0.005, maxpos=10):
    CJ, CPX, CRK, LG, SZ = c.j.values, c.px0.values, c.risk.values, c.legs.values, c.size_mult.values
    cash, pos = 1.0, {}         # j -> list of [shares, day, px]
    eq = np.empty(E - S + 1); ent = 0
    def settle(d):
        nonlocal cash
        for j in list(pos):
            rest = []
            for q in pos[j]:
                if q[1] == d: cash += q[0] * q[2] * (1 - CS)
                else: rest.append(q)
            if rest: pos[j] = rest
            else: del pos[j]
    for d in range(S, E + 1):
        settle(d)
        cf = Cf[d]
        E_ = cash + sum(q[0] * cf[j] for j, qs in pos.items() for q in qs)
        free = maxpos - len(pos)
        for r in od.get(d, []):
            if free <= 0: break
            j = CJ[r]
            if j in pos: continue
            val = rp * E_ * SZ[r] / max(CRK[r], .003)
            if val <= 0: continue
            cash -= val * (1 + CB); sh = val / CPX[r]
            pos[j] = [[sh * w, dd, px] for dd, px, w in LG[r]]; free -= 1; ent += 1
        settle(d)          # 산 날 장중 손절 (엔진과 같게)
        eq[d - S] = cash + sum(q[0] * cf[j] for j, qs in pos.items() for q in qs)
    return eq, ent
base = build([(C < M.ema(C, 21), 1.0)])
half = build([(C < M.ema(C, 14), 0.5), (C < M.ema(C, 21), 0.5)])
print(f"후보 {len(base)} / {len(half)} · {(time.time()-t0)/60:.1f}분", flush=True)
for lab, A, B in (("연습 2015.07~22", "2015-07-01", "2022-12-31"), ("시험 2023~", "2023-01-01", "2026-12-31")):
    S, E = RT.sidx(W, A), min(RT.eidx(W, B), n - 1)
    print(f"[{lab}]")
    for nm, c in (("기준 (21선 한 번에)", base), ("14선 절반 + 21선 나머지", half)):
        cc = c[c.i >= S].reset_index(drop=True)
        eq, ent = sim(cc, orders(cc), S, E); mt = RT.metr(eq)
        print(f"  {nm:24s} 연 {mt['cagr']:+6.1f}% 낙폭 {mt['mdd']:5.0f}% MAR {mt['mar']:5.2f} 샤프 {mt['sharpe']:.2f} · 산 횟수 {ent}", flush=True)
print("끝")
