"""상승 초기 진입 — Claude 사전등록(prereg_claude_early_entry.md) vs GPT 사전등록(prereg_gpt_early_entry.md) 동시 실행 (2026-10-10 KST).
각자의 정의·평가·채택 기준 그대로. 교차 평가(내 가설을 GPT 기준으로, GPT 가설을 내 기준으로)도 참고로 같이 낸다.
실행: cd /home/junp/stock_option_pj && set -a && . ./.env && set +a && nice -n 10 .venv/bin/python /home/junp/tmp_claude/early_lab.py
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
from math import erf, sqrt, log
src = open("/home/junp/tmp_claude/gpt_tests.py").read().split("LEGS = [(b_(C < M.ema(C, 21)), 1.0)]")[0]
exec(src)                                   # D, buy(), E0, 지수(idx), is_kq, liq, RS, stop, risk, ...
import ma_lab as M
from scipy.stats import norm, skew as sp_skew, kurtosis as sp_kurt

rng = np.random.default_rng(2026)
LEGS = [(b_(C < M.ema(C, 21)), 1.0)]
Cf = D["Cf"]; tv20 = D["tv20"]
PER = [("A 2015.07~22", "2015-07-01", "2022-12-31"), ("B 2023~25.05", "2023-01-01", "2025-05-31"), ("C 2025.06~", "2025-06-01", "2026-12-31")]
with np.errstate(all="ignore"):
    G = liq & Bm & b_(C > e20) & b_(e20 > e60) & b_(risk <= 0.08) & b_(risk > 0)
    Od = pd.DataFrame(O); pc = Cd.shift(1)
    RSd = pd.DataFrame(np.where(np.isfinite(RS), RS, np.nan))
    IDXP = np.where(is_kq[None, :], idx["^KQ11"].values[:, None], idx["^KS11"].values[:, None])
    # ── Claude
    RSL = pd.DataFrame(C / IDXP)
    CH1 = G & b_(RSL.values >= RSL.shift(1).rolling(59).max().values) & b_(C < 0.95 * Hd.rolling(60).max().values) & b_(C > O) & b_((C - L) / np.where(H - L == 0, np.nan, H - L) >= 0.5)
    CH2 = G & b_((RS >= 50) & (RS < 70)) & b_((RSd - RSd.shift(20)).values >= 25) & b_(C > pc.rolling(10).max().values)
    vdown = pd.DataFrame(np.where(C < pc.values, V, np.nan)).shift(1).rolling(10, min_periods=1).max().values
    sma10 = Cd.rolling(10).mean().values
    CH3 = G & b_(C > O) & b_(C > pc.values) & b_(V > vdown) & b_(C > sma10) & b_(C / sma10 - 1 < 0.05) & b_(chg < 0.08)

    def first(cond):
        return cond & ~np.vstack([np.zeros((1, m), bool), cond[:-1]])
    # ── GPT (G & S0=0, 처음 참인 날)
    GH1 = first(G & ~E0 & b_((RS >= 40) & (RS <= 69)) & b_((RSd - RSd.shift(10)).values >= 20) & b_((C / pc.shift(9).values - 1 >= 0.04) & (C / pc.shift(9).values - 1 <= 0.18))
                & b_(e20 / pd.DataFrame(e20).shift(5).values - 1 >= 0.005))
    db = SessionLocal()
    fl = pd.read_sql(text("select stock_code, trading_date, foreign_net_buy + institution_net_buy nb from spot_investor_flows"), db.connection())
    di = {d: i for i, d in enumerate(D["dates"])}; ci = {c: j for j, c in enumerate(D["codes"])}
    NB = np.full((n, m), np.nan)
    fl = fl[fl.trading_date.isin(di) & fl.stock_code.isin(ci)]
    NB[fl.trading_date.map(di).values, fl.stock_code.map(ci).values] = fl.nb.values
    NBd, Tdf = pd.DataFrame(NB), pd.DataFrame(T)
    ratio = (NBd.shift(1).rolling(5).sum() / Tdf.shift(1).rolling(5).sum()).values
    posd = (NBd > 0).astype(float).where(NBd.notna()).shift(1).rolling(5).sum().values
    r5 = (pc / Cd.shift(6) - 1).values
    mx3 = pd.concat([Cd.shift(1), Cd.shift(2), Cd.shift(3)]).groupby(level=0).max().values
    GH2 = first(G & ~E0 & b_(ratio >= 0.03) & b_(posd >= 3) & b_((r5 >= -0.02) & (r5 <= 0.08)) & b_(C >= 1.005 * mx3) & b_((chg >= 0) & (chg <= 0.06)))
    er = ((Cd - Cd.shift(10)) / Cd.diff().abs().rolling(10).sum()).values
    r10 = (Cd / Cd.shift(10) - 1).values
    upd = (pd.DataFrame(chg) > 0).astype(float).rolling(10).sum().values
    mxc = pd.DataFrame(chg).rolling(10).max().values
    GH3 = first(G & ~E0 & b_(er >= 0.55) & b_((r10 >= 0.04) & (r10 <= 0.15)) & b_(upd >= 6) & b_(mxc <= 0.06))
HYP = {"Claude H1 RS선 선행 신고가": CH1, "Claude H2 RS 급상승": CH2, "Claude H3 포켓 피벗": CH3,
       "GPT H1 RS 가속": GH1, "GPT H2 수급 매집(2026만)": GH2, "GPT H3 매끄러운 상승": GH3}
for k, v in HYP.items():
    M.log(f"신호 {k}: {int(v.sum())}개")
M.log(f"BASE(S0) 신호 {int(E0.sum())}개 · 실행 가능 풀 G {int(G.sum())}개")

# ── 거래 (같은 청산). 계좌용 = 겹침 포함, 신호 품질용 = first_only
COSTS = {"0.3%": (M.COST_BUY, M.COST_SELL), "0.5%": (M.COST_BUY * 5 / 3, M.COST_SELL * 5 / 3), "0.6%": (M.COST_BUY * 2, M.COST_SELL * 2)}


def raw_trades(E):
    t = M.trades(D, E, LEGS, stop=stop, start=260)
    t["date"] = dates[t.i.values]; t["xpx"] = [lg[0][1] for lg in t.legs]; t["xday"] = [lg[0][0] for lg in t.legs]
    return t


def addR(t, cost="0.3%", entry="close"):
    t = t.copy()
    cb, cs = COSTS[cost]
    if entry == "open":
        o1 = O[np.minimum(t.i.values + 1, n - 1), t.j.values]; st = stop[t.i.values, t.j.values]
        ok = np.isfinite(o1) & (o1 > 0); t = t[ok].copy(); o1 = o1[ok]; st = st[ok]
        t["ret"] = np.where(o1 <= st, 0.0, t.xpx.values / o1 - 1); t["risk"] = np.where(o1 <= st, 0.01, 1 - st / o1); t["px0"] = o1
    t["net"] = t.ret - cb - cs; t["R"] = t.net / t.risk
    return t


M.log("거래 계산 중 (풀 포함)")
TR = {k: raw_trades(v) for k, v in HYP.items()}
TR["BASE"] = raw_trades(E0)
POOL = raw_trades(G)
M.log(f"풀 거래 {len(POOL)}건")
FO = {k: M.first_only(t).reset_index(drop=True) for k, t in TR.items()}


def per_mask(t, a, b):
    return (t.date >= a) & (t.date <= b)


# ── Claude 평가 ①: 풀 무작위 대비, 20거래일 연속 구간 짝 부트스트랩 (블록 합으로)
def block_diff(h, pool, a, b, alpha=0.05, nb=4000, blk=20):
    hh = h[per_mask(h, a, b)]; pp = pool[per_mask(pool, a, b)]
    if len(hh) < 10:
        return None
    bh = hh.i.values // blk; bp = pp.i.values // blk
    u = np.unique(np.concatenate([bh, bp]))
    pos = {x: k for k, x in enumerate(u)}
    sh = np.zeros(len(u)); nh = np.zeros(len(u)); sp = np.zeros(len(u)); npp = np.zeros(len(u))
    np.add.at(sh, [pos[x] for x in bh], hh.R.values); np.add.at(nh, [pos[x] for x in bh], 1)
    np.add.at(sp, [pos[x] for x in bp], pp.R.values); np.add.at(npp, [pos[x] for x in bp], 1)
    pick = rng.integers(0, len(u), (nb, len(u)))
    d = sh[pick].sum(1) / np.maximum(nh[pick].sum(1), 1) - sp[pick].sum(1) / np.maximum(npp[pick].sum(1), 1)
    lo, hi = np.percentile(d, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return len(hh), hh.R.mean(), pp.R.mean(), hh.R.mean() - pp.R.mean(), lo, hi


# ── GPT 평가: matched random (같은 날·G·S0=0·같은 시장·시총 5분위·ADV 5분위·손절폭 2%p 구간), 후보 평균 기대값
db2 = SessionLocal()
sh_out = dict(db2.execute(text("select code, shares_outstanding from stocks")).all())
shares = np.array([float(sh_out.get(c) or np.nan) for c in D["codes"]])
mcap = C * shares[None, :]                       # 현재 주식수 × 그날 종가 (근사)


def qcut_day(X, mask):
    Q = np.full(X.shape, -1, dtype=np.int8)
    for t in range(n):
        mm = mask[t] & np.isfinite(X[t])
        if mm.sum() >= 5:
            r = pd.Series(X[t, mm]).rank(pct=True).values
            Q[t, np.nonzero(mm)[0]] = np.minimum((r * 5).astype(int), 4)
    return Q


QM, QA = qcut_day(mcap, G), qcut_day(tv20, G)
SB = np.clip((risk * 100 // 2).astype(np.int16), 0, 3)
pool_key = POOL.copy()
pool_key["key"] = list(zip(pool_key.i.values, is_kq[pool_key.j.values], QM[pool_key.i.values, pool_key.j.values], QA[pool_key.i.values, pool_key.j.values], SB[pool_key.i.values, pool_key.j.values]))


def matched_delta(name, cost="0.3%"):
    h = addR(FO[name], cost); sig = HYP[name]
    pk = addR(pool_key, cost)
    pk = pk[~E0[pk.i.values, pk.j.values] & ~sig[pk.i.values, pk.j.values]]
    grp = pk.groupby("key").R.mean()
    keys = list(zip(h.i.values, is_kq[h.j.values], QM[h.i.values, h.j.values], QA[h.i.values, h.j.values], SB[h.i.values, h.j.values]))
    exp_ = np.array([grp.get(k, np.nan) for k in keys])
    h = h.assign(expR=exp_, delta=h.R.values - exp_)
    return h


def month_boot(h, nb=10000):
    g = h.dropna(subset=["delta"])
    if len(g) < 10:
        return np.nan, np.nan
    mo = g.date.str[:7].values; u = np.unique(mo)
    s = pd.Series(g.delta.values).groupby(mo).sum().reindex(u).values; c = pd.Series(np.ones(len(g))).groupby(mo).sum().reindex(u).values
    pick = rng.integers(0, len(u), (nb, len(u)))
    d = s[pick].sum(1) / c[pick].sum(1)
    return tuple(np.percentile(d, [2.5, 97.5]))


# ── 계좌 시뮬 (S0 우선)
COSTB, COSTS_ = M.COST_BUY, M.COST_SELL


def simulate(cands, start, end, mode, maxpos, cost_mult=1.0):
    """cands: DataFrame(i, j, px0, xday, xpx, risk, R, grp('S0'/'H'), rk). 반환: 일별 자본, 통계."""
    cb, cs = COSTB * cost_mult, COSTS_ * cost_mult
    c = cands[(cands.i >= start) & (cands.i <= end)].sort_values(["i", "gk", "rk"])
    by = {k: g for k, g in c.groupby("i")}
    cash, pos = 1.0, {}                       # pos[j] = (shares, xday, xpx, grp, R)
    eq = np.full(end - start + 1, np.nan); expo = np.zeros_like(eq); npos = np.zeros_like(eq)
    blocked, hentries, full_days = [], [], 0
    for d in range(start, end + 1):
        for j in [j for j, p in pos.items() if p[1] == d]:
            shs, _, xp, _, _ = pos.pop(j); cash += shs * xp * (1 - cs)
        mv = sum(p[0] * Cf[d, j] for j, p in pos.items()); E_ = cash + mv
        if len(pos) >= maxpos:
            full_days += 1
        for r in (by[d].itertuples(index=False) if d in by else []):
            if r.j in pos:
                continue
            if len(pos) >= maxpos:
                if r.grp == "S0":
                    blocked.append(r.R)
                continue
            if mode == "gpt_risk":
                val = 0.005 * E_ / r.risk
            elif mode == "gpt_cash":
                val = 0.005 * E_ / r.risk
                if cash < val * (1 + cb):
                    if r.grp == "S0":
                        blocked.append(r.R)
                    continue
            elif mode == "my_ew":
                val = E_ / maxpos
                if cash < val * (1 + cb):
                    val = cash / (1 + cb)
                    if val < E_ * 0.02:
                        if r.grp == "S0":
                            blocked.append(r.R)
                        continue
            else:                              # my_risk
                val = min(E_ * 0.005 / r.risk, E_ * 0.20)
                if cash < val * (1 + cb):
                    val = cash / (1 + cb)
                    if val < E_ * 0.02:
                        if r.grp == "S0":
                            blocked.append(r.R)
                        continue
            cash -= val * (1 + cb)
            xd = int(max(r.xday, d + 1)); pos[r.j] = (val / r.px0, xd if xd <= end else 10 ** 9, r.xpx, r.grp, r.R)
            if r.grp == "H":
                hentries.append(r.R)
        mv = sum(p[0] * Cf[d, j] for j, p in pos.items()); eq[d - start] = cash + mv
        expo[d - start] = mv / eq[d - start] if eq[d - start] > 0 else 0; npos[d - start] = len(pos)
    e = eq[np.isfinite(eq)]
    yrs = len(e) / 245; cagr = (e[-1] / e[0]) ** (1 / yrs) - 1 if yrs > 0.3 else e[-1] / e[0] - 1
    mdd = float(np.min(e / np.maximum.accumulate(e) - 1))
    r = np.diff(np.log(np.maximum(e, 1e-9)))
    shp = float(np.mean(r) / np.std(r) * np.sqrt(245)) if np.std(r) > 0 else np.nan
    mo = pd.Series(e, index=pd.to_datetime(dates[start:end + 1][:len(e)])).resample("ME").last().pct_change().dropna()
    return dict(cagr=cagr * 100, mdd=mdd * 100, mar=(cagr / abs(mdd)) if mdd < 0 else np.nan, sharpe=shp, worstm=float(mo.min() * 100) if len(mo) else np.nan,
                expo=float(np.mean(expo)) * 100, npos=float(np.mean(npos)), full=100 * full_days / len(eq), hN=len(hentries), hR=float(np.mean(hentries)) if hentries else np.nan,
                blkN=len(blocked), blkR=float(np.mean(blocked)) if blocked else np.nan, daily=r)


def cand_table(names, rank_style):
    b = addR(TR["BASE"]); b["grp"] = "S0"; b["rk"] = -np.nan_to_num(RS[b.i.values, b.j.values], nan=-1)
    parts = [b]
    if names:
        cnt = sum(HYP[k].astype(np.int8) for k in names)
        hs = pd.concat([addR(TR[k]) for k in names]).drop_duplicates(["i", "j"])
        hs = hs[~E0[hs.i.values, hs.j.values]]              # S0와 같은 날은 S0로
        hs["grp"] = "H"
        if rank_style == "gpt":                         # 동시 만족 H 개수↓, ADV20↓, 손절폭 작은 순, 코드
            hs = hs.assign(k1=-cnt[hs.i.values, hs.j.values], k2=-np.nan_to_num(tv20[hs.i.values, hs.j.values]), k3=hs.risk.values, k4=hs.j.values)
            hs = hs.sort_values(["k1", "k2", "k3", "k4"]); hs["rk"] = np.arange(len(hs), dtype=float)
        else:                                           # Claude: RS 높은 순
            hs["rk"] = -np.nan_to_num(RS[hs.i.values, hs.j.values], nan=-1) + 1e3
        parts.append(hs)
    out = pd.concat(parts, ignore_index=True)[["i", "j", "px0", "xday", "xpx", "risk", "R", "grp", "rk"]]
    out["gk"] = (out.grp == "H").astype(int)                 # S0 먼저
    return out


def s_idx(a):
    return next(k for k, d in enumerate(dates) if d >= a)


def e_idx(b):
    return max(k for k, d in enumerate(dates) if d <= b)


_PC = {}


def poolR(cost="0.3%", entry="close"):
    if (cost, entry) not in _PC:
        _PC[(cost, entry)] = addR(POOL, cost, entry)[["i", "j", "date", "R"]]
    return _PC[(cost, entry)]


# ════════════════ 1. 신호 품질 ════════════════
M.log("=" * 160)
M.log("1) 신호 품질 (겹침 뺀 거래). R = 순손익/손절폭. 풀 = 실행 가능한 날 무작위 · matched = GPT식 같은 조건 비신호 종목 기대값")
for name in HYP:
    h0 = addR(FO[name]); hm = matched_delta(name)
    M.log(f"◆ {name}: 거래 {len(h0)}건 · 전체 E[R] {h0.R.mean():+.2f} · 중앙 {h0.R.median():+.2f} · 승률 {100 * (h0.net > 0).mean():.0f}% · 보유 {h0.hold.mean():.1f}일 · 비용0.5% E[R] {addR(FO[name], '0.5%').R.mean():+.2f}"
          + (f" · 상위5% 거래 P&L 비중 {100 * np.sort(h0.net.values)[-max(1, len(h0) // 20):].sum() / h0.net.sum():.0f}%" if h0.net.sum() > 0 else " · 순손익 합 ≤ 0"))
    for lab, a, b in PER:
        hh = h0[per_mask(h0, a, b)]; mm = hm[per_mask(hm, a, b)]
        bd = block_diff(h0, poolR(), a, b, alpha=0.017 if lab.startswith("A") else 0.05)
        bs = addR(FO["BASE"]); bs = bs[per_mask(bs, a, b)]
        lo_m, hi_m = month_boot(mm)
        if bd is None:
            M.log(f"   {lab}: 거래 {len(hh)}건 (표본 부족)"); continue
        M.log(f"   {lab}: {bd[0]:4d}건 E[R] {bd[1]:+.2f} (BASE {bs.R.mean():+.2f}) | 풀 {bd[2]:+.2f} 차이 {bd[3]:+.2f} [{'98.3' if lab.startswith('A') else '95'}% {bd[4]:+.2f},{bd[5]:+.2f}]"
              f" | matched Δ {np.nanmean(mm.delta):+.2f} [월 95% {lo_m:+.2f},{hi_m:+.2f}] (짝 없음 {int(mm.expR.isna().sum())}) | 5%/95% R {np.percentile(hh.R, 5):+.2f}/{np.percentile(hh.R, 95):+.2f} · 손절 비율 {100 * (hh.R < -0.9).mean():.0f}%")
    # Claude 견고성: 비용 2배·다음 날 시가 (연습 A 풀 대비 방향)
    a, b = PER[0][1], PER[0][2]
    r1 = block_diff(addR(FO[name], "0.6%"), poolR("0.6%"), a, b); r2 = block_diff(addR(FO[name], "0.3%", "open"), poolR("0.3%", "open"), a, b)
    if r1 and r2:
        M.log(f"   견고성(A 풀 대비 차이): 비용 2배 {r1[3]:+.2f} · 다음 날 시가 진입 {r2[3]:+.2f}")

# ════════════════ 2. 계좌 ════════════════
M.log("=" * 160)
M.log("2) 계좌 — S0 우선. 기간마다 자본 1로 다시 시작 + 전체 연속(2015.07~). 지표: 연수익/최대낙폭/MAR/샤프/최악 월/평균 노출/평균 보유 수/10칸 꽉 찬 날 %/H 진입 수·평균 R/막힌 S0 수·shadow R")
PORT = {"B": []} | {f"B+{k}": [k] for k in HYP} | {"B+GPT ALL": [k for k in HYP if k.startswith("GPT")], "B+Claude ALL": [k for k in HYP if k.startswith("Claude")]}
ACC = {}
for mode, maxpos, style in (("gpt_risk", 10, "gpt"), ("gpt_cash", 10, "gpt"), ("my_ew", 10, "claude"), ("my_risk", 15, "claude")):
    M.log(f"◆ 방식 {mode} (최대 {maxpos})")
    for pname, names in PORT.items():
        ct = cand_table(names, style)
        res = {}
        for lab, a, b in PER + [("전체", "2015-07-01", "2026-12-31")]:
            res[lab] = simulate(ct, s_idx(a), e_idx(b), mode, maxpos)
        if mode == "gpt_risk":
            res["전체 비용0.5%"] = simulate(ct, s_idx("2015-07-01"), e_idx("2026-12-31"), mode, maxpos, cost_mult=5 / 3)
        ACC[(mode, pname)] = res
        line = " | ".join(f"{lab} {v['cagr']:+.1f}%/{v['mdd']:.0f}%" for lab, v in res.items() if lab != "전체 비용0.5%")
        tot = res["전체"]
        M.log(f"   {pname:30s} {line} || MAR {tot['mar']:.2f} 샤프 {tot['sharpe']:.2f} 최악월 {tot['worstm']:.0f}% 노출 {tot['expo']:.0f}% 보유 {tot['npos']:.1f} 꽉참 {tot['full']:.0f}% H {tot['hN']}건 R{tot['hR']:+.2f} 막힌S0 {tot['blkN']}건 R{tot['blkR']:+.2f}"
              + (f" | 비용0.5% 전체 {res['전체 비용0.5%']['cagr']:+.1f}%" if "전체 비용0.5%" in res else ""))

# ════════════════ 3. DSR · SPA (gpt_risk 전체 일별) ════════════════
M.log("=" * 160)
M.log("3) 다중검정 — gpt_risk 전체 연속 일별 수익")
cand_names = [p for p in PORT if p != "B"]
srs = {p: np.mean(ACC[("gpt_risk", p)]["전체"]["daily"]) / np.std(ACC[("gpt_risk", p)]["전체"]["daily"]) for p in PORT}
V = np.var([srs[p] for p in cand_names], ddof=1)
gam = 0.5772156649
for p in PORT:
    r = ACC[("gpt_risk", p)]["전체"]["daily"]; sr = srs[p]; Tn = len(r); sk = sp_skew(r); ku = sp_kurt(r, fisher=False)
    out = []
    for N in (50, 100, 300):
        sr0 = np.sqrt(V) * ((1 - gam) * norm.ppf(1 - 1 / N) + gam * norm.ppf(1 - 1 / (N * np.e)))
        out.append(f"N={N} {norm.cdf((sr - sr0) * np.sqrt(Tn - 1) / np.sqrt(1 - sk * sr + (ku - 1) / 4 * sr ** 2)):.2f}")
    M.log(f"   {p:30s} 일별 샤프 {sr:.3f} (연 {sr * np.sqrt(245):.2f}) · DSR " + " · ".join(out))


def spa(names, nb=10000, mean_blk=20, chunk=250):
    rb = ACC[("gpt_risk", "B")]["전체"]["daily"]
    dd = np.array([ACC[("gpt_risk", p)]["전체"]["daily"] - rb for p in names])
    k, nn = dd.shape; dbar = dd.mean(1); p_ = 1 / mean_blk
    stats = []
    ar = np.arange(nn)
    for _ in range(nb // chunk):
        jump = rng.random((chunk, nn)) < p_; jump[:, 0] = True
        newp = rng.integers(0, nn, (chunk, nn))
        li = np.maximum.accumulate(np.where(jump, ar, 0), axis=1)
        idx_ = (np.take_along_axis(newp, li, axis=1) + (ar - li)) % nn
        stats.append(dd[:, idx_].mean(2).T)
    stats = np.vstack(stats)
    om = np.sqrt(nn) * stats.std(0)
    Tstat = max(0.0, float(np.max(np.sqrt(nn) * dbar / om)))
    muc = dbar * (np.sqrt(nn) * dbar / om >= -np.sqrt(2 * np.log(np.log(nn))))
    Z = np.sqrt(nn) * ((stats - dbar) + muc) / om
    Tb = np.maximum(Z.max(1), 0)
    return float(np.mean(Tb >= Tstat)), Tstat, dbar * 245 * 100


g_names = ["B+GPT H1 RS 가속", "B+GPT H2 수급 매집(2026만)", "B+GPT H3 매끄러운 상승", "B+GPT ALL"]
c_names = ["B+Claude H1 RS선 선행 신고가", "B+Claude H2 RS 급상승", "B+Claude H3 포켓 피벗", "B+Claude ALL"]
for lab, nm in (("GPT 후보 4개(사전등록)", g_names), ("Claude 후보 4개(참고)", c_names)):
    p, t_, ex = spa(nm)
    M.log(f"   SPA {lab}: p = {p:.3f} (통계량 {t_:.2f}, 10,000회, 평균 블록 20일) · B 대비 연 초과(단순) " + " / ".join(f"{x:+.1f}%" for x in ex))
