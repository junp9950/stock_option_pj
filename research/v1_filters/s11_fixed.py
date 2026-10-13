"""시험 H (PREREG_H.md) — s10_full 정정판: 불타기 손절 max · 첫날 판정 묶음별 · 횟수 제한 없음 · 후보 H · 미청산 포함 기여
시험 F (PREREG_F.md): 지금 운용 규칙 전체 기준선 + 아스트라 후보 3개 + AI·반도체 의존. 실행: bash run.sh s10_full.py"""
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
O, C, Cf = D["o"], D["c"], D["Cf"]
CB, CS = RR.CB, RR.CS
# ── 후보: 지금 규칙(E0) ∪ 돌파(ENT) — s8과 같은 식
Od, Hd, Ld, Cd, Td = (pd.DataFrame(np.asarray(D[k], dtype="float64")) for k in "ohlct")
chg = Cd / Cd.shift(1) - 1; tvx = Td / Td.rolling(20).mean().shift(1)
e5, e10, e20, e60 = (Cd.ewm(span=k, adjust=False).mean() for k in (5, 10, 20, 60))
ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
gap_prev = ((ehi - elo) / Cd).shift(1)
ma20 = Cd.rolling(20).mean(); ma200 = Cd.rolling(200, min_periods=180).mean()
s50, s150 = Cd.rolling(50).mean(), Cd.rolling(150, min_periods=135).mean()
hi52, lo52 = Hd.rolling(250, min_periods=200).max(), Ld.rolling(250, min_periods=200).min()
tt7 = (((Cd > s150) & (Cd > ma200)).astype(int) + (s150 > ma200).astype(int) + (ma200 > ma200.shift(21)).astype(int)
       + ((s50 > s150) & (s50 > ma200)).astype(int) + (Cd > s50).astype(int) + (Cd >= lo52 * 1.3).astype(int) + (Cd >= hi52 * 0.75).astype(int))
hi20p, lo20p = Hd.shift(1).rolling(20).max(), Ld.shift(1).rolling(20).min(); hi10p = Hd.shift(1).rolling(10).max()
box = (hi20p / lo20p - 1 <= 0.20) & (Cd > hi20p) & (chg >= 0.05) & (tvx >= 2) & (Cd > ma200)
emab = (gap_prev <= 0.04) & (Cd > ehi) & (Cd > hi10p) & (chg >= 0.03) & (chg < 0.29) & (tvx >= 1.5)
up60 = (Cd > e60) & (e20 > e60)
ENT = ((box | (emab & up60)) & (tt7 >= 6) & (chg < 0.08) & (Cd / ma20 - 1 < 0.15)).fillna(False).values & D["bull"][:, None] & D["liq"]
E0 = W["E0"]; li = RT.last_idx(C)
t = M.trades(D, E0 | ENT, [(C < M.ema(C, 21), 1.)], stop=W["stop"], start=260)
c = RT.make_cand(W, t)
over = (c.xday.values > li[c.j.values]) & (li[c.j.values] < n - 1)
if over.any():
    jj = c.j.values[over]; lx = li[jj]
    c.loc[over, "xday"] = lx; c.loc[over, "xpx"] = Cf[lx, jj]; c.loc[over, "exit_phase"] = "open"
c["e0"] = E0[c.signal_i.values, c.j.values]
# G2 다른 청산: 5거래일 종가 최고 < 매수가×(1+0.5×손절폭) 이고 5일째 종가 ≤ 매수가 → 6일째 시가
g2x, g2p = c.xday.values.copy(), c.xpx.values.copy()
for r in range(len(c)):
    i, j, px0, rk, xd = int(c.i.values[r]), int(c.j.values[r]), c.px0.values[r], c.risk.values[r], int(c.xday.values[r])
    if i + 6 >= n or xd <= i + 6:
        continue
    seg = C[i + 1:i + 6, j]
    if np.all(np.isfinite(seg)) and seg.max() < px0 * (1 + 0.5 * rk) and seg[-1] <= px0 and np.isfinite(O[i + 6, j]) and O[i + 6, j] > 0:
        g2x[r], g2p[r] = i + 6, O[i + 6, j]
c["g2x"], c["g2p"] = g2x, g2p
def set_fresh(cc):
    k_ = set(zip(cc.signal_i.values.tolist(), cc.j.values.tolist()))
    cc = cc.copy(); cc["fresh"] = [(si - 1, j) not in k_ for si, j in zip(cc.signal_i.values, cc.j.values)]
    return cc
