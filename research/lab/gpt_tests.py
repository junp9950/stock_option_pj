"""GPT 교차검증 1단계 답변의 검증 설계를 그대로 (2026-10-10 KST). GPT는 우리 숫자를 보기 전에 기준을 정했다 → 정의를 바꾸지 않는다.
TEST 1 (veto audit): 과열 필터 A(20일선 +15%) · B(당일 +8%) · C(손절폭 8% 초과)를 하나씩만 풀어 "그 필터 하나 때문에 막힌 신호"를 BASE와 비교.
        같은 청산(산 날 저가 -1% 손절 · 21일선 아래 종가 → 다음 날 시가). 지표: E[R] · 중앙 R · 상위 5% R · CVaR(최악 5% 평균 R) · MFE · MAE · 보유일.
        장세 = Normal / StrongTrend (GPT 정의, 과거 3년 이동 백분위, t-1까지만):
          지수(코스피 종목은 코스피, 코스닥은 코스닥) > MA120 · MA120 > 20일 전 MA120
          · 60일선 위 종목 비율 > 과거 3년 60백분위 · 52주 고가 95% 이상 종목 비율 > 과거 3년 60백분위
          · 분산(종목 20일 수익 − 지수 20일 수익 절대값의 중앙) > 과거 3년 중앙 · 지수 20일 실현변동성 < 과거 3년 90백분위
LOOKAHEAD: BASE를 종가 진입 vs 다음 날 시가 진입.
실행: cd /home/junp/stock_option_pj && set -a && . ./.env && set +a && nice -n 10 .venv/bin/python /home/junp/tmp_claude/gpt_tests.py
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
import ma_lab as M
from sqlalchemy import text
from backend.db.database import SessionLocal

rng = np.random.default_rng(17)
COST = M.COST_BUY + M.COST_SELL
D = M.prep(M.load())
O, H, L, C, V, T = (D[k] for k in "ohlcvt")
n, m = D["n"], D["m"]
dates = np.array([str(d) for d in D["dates"]])
Cd, Hd, Vd, Td = pd.DataFrame(C), pd.DataFrame(H), pd.DataFrame(V), pd.DataFrame(T)
liq, RS, chg = D["liq"], D["RS"], D["chg"]
Bm = D["bull"][:, None]

# ── 우리 매수 (ma_lab.our_buy와 같은 계산, 필터 값만 바꿀 수 있게)
e5, e10, e20, e60 = (M.ema(C, k) for k in (5, 10, 20, 60))
trend = (C > e20) & (e20 > e60) & liq
with np.errstate(invalid="ignore", divide="ignore"):
    vx = (Vd / Vd.shift(1).rolling(20).mean()).values
    ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
    F0 = (Cd / Hd.rolling(60).max() - 1).values >= -0.05
    F1 = (RS >= 70) & (RS < 95)
    F2 = (vx >= 0.7) & (vx < 3)
    F3 = (C - L) / np.where(H - L == 0, np.nan, H - L) >= 0.7
    ext = (Cd / Cd.rolling(20).mean() - 1).values
    F6 = (ehi - elo) / C < 0.06
    stop = (L * 0.99).astype("float32"); risk = 1 - stop / C
    tvx = (Td / Td.rolling(20).mean().shift(1)).values
    gap_prev = np.vstack([np.full((1, m), np.nan), ((ehi - elo) / C)[:-1]])
    hi10p = Hd.shift(1).rolling(10).max().values
    up60 = (C > e60) & (e20 > e60)
b_ = lambda x: np.nan_to_num(np.asarray(x, dtype=float)).astype(bool)
F0, F1, F2, F3, F6 = b_(F0), b_(F1), b_(F2), b_(F3), b_(F6)


def buy(ext_max=0.15, day_max=0.08, risk_max=0.08):
    with np.errstate(invalid="ignore"):
        F4 = b_((chg >= 0) & (chg < day_max)); F5 = b_(ext < ext_max)
        score = F0.astype(np.int8) + F1 + F2 + F3 + F4 + F5 + F6
        base = Bm & trend & F1 & b_(risk <= risk_max) & b_(risk > 0)
        brk = b_((gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < day_max) & (tvx >= 1.5)) & liq
        return (base & (score >= 6)) | (base & brk & up60) | (base & (score == 5) & ~F5 & ~F6 & F0 & F2 & F3 & F4)


E0 = buy()
E_ref, _ = M.our_buy(D)
assert int(E0.sum()) == int(E_ref.sum()), (int(E0.sum()), int(E_ref.sum()))
M.log(f"BASE 신호 {int(E0.sum())}개 (ma_lab.our_buy와 같음 확인)")

# ── 장세 (GPT 정의)
idx = pd.read_csv("/home/junp/tmp_claude/kr_index_daily.csv", index_col=0, parse_dates=True)
idx.index = idx.index.date
idx = idx[~pd.Index(idx.index).duplicated()].reindex(D["dates"]).ffill()
db = SessionLocal()
mk = dict(db.execute(text("select code, market from stocks")).all())
is_kq = np.array([("KOSDAQ" in (mk.get(c) or "KOSDAQ")) for c in D["codes"]])
W = 735                                      # 과거 3년


def past_pct(x, q, minp=250):
    """t일 값과 비교할 기준: t-1까지 과거 3년 백분위."""
    s = pd.Series(x)
    return s.shift(1).rolling(W, min_periods=minp).quantile(q).values


ind = {}
for sym in ("^KS11", "^KQ11"):
    p = idx[sym].values.astype(float)
    ma120 = pd.Series(p).rolling(120).mean().values
    tr_ok = (p > ma120) & (ma120 > np.concatenate([np.full(20, np.nan), ma120[:-20]]))
    r = pd.Series(p).pct_change()
    rv = (r.rolling(20).std() * np.sqrt(252)).values
    r20 = pd.Series(p).pct_change(20).values
    ind[sym] = dict(tr=tr_ok, rv=rv, rv_ok=rv < past_pct(rv, 0.90), r20=r20)
with np.errstate(all="ignore"):
    lq = liq.astype(bool)
    br60 = np.nanmean(np.where(lq, C > Cd.rolling(60).mean().values, np.nan), axis=1)
    nh52 = np.nanmean(np.where(lq, C > 0.95 * Hd.rolling(252, min_periods=200).max().values, np.nan), axis=1)
    r20s = (Cd / Cd.shift(20) - 1).values
    mret = np.where(is_kq[None, :], ind["^KQ11"]["r20"][:, None], ind["^KS11"]["r20"][:, None])
    disp = np.nanmedian(np.where(lq, np.abs(r20s - mret), np.nan), axis=1)
mkt_ok = (br60 > past_pct(br60, 0.60)) & (nh52 > past_pct(nh52, 0.60)) & (disp > past_pct(disp, 0.50))
TR = np.where(is_kq[None, :], (ind["^KQ11"]["tr"] & ind["^KQ11"]["rv_ok"])[:, None], (ind["^KS11"]["tr"] & ind["^KS11"]["rv_ok"])[:, None])
STRONG = TR & mkt_ok[:, None]
for lab, a, b in (("2015~18", "2015-07-01", "2018-12-31"), ("2019~22", "2019-01-01", "2022-12-31"), ("2023~25.05", "2023-01-01", "2025-05-31"), ("AI장 25.06~", "2025-06-01", "2026-12-31")):
    mm = (dates >= a) & (dates <= b)
    M.log(f"StrongTrend 날 비율 {lab}: 코스피 종목 {100 * np.mean(STRONG[mm][:, ~is_kq].any(axis=1)):.0f}% · 코스닥 종목 {100 * np.mean(STRONG[mm][:, is_kq].any(axis=1)):.0f}% · 시장 조건만 {100 * np.mean(mkt_ok[mm]):.0f}%")

LEGS = [(b_(C < M.ema(C, 21)), 1.0)]


def trades(E, entry="close"):
    tr = M.first_only(M.trades(D, E, LEGS, stop=stop, start=260)).reset_index(drop=True)
    if entry == "open":                       # 다음 날 시가 진입: 같은 손절·정리, 진입가만 바꿈 (시가가 손절가 아래면 시가에 바로 손절)
        o1 = O[np.minimum(tr.i.values + 1, n - 1), tr.j.values]
        ok = np.isfinite(o1) & (o1 > 0)
        tr = tr[ok].copy(); o1 = o1[ok]
        st = stop[tr.i.values, tr.j.values]
        xp = np.array([lg[0][1] for lg in tr.legs])
        tr["ret"] = np.where(o1 <= st, 0.0, xp / o1 - 1)
        tr["risk"] = np.where(o1 <= st, np.nan, 1 - st / o1)
        tr = tr[np.isfinite(tr.risk) | (o1 <= st)]
        tr["risk"] = tr.risk.fillna(0.01)
        tr["px0"] = o1
    tr["net"] = tr.ret - COST; tr["R"] = tr.net / tr.risk; tr["date"] = dates[tr.i.values]
    tr["strong"] = STRONG[tr.i.values, tr.j.values]
    mfe, mae = [], []
    for r in tr.itertuples(index=False):
        ex = min(r.exit, n - 1)
        hs, ls = H[r.i + 1:ex + 1, r.j], L[r.i + 1:ex + 1, r.j]
        mfe.append(np.nanmax(hs) / r.px0 - 1 if len(hs) and np.isfinite(hs).any() else np.nan)
        mae.append(np.nanmin(ls) / r.px0 - 1 if len(ls) and np.isfinite(ls).any() else np.nan)
    tr["mfe"], tr["mae"] = mfe, mae
    return tr


def desc(g):
    R = g.R.values; k = max(1, int(len(R) * 0.05)); srt = np.sort(R)
    return (f"{len(g):5d}건 E[R] {R.mean():+.2f} 중앙 {np.median(R):+.2f} 상위5% {np.percentile(R, 95):+.2f} CVaR5 {srt[:k].mean():+.2f} "
            f"MFE {100 * np.nanmedian(g.mfe):+.1f}% MAE {100 * np.nanmedian(g.mae):+.1f}% 보유 {g.hold.mean():.1f}일")


def bdiff(a, b, nb=500):
    ga = a.groupby("date").R.apply(np.array); gb = b.groupby("date").R.apply(np.array)
    A, Bv = list(ga.values), list(gb.values)
    if len(A) < 10 or len(Bv) < 10:
        return np.nan, np.nan
    out = [np.concatenate([A[k] for k in rng.integers(0, len(A), len(A))]).mean() - np.concatenate([Bv[k] for k in rng.integers(0, len(Bv), len(Bv))]).mean() for _ in range(nb)]
    return tuple(np.percentile(out, [2.5, 97.5]))


PER = [("2015~18", "2015-07-01", "2018-12-31"), ("2019~22", "2019-01-01", "2022-12-31"), ("2023~25.05", "2023-01-01", "2025-05-31"), ("AI장 25.06~", "2025-06-01", "2026-12-31")]
M.log("=" * 150)
M.log("TEST 1 — 필터 하나씩만 풀었을 때 그 필터 때문에만 막혔던 신호(veto) vs BASE  [차이 = veto E[R] − BASE E[R], 날짜 묶음 부트스트랩 95%]")
for key, kw, lab in (("A", dict(ext_max=9.0), "A: 20일선 +15%"), ("B", dict(day_max=0.30), "B: 당일 +8%"), ("C", dict(risk_max=0.20), "C: 손절폭 8% 초과(20%까지)")):
    EX = buy(**kw)
    tr = trades(EX)
    tr["veto"] = ~E0[tr.i.values, tr.j.values]
    M.log(f"◆ {lab} — 이 필터 때문에만 막힌 신호 {int((EX & ~E0).sum())}개, 겹침 뺀 거래 중 veto {int(tr.veto.sum())}건")
    for plab, a, b in PER:
        g = tr[(tr.date >= a) & (tr.date <= b)]
        for sv, slab in ((False, "Normal"), (True, "Strong")):
            gg = g[g.strong == sv]; bs, vt = gg[~gg.veto], gg[gg.veto]
            if len(vt) < 20 or len(bs) < 20:
                M.log(f"   {plab:11s} {slab:6s} | 표본 부족 (BASE {len(bs)} · veto {len(vt)})"); continue
            lo, hi = bdiff(vt, bs)
            M.log(f"   {plab:11s} {slab:6s} | BASE {desc(bs)}")
            M.log(f"   {'':11s} {'':6s} | veto {desc(vt)} | 차이 {vt.R.mean() - bs.R.mean():+.2f} [{lo:+.2f},{hi:+.2f}]")
M.log("=" * 150)
M.log("LOOKAHEAD — BASE 종가 진입 vs 다음 날 시가 진입")
t_c, t_o = trades(E0, "close"), trades(E0, "open")
for plab, a, b in PER:
    gc, go = t_c[(t_c.date >= a) & (t_c.date <= b)], t_o[(t_o.date >= a) & (t_o.date <= b)]
    M.log(f"   {plab:11s} 종가 {len(gc)}건 E[R] {gc.R.mean():+.2f} 평균 {100 * gc.net.mean():+.2f}% | 다음 날 시가 {len(go)}건 E[R] {go.R.mean():+.2f} 평균 {100 * go.net.mean():+.2f}% (시가가 손절가 아래 {int((go.ret == 0).sum())}건)")
for nm, t in (("종가 진입", t_c), ("다음 날 시가 진입", t_o)):
    tt = t.copy()
    if nm != "종가 진입":
        tt["i"] = tt.i + 1                    # 산 날 = 다음 날 (계좌 시뮬은 그날 종가 평가)
    tt["legs"] = [[(max(lg[0][0], i0 + 1), lg[0][1], 1.0)] for lg, i0 in zip(tt.legs, tt.i)]
    eq, inv, dn = M.portfolio(D, tt, mode="ew", maxpos=10)
    mt = M.metrics(D, eq, inv, dn)
    M.log(f"   계좌 {nm}: " + " | ".join(f"{k} 연 {v['수익(연)']:+.0f}% 낙폭 {v['최대낙폭']:.0f}%" for k, v in mt.items()))
