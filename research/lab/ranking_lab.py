"""신호가 넘칠 때 고르는 순서 — Claude(prereg_claude_ranking.md) vs GPT(prereg_gpt_ranking.md) 동시 실행 + GPT의 K 구조 시험 + 초기진입 '새로 막힌 S0' 확인 (2026-10-10 KST).
실행: cd /home/junp/stock_option_pj && set -a && . ./.env && set +a && nice -n 10 .venv/bin/python /home/junp/tmp_claude/ranking_lab.py
"""
import sys, hashlib, time as _t
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
src = open("/home/junp/tmp_claude/gpt_tests.py").read().split("LEGS = [(b_(C < M.ema(C, 21)), 1.0)]")[0]
exec(src)
import ma_lab as M
from multiprocessing import Pool

LEGS = [(b_(C < M.ema(C, 21)), 1.0)]
Cf = D["Cf"]; tv20 = D["tv20"]; codes = D["codes"]
CB, CS = M.COST_BUY, M.COST_SELL
t0 = M.trades(D, E0, LEGS, stop=stop, start=260)
cand = pd.DataFrame({"i": t0.i.values, "j": t0.j.values, "px0": t0.px0.values, "risk": t0.risk.values,
                     "xday": [lg[0][0] for lg in t0.legs], "xpx": [lg[0][1] for lg in t0.legs]})
cand["R"] = (cand.xpx / cand.px0 - 1 - CB - CS) / cand.risk
ii, jj = cand.i.values, cand.j.values
# ── 순서 점수
with np.errstate(all="ignore"):
    cross = b_(e20 > e60) & ~np.vstack([np.zeros((1, m), bool), b_(e20 > e60)[:-1]])
    lastc = pd.DataFrame(np.where(cross, np.arange(n)[:, None], np.nan)).ffill().values
    age = np.arange(n)[:, None] - lastc; age = np.where(np.isfinite(age) & (age <= 120), age, 121)
    RV = (Td / Td.rolling(20).mean().shift(1))
    vp5 = RV.shift(1).rolling(5).median().values
    clv = np.where(H - L == 0, 0.5, (C - L) / np.where(H - L == 0, 1, H - L))
    pcs10 = pd.DataFrame(clv).shift(1).rolling(10).mean().values
sha = np.array([int(hashlib.sha256(("RANK-20261010" + dates[i] + codes[j]).encode()).hexdigest()[:15], 16) for i, j in zip(ii, jj)])
codei = np.array([int(codes[j]) if codes[j].isdigit() else int(hashlib.md5(codes[j].encode()).hexdigest()[:8], 16) for j in jj])
nanlast = lambda x: np.where(np.isfinite(x), x, np.inf)
KEYS = {   # 오름차순 정렬 키 (주 키, 동점 키)
    "RS 순(지금)": (nanlast(-RS[ii, jj]), codei),
    "Claude C1 손절폭 작은 순": (nanlast(risk[ii, jj]), codei),
    "Claude C2 거래대금 큰 순": (nanlast(-tv20[ii, jj]), codei),
    "Claude C3 20일선 이격 작은 순": (nanlast(ext[ii, jj]), codei),
    "GPT R1 추세 신선도": (age[ii, jj].astype(float), sha),
    "GPT R2 지속 참여(VP5)": (nanlast(-vp5[ii, jj]), sha),
    "GPT R3 지속 종가 강도(PCS10)": (nanlast(-pcs10[ii, jj]), sha),
}
RANKERS = [k for k in KEYS if k != "RS 순(지금)"]
day_rows = {d: g.index.values for d, g in cand.groupby("i")}
ORDER = {}
for k, (k1, k2) in KEYS.items():
    o = np.lexsort((k2, k1, ii))                     # i, 주 키, 동점 키
    od = {}
    for r in o:
        od.setdefault(ii[r], []).append(r)
    ORDER[k] = {d: np.array(v) for d, v in od.items()}
CJ, CPX, CRK, CXD, CXP, CR = (cand[c].values for c in ("j", "px0", "risk", "xday", "xpx", "R"))
CXD = np.maximum(CXD, ii + 1)


