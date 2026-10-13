"""12년(2014-07~) 검증 — spot_daily_hist(네이버 정규장 종가·분할 반영). 2026-10-09 사용자 "3년에 묶여 보수적이 된 거 아니냐 · 12년으로".
기간: 앞 2014~2018 · 가운데 2019~2022 · 뒤(시험지) 2023~ / 매도 = 그날 저가 -1% 예약 손절 · 21일선 아래 종가 (다음 날 시가 대신 그 종가로 근사)."""
import sys; sys.path.insert(0, "/home/junp/stock/futures-options-analyzer")
import numpy as np, pandas as pd
from sqlalchemy import text
from backend.db.database import SessionLocal
from backend.screener.market_regime import regime_series
db = SessionLocal()
codes = [r[0] for r in db.execute(text("select stock_code from spot_daily_hist group by 1 having max(trading_value) >= 3e9")).all()]
dates = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_hist where trading_date >= '2014-07-16' order by 1")).all()]
ci, di = {c: i for i, c in enumerate(codes)}, {d: i for i, d in enumerate(dates)}
A = {k: np.full((len(dates), len(codes)), np.nan, dtype="float32") for k in "ohlcvt"}
for s, d, o, h, l, c, v, t in db.execute(text("select stock_code, trading_date, open_price, high_price, low_price, close_price, volume, trading_value from spot_daily_hist where stock_code = any(:cs) and trading_date >= '2014-07-16'"), {"cs": codes}):
    i = di.get(d)
    if i is None: continue
    j = ci[s]
    A["o"][i, j], A["h"][i, j], A["l"][i, j], A["c"][i, j], A["v"][i, j], A["t"][i, j] = o or np.nan, h or np.nan, l or np.nan, c or np.nan, v or np.nan, t or np.nan
O, H, L, C, V, T = (pd.DataFrame(A[k], index=dates, columns=codes) for k in "ohlcvt")
del A
n = len(dates); print("종목", len(codes), "날", n, dates[0], dates[-1], flush=True)
chg = (C / C.shift(1) - 1)
tv20 = T.rolling(20).mean()
liq = (tv20 >= 3e9).values; liq10 = (tv20 >= 1e9)
mkt = chg.where(liq10).clip(-.3, .3).mean(axis=1)
reg = regime_series({d: float(v) * 100 for d, v in mkt.items() if np.isfinite(v)})
bull = np.array([reg.get(d, {}).get("state") in ("상승", "횡보") for d in dates])
lvl = (1 + mkt.fillna(0)).cumprod(); strong_bull = ((lvl / lvl.shift(60) - 1) >= 0.10).values & bull     # 60일 +10%↑ = 강한 상승장
mk = mkt.values
e5, e10, e20, e21, e60 = (C.ewm(span=k, adjust=False).mean() for k in (5, 10, 20, 21, 60))
raw = 0.4 * (C / C.shift(63) - 1) + 0.2 * (C / C.shift(126) - 1) + 0.2 * (C / C.shift(189) - 1) + 0.2 * (C / C.shift(252) - 1)
RS = (raw.where(tv20 >= 3e9).rank(axis=1, pct=True) * 98 + 1).values
vx = V / V.shift(1).rolling(20).mean()
ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
flags = [C / H.rolling(60).max() - 1 >= -0.05, (pd.DataFrame(RS, index=dates, columns=codes) >= 70) & (pd.DataFrame(RS, index=dates, columns=codes) < 95), (vx >= 0.7) & (vx < 3),
         (C - L) / (H - L).replace(0, np.nan) >= 0.7, (chg >= 0) & (chg < 0.08), C / C.rolling(20).mean() - 1 < 0.15, (ehi - elo) / C < 0.06]
score = sum(f.fillna(False).astype(np.int8) for f in flags).values
trend = ((C > e20) & (e20 > e60)).values & liq
Cn, Ln, Hn, On, E21, E20 = C.values, L.values, H.values, O.values, e21.values, e20.values
chv = chg.values; risk = 1 - Ln * 0.99 / Cn
hi60 = (C / H.rolling(60).max() - 1).values

