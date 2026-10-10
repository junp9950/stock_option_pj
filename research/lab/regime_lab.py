"""장세에 따라 과열 필터를 풀어도 되는가 (2026-10-10 KST, 사용자 "장세는 데이터로 보여 달라 · 지금 장에서 신호가 늦다").
질문: 우리 매수에서 과열 필터(20일선 +15% 안 · EMA 간격 6% 안 · 그날 +8% 미만 · 손절폭 8% 이하)를 풀면 추가되는 신호("추가분")가
      어떤 장세(숫자)에서 지금 신호만큼 좋고, 어떤 장세에서 나쁜가. 지금 장(25.06~)만이 아니라 과거 뜨거운 장에서도 같아야 쓴다.
장세 숫자(그날까지의 값만, 앞날 안 봄): 시장 폭(20일선 위 종목 비율, 10일 평균) · 60일 신고가 종목 비율(10일 평균) · 주도주 쏠림(RS 상위 20% 60일 수익 − 전체 중앙)
      · 시장 60일 수익(같은 무게 지수) · 최근 성적(지난 60거래일 동안 이미 정리된 추가분 거래의 평균 손익).
장세 구분: 연습 기간(2015-07~2022-12) 값으로 3등분 기준을 정하고(뜨거움=상위 1/3) 시험 기간(2023~)에도 그 기준 그대로.
거래: 종가 진입 · 신호 날 저가 -1% 손절 · 21일선 아래 종가 → 다음 날 시가. 풀린 체계 전체로 겹침 제거한 뒤 각 거래를 '지금 신호'/'추가분'으로 나눔.
실행: cd /home/junp/stock_option_pj && set -a && . ./.env && set +a && nice -n 10 .venv/bin/python /home/junp/tmp_claude/regime_lab.py
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
import ma_lab as M

rng = np.random.default_rng(3)
COST = M.COST_BUY + M.COST_SELL
D = M.prep(M.load())
O, H, L, C, V, T = (D[k] for k in "ohlcvt")
n, m = D["n"], D["m"]
dates = np.array([str(d) for d in D["dates"]])
Cd, Hd, Vd, Td = pd.DataFrame(C), pd.DataFrame(H), pd.DataFrame(V), pd.DataFrame(T)
liq, RS, chg = D["liq"], D["RS"], D["chg"]
B = D["bull"][:, None]

# ── our_buy 내부와 같은 계산 (ma_lab.our_buy를 그대로 따름)
e5, e10, e20, e60 = (M.ema(C, k) for k in (5, 10, 20, 60))
trend = (C > e20) & (e20 > e60) & liq
with np.errstate(invalid="ignore", divide="ignore"):
    vx = (Vd / Vd.shift(1).rolling(20).mean()).values
    ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
    F = [(Cd / Hd.rolling(60).max() - 1).values >= -0.05, (RS >= 70) & (RS < 95), (vx >= 0.7) & (vx < 3),
         (C - L) / np.where(H - L == 0, np.nan, H - L) >= 0.7, (chg >= 0) & (chg < 0.08), (Cd / Cd.rolling(20).mean() - 1).values < 0.15, (ehi - elo) / C < 0.06]
    F = [np.nan_to_num(f.astype(float)).astype(bool) for f in F]
    stop = (L * 0.99).astype("float32"); risk = 1 - stop / C
    tvx = (Td / Td.rolling(20).mean().shift(1)).values
    gap_prev = np.vstack([np.full((1, m), np.nan), ((ehi - elo) / C)[:-1]])
    hi10p = Hd.shift(1).rolling(10).max().values
    up60 = (C > e60) & (e20 > e60)
    brk_core = (gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (tvx >= 1.5) & liq
E_cur, _ = M.our_buy(D)
# 풀린 체계: 과열 두 항목(20일선 +15%·EMA 간격 6%)을 점수에서 빼고, 그날 상한 +8% → +29%, 손절폭 8% → 12%
F4l = np.nan_to_num(((chg >= 0) & (chg < 0.29)).astype(float)).astype(bool)
score5 = F[0].astype(int) + F[1] + F[2] + F[3] + F4l
base_l = B & trend & F[1] & (risk <= 0.12) & (risk > 0)
with np.errstate(invalid="ignore"):
    E_loose = E_cur | (base_l & (score5 >= 5)) | (base_l & brk_core & (chg < 0.29) & up60)
M.log(f"지금 신호 {int(E_cur.sum())}개 · 풀린 체계 {int(E_loose.sum())}개 (추가분 {int((E_loose & ~E_cur).sum())}개)")

LEGS = [(np.nan_to_num((C < M.ema(C, 21)).astype(float)).astype(bool), 1.0)]
tr = M.first_only(M.trades(D, E_loose, LEGS, stop=stop, start=260)).reset_index(drop=True)
tr["net"] = tr.ret - COST; tr["R"] = tr.net / tr.risk; tr["date"] = dates[tr.i.values]
tr["added"] = ~E_cur[tr.i.values, tr.j.values]
M.log(f"거래 {len(tr)}건 (겹침 뺌) · 그중 추가분 {int(tr.added.sum())}건")

# ── 장세 숫자 (날마다)
with np.errstate(all="ignore"):
    lq = liq.astype(bool)
    above20 = np.where(lq, (C > Cd.rolling(20).mean().values), np.nan)
    breadth = pd.Series(np.nanmean(above20, axis=1)).rolling(10).mean().values
    nh = np.where(lq, (C >= Hd.rolling(60).max().values), np.nan)
    nh60 = pd.Series(np.nanmean(nh, axis=1)).rolling(10).mean().values
    r60 = (Cd / Cd.shift(60) - 1).values
    r60l = np.where(lq, r60, np.nan)
    top = np.where(lq & (np.nan_to_num(RS) >= 80), r60, np.nan)
    lead = np.nanmedian(top, axis=1) - np.nanmedian(r60l, axis=1)
    lvl = D["lvl"]; idx60 = lvl / np.concatenate([np.full(60, np.nan), lvl[:-60]]) - 1
# 최근 성적: 지난 60거래일 안에 '이미 정리된' 추가분 거래 평균 손익 (앞날 안 봄)
ad = tr[tr.added]
recent = np.full(n, np.nan)
ex_i, nets = ad.exit.values, ad.net.values
order = np.argsort(ex_i); ex_i, nets = ex_i[order], nets[order]
for t in range(260, n):
    lo_, hi_ = np.searchsorted(ex_i, t - 60), np.searchsorted(ex_i, t)       # 정리일이 t-60 ~ t-1
    if hi_ - lo_ >= 15:
        recent[t] = nets[lo_:hi_].mean()
REG = {"시장 폭(20일선 위 비율)": breadth, "60일 신고가 종목 비율": nh60, "주도주 쏠림(RS80↑ 60일 수익 − 전체)": lead,
       "시장 60일 수익": idx60, "최근 성적(지난 60일 추가분 손익)": recent}
PRAC = (dates >= "2015-07-01") & (dates <= "2022-12-31")


def bootdiff(a_df, b_df, col="R", nb=500):
    ga = a_df.groupby("date")[col].apply(np.array); gb = b_df.groupby("date")[col].apply(np.array)
    A, Bv = list(ga.values), list(gb.values)
    if len(A) < 10 or len(Bv) < 10:
        return np.nan, np.nan
    out = [np.concatenate([A[k] for k in rng.integers(0, len(A), len(A))]).mean() - np.concatenate([Bv[k] for k in rng.integers(0, len(Bv), len(Bv))]).mean() for _ in range(nb)]
    return tuple(np.percentile(out, [2.5, 97.5]))


M.log("=" * 140)
M.log("장세별: 지금 신호 R vs 추가분 R · 차이(추가분 − 지금) [95%] — 뜨거운 장에서 차이가 0 근처(또는 +)이고 식은 장에서 크게 −면 '뜨거운 장에만 풀기'가 맞다")
for name, x in REG.items():
    q1, q2 = np.nanpercentile(x[PRAC], [33.3, 66.7])
    st = np.where(np.isnan(x), -1, np.where(x >= q2, 2, np.where(x >= q1, 1, 0)))
    tr["st"] = st[tr.i.values]
    M.log(f"◆ {name} (연습 기준 3등분: {q1:.3f} / {q2:.3f})")
    for plab, a, b in (("연습 2015~22", "2015-07-01", "2022-12-31"), ("시험 2023~", "2023-01-01", "2026-12-31")):
        g = tr[(tr.date >= a) & (tr.date <= b)]
        parts = []
        for s_, slab in ((2, "뜨거움"), (1, "중간"), (0, "식음")):
            gg = g[g.st == s_]; cu, adx = gg[~gg.added], gg[gg.added]
            if len(adx) < 30 or len(cu) < 30:
                parts.append(f"{slab}: 표본 부족({len(cu)}/{len(adx)})"); continue
            lo, hi = bootdiff(adx, cu)
            parts.append(f"{slab}: 지금 {len(cu)}건 R{cu.R.mean():+.2f} · 추가 {len(adx)}건 R{adx.R.mean():+.2f} ({100 * adx.net.mean():+.1f}%) 차이 {adx.R.mean() - cu.R.mean():+.2f} [{lo:+.2f},{hi:+.2f}]")
        M.log(f"   {plab} | " + " | ".join(parts))
M.log("=" * 140)
M.log("참고: 과거 '뜨거운 장' 구간별 추가분 성적 (날짜로 자른 것 — 장세 숫자가 이 구간들을 잡는지 보려는 것)")
for lab, a, b in (("2017 반도체·바이오장", "2017-01-01", "2018-01-31"), ("2020.04~21.06 유동성장", "2020-04-01", "2021-06-30"), ("2023 2차전지장", "2023-01-01", "2023-08-31"),
                  ("2015~16 박스", "2015-07-01", "2016-12-31"), ("2018.02~19 하락·박스", "2018-02-01", "2019-12-31"), ("2021.07~22 하락", "2021-07-01", "2022-12-31"), ("AI장 25.06~", "2025-06-01", "2026-12-31")):
    g = tr[(tr.date >= a) & (tr.date <= b)]; cu, adx = g[~g.added], g[g.added]
    if len(adx) >= 20:
        M.log(f"   {lab}: 지금 {len(cu)}건 R{cu.R.mean():+.2f} · 추가분 {len(adx)}건 R{adx.R.mean():+.2f} ({100 * adx.net.mean():+.1f}%) · 그 기간 시장 폭 평균 {np.nanmean(breadth[(dates >= a) & (dates <= b)]):.2f} · 신고가 비율 {np.nanmean(nh60[(dates >= a) & (dates <= b)]):.3f}")