def sim(order, start, end, mode="risk", maxpos=10, rp=0.005, cost=1.0, rng=None, record=False, extra=None):
    """order: dict d -> 후보 행 배열 (None이면 rng로 매일 섞음). extra: (행 배열 dict, 같은 형식 배열들) — H 후보(S0 다음)."""
    cb, cs = CB * cost, CS * cost
    cash = 1.0; pos = {}; exits = {}
    eq = np.empty(end - start + 1); lifts = []; entered = set(); hent = []
    for d in range(start, end + 1):
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - cs); del pos[j]
        mv = 0.0
        for j, p in pos.items():
            mv += p[0] * Cf[d, j]
        E_ = cash + mv
        rows = order.get(d) if order is not None else (rng.permutation(day_rows[d]) if d in day_rows else None)
        free = maxpos - len(pos)
        if rows is not None:
            avail = [r for r in rows if CJ[r] not in pos]
            if record and len(avail) > free > 0:
                sel = avail[:free]; lifts.append((d, free, np.mean(CR[sel]) - np.mean(CR[avail])))
            for r in avail:
                if free <= 0:
                    break
                j = CJ[r]
                if j in pos:
                    continue
                if mode == "risk":
                    val = rp * E_ / CRK[r]
                else:
                    val = E_ / maxpos
                    if cash < val * (1 + cb):
                        val = cash / (1 + cb)
                        if val < 0.02 * E_:
                            break
                cash -= val * (1 + cb); xd = int(CXD[r])
                pos[j] = (val / CPX[r], xd, CXP[r]); exits.setdefault(xd, []).append(j); free -= 1
                entered.add(r)
        if extra is not None and d in extra[0] and free > 0:
            HJ, HPX, HRK, HXD, HXP, HR = extra[1]
            for r in extra[0][d]:
                if free <= 0:
                    break
                j = HJ[r]
                if j in pos:
                    continue
                val = rp * E_ / HRK[r]
                cash -= val * (1 + cb); xd = int(max(HXD[r], d + 1))
                pos[j] = (val / HPX[r], xd, HXP[r]); exits.setdefault(xd, []).append(j); free -= 1; hent.append(HR[r])
        mv = 0.0
        for j, p in pos.items():
            mv += p[0] * Cf[d, j]
        eq[d - start] = cash + mv
    return (eq, lifts, entered, hent) if record or extra is not None else eq


def metr(eq):
    yrs = len(eq) / 245; cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1)); r = np.diff(np.log(eq))
    return dict(cagr=100 * cagr, mdd=100 * mdd, mar=cagr / abs(mdd) if mdd < 0 else np.nan, sharpe=float(r.mean() / r.std() * np.sqrt(245)))


def sidx(a):
    return int(np.searchsorted(dates, a))


def eidx(b):
    return int(np.searchsorted(dates, b, side="right")) - 1


PER = [("A 2015.07~22", "2015-07-01", "2022-12-31"), ("B 2023~25.05", "2023-01-01", "2025-05-31"), ("C 2025.06~", "2025-06-01", "2026-12-31")]
S_ALL, E_ALL = sidx("2015-07-01"), n - 1
_tt = _t.time(); sim(ORDER["RS 순(지금)"], S_ALL, E_ALL); M.log(f"시뮬 1회 {(_t.time() - _tt):.2f}초")
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "time":
    sys.exit(0)


# ── 무작위 (병렬)
def job_gpt(seeds):
    out = []
    for s in seeds:
        eq = sim(None, S_ALL, E_ALL, "risk", rng=np.random.default_rng(10_000_000 + s)); mt = metr(eq); out.append((mt["cagr"], mt["mar"]))
    return out


def job_claude(args):
    mode, a, b, seeds = args
    out = []
    for s in seeds:
        eq = sim(None, sidx(a), eidx(b), mode, rng=np.random.default_rng(20_000_000 + s)); mt = metr(eq); out.append((mt["cagr"], mt["mar"], mt["mdd"]))
    return out