# ===== 2026-10-13 예전 ▲진입 vs 지금 ↑매수 — 12년 같은 데이터·같은 매도로 나란히 =====
# 미리 정함: 같은 매도(산 날 저가 −1% 장중 손절 · 21일선 아래 종가) · 종목마다 들고 있는 동안 새로 안 삼 · 기간 2014~18/2019~22/2023~
# 판정: R 차이가 세 기간 모두 같은 방향이면 '더 낫다', 엇갈리면 '비슷'
print("데이터 준비", flush=True)
yr = np.array([d.year for d in dates])
H_, L_, O_ = H, L, O
ma20 = C.rolling(20).mean(); ma200 = C.rolling(200, min_periods=180).mean()
s50, s150 = C.rolling(50).mean(), C.rolling(150, min_periods=135).mean()
hi52, lo52 = H.rolling(250, min_periods=200).max(), L.rolling(250, min_periods=200).min()
tt7 = (((C > s150) & (C > ma200)).astype(int) + (s150 > ma200).astype(int) + (ma200 > ma200.shift(21)).astype(int)
       + ((s50 > s150) & (s50 > ma200)).astype(int) + (C > s50).astype(int) + (C >= lo52 * 1.3).astype(int) + (C >= hi52 * 0.75).astype(int))
tvx = T / T.rolling(20).mean().shift(1)
hi20p, lo20p = H.shift(1).rolling(20).max(), L.shift(1).rolling(20).min()
hi10p = H.shift(1).rolling(10).max()
gap_prev = ((ehi - elo) / C).shift(1)
box = (hi20p / lo20p - 1 <= 0.20) & (C > hi20p) & (chg >= 0.05) & (tvx >= 2) & (C > ma200)
emab = (gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.29) & (tvx >= 1.5)
up60 = (C > e60) & (e20 > e60)
B = np.repeat(bull[:, None], len(codes), 1)
liq = (tv20 >= 3e9).values
ENTRY = ((box | (emab & up60)) & (tt7 >= 6) & (chg < 0.08) & (C / ma20 - 1 < 0.15)).fillna(False).values & B & liq
BUY = B & trend & (score >= 6) & (risk <= .08) & (RS >= 70) & (RS < 95)
E14 = e14v = C.ewm(span=14, adjust=False).mean().values
P = {"2014~18": yr <= 2018, "2019~22": (yr >= 2019) & (yr <= 2022), "2023~": yr >= 2023}


def sim(M, half14=False):
    """종목마다 시간 순으로, 들고 있는 동안 새 신호 무시. 반환: (산 날 index, 수익률, 손절폭)."""
    out = []
    M = M.copy(); M[:260] = False; M[-2:] = False
    for j in range(M.shape[1]):
        ii = np.where(M[:, j])[0]
        free = -1
        for i in ii:
            if i <= free: continue
            p, st = Cn[i, j], Ln[i, j] * 0.99
            if not (np.isfinite(p) and np.isfinite(st) and st < p): continue
            rk = 1 - st / p
            res, half, ex = None, None, None
            for m in range(i + 1, min(i + 250, n)):
                c = Cn[m, j]
                if not np.isfinite(c): continue
                if Ln[m, j] < st:
                    px = min(On[m, j], st) if np.isfinite(On[m, j]) else st
                    res = (px / p - 1) if half is None else 0.5 * half + 0.5 * (px / p - 1); ex = m; break
                if half14 and half is None and m - i > 1 and c < E14[m, j]:
                    half = c / p - 1
                if m - i > 1 and c < E21[m, j]:
                    res = (c / p - 1) if half is None else 0.5 * half + 0.5 * (c / p - 1); ex = m; break
            if res is None: continue
            out.append((i, res, rk)); free = ex
    return np.array(out)


def rep(lab, A):
    if not len(A): print(lab, "없음"); return {}
    i, r, rk = A[:, 0].astype(int), A[:, 1], A[:, 2]
    res = {}
    line = []
    for pl, pm in P.items():
        m = pm[i]
        R = r[m] / rk[m]
        res[pl] = R
        line.append(f"{pl} {m.sum()}건 이김 {np.mean(r[m]>0)*100:.0f}% 평균 {r[m].mean()*100:+.2f}% R {R.mean():+.2f}")
    q = np.quantile(r, .1)
    print(f"■ {lab} 전체 {len(r)}건 R {(r/rk).mean():+.2f} · 최악10% {r[r<=q].mean()*100:+.1f}% · 손절폭 {rk.mean()*100:.1f}%\n    " + " | ".join(line), flush=True)
    return res



