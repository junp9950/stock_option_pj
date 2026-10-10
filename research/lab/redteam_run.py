"""연구 1 RS 레드팀 + 연구 2 낙폭 overlay — Claude(prereg_claude_redteam_dd.md f3a091da) + GPT(prereg_gpt_redteam_dd.md 9a60b8c2) 동시 실행 (2026-10-10 KST).
데이터: ma_lab_cache_full.npz (상폐 625 추가). 네이버 종가×거래량 = 실제 거래대금 검증(40종목 116,344일 100%가 ±10% 안, 삼성전자 분할 전후 1.000).
실행: cd /home/junp/stock_option_pj && set -a && . ./.env && set +a && nice -n 10 .venv/bin/python /home/junp/tmp_claude/redteam_run.py
"""
import sys, hashlib
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
import redteam_lab as RT
import ma_lab as M
from multiprocessing import Pool
from sqlalchemy import text, create_engine

GPT_HASH = "9a60b8c2a8dd74a801aa24f42b22ecb8aadb70ac1ba19005fc3a431f30467092"
CL_HASH = "f3a091dafb8fc4dedd4d87eae64315f9161e519aa83ba780f6d23c724765d69a"
seed_of = lambda h, j: int(hashlib.sha256((h + str(j)).encode()).hexdigest()[:16], 16)
CB, CS = RT.COSTB, RT.COSTS
PER4 = [("2015~18", "2015-07-01", "2018-12-31"), ("2019~22", "2019-01-01", "2022-12-31"), ("2023~25.05", "2023-01-01", "2025-05-31"), ("2025.06~", "2025-06-01", "2026-12-31")]
PER3 = [("A 2015.07~22", "2015-07-01", "2022-12-31"), ("B 2023~25.05", "2023-01-01", "2025-05-31"), ("C 2025.06~", "2025-06-01", "2026-12-31")]

# ── 데이터
W = RT.build("full")
D, n, m, dates, n0 = W["D"], W["n"], W["m"], W["dates"], W["n0"]
O, H, L, C = D["o"], D["h"], D["l"], D["c"]
codes = list(D["codes"])
kind = pd.read_csv("/home/junp/tmp_claude/kind_delisting.csv", dtype={"종목코드": str}); kind["code"] = kind["종목코드"].str.zfill(6)
merger_codes = set(kind[kind["폐지사유"].str.contains("합병|이전상장|지주|스팩|기업인수목적|주식교환|주식이전|포괄", na=False)].code)
li = RT.last_idx(C)
delisted_j = np.array([j >= n0 for j in range(m)])
eng = create_engine(open("/home/junp/.local_db_url").read().strip())
mk = dict(eng.connect().execute(text("select code, market from stocks")).all())
is_kq = np.array([("KOSDAQ" in (mk.get(c) or "KOSDAQ")) for c in codes])      # 상폐 종목은 시장 정보 없음 → 코스닥으로(대부분 코스닥)


