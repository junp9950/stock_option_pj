"""GPT 마무리 검토의 감사 항목 (2026-10-10 KST) — 새 전략 연구 아님, 데이터·엔진 점검.
1) 정리매매 기간 추정(마지막 거래정지 뒤 짧은 재개 구간, 없으면 실패형은 마지막 7거래일) · 그 안 신규 S0 신호/Top10 진입 수 · 제외 후 RS 재계산
2) 합병형 4건 = 강제청산을 기본으로
3) AI장 TopKLift -0.07(원래 데이터) → +0.217(정정판) 원인: 같은 엔진으로 두 데이터 비교 · 후보 Jaccard · Top10 Jaccard · 공통 후보 RS 순위 상관 · 상폐 종목이 Top10에 들어간 수 · 거래소별 TopKLift
4) 다음 날 시가 +33.7% 분해: N0 종가 · N1 슬롯 예약 후 시가 · N2 같은 수량 시가 · N3 시가 엔진(RS는 신호 날) · N3x 예전 코드(RS를 진입일 종가로 = 미래 정보)
5) 실제 거래소로 GPT H1·H2 다시
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
src = open("/home/junp/tmp_claude/redteam_run.py").read().split('if __name__ == "__main__":')[0]
exec(src)                                     # W(정정판), D, cand_variant, sim2, metr, orders_rs, lift_stats, PER4, codes, is_kq ...
from scipy.stats import spearmanr

# 실제 거래소 (상폐 종목: KIND 시장별 목록 · 코넥스·불명은 코스닥 쪽)
km = pd.read_csv("/home/junp/tmp_claude/kind_delisting_market.csv", dtype={"code": str})
kmap = km.dropna(subset=["market"]).drop_duplicates("code", keep="last").set_index("code").market.to_dict()
for jj in range(n0, m):
    is_kq[jj] = kmap.get(codes[jj], "KOSDAQ") != "KOSPI"
M.log(f"상폐 종목 거래소: 코스피 {int((~is_kq[n0:]).sum())} · 코스닥/코넥스/불명 {int(is_kq[n0:].sum())}")

# ── 1) 정리매매 창 추정
reason = km.drop_duplicates("code", keep="last").set_index("code")["폐지사유"].to_dict()
fin = np.isfinite(C)
liq_win = np.zeros((n, m), bool); win_info = {"halt_seg": 0, "last7": 0, "none": 0}
for jj in range(n0, m):
    f = np.nonzero(fin[:, jj])[0]
    if not len(f):
        continue
    end = f[-1]; gaps = np.nonzero(np.diff(f) >= 6)[0]          # 5거래일 이상 거래 없음 = 정지
    seg_start = f[gaps[-1] + 1] if len(gaps) else None
    merger = any(k in str(reason.get(codes[jj], "")) for k in ("합병", "이전상장", "지주", "스팩", "기업인수목적", "주식교환", "주식이전", "포괄"))
    if seg_start is not None and (np.searchsorted(f, end) - np.searchsorted(f, seg_start) + 1) <= 10:
        liq_win[seg_start:end + 1, jj] = True; win_info["halt_seg"] += 1
    elif not merger:
        liq_win[f[max(len(f) - 7, 0)]:end + 1, jj] = True; win_info["last7"] += 1
    else:
        win_info["none"] += 1
E0 = W["E0"]
M.log(f"정리매매 창: 정지 뒤 짧은 재개 구간 {win_info['halt_seg']} · 실패형 마지막 7일 {win_info['last7']} · 합병형 등 없음 {win_info['none']} · 그 안 S0 신호 {int((E0 & liq_win).sum())}개")


def cand_fixed(drop_liq=True, entry="close", rs_day="signal"):
    """강제청산 기본 + 정리매매 창 신호 제외 + 잠김은 창 밖에서만."""
    c, info = cand_variant("forced", entry)
    if drop_liq:
        si = c.i.values - (1 if entry == "open" else 0)
        c = c[~liq_win[si, c.j.values]].reset_index(drop=True)
    if entry == "open" and rs_day == "signal":
        c["rs"] = np.nan_to_num(D["RS"][c.i.values - 1, c.j.values], nan=-1)
    return c


cf = cand_fixed()
od = orders_rs(cf)
eqF, _, lifF, _ = sim2(cf, od, S_ALL, E_ALL, record=True); mF = metr(eqF); tlF = lift_stats(lifF)
M.log("=" * 140)
M.log(f"1·2) 정리매매 창 신호 제외 + 합병형 강제청산: RS 순 연 {mF['cagr']:+.1f}% 낙폭 {mF['mdd']:.0f}% MAR {mF['mar']:.2f} · TopKLift {tlF[0]:+.3f}R [95% {tlF[1]:+.3f}, {tlF[2]:+.3f}] · "
      + " / ".join(f"{k} {v:+.3f}" for k, v in tlF[3].items()))
CAND["fixed"] = cf


def job_r(seeds):
    out = []
    for sd in seeds:
        eq, _, _, _ = sim2(CAND["fixed"], None, S_ALL, E_ALL, rng=np.random.default_rng(sd)); mt = metr(eq); out.append((mt["cagr"], mt["mar"]))
    return out


# ── 3) AI장 TopKLift 원인
def lifts_generic(c, Cf_, start, end, rs_col="rs"):
    o = np.lexsort((c.j.values, -c[rs_col].values, c.i.values)); od_ = {}
    for r in o:
        od_.setdefault(int(c.i.values[r]), []).append(r)
    CJ, CPX, CRK, CXD, CXP, CR = c.j.values, c.px0.values, c.risk.values, c.xday.values.astype(int), c.xpx.values, c.R.values
    cash, pos, exits, lif, sel_all = 1.0, {}, {}, [], []
    for d in range(start, end + 1):
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - CS); del pos[j]
        E_ = cash + sum(p[0] * Cf_[d, j] for j, p in pos.items())
        rows = od_.get(d)
        free = 10 - len(pos)
        if rows is not None:
            avail = [r for r in rows if CJ[r] not in pos]
            if len(avail) > free > 0:
                lif.append((d, free, float(np.mean(CR[avail[:free]]) - np.mean(CR[avail])), [CJ[r] for r in avail[:free]], [CJ[r] for r in avail]))
            for r in avail[:max(free, 0)]:
                val = 0.005 * E_ / CRK[r]; cash -= val * (1 + CB); xd = int(CXD[r])
                pos[CJ[r]] = (val / CPX[r], xd, CXP[r]); exits.setdefault(xd, []).append(CJ[r]); sel_all.append((d, CJ[r]))
    return lif, sel_all


WO = RT.build("orig"); co = WO["cand"]
a0, b0 = RT.sidx(W, "2025-06-01"), n - 1
lo_, so_ = lifts_generic(co, WO["D"]["Cf"], a0, b0)
lf_, sf_ = lifts_generic(cf, D["Cf"], a0, b0)
def tl(L):
    return sum(x[1] * x[2] for x in L) / max(1, sum(x[1] for x in L))
code_o = WO["D"]["codes"]
M.log("=" * 140)
M.log(f"3) AI장(2025.06~) 같은 엔진: 원래 데이터 TopKLift {tl(lo_):+.3f} (경합일 {len(lo_)}) · 정정판 {tl(lf_):+.3f} (경합일 {len(lf_)})")
ko = {(int(i), code_o[j]) for i, j in zip(co.i, co.j) if i >= a0}; kf = {(int(i), codes[j]) for i, j in zip(cf.i, cf.j) if i >= a0}
M.log(f"   후보(날짜·종목) Jaccard {len(ko & kf) / len(ko | kf):.3f} (원래 {len(ko)} · 정정판 {len(kf)} · 공통 {len(ko & kf)})")
selo = {(d, code_o[j]) for d, j in so_}; self_ = {(d, codes[j]) for d, j in sf_}
M.log(f"   실제로 산 것 Jaccard {len(selo & self_) / max(1, len(selo | self_)):.3f} · 정정판에서 산 것 중 상폐 종목 {sum(1 for d, j in sf_ if j >= n0)}건")
rso = {(int(i), code_o[j]): r for i, j, r in zip(co.i, co.j, co.rs)}; rsf = {(int(i), codes[j]): r for i, j, r in zip(cf.i, cf.j, cf.rs)}
com = sorted(ko & kf)
M.log(f"   공통 후보 RS 순위 상관(Spearman) {spearmanr([rso[k] for k in com], [rsf[k] for k in com])[0]:.3f} · 정정판 후보 수 대비 RS 평균 차 {np.mean([rsf[k] - rso[k] for k in com]):+.2f}")
for nm, sel in (("코스피", ~is_kq), ("코스닥", is_kq)):
    sub = [x for x in lf_ if all(sel[j] for j in x[4])]
    M.log(f"   정정판 {nm}만 후보인 경합일 TopKLift {tl(sub):+.3f} ({len(sub)}일)")
# 기간별 원래 데이터 (같은 엔진)
for lab, a, b in PER4:
    l1, _ = lifts_generic(co, WO["D"]["Cf"], RT.sidx(W, a), RT.eidx(W, b)); l2, _ = lifts_generic(cf, D["Cf"], RT.sidx(W, a), RT.eidx(W, b))
    M.log(f"   {lab}: 원래 {tl(l1):+.3f} · 정정판 {tl(l2):+.3f}  (기간마다 자본 다시 시작)")

# ── 4) 다음 날 시가 분해
M.log("=" * 140)
M.log("4) 다음 날 시가 분해 (정정판 · 정리매매 제외 · 강제청산)")


def sim_open(c_close, start, end, variant):
    """N0 종가 · N1 종가에 고르고 칸 예약 → 다음 날 시가 체결(크기는 시가 기준) · N2 같은 수량 · 반환 (자본, 체결 수, 시가≤손절 수)."""
    Cf_ = D["Cf"]; CJ, CPX, CRK, CXD, CXP = c_close.j.values, c_close.px0.values, c_close.risk.values, c_close.xday.values.astype(int), c_close.xpx.values
    st = W["stop"]
    o = np.lexsort((CJ, -c_close.rs.values, c_close.i.values)); od_ = {}
    for r in o:
        od_.setdefault(int(c_close.i.values[r]), []).append(r)
    cash, pos, exits, pend = 1.0, {}, {}, {}
    eq = np.empty(end - start + 1); nent = 0; under = 0
    for d in range(start, end + 1):
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - CS); del pos[j]
        for j, (r, sh_fixed, valE) in list(pend.items()):        # 어제 고른 것 오늘 시가 체결
            o1 = O[d, j]; s_ = st[d - 1, j]
            if not np.isfinite(o1) or o1 <= 0:
                del pend[j]; continue
            if variant == "N2":
                sh = sh_fixed
            else:
                rk = 1 - s_ / o1 if o1 > s_ else 0.01; sh = 0.005 * valE / rk / o1
            cash -= sh * o1 * (1 + CB); nent += 1
            if o1 <= s_:                                         # 시가가 이미 손절 아래 → 바로 손절
                cash += sh * o1 * (1 - CS); under += 1; del pend[j]; continue
            xd = int(max(CXD[r], d)); pos[j] = (sh, xd if xd > d else d + 1, CXP[r]); exits.setdefault(pos[j][1], []).append(j); del pend[j]
        E_ = cash + sum(p[0] * Cf_[d, j] for j, p in pos.items())
        rows = od_.get(d)
        if rows is not None:
            free = 10 - len(pos) - len(pend)
            for r in rows:
                if free <= 0:
                    break
                j = CJ[r]
                if j in pos or j in pend:
                    continue
                if variant == "N0":
                    val = 0.005 * E_ / CRK[r]; cash -= val * (1 + CB); xd = int(CXD[r]); pos[j] = (val / CPX[r], xd, CXP[r]); exits.setdefault(xd, []).append(j); nent += 1
                else:
                    pend[j] = (r, 0.005 * E_ / CRK[r] / CPX[r], E_)
                free -= 1
        eq[d - start] = cash + sum(p[0] * Cf_[d, j] for j, p in pos.items())
    return eq, nent, under


for v in ("N0", "N1", "N2"):
    eqv, ne, un = sim_open(cf, S_ALL, E_ALL, v); mv = metr(eqv)
    M.log(f"   {v}: 연 {mv['cagr']:+.1f}% 낙폭 {mv['mdd']:.0f}% MAR {mv['mar']:.2f} · 체결 {ne}건 · 시가가 이미 손절 아래 {un}건")
c3 = cand_fixed(entry="open", rs_day="signal"); e3, x3, _, _ = sim2(c3, orders_rs(c3), S_ALL, E_ALL); m3 = metr(e3)
c3x = cand_fixed(entry="open", rs_day="entry"); e3x, _, _, _ = sim2(c3x, orders_rs(c3x), S_ALL, E_ALL); m3x = metr(e3x)
M.log(f"   N3 시가 엔진(같은 시가에 판 칸 바로 재사용 · RS는 신호 날): 연 {m3['cagr']:+.1f}% 낙폭 {m3['mdd']:.0f}% MAR {m3['mar']:.2f}")
M.log(f"   N3x 예전 코드(RS를 진입일 종가로 = 미래 정보): 연 {m3x['cagr']:+.1f}% 낙폭 {m3x['mdd']:.0f}% MAR {m3x['mar']:.2f}")
und = int(((O[np.minimum(cf.i.values + 1, n - 1), cf.j.values]) <= W["stop"][cf.i.values, cf.j.values]).sum())
M.log(f"   후보 중 다음 날 시가가 이미 손절가 아래인 경우 {und}건 / {len(cf)}")

# ── 5) 실제 거래소로 GPT H1·H2 (기본 수치만)
M.log("=" * 140)
idx = pd.read_csv("/home/junp/tmp_claude/kr_index_daily.csv", index_col=0, parse_dates=True); idx.index = idx.index.date
idx = idx[~pd.Index(idx.index).duplicated()].reindex(D["dates"]).ffill()
def mult_h1():
    out = np.ones((n, m), dtype="float32")
    for sym, sel in (("^KS11", ~is_kq), ("^KQ11", is_kq)):
        r = pd.Series(idx[sym].values).pct_change(); rv = r.rolling(20).std() * np.sqrt(252)
        hot = (rv.shift(1) > rv.shift(2).rolling(756, min_periods=756).quantile(0.80)).values
        out[np.ix_(hot, np.nonzero(sel)[0])] = 0.5
    return out
def mult_h2():
    out = np.ones((n, m), dtype="float32"); e20 = M.ema(C, 20)
    for sel in (~is_kq, is_kq):
        lq = D["liq"] & sel[None, :]
        with np.errstate(all="ignore"):
            br = pd.Series(np.nanmean(np.where(lq, C > e20, np.nan), axis=1))
        weak = (br.shift(1) < br.shift(2).rolling(756, min_periods=756).quantile(0.30)).values
        out[np.ix_(weak, np.nonzero(sel)[0])] = 0.5
    return out
for nm, mlt in (("GPT H1 고변동성", mult_h1()), ("GPT H2 약한 폭", mult_h2())):
    eh, exh, _, _ = sim2(cf, od, S_ALL, E_ALL, mult=mlt); mh = metr(eh)
    M.log(f"5) 실제 거래소로 {nm}: 연 {mh['cagr']:+.1f}% 낙폭 {mh['mdd']:.0f}% MAR {mh['mar']:.2f} (B0 {mF['cagr']:+.1f}%/{mF['mdd']:.0f}%/{mF['mar']:.2f})")

if __name__ == "__main__":
    G = [seed_of(GPT_HASH, j) for j in range(10000)]
    with Pool(2) as pool:
        rr = [x for part in pool.map(job_r, [G[k:k + 250] for k in range(0, 10000, 250)]) for x in part]
    rc = np.array([x[0] for x in rr]); rm = np.array([x[1] for x in rr])
    M.log("=" * 140)
    M.log(f"1·2) 무작위 10,000(같은 seed) 대비: 연수익 {100 * np.mean(rc < mF['cagr']):.1f}백분위 · MAR {100 * np.mean(rm < mF['mar']):.1f}백분위 · 무작위 중앙 {np.median(rc):+.1f}%")