import time
t0=time.time()
def legs(i, j, mode):
    """두 반쪽의 (청산일, 가격). 한 번에 = 둘이 같음."""
    p, st = Cn[i, j], Ln[i, j] * 0.99
    rk = 1 - st / p
    tgt = p * (1 + (3 if mode == "half3R" else 2) * rk)
    h1 = None
    for m in range(i + 1, min(i + 250, n)):
        c = Cn[m, j]
        if not np.isfinite(c): continue
        o, h = On[m, j], Hn[m, j]
        if Ln[m, j] < st:
            px = min(o, st) if np.isfinite(o) else st
            return (h1 or (m, px)), (m, px)
        if h1 is None and mode in ("half2R", "half3R") and np.isfinite(h) and h >= tgt:
            h1 = (m, max(o, tgt) if np.isfinite(o) else tgt)
        if h1 is None and mode == "half14" and m - i > 1 and c < E14[m, j]:
            h1 = (m, c)
        if m - i > 1 and c < E21[m, j]:
            return (h1 or (m, c)), (m, c)
    m = min(i + 249, n - 1)
    return (h1 or (m, Cn[m, j])), (m, Cn[m, j])

M = BUY.copy(); M[:260] = False; M[-2:] = False
ii, jj = np.where(M)
RSn = np.nan_to_num(RS, nan=-1)
by_day = {}
for i, j in zip(ii, jj):
    if np.isfinite(Cn[i, j]) and np.isfinite(Ln[i, j]) and Ln[i, j] * 0.99 < Cn[i, j]:
        by_day.setdefault(i, []).append(j)
for d in by_day:
    by_day[d].sort(key=lambda j: -RSn[d, j])
Cf = pd.DataFrame(Cn).ffill().values
CB, CS = 0.0005, 0.0025
def account(mode, A, B):
    cash, pos = 1.0, {}     # j -> [sh_half1, sh_half2, (d1,p1), (d2,p2)]
    eq = []; trades = 0; slotdays = 0; free_cash_min = 1.0
    cache = {}
    for d in range(A, B + 1):
        for j in list(pos):
            q = pos[j]
            for k in (0, 1):
                if q[k] > 0 and q[2 + k][0] == d:
                    cash += q[k] * q[2 + k][1] * (1 - CS); q[k] = 0
            if q[0] == 0 and q[1] == 0: del pos[j]
        E = cash + sum((q[0] + q[1]) * Cf[d, j] for j, q in pos.items())
        free = 10 - len(pos)
        for j in by_day.get(d, []):
            if free <= 0: break
            if j in pos: continue
            p = Cn[d, j]; rk = 1 - Ln[d, j] * 0.99 / p
            val = 0.005 * E / max(rk, .003)
            if val > cash: val = cash
            if val <= 0: break
            key = (d, j)
            l1, l2 = legs(d, j, mode)
            sh = val / p / (1 + CB); cash -= val
            pos[j] = [sh / 2, sh / 2, l1, l2]; free -= 1; trades += 1
        slotdays += len(pos)
        eq.append(cash + sum((q[0] + q[1]) * Cf[d, j] for j, q in pos.items()))
    eq = np.array(eq); yrs = len(eq) / 245
    cagr = eq[-1] ** (1 / yrs) - 1; mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    return cagr, mdd, trades, slotdays / len(eq)
di = {d: k for k, d in enumerate(dates)}
def idx(s): return next(k for k, d in enumerate(dates) if str(d) >= s)
for lab, A, B in (("2015.07~22", idx("2015-07-01"), idx("2023-01-01") - 1), ("2023~", idx("2023-01-01"), n - 2)):
    print(f"[{lab}] 10칸 · 거래당 위험 0.5% · 강도 순 · 판 돈은 바로 현금", flush=True)
    for nm, md in (("한 번에 (지금)", "all"), ("14일선 아래 절반", "half14"), ("+2R에서 절반 익절", "half2R"), ("+3R에서 절반 익절", "half3R")):
        cg, md_, tr, sl = account(md, A, B)
        print(f"  {nm:18s} 연 {cg*100:+6.1f}% · 낙폭 {md_*100:5.0f}% · MAR {cg/abs(md_):.2f} · 산 횟수 {tr} · 평균 찬 칸 {sl:.1f}/10", flush=True)
print("끝", f"{(time.time()-t0)/60:.1f}분")