def cand_variant(merger_mode="primary", cost_entry="close"):
    """잠김 규칙: 정리매매(상폐 종목 마지막 10거래일)엔 적용 안 함. merger_mode: primary = 합병형 상폐로 폐지 때까지 보유된 거래 제외 / forced = 마지막 거래일 종가 강제청산."""
    t0 = M.trades(D, W["E0"], [(np.nan_to_num((C < M.ema(C, 21)).astype(float)).astype(bool), 1.0)], stop=W["stop"], start=260)
    chg = D["chg"]
    locked = (np.nan_to_num(H) == np.nan_to_num(L)) & (np.nan_to_num(chg) <= -0.29) & np.isfinite(C)
    for j in range(n0, m):
        if li[j] >= 0:
            locked[max(li[j] - 9, 0):li[j] + 1, j] = False
    xday = np.array([lg[0][0] for lg in t0.legs]); xpx = np.array([lg[0][1] for lg in t0.legs], dtype=float)
    i, j = t0.i.values, t0.j.values
    over = (xday > li[j]) & (li[j] < n - 1)
    is_merg = np.array([codes[jj] in merger_codes for jj in j]) & delisted_j[j]
    xday = np.where(over, li[j], xday); xpx = np.where(over, D["Cf"][np.minimum(li[j], n - 1), j], xpx)
    nlock = 0
    for k in range(len(xday)):
        d = xday[k]
        if d < n and locked[d, j[k]]:
            dd = d
            while dd < min(n - 1, li[j[k]]) and (locked[dd, j[k]] or not np.isfinite(O[dd, j[k]])):
                dd += 1
            xday[k] = dd; xpx[k] = float(O[dd, j[k]]) if np.isfinite(O[dd, j[k]]) else float(D["Cf"][dd, j[k]]); nlock += 1
    keep = ~(over & is_merg) if merger_mode == "primary" else np.ones(len(i), bool)
    px0 = t0.px0.values.astype(float); risk = t0.risk.values.astype(float)
    if cost_entry == "open":
        o1 = O[np.minimum(i + 1, n - 1), j]; st = W["stop"][i, j]; ok = np.isfinite(o1) & (o1 > 0)
        px0 = np.where(ok, o1, np.nan); risk = np.where(ok & (o1 > st), 1 - st / o1, 0.01); xpx = np.where(ok & (o1 <= st), o1, xpx); i = i + 1
    c = pd.DataFrame({"i": i, "j": j, "px0": px0, "risk": risk, "xday": np.maximum(xday, i + 1), "xpx": xpx})[keep]
    c = c[np.isfinite(c.px0) & (c.px0 > 0)].reset_index(drop=True)
    c["R"] = (c.xpx / c.px0 - 1 - CB - CS) / c.risk
    c["rs"] = np.nan_to_num(D["RS"][np.minimum(c.i.values, n - 1), c.j.values], nan=-1)
    return c, dict(merger_open=int((over & is_merg).sum()), delist_open=int((over & delisted_j[j]).sum()), locked=nlock)


# ── 시뮬 (연구 2 overlay·노출 기록 포함)
RET = np.vstack([np.full((1, m), np.nan), C[1:] / C[:-1] - 1]).astype("float32")