codes = list(D["codes"])
from backend.screener.rotation import family_members  # noqa: E402
from backend.db.database import SessionLocal  # noqa: E402
fm = family_members(SessionLocal())
AI = set(fm["반도체 장비·재료"]) | set(fm["AI메모리·기판"])
c["ai"] = [codes[j] in AI for j in c.j.values]
print(f"후보 {len(c)} (지금 규칙 {int(c.e0.sum())} · 돌파만 {int((~c.e0).sum())}) · AI·반도체 {int(c.ai.sum())} · {(time.time()-t0)/60:.1f}분", flush=True)


def orders(cc):
    o = np.lexsort((cc.j.values, -cc.rs.values, ~cc.e0.values, cc.i.values))   # 날마다: 지금 규칙 먼저(RS 순) → 돌파(RS 순)
    od = {}
    for r in o:
        od.setdefault(int(cc.i.values[r]), []).append(r)
    return od


def sim(cc, S, E, pyramid=False, cap=False, g2=False, g3=False, budget=False, rp=0.005, max_adds=None):
    cc = set_fresh(cc)
    od = orders(cc)
    CJ, PX, RK, SZ, XD, XP, PH = cc.j.values, cc.px0.values, cc.risk.values, cc.size_mult.values, cc.xday.values.astype(int), cc.xpx.values, cc.exit_phase.values
    if g2:
        XD, XP = cc.g2x.values.astype(int), cc.g2p.values
        PH = np.where(cc.g2x.values != cc.xday.values, "open", PH)
    FR, AIf = cc.fresh.values, cc.ai.values
    cash, pos = 1.0, {}
    ban = {}
    eq = np.empty(E - S + 1); gross = np.empty(E - S + 1); ent = adds = forced = 0
    pnl = {True: 0.0, False: 0.0}

    def settle(d):
        nonlocal cash
        for j in [j for j, p in pos.items() if p["xd"] == d]:
            p = pos.pop(j)
            proceeds = p["sh"] * p["xp"] * (1 - CS)
            cash += proceeds; pnl[p["ai"]] += proceeds - p["cost"]
            if p["ph"] == "intraday":
                ban[j] = d + 5
    for d in range(S, E + 1):
        settle(d)
        cf = Cf[d]
        E_ = cash + sum(p["sh"] * cf[j] for j, p in pos.items())
        free = 10 - len(pos)
        for r in od.get(d, []):
            j = CJ[r]
            if j in pos:
                p = pos[j]
                if pyramid and FR[r] and (cf[j] / p["px0"] - 1) / p["rk"] >= 1 and XD[r] > d and (max_adds is None or p.get("na", 0) < max_adds):
                    s_new = PX[r] * (1 - RK[r]); s_new_eff = max(p["stop"], s_new)
                    val = min(rp * E_ * SZ[r] / max(RK[r], .003), p["v0"])
                    if budget:     # 후보 H: 추가 후 손절까지 손실 ≤ 추가 전 손절까지 손실
                        P = cf[j]; q_old = p["sh"]
                        q_max = q_old * (P - p["stop"]) / max(P - s_new_eff, 1e-9) - q_old
                        val = min(val, max(q_max, 0) * PX[r])
                    if cap:
                        val = min(val, cash)
                    if val > 0:
                        cash -= val * (1 + CB); p["sh"] += val / PX[r]; p["cost"] += val * (1 + CB); adds += 1; p["na"] = p.get("na", 0) + 1
                    if s_new >= p["stop"]:          # 손절 올리기: 더 높은 손절을 가진 쪽(새 신호)의 청산 경로로
                        p["stop"] = s_new; p["xd"], p["xp"], p["ph"] = int(XD[r]), XP[r], PH[r]
                continue
            if free <= 0:
                continue
            if g3 and ban.get(j, -1) >= d:
                continue
            val = rp * E_ * SZ[r] / max(RK[r], .003)
            if cap:
                val = min(val, cash)
            if val <= 0:
                continue
            cash -= val * (1 + CB)
            pos[j] = dict(sh=val / PX[r], xd=int(XD[r]), xp=XP[r], ph=PH[r], px0=PX[r], rk=RK[r], v0=val, ai=bool(AIf[r]), cost=val * (1 + CB), stop=PX[r] * (1 - RK[r]))
            if int(XD[r]) <= n - 1 and li[j] < n - 1 and int(XD[r]) == li[j]:
                forced += 1
            free -= 1; ent += 1
        settle(d)
        mv = sum(p["sh"] * cf[j] for j, p in pos.items())
        eq[d - S] = cash + mv
        gross[d - S] = mv / eq[d - S] if eq[d - S] > 0 else np.nan
    for j, p in pos.items():       # 기간 끝 미청산도 기여에 넣음 (아스트라 3차)
        pnl[p["ai"]] += p["sh"] * Cf[E, j] * (1 - CS) - p["cost"]
    mt = CM.metr(eq)
    tot = pnl[True] + pnl[False]
    mt.update(ent=ent, adds=adds, g_avg=float(np.nanmean(gross)), g_max=float(np.nanmax(gross)), ai_share=pnl[True] / tot if tot else np.nan, forced=forced)
    return mt