if __name__ == "__main__":
    NG = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    with Pool(2) as pool:
        chunks = [list(range(k, min(k + 250, NG))) for k in range(0, NG, 250)]
        rg = np.array([x for part in pool.map(job_gpt, chunks) for x in part])
        M.log(f"GPT 무작위 {len(rg)}번 끝")
        cjobs = [(mode, a, b, list(range(k, k + 125))) for mode in ("risk", "ew") for _, a, b in PER for k in range(0, 500, 125)]
        cres = pool.map(job_claude, cjobs)
    RC = {}
    for (mode, a, b, _), res in zip(cjobs, cres):
        RC.setdefault((mode, a), []).extend(res)
    np.savez("/home/junp/tmp_claude/ranking_random.npz", gpt=rg, **{f"{k[0]}_{k[1]}": np.array(v) for k, v in RC.items()})

    M.log("=" * 150)
    M.log("0) 먼저: 지금 RS 순이 무작위 순서의 몇 백분위인가 (GPT 방식: 12년 경로, 위험 0.5%/손절폭, 최대 10)")
    eqs, lifts_all, info = {}, {}, {}
    for k in KEYS:
        eq, lifts, _, _ = sim(ORDER[k], S_ALL, E_ALL, "risk", record=True); eqs[k] = eq; lifts_all[k] = lifts
    mrs = metr(eqs["RS 순(지금)"])
    M.log(f"   RS 순: 연 {mrs['cagr']:+.1f}% · 낙폭 {mrs['mdd']:.0f}% · MAR {mrs['mar']:.2f} → 무작위 대비 연수익 {100 * np.mean(rg[:, 0] < mrs['cagr']):.1f} 백분위 · MAR {100 * np.mean(rg[:, 1] < mrs['mar']):.1f} 백분위"
          f" (무작위 연수익 중앙 {np.median(rg[:, 0]):+.1f}% · 5~95% {np.percentile(rg[:, 0], 5):+.1f}~{np.percentile(rg[:, 0], 95):+.1f}%)")

    M.log("=" * 150)
    M.log("1) GPT 기준 — TopKLift(순서가 결과를 바꾸는 날, 뽑힌 것 평균 R − 전체 후보 평균 R) · 무작위 p(Holm) · RS 대비 ΔCAGR/ΔMDD · 비용 0.5%")
    pvals = {}
    for k in KEYS:
        L_ = pd.DataFrame(lifts_all[k], columns=["d", "K", "lift"]); L_["date"] = dates[L_.d.values]
        tl = (L_.K * L_.lift).sum() / L_.K.sum()
        per = []
        for lab, a, b in PER:
            g = L_[(L_.date >= a) & (L_.date <= b)]; per.append((g.K * g.lift).sum() / max(1, g.K.sum()))
        mo = L_.date.str[:7].values; u = np.unique(mo)
        sk = pd.Series(L_.K * L_.lift).groupby(mo).sum().reindex(u).values; kk = pd.Series(L_.K).groupby(mo).sum().reindex(u).values
        pick = np.random.default_rng(7).integers(0, len(u), (10000, len(u)))
        ppos = np.mean(sk[pick].sum(1) / kk[pick].sum(1) > 0)
        mt = metr(eqs[k]); p_r = (1 + np.sum(rg[:, 0] >= mt["cagr"])) / (1 + len(rg)); pvals[k] = p_r
        e05 = metr(sim(ORDER[k], S_ALL, E_ALL, "risk", cost=5 / 3)); r05 = metr(sim(ORDER["RS 순(지금)"], S_ALL, E_ALL, "risk", cost=5 / 3))
        sub = []
        for lab, a, b in PER:
            s_, e_ = sidx(a) - S_ALL, eidx(b) - S_ALL
            m1, m0 = metr(eqs[k][s_:e_ + 1]), metr(eqs["RS 순(지금)"][s_:e_ + 1]); sub.append(m1["cagr"] - m0["cagr"])
        info[k] = dict(tl=tl, per=per, ppos=ppos, mt=mt, p=p_r, d05=e05["cagr"] - r05["cagr"], sub=sub, contested=len(L_))
        M.log(f"   {k:28s} 경합일 {len(L_)} · TopKLift {tl:+.3f}R (A {per[0]:+.3f} / B {per[1]:+.3f} / C {per[2]:+.3f}) P(>0) {100 * ppos:.0f}% | 연 {mt['cagr']:+.1f}% 낙폭 {mt['mdd']:.0f}% MAR {mt['mar']:.2f} 샤프 {mt['sharpe']:.2f}"
              f" | 무작위 p {p_r:.4f} | RS 대비 ΔCAGR {mt['cagr'] - mrs['cagr']:+.1f}%p ΔMDD {mt['mdd'] - mrs['mdd']:+.1f}%p (A {sub[0]:+.1f} B {sub[1]:+.1f} C {sub[2]:+.1f}) 비용0.5% Δ {e05['cagr'] - r05['cagr']:+.1f}%p")
    # Holm (6개)
    ps = sorted((pvals[k], k) for k in RANKERS); holm = {}
    run = 0
    for r_, (p, k) in enumerate(ps):
        run = max(run, min(1, p * (len(ps) - r_))); holm[k] = run
    M.log("   Holm 보정 p: " + " · ".join(f"{k.split()[0]} {k.split()[1]} {holm[k]:.3f}" for k in RANKERS))
    # SPA vs RS
    rb = np.diff(np.log(eqs["RS 순(지금)"])); dd = np.array([np.diff(np.log(eqs[k])) - rb for k in RANKERS])
    kk_, nn = dd.shape; dbar = dd.mean(1); g = np.random.default_rng(11); stats = []; ar = np.arange(nn)
    for _ in range(40):
        jump = g.random((250, nn)) < 1 / 20; jump[:, 0] = True; newp = g.integers(0, nn, (250, nn))
        li = np.maximum.accumulate(np.where(jump, ar, 0), axis=1); ix = (np.take_along_axis(newp, li, axis=1) + (ar - li)) % nn
        stats.append(dd[:, ix].mean(2).T)
    stats = np.vstack(stats); om = np.sqrt(nn) * stats.std(0)
    Ts = max(0.0, float(np.max(np.sqrt(nn) * dbar / om))); muc = dbar * (np.sqrt(nn) * dbar / om >= -np.sqrt(2 * np.log(np.log(nn))))
    p_spa = float(np.mean(np.maximum((np.sqrt(nn) * ((stats - dbar) + muc) / om).max(1), 0) >= Ts))
    M.log(f"   SPA (6개 vs RS, 10,000회): p = {p_spa:.3f}")
    M.log("   GPT 채택 판정:")
    for k in RANKERS:
        x = info[k]; mt = x["mt"]
        c1 = x["tl"] >= 0.05 and x["per"][0] > 0 and x["per"][1] > 0 and x["per"][2] >= -0.03 and x["ppos"] >= 0.95
        c2 = holm[k] <= 0.05; c3 = p_spa <= 0.10
        c4 = (mt["cagr"] - mrs["cagr"] >= 1.0 and mt["mdd"] - mrs["mdd"] >= -2.0 and (mt["mar"] >= 1.05 * mrs["mar"] or mt["sharpe"] >= mrs["sharpe"] + 0.05)
              and x["d05"] > 0 and x["sub"][0] >= 0 and x["sub"][1] >= 0 and x["sub"][2] >= -1.0)
        M.log(f"     {k:28s} ①Lift {'✅' if c1 else '⛔'} ②무작위 {'✅' if c2 else '⛔'} ③SPA {'✅' if c3 else '⛔'} ④계좌 {'✅' if c4 else '⛔'} → {'채택' if c1 and c2 and c3 and c4 else '기각'}")

    M.log("=" * 150)
    M.log("2) Claude 기준 — 기간마다 자본 1로 시작, MAR이 무작위 500번의 몇 백분위인가 (A는 90, C1은 95 필요) · RS 순 대비")
    for mode in ("risk", "ew"):
        M.log(f"◆ 방식 {'위험 0.5%/손절폭·최대 10' if mode == 'risk' else '동일금액 1/10·현금 한도'}")
        res = {}
        for k in KEYS:
            row = []
            for lab, a, b in PER:
                mt = metr(sim(ORDER[k], sidx(a), eidx(b), mode)); rr = np.array(RC[(mode, a)])
                row.append((mt, 100 * np.mean(rr[:, 1] < mt["mar"]), np.median(rr[:, 1])))
            res[k] = row
            M.log(f"   {k:28s} " + " | ".join(f"{lab} MAR {r[0]['mar']:.2f} ({r[1]:.0f}백분위, 무작위 중앙 {r[2]:.2f}) 연 {r[0]['cagr']:+.1f}% 낙폭 {r[0]['mdd']:.0f}%" for (lab, _, _), r in zip(PER, row)))
        info[("claude", mode)] = res
    M.log("   Claude 채택 판정 (두 방식 모두 성립해야):")
    for k in [x for x in RANKERS if x.startswith("Claude")] + [x for x in RANKERS if x.startswith("GPT")]:
        ok_all = True
        for mode in ("risk", "ew"):
            row = info[("claude", mode)][k]; base = info[("claude", mode)]["RS 순(지금)"]
            need = 95 if "C1" in k else 90
            c1 = row[0][1] >= need; c2 = row[1][0]["mar"] > row[1][2] and row[2][0]["mar"] > row[2][2]
            wins = sum(row[p][0]["mar"] > base[p][0]["mar"] for p in range(3)); dd_ok = all(row[p][0]["mdd"] - base[p][0]["mdd"] >= -3 for p in range(3))
            c3 = wins >= 2 and dd_ok
            ok_all &= c1 and c2 and c3
        M.log(f"     {k:28s} → {'채택' if ok_all else '기각'}")

    M.log("=" * 150)
    M.log("3) GPT 구조 시험 — 칸 수 K (RS 순 고정). 주: 총 위험 5% (거래당 5%/K) · 보조: 거래당 0.5%. 12년 경로, 기간별은 같은 경로를 잘라 봄")
    for lab_r, rpf in (("총 위험 5%", lambda K: 0.05 / K), ("거래당 0.5%", lambda K: 0.005)):
        M.log(f"◆ {lab_r}")
        for K in (5, 10, 15, 20):
            eq = sim(ORDER["RS 순(지금)"], S_ALL, E_ALL, "risk", maxpos=K, rp=rpf(K)); mt = metr(eq)
            sub = []
            for lab, a, b in PER:
                s_, e_ = sidx(a) - S_ALL, eidx(b) - S_ALL; ms = metr(eq[s_:e_ + 1]); sub.append(f"{lab[0]} {ms['cagr']:+.0f}%/{ms['mdd']:.0f}%")
            M.log(f"   K={K:2d} 거래당 {100 * rpf(K):.2f}% | 전체 연 {mt['cagr']:+.1f}% 낙폭 {mt['mdd']:.0f}% MAR {mt['mar']:.2f} 샤프 {mt['sharpe']:.2f} | " + " · ".join(sub))