def sim2(c, order, start, end, rp=0.005, cost=1.0, rng=None, mult=None, corr_h3=False, place=None, record=False, day_cap=None, dd_brake=None, mode="risk", keylog=None):
    """mult: (n, m) 배수 배열(H1·H2·D3) · corr_h3: H3 상관 쏠림 · place: (rng, dict group->p) placebo · day_cap(D1) · dd_brake(D2)."""
    Cf = D["Cf"]; cb, cs = CB * cost, CS * cost
    CJ, CPX, CRK, CXD, CXP, CR = c.j.values, c.px0.values, c.risk.values, c.xday.values.astype(int), c.xpx.values, c.R.values
    dr = {d: g.index.values for d, g in c.groupby("i")}
    cash, pos, exits = 1.0, {}, {}
    eq = np.empty(end - start + 1); expo = np.empty(end - start + 1); peak = 1.0; lifts = []; ent = []; used = []
    for d in range(start, end + 1):
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - cs); del pos[j]
        mv = 0.0
        for j, p in pos.items():
            mv += p[0] * Cf[d, j]
        E_ = cash + mv; peak = max(peak, E_)
        rows = order.get(d) if order is not None else (rng.permutation(dr[d]) if d in dr else None)
        free = maxpos = 10
        free = maxpos - len(pos); newn = 0
        if rows is not None:
            avail = [r for r in rows if CJ[r] not in pos]
            if record and len(avail) > free > 0:
                sel = avail[:free]; lifts.append((d, free, float(np.mean(CR[sel]) - np.mean(CR[avail]))))
            for r in avail:
                if free <= 0 or (day_cap is not None and newn >= day_cap):
                    break
                j = CJ[r]
                if j in pos:
                    continue
                rr = rp
                if dd_brake is not None and E_ < peak * (1 - dd_brake[0]):
                    rr = rp * dd_brake[1]
                if mult is not None:
                    rr = rp * mult[d, j]
                if corr_h3 and len(pos) >= 3:
                    a = RET[max(d - 59, 1):d, j]; cnt = 0
                    for h in pos:
                        b = RET[max(d - 59, 1):d, h]; ok = np.isfinite(a) & np.isfinite(b)
                        if ok.sum() >= 50 and np.corrcoef(a[ok], b[ok])[0, 1] >= 0.70:
                            cnt += 1
                    if cnt >= 3:
                        rr = rp * 0.5
                if place is not None:
                    g_ = (dates[d][:4], bool(is_kq[j]))
                    if place[0].random() < place[1].get(g_, 0.0):
                        rr = rp * 0.5
                val = rr * E_ / CRK[r]
                if mode == "cash" and cash < val * (1 + cb):
                    continue
                cash -= val * (1 + cb); xd = int(CXD[r])
                pos[j] = (val / CPX[r], xd, CXP[r], val * CRK[r]); exits.setdefault(xd, []).append(j); free -= 1; newn += 1; used.append(rr)
                if keylog is not None:
                    keylog.append((dates[d][:4], bool(is_kq[j]), rr < rp * 0.75))
        mv = 0.0; rk_amt = 0.0
        for j, p in pos.items():
            mv += p[0] * Cf[d, j]; rk_amt += p[3]
        eq[d - start] = cash + mv; expo[d - start] = rk_amt / eq[d - start] if eq[d - start] > 0 else 0
    return eq, expo, lifts, (float(np.mean(used)) if used else rp)


def metr(eq):
    return RT.metr(eq)


def orders_rs(c):
    o = np.lexsort((c.j.values, -c.rs.values, c.i.values)); od = {}
    for r in o:
        od.setdefault(int(c.i.values[r]), []).append(r)
    return {d: np.array(v) for d, v in od.items()}


S_ALL, E_ALL = RT.sidx(W, "2015-07-01"), n - 1
CAND = {}


def job_random(args):
    key, s, e, seeds, cost = args
    c = CAND[key]; out = []
    for sd in seeds:
        eq, _, _, _ = sim2(c, None, s, e, cost=cost, rng=np.random.default_rng(sd))
        mt = metr(eq); yr = RT.yearly(W, eq, s)
        out.append((mt["cagr"], mt["mar"], mt["mdd"], mt["sharpe"], yr.to_dict()))
    return out


def job_placebo(args):
    key, probs, seeds = args
    c = CAND[key]; od = orders_rs(c); out = []
    for sd in seeds:
        eq, _, _, _ = sim2(c, od, S_ALL, E_ALL, place=(np.random.default_rng(sd), probs)); out.append(metr(eq)["mar"])
    return out