def line(lab, mt):
    return (f"  {lab:34s} 연 {mt['cagr']:+6.1f}% 낙폭 {mt['mdd']:5.0f}% MAR {mt['mar']:5.2f} · 진입 {mt['ent']} 불타기 {mt['adds']}"
            f" · 총매수/순자산 평균 {mt['g_avg']*100:4.0f}% 최대 {mt['g_max']*100:4.0f}% · AI·반도체 손익 몫 {mt['ai_share']*100:4.0f}% · 폐지 강제정리 {mt['forced']}")


P = {"연습 2015.07~22": ("2015-07-01", "2022-12-31"), "시험 2023~": ("2023-01-01", "2026-12-31")}
res = {}
for part, (A, B) in P.items():
    S, E = RT.sidx(W, A), min(RT.eidx(W, B), n - 1)
    base_old = c[c.e0 & (c.i >= S)].reset_index(drop=True)
    allc = c[c.i >= S].reset_index(drop=True)
    print(f"[{part}]", flush=True)
    R = {}
    R["a"] = sim(base_old, S, E); print(line("(a) 예전 숫자: 불타기·돌파 없음", R["a"]), flush=True)
    R["b"] = sim(base_old, S, E, pyramid=True); print(line("(b) + 불타기", R["b"]), flush=True)
    R["c"] = sim(allc, S, E); print(line("(c) + 돌파 남는 칸", R["c"]), flush=True)
    R["d"] = sim(allc, S, E, pyramid=True); print(line("(d) 지금 운용 규칙(둘 다)", R["d"]), flush=True)
    R["h"] = sim(allc, S, E, pyramid=True, budget=True); print(line("H 추가매수 손실 예산", R["h"]), flush=True)
    R["d1"] = sim(allc, S, E, pyramid=True, max_adds=1); print(line("(참고) 불타기 종목당 1번만 + 돌파", R["d1"]), flush=True)
    res[part] = R
print("\n판정 (기준 = 정정된 (d), 연습·시험 둘 다: 낙폭 5%p↑ 감소 · 연수익 90%↑ · MAR 15%↑ 개선)")
for g in ("h",):
    ok = []
    for part in P:
        b, x = res[part]["d"], res[part][g]
        ok.append((abs(x["mdd"]) <= abs(b["mdd"]) - 5) and (x["cagr"] >= 0.9 * b["cagr"] if b["cagr"] > 0 else x["cagr"] >= b["cagr"]) and (x["mar"] >= b["mar"] * 1.15 if b["mar"] > 0 else x["mar"] > b["mar"]))
    print(f"  {g}: {'통과' if all(ok) else '기각'} (연습 {'O' if ok[0] else 'X'} · 시험 {'O' if ok[1] else 'X'})")
# AI·반도체 의존
print("\nAI·반도체 빼고 (지금 운용 규칙 (d))")
for lab, A, B in (("2015~22", "2015-07-01", "2022-12-31"), ("2023~24", "2023-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2026-12-31")):
    S, E = RT.sidx(W, A), min(RT.eidx(W, B), n - 1)
    allc = c[c.i >= S].reset_index(drop=True); noai = c[(c.i >= S) & ~c.ai].reset_index(drop=True)
    a, b = sim(allc, S, E, pyramid=True), sim(noai, S, E, pyramid=True)
    print(f"  {lab}: 전체 연 {a['cagr']:+.1f}% MAR {a['mar']:.2f} (AI·반도체 손익 몫 {a['ai_share']*100:.0f}%) → 빼면 연 {b['cagr']:+.1f}% MAR {b['mar']:.2f}", flush=True)
print("끝", f"{(time.time()-t0)/60:.1f}분")