def lift_stats(lifts, nb=10000, seed=1):
    Lf = pd.DataFrame(lifts, columns=["d", "K", "lift"])
    tl = (Lf.K * Lf.lift).sum() / Lf.K.sum()
    per = {}
    for lab, a, b in PER4:
        g = Lf[(dates[Lf.d.values] >= a) & (dates[Lf.d.values] <= b)]; per[lab] = (g.K * g.lift).sum() / max(1, g.K.sum())
    num = np.zeros(n); den = np.zeros(n); num[Lf.d.values] = Lf.K * Lf.lift; den[Lf.d.values] = Lf.K
    num, den = num[S_ALL:], den[S_ALL:]; nn = len(num); g = np.random.default_rng(seed); ar = np.arange(nn); bs = []
    for _ in range(nb // 250):
        jump = g.random((250, nn)) < 1 / 20; jump[:, 0] = True; newp = g.integers(0, nn, (250, nn))
        lix = np.maximum.accumulate(np.where(jump, ar, 0), axis=1); ix = (np.take_along_axis(newp, lix, axis=1) + (ar - lix)) % nn
        bs.append(num[ix].sum(1) / np.maximum(den[ix].sum(1), 1))
    lo, hi = np.percentile(np.concatenate(bs), [2.5, 97.5])
    return tl, lo, hi, per


if __name__ == "__main__":
    for key, mm_, ce in (("orig", None, None), ("primary", "primary", "close"), ("forced", "forced", "close"), ("open", "primary", "open")):
        if key == "orig":
            W0 = RT.build("orig"); CAND[key] = None; WORIG = W0
        else:
            c, info = cand_variant(mm_, ce); CAND[key] = c
            if key == "primary":
                M.log(f"정정판 후보 {len(c)} · 합병형 상폐로 폐지까지 보유된 거래 {info['merger_open']}건(기본에선 제외) · 상폐까지 보유 전체 {info['delist_open']} · 하한가 잠김 이월 {info['locked']}건")
    CAND["primary_cost06"] = CAND["primary"]
    pr = CAND["primary"]; odp = orders_rs(pr)
    G = [seed_of(GPT_HASH, j) for j in range(10000)]; Cl = [seed_of(CL_HASH, j) for j in range(2000)]
    jobs = [("primary", S_ALL, E_ALL, G[k:k + 250], 1.0) for k in range(0, 10000, 250)] + [("primary", S_ALL, E_ALL, G[k:k + 250], 2.0) for k in range(0, 10000, 250)]
    jobs += [("primary", RT.sidx(W, "2015-07-01"), RT.eidx(W, "2022-12-31"), Cl[k:k + 250], 1.0) for k in range(0, 2000, 250)]
    jobs += [("primary", S_ALL, E_ALL, Cl[k:k + 250], 5 / 3) for k in range(0, 2000, 250)]
    jobs += [("open", S_ALL, E_ALL, Cl[k:k + 250], 1.0) for k in range(0, 2000, 250)]
    with Pool(2) as pool:
        res = pool.map(job_random, jobs)
    R_ = {}
    for (key, s, e, _, cost), r in zip(jobs, res):
        R_.setdefault((key, s, e, cost), []).extend(r)
    M.log("무작위 끝")

    # ═════ 연구 1
    M.log("=" * 150)
    M.log("연구 1 — RS 순 레드팀 (정정판 = 상폐 625 포함·RS 다시 계산·잠김 이월·정리매매 제한 없음 · 기본 = 합병형 상폐 미추적 거래 제외)")
    def pct(arr, v):
        return 100 * np.mean(np.array(arr) < v)
    rnd = R_[("primary", S_ALL, E_ALL, 1.0)]; rc = np.array([x[0] for x in rnd]); rmar = np.array([x[1] for x in rnd]); rmdd = np.array([x[2] for x in rnd]); rsh = np.array([x[3] for x in rnd])
    eq, ex, lifts, _ = sim2(pr, odp, S_ALL, E_ALL, record=True); mt = metr(eq)
    tl, lo, hi, per = lift_stats(lifts)
    M.log(f"   RS 순: 연 {mt['cagr']:+.1f}% 낙폭 {mt['mdd']:.0f}% MAR {mt['mar']:.2f} 샤프 {mt['sharpe']:.2f} | 무작위 10,000 백분위: 연수익 {pct(rc, mt['cagr']):.1f} · MAR {pct(rmar, mt['mar']):.1f} · 낙폭 {pct(rmdd, mt['mdd']):.1f} · 샤프 {pct(rsh, mt['sharpe']):.1f}"
          f" | 무작위 중앙 연 {np.median(rc):+.1f}% (5~95% {np.percentile(rc, 5):+.1f}~{np.percentile(rc, 95):+.1f})")
    M.log(f"   TopKLift {tl:+.3f}R [95% {lo:+.3f}, {hi:+.3f}] · 기간별 " + " / ".join(f"{k} {v:+.3f}" for k, v in per.items()) + "  (원래 데이터 +0.270)")
    eqo, _ = RT.sim(WORIG, WORIG["cand"], RT.orders(WORIG["cand"]), RT.sidx(WORIG, "2015-07-01"), WORIG["n"] - 1); mo = metr(eqo)
    M.log(f"   참고: 원래 데이터 RS 순 연 {mo['cagr']:+.1f}% 낙폭 {mo['mdd']:.0f}%")
    fc = CAND["forced"]; eqf, _, liff, _ = sim2(fc, orders_rs(fc), S_ALL, E_ALL, record=True); mf = metr(eqf); tlf = lift_stats(liff, nb=2000)
    M.log(f"   민감도(합병형 상폐 강제청산): RS 순 연 {mf['cagr']:+.1f}% 낙폭 {mf['mdd']:.0f}% TopKLift {tlf[0]:+.3f}R")
    r6 = R_[("primary", S_ALL, E_ALL, 2.0)]; eq6, _, _, _ = sim2(pr, odp, S_ALL, E_ALL, cost=2.0); m6 = metr(eq6)
    M.log(f"   비용 0.6%: RS 연 {m6['cagr']:+.1f}% MAR {m6['mar']:.2f} → 무작위(0.6%) 백분위 연수익 {pct([x[0] for x in r6], m6['cagr']):.1f} · MAR {pct([x[1] for x in r6], m6['mar']):.1f}")
    # GPT 판정
    pos4 = sum(v > 0 for v in per.values()); worst = min(per.values())
    strong = tl >= 0.135 and lo > 0 and pct(rc, mt["cagr"]) >= 99 and pct(rmar, mt["mar"]) >= 99 and pos4 >= 3 and worst > -0.15 and pct([x[0] for x in r6], m6["cagr"]) >= 95 and pct([x[1] for x in r6], m6["mar"]) >= 95
    biased = tl <= 0 or hi <= 0 or (pct(rc, mt["cagr"]) < 90 and pct(rmar, mt["mar"]) < 90) or (tl < 0.0675 and lo <= 0) or pos4 <= 1
    M.log(f"   GPT 판정: {'강하게 통과' if strong else ('편향 가능성 높음' if biased else '부분 통과/불확실')}")
    # Claude 판정
    ra = R_[("primary", RT.sidx(W, "2015-07-01"), RT.eidx(W, "2022-12-31"), 1.0)]
    eqa, _, _, _ = sim2(pr, odp, RT.sidx(W, "2015-07-01"), RT.eidx(W, "2022-12-31")); ma_ = metr(eqa)
    yr_rs = RT.yearly(W, eq, S_ALL); yrs = sorted(yr_rs.index)
    med_y = {y: np.median([x[4].get(y, np.nan) for x in rnd]) for y in yrs}
    win_y = sum(yr_rs[y] > med_y[y] for y in yrs if y >= 2015)
    r05 = R_[("primary", S_ALL, E_ALL, 5 / 3)]; eq05, _, _, _ = sim2(pr, odp, S_ALL, E_ALL, cost=5 / 3); m05 = metr(eq05)
    ro = R_[("open", S_ALL, E_ALL, 1.0)]; oc = CAND["open"]; eqop, _, _, _ = sim2(oc, orders_rs(oc), S_ALL, E_ALL); mop = metr(eqop)
    M.log(f"   A 2015.07~22(따로 시작): RS 연 {ma_['cagr']:+.1f}% → 무작위 2,000 백분위 {pct([x[0] for x in ra], ma_['cagr']):.1f}")
    M.log(f"   연도별 RS > 무작위 중앙: {win_y}/{len([y for y in yrs if y >= 2015])}년 · " + " ".join(f"{y} {100 * yr_rs[y]:+.0f}%/{100 * med_y[y]:+.0f}%" for y in yrs))
    M.log(f"   비용 0.5%: {pct([x[0] for x in r05], m05['cagr']):.1f}백분위 · 다음 날 시가 진입: RS 연 {mop['cagr']:+.1f}% → {pct([x[0] for x in ro], mop['cagr']):.1f}백분위")
    cl_ok = pct(rc, mt["cagr"]) >= 95 and pct([x[0] for x in ra], ma_["cagr"]) >= 95 and (mt["cagr"] - np.median(rc)) >= 5 and win_y >= 8 and pct([x[0] for x in r05], m05["cagr"]) >= 90 and pct([x[0] for x in ro], mop["cagr"]) >= 90
    M.log(f"   Claude 판정: {'통과' if cl_ok else '실패'} (전체 95↑ · A 95↑ · 무작위 중앙 +5%p↑ · 8년↑ · 비용 0.5%·다음 시가 90↑)")
    # 참고(Claude 견고성): AI장 수익 상위 5종목 제외 · 2025~26 제외
    led = pd.DataFrame({"j": pr.j, "i": pr.i, "R": pr.R}); top5 = led[dates[led.i.values] >= "2025-06-01"].groupby("j").R.sum().sort_values().index[-5:]
    p5 = pr[~pr.j.isin(top5)].reset_index(drop=True); m5 = metr(sim2(p5, orders_rs(p5), S_ALL, E_ALL)[0])
    mx = metr(eq[:RT.eidx(W, "2024-12-31") - S_ALL + 1])
    M.log(f"   참고: AI장 상위 5종목 제외 RS 연 {m5['cagr']:+.1f}% · 2025~26 제외(2015.07~2024) RS 연 {mx['cagr']:+.1f}% 낙폭 {mx['mdd']:.0f}%")

    # ═════ 연구 2
    M.log("=" * 150)
    M.log("연구 2 — 낙폭 overlay (정정판 기본 · RS 순 · K10 · 0.5%) · 노출 = 열린 포지션 초기 위험 합 / 자본")
    eqB, exB, _, _ = sim2(pr, odp, S_ALL, E_ALL); mB = metr(eqB)
    def per_mar(eqx):
        return [metr(eqx[RT.sidx(W, a) - S_ALL:RT.eidx(W, b) - S_ALL + 1])["mar"] for _, a, b in PER4]
    pmB = per_mar(eqB)
    M.log(f"   B0: 연 {mB['cagr']:+.1f}% 낙폭 {mB['mdd']:.0f}% MAR {mB['mar']:.2f} · 평균 노출 {100 * exB.mean():.2f}% · 기간별 MAR " + " / ".join(f"{x:.2f}" for x in pmB))
    # 시장별 변동성·폭 (GPT H1·H2)
    idx = pd.read_csv("/home/junp/tmp_claude/kr_index_daily.csv", index_col=0, parse_dates=True); idx.index = idx.index.date
    idx = idx[~pd.Index(idx.index).duplicated()].reindex(D["dates"]).ffill()
    def h1_mult():
        out = np.ones((n, m), dtype="float32")
        for sym, sel in (("^KS11", ~is_kq), ("^KQ11", is_kq)):
            r = pd.Series(idx[sym].values).pct_change(); rv = r.rolling(20).std() * np.sqrt(252)
            rv1 = rv.shift(1); p80 = rv.shift(2).rolling(756, min_periods=756).quantile(0.80)
            hot = (rv1 > p80).values
            out[np.ix_(hot, np.nonzero(sel)[0])] = 0.5
        return out
    def h2_mult():
        out = np.ones((n, m), dtype="float32"); e20 = M.ema(C, 20)
        for sel in (~is_kq, is_kq):
            lq = D["liq"] & sel[None, :]
            with np.errstate(all="ignore"):
                br = pd.Series(np.nanmean(np.where(lq, C > e20, np.nan), axis=1))
            b1 = br.shift(1); p30 = br.shift(2).rolling(756, min_periods=756).quantile(0.30)
            weak = (b1 < p30).values
            out[np.ix_(weak, np.nonzero(sel)[0])] = 0.5
        return out
    M1, M2 = h1_mult(), h2_mult()
    D3 = RT.market_vol_scale(W); M3 = np.repeat(D3[:, None], m, axis=1).astype("float32")
    HYP = {"GPT H1 고변동성": dict(mult=M1), "GPT H2 약한 폭": dict(mult=M2), "GPT H3 상관 쏠림": dict(corr_h3=True),
           "Claude D1 하루 신규 3": dict(day_cap=3), "Claude D2 낙폭 브레이크": dict(dd_brake=(0.15, 0.5)), "Claude D3 시장 변동성 맞춤": dict(mult=M3)}
    out2 = {}
    for name, kw in HYP.items():
        kl = []
        eqH, exH, _, _ = sim2(pr, odp, S_ALL, E_ALL, keylog=kl, **kw); mH = metr(eqH)
        # 같은 평균 노출 대조: 일정 위험 rp*를 비례 조정 3번
        rp_ = 0.005 * exH.mean() / exB.mean()
        for _ in range(3):
            eqc, exc, _, _ = sim2(pr, odp, S_ALL, E_ALL, rp=rp_); rp_ *= exH.mean() / max(exc.mean(), 1e-9)
        eqc, exc, _, _ = sim2(pr, odp, S_ALL, E_ALL, rp=rp_); mc = metr(eqc)
        eq06, _, _, _ = sim2(pr, odp, S_ALL, E_ALL, cost=2.0, **kw); eqB06, _, _, _ = sim2(pr, odp, S_ALL, E_ALL, cost=2.0)
        m06, mB06 = metr(eq06), metr(eqB06)
        kl = pd.DataFrame(kl, columns=["y", "kq", "thr"]); probs = kl.groupby(["y", "kq"]).thr.mean().to_dict()
        out2[name] = dict(mH=mH, mc=mc, exH=exH.mean(), exc=exc.mean(), pm=per_mar(eqH), m06=m06, mB06=mB06, probs=probs, thr=float(kl.thr.mean()), eqH=eqH)
        M.log(f"   {name:22s} 연 {mH['cagr']:+.1f}% 낙폭 {mH['mdd']:.0f}% MAR {mH['mar']:.2f} · 노출 {100 * exH.mean():.2f}% (줄인 진입 {100 * kl.thr.mean():.0f}%) | 같은 노출 대조 연 {mc['cagr']:+.1f}% 낙폭 {mc['mdd']:.0f}% MAR {mc['mar']:.2f}"
              f" | 기간별 MAR " + " / ".join(f"{x:.2f}" for x in out2[name]["pm"]) + f" | 비용0.6% MAR {m06['mar']:.2f} vs B0 {mB06['mar']:.2f}")
    # placebo (GPT): 같은 연도×시장 안 같은 비율로 무작위 절반 위험
    pjobs = []
    for k_, name in enumerate([x for x in HYP if x.startswith("GPT")]):
        P = [seed_of(GPT_HASH, 100000 * (k_ + 1) + j) for j in range(10000)]
        pjobs += [(name, out2[name]["probs"], P[q:q + 250]) for q in range(0, 10000, 250)]
    CAND_P = {}
    with Pool(2) as pool:
        pres = pool.map(job_placebo, [("primary", pr_, sd) for (_, pr_, sd) in pjobs])
    PL = {}
    for (name, _, _), r in zip(pjobs, pres):
        PL.setdefault(name, []).extend(r)
    pv = {nm: (1 + np.sum(np.array(PL[nm]) >= out2[nm]["mH"]["mar"])) / (1 + len(PL[nm])) for nm in PL}
    ps = sorted((v, k) for k, v in pv.items()); holm = {}; run = 0
    for r_, (p, k) in enumerate(ps):
        run = max(run, min(1, p * (len(ps) - r_))); holm[k] = run
    M.log("   GPT 판정:")
    for nm in [x for x in HYP if x.startswith("GPT")]:
        o = out2[nm]; mH, mc = o["mH"], o["mc"]
        cond = [mH["cagr"] >= 0.9 * mB["cagr"], abs(mH["mdd"]) <= 0.8 * abs(mB["mdd"]), mH["mar"] >= 1.25 * mB["mar"], mH["mar"] >= 1.10 * mc["mar"], mH["mdd"] - mc["mdd"] >= 5,
                pct(PL[nm], mH["mar"]) >= 95, holm[nm] < 0.05, sum(a > b for a, b in zip(o["pm"], pmB)) >= 3, o["m06"]["mar"] >= o["mB06"]["mar"]]
        lab = ["CAGR≥90%", "MDD 20%↓", "MAR+25%", "대조 MAR+10%", "대조 MDD 5%p", "placebo 95", "Holm", "4기간 중 3", "비용0.6%"]
        M.log(f"     {nm:20s} placebo 백분위 {pct(PL[nm], mH['mar']):.1f} · Holm p {holm[nm]:.3f} | " + " ".join(f"{l} {'✅' if c_ else '⛔'}" for l, c_ in zip(lab, cond)) + f" → {'통과(V1.1 shadow 후보)' if all(cond) else '기각'}")
    # Claude 판정 (A·B·C 따로 시작)
    M.log("   Claude 판정 (전체·A 낙폭 5%p↑ 개선 · MAR 1.1배↑ · 같은 노출 대조보다 높음(D2·D3) · B·C MAR 0.9배↑ · 비용 0.5% 방향):")
    def run_per(kw, a, b, cost=1.0):
        return metr(sim2(pr, odp, RT.sidx(W, a), RT.eidx(W, b), cost=cost, **kw)[0])
    base_p = {lab: run_per({}, a, b) for lab, a, b in PER3}
    for nm in [x for x in HYP if x.startswith("Claude")]:
        kw = HYP[nm]; o = out2[nm]; pp = {lab: run_per(kw, a, b) for lab, a, b in PER3}
        b05 = metr(sim2(pr, odp, S_ALL, E_ALL, cost=5 / 3)[0]); h05 = metr(sim2(pr, odp, S_ALL, E_ALL, cost=5 / 3, **kw)[0])
        c1 = (o["mH"]["mdd"] - mB["mdd"] >= 5) and (pp["A 2015.07~22"]["mdd"] - base_p["A 2015.07~22"]["mdd"] >= 5)
        c2 = o["mH"]["mar"] >= 1.1 * mB["mar"] and pp["A 2015.07~22"]["mar"] >= 1.1 * base_p["A 2015.07~22"]["mar"] and ("D1" in nm or o["mH"]["mar"] > o["mc"]["mar"])
        c3 = all(pp[l]["mar"] >= 0.9 * base_p[l]["mar"] for l in ("B 2023~25.05", "C 2025.06~"))
        c4 = (h05["mdd"] >= b05["mdd"]) and (h05["mar"] >= b05["mar"])
        M.log(f"     {nm:22s} A: 연 {pp['A 2015.07~22']['cagr']:+.1f}% 낙폭 {pp['A 2015.07~22']['mdd']:.0f}% MAR {pp['A 2015.07~22']['mar']:.2f} (B0 {base_p['A 2015.07~22']['mar']:.2f}) · B MAR {pp['B 2023~25.05']['mar']:.2f} ({base_p['B 2023~25.05']['mar']:.2f}) · C MAR {pp['C 2025.06~']['mar']:.2f} ({base_p['C 2025.06~']['mar']:.2f})"
              f" | ①{'✅' if c1 else '⛔'} ②{'✅' if c2 else '⛔'} ③{'✅' if c3 else '⛔'} ④{'✅' if c4 else '⛔'} → {'통과' if c1 and c2 and c3 and c4 else '기각'}")
