"""이평선 매매법 대검증 공용 도구 (2026-10-09 사용자 "EMA·SMA·맥긴리 다이나믹·기타 이평선 매매법 검증하고, 혼합해서 쓸 때도 정확하게").

데이터: spot_daily_hist (네이버 정규장 · 분할 반영, 2014-07-16~). 지금 상장 종목 위주(상폐 13개뿐) → 절대 수익은 부풀려짐, 방법끼리 비교용.
체결: 매수 = 신호 날 종가 · 선 아래 종가(신호) → 다음 날 시가 · 손절 = 장중 손절가 닿으면 손절가(시가가 아래면 시가) · 비용 왕복 0.3%.
분할 반영이 틀어진 봉(하루 ±30.5% 넘음, 2015-06-15 전 ±15.5%)에 걸친 거래는 뺌.
"""
from __future__ import annotations
from lab_paths import APP_ROOT, DATA_DIR, LAB_DIR

import os
import sys
import time

sys.path.insert(0, str(APP_ROOT))
import numpy as np
DROPPED: list = []      # 가격 이상 봉에 걸쳐 뺀 거래 (LAB_DROP_ANOMALY)
import pandas as pd
from backend.services.trading_rules import entry_masks, market_returns, relative_strength, net_return

CACHE = str(DATA_DIR / 'ma_lab_cache.npz')
COST_BUY, COST_SELL = 0.0005, 0.0025        # 왕복 0.3% (수수료·세금·미끄러짐)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ───────────────────────── 데이터 ─────────────────────────
def load() -> dict:
    if os.path.exists(CACHE):
        z = np.load(CACHE, allow_pickle=True)
        D = {k: z[k] for k in z.files}
        D["dates"] = list(pd.to_datetime(D["dates"]).date)
        D["codes"] = list(D["codes"])
        return D
    from sqlalchemy import text
    from backend.db.database import SessionLocal
    db = SessionLocal()
    codes = [r[0] for r in db.execute(text("select stock_code from spot_daily_hist group by 1 having max(trading_value) >= 3e9")).all()]
    dates = [r[0] for r in db.execute(text("select distinct trading_date from spot_daily_hist where trading_date >= '2014-07-16' order by 1")).all()]
    ci, di = {c: i for i, c in enumerate(codes)}, {d: i for i, d in enumerate(dates)}
    A = {k: np.full((len(dates), len(codes)), np.nan, dtype="float32") for k in "ohlcvt"}
    for s, d, o, h, l, c, v, t in db.execute(text("select stock_code, trading_date, open_price, high_price, low_price, close_price, volume, trading_value "
                                                  "from spot_daily_hist where trading_date >= '2014-07-16'")):
        i = di.get(d); j = ci.get(s)
        if i is None or j is None:
            continue
        A["o"][i, j], A["h"][i, j], A["l"][i, j], A["c"][i, j] = o or np.nan, h or np.nan, l or np.nan, c or np.nan
        A["v"][i, j], A["t"][i, j] = v if v is not None else np.nan, t if t is not None else np.nan
    np.savez(CACHE, dates=np.array([str(d) for d in dates]), codes=np.array(codes), **A)
    return load()


def prep(D: dict) -> dict:
    """공통 파생: 거래대금 20일 평균 · 유동성 · 시장 지수 · 상승장 · RS · 분할 오류 봉."""
    from backend.screener.market_regime import regime_series
    O, H, L, C, V, T = (D[k] for k in "ohlcvt")
    n, m = C.shape
    Cd = pd.DataFrame(C)
    chg = (Cd / Cd.shift(1) - 1).values
    tv20 = pd.DataFrame(T).rolling(20).mean().values
    liq = tv20 >= 3e9
    mk = market_returns(Cd, pd.DataFrame(T)).values
    lvl = np.cumprod(1 + mk)
    reg = regime_series({d: float(v) * 100 for d, v in zip(D["dates"], mk)})
    bull = np.array([reg.get(d, {}).get("state") in ("상승", "횡보") for d in D["dates"]])
    RS = relative_strength(Cd, pd.DataFrame(T)).values.astype("float32")
    dates = D["dates"]
    old = np.array([d < pd.Timestamp("2015-06-15").date() for d in dates])[:, None]
    bad = np.nan_to_num(np.abs(chg)) > np.where(old, 0.155, 0.305)
    badcum = np.cumsum(bad, axis=0).astype("int32")
    Cf = pd.DataFrame(C).ffill().values.astype("float32")          # 평가용 (거래 정지 날은 전날 종가)
    D.update(chg=chg.astype("float32"), tv20=tv20.astype("float32"), liq=liq, mk=mk, lvl=lvl, bull=bull, RS=RS, badcum=badcum, Cf=Cf, n=n, m=m)
    return D


# ───────────────────────── 이평선 13종 ─────────────────────────
def _df(x):
    return pd.DataFrame(x, dtype="float64")


def sma(x, n):
    return _df(x).rolling(n, min_periods=n).mean().values


def ema(x, n):
    return _df(x).ewm(span=n, adjust=False).mean().values


def _lagsum(x, w):
    """가중 합 Σ w[k] · x[t-k] (w[0] = 오늘). 창 안 NaN이면 NaN."""
    x = np.asarray(x, dtype="float64")
    out = np.zeros_like(x)
    for k, wk in enumerate(w):
        if k == 0:
            out += wk * x
        else:
            sh = np.full_like(x, np.nan)
            sh[k:] = x[:-k]
            out += wk * sh
    return out


def wma(x, n):
    w = np.arange(n, 0, -1, dtype="float64")
    return _lagsum(x, w / w.sum())


def hma(x, n):
    return wma(2 * wma(x, max(n // 2, 1)) - wma(x, n), max(int(np.sqrt(n)), 1))


def dema(x, n):
    e1 = ema(x, n)
    return 2 * e1 - ema(e1, n)


def tema(x, n):
    e1 = ema(x, n); e2 = ema(e1, n); e3 = ema(e2, n)
    return 3 * e1 - 3 * e2 + e3


def zlema(x, n):
    lag = (n - 1) // 2
    xd = _df(x)
    return ema((xd + (xd - xd.shift(lag))).values, n)


def kama(x, n, f=2, s=30):
    x = np.asarray(x, dtype="float64")
    d = np.abs(np.diff(x, axis=0, prepend=np.nan))
    vol = _df(d).rolling(n).sum().values
    prev = np.full_like(x, np.nan); prev[n:] = x[:-n]
    with np.errstate(invalid="ignore", divide="ignore"):
        er = np.abs(x - prev) / vol
    sc = (np.nan_to_num(er) * (2 / (f + 1) - 2 / (s + 1)) + 2 / (s + 1)) ** 2
    out = np.full_like(x, np.nan); k = np.full(x.shape[1], np.nan)
    for i in range(x.shape[0]):
        k = np.where(np.isfinite(k), k + sc[i] * (x[i] - k), x[i])
        k = np.where(np.isfinite(x[i]), k, np.nan) if False else k
        out[i] = k
    out[~np.isfinite(x)] = np.nan
    return out


def mcginley(x, n):
    """TradingView 식: MD = MD[-1] + (P - MD[-1]) / (N · (P / MD[-1])^4), 처음은 EMA. 비율은 0.5~2로 묶음(튐 방지)."""
    x = np.asarray(x, dtype="float64")
    e = ema(x, n)
    out = np.full_like(x, np.nan); md = np.full(x.shape[1], np.nan)
    for i in range(x.shape[0]):
        c = x[i]
        ok = np.isfinite(c) & np.isfinite(md) & (md > 0)
        r = np.where(ok, c / np.where(ok, md, 1.0), 1.0)
        md = np.where(ok, md + (c - md) / (n * np.clip(r, 0.5, 2.0) ** 4), np.where(np.isfinite(md), md, e[i]))
        out[i] = md
    out[~np.isfinite(x)] = np.nan
    return out


def alma(x, n, off=0.85, sig=6.0):
    mu, s = off * (n - 1), n / sig
    i = np.arange(n, dtype="float64")              # i=0 가장 오래된 날 … n-1 오늘
    w = np.exp(-((i - mu) ** 2) / (2 * s * s)); w /= w.sum()
    return _lagsum(x, w[::-1])                      # _lagsum은 w[0] = 오늘


def vwma(x, n, v):
    xv = _df(np.asarray(x, "float64") * np.asarray(v, "float64")).rolling(n, min_periods=n).sum().values
    vv = _df(v).rolling(n, min_periods=n).sum().values
    with np.errstate(invalid="ignore", divide="ignore"):
        return xv / vv


def lsma(x, n):
    return 3 * wma(x, n) - 2 * sma(x, n)


def t3(x, n, v=0.7):
    e1 = ema(x, n); e2 = ema(e1, n); e3 = ema(e2, n); e4 = ema(e3, n); e5 = ema(e4, n); e6 = ema(e5, n)
    c1 = -v ** 3; c2 = 3 * v * v + 3 * v ** 3; c3 = -6 * v * v - 3 * v - 3 * v ** 3; c4 = 1 + 3 * v + v ** 3 + 3 * v * v
    return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


MA_TYPES = ["SMA", "EMA", "WMA", "HMA", "DEMA", "TEMA", "ZLEMA", "KAMA", "McGinley", "ALMA", "VWMA", "LSMA", "T3"]


def ma(D, typ, n, src=None):
    x = D["c"] if src is None else src
    f = {"SMA": sma, "EMA": ema, "WMA": wma, "HMA": hma, "DEMA": dema, "TEMA": tema, "ZLEMA": zlema, "KAMA": kama,
         "McGinley": mcginley, "ALMA": alma, "LSMA": lsma, "T3": t3}
    if typ == "VWMA":
        out = vwma(x, n, D["v"])
    else:
        out = f[typ](x, n)
    out = np.asarray(out, dtype="float32")
    out[~np.isfinite(np.asarray(x, "float32"))] = np.nan
    return out


# ───────────────────────── 거래 엔진 ─────────────────────────
def next_true(X):
    """NX[t, j] = t 이후(포함) 처음 X가 참인 날, 없으면 n."""
    n, m = X.shape
    NX = np.empty((n + 1, m), dtype=np.int32); NX[n] = n
    for t in range(n - 1, -1, -1):
        NX[t] = np.where(X[t], t, NX[t + 1])
    return NX


def _px_at(D, day, j, kind="o"):
    """First valid trading bar on/after day; n means unfilled, final mark only."""
    from backend.services.trading_rules import tradable_bar, locked_down
    n = D["n"]
    changes = D.get("chg")
    for t in range(day,n):
        bar = (t,D["o"][t,j],D["h"][t,j],D["l"][t,j],D["c"][t,j],changes[t,j]*100 if changes is not None else 0.)
        if tradable_bar(bar) and not locked_down(bar):
            return float(D[kind][t,j]),t
    return float(D["Cf"][n-1,j]),n


def trades(D, E, legs, stop=None, start=260, be_at=None, chand=None, maxhold=None, entry="close"):
    """E: 매수 신호(종가) bool (n, m). legs: [(X 정리 신호 bool (n,m) — 종가에 참이면 다음 날 시가 정리, 비중)].
    stop: 손절가 (n, m) (신호 날 기준) 또는 None. be_at: +k R 종가 뒤 손절을 본전으로. chand: (atr 배열, 배수) 샹들리에 추적.
    반환 DataFrame: i, j, px0, ret(비용 전·비중 합), exit(마지막 정리 날), legs[(day, px, w)], risk, R."""
    n = D["n"]; O, L, C = D["o"], D["l"], D["c"]
    if entry not in ("close", "open"):
        raise ValueError("entry must be close or open")
    valid = np.isfinite(O) & (O > 0) & np.isfinite(L) & (L > 0) & np.isfinite(C) & (C > 0) & np.isfinite(D["h"]) & (D["h"] > 0)
    valid &= (L <= np.minimum(O,C)) & (np.maximum(O,C) <= D["h"])
    E = E.copy(); E[:start] = False; E[n - 1] = False
    ii, jj = np.nonzero(E)
    NXs = [(next_true(X), w) for X, w in legs]
    badcum = D["badcum"]
    out_i, out_j, out_px0, out_ret, out_exit, out_risk, out_legs = [], [], [], [], [], [], []
    out_signal, out_phase = [], []
    for signal_i, j in zip(ii, jj):
        i = signal_i + (entry == "open")
        if not valid[i,j]:
            continue
        px0 = float(O[i,j] if entry == "open" else C[i,j])
        scan_start = i if entry == "open" else i + 1
        if not np.isfinite(px0) or px0 <= 0:
            continue
        sigs = [int(NX[scan_start, j]) for NX, _ in NXs]           # 정리 신호 날(종가)
        last_sig = max(sigs)
        st = float(stop[signal_i, j]) if stop is not None else None
        if st is not None and (not np.isfinite(st) or st <= 0 or px0 <= st):
            continue
        sd, spx = n, None                                     # 손절 날·값
        if st is not None or chand is not None:
            hi = min(last_sig, n - 1)
            if hi >= scan_start:
                lo_seg = np.where(valid[scan_start:hi+1,j],L[scan_start:hi+1,j],np.nan)
                if be_at is not None and st is not None:
                    r1 = px0 - st
                    cseg = C[scan_start:hi + 1, j]
                    hit = np.nonzero(cseg >= px0 + be_at * r1)[0]
                    stv = np.full(len(lo_seg), st, dtype="float64")
                    if len(hit):
                        stv[hit[0] + 1:] = max(st, px0)       # 그 다음 날부터 본전
                    m_ = np.nonzero(lo_seg <= stv)[0]
                    if len(m_):
                        sd = scan_start + int(m_[0]); lv = stv[m_[0]]
                        o = O[sd, j]; spx = float(min(o, lv)) if np.isfinite(o) else float(lv)
                elif st is not None:
                    m_ = np.nonzero(lo_seg <= st)[0]
                    if len(m_):
                        sd = scan_start + int(m_[0]); o = O[sd, j]
                        spx = float(min(o, st)) if np.isfinite(o) else st
                if chand is not None:
                    atr, k = chand
                    hseg = D["h"][signal_i:hi + 1, j]
                    offset = scan_start - signal_i
                    trail = np.fmax.accumulate(np.nan_to_num(hseg, nan=0.0))[offset:] - k * atr[scan_start:hi + 1, j]
                    cseg = C[scan_start:hi + 1, j]
                    m2 = np.nonzero(cseg < trail)[0]
                    if len(m2):                               # 샹들리에는 종가 신호 → 다음 날 시가
                        cs = scan_start + int(m2[0])
                        sigs = [min(s_, cs) for s_ in sigs]
                        last_sig = max(sigs)
                        if sd > last_sig:
                            sd, spx = n, None
        if maxhold is not None:
            sigs = [min(s_, i + maxhold) for s_ in sigs]; last_sig = max(sigs)
        lg, phases = [], []
        for (NX, w), s_ in zip(NXs, sigs):
            if spx is not None and sd <= s_:                  # 손절이 먼저
                changes = D.get("chg")
                locked = D["h"][sd,j] == L[sd,j] and changes is not None and changes[sd,j] <= -.29
                if locked:
                    delayed_px, delayed_day = _px_at(D, sd + 1, j)
                    lg.append((delayed_day, delayed_px, w)); phases.append("open")
                else:
                    lg.append((sd, spx, w)); phases.append("open" if O[sd,j] <= spx else "intraday")
            else:
                px, dday = _px_at(D, s_ + 1, j)
                lg.append((dday, px, w)); phases.append("open")
        ex = max(d for d, _, _ in lg)
        if badcum[min(ex, n - 1), j] - badcum[signal_i, j] > 0:
            if os.environ.get("LAB_DROP_ANOMALY"):       # Claude 2026-10-11: 데이터 고치기 전까지 예전처럼 빼고 셈, 건수 기록
                DROPPED.append((int(i), int(j))); continue
            raise ValueError(f"Unresolved price anomaly in trade ({i}, {j}) through {ex}; repair data before portfolio evaluation")
        ret = sum(w * (px / px0 - 1) for _, px, w in lg)
        out_signal.append(signal_i); out_phase.append("intraday" if any(d == ex and ph == "intraday" for (d, _, _), ph in zip(lg,phases)) else "open")
        out_i.append(i); out_j.append(j); out_px0.append(px0); out_ret.append(ret); out_exit.append(ex)
        out_risk.append((1 - st / px0) if st is not None else np.nan); out_legs.append(lg)
    df = pd.DataFrame({"i": out_i, "j": out_j, "px0": out_px0, "ret": out_ret, "exit": out_exit, "risk": out_risk, "legs": out_legs, "signal_i": out_signal, "exit_phase": out_phase})
    df = df.astype({"i":"int64", "j":"int64", "signal_i":"int64", "exit":"int64"})
    df["net"] = (1 + df.ret) * (1 - COST_SELL) - (1 + COST_BUY)
    df["R"] = df.net / df.risk
    df["hold"] = df.exit - df.i
    return df


def first_only(df):
    """같은 종목은 정리한 뒤 신호부터 (신호 품질 비교용)."""
    df = df.sort_values(["j", "i"])
    keep = []; last_j, free = -1, -1
    for k, (i, j, ex) in enumerate(zip(df.i.values, df.j.values, df.exit.values)):
        if j != last_j:
            last_j, free = j, -1
        if i >= free:
            keep.append(k); free = ex
    return df.iloc[keep]


# ───────────────────────── 계좌 시뮬레이션 ─────────────────────────
PERIODS = [("2015~18 박스장", "2015-07-01", "2018-12-31"), ("2019~22", "2019-01-01", "2022-12-31"), ("2023~26.10", "2023-01-01", "2026-12-31"),
           ("최근 25.06~", "2025-06-02", "2026-12-31")]


def portfolio(D, tr, mode="ew", maxpos=10, risk=0.005, cap=0.20, rank="rs", start_date="2015-07-01"):
    """tr: trades() 결과 (같은 종목 겹친 신호 포함) → 실제 계좌처럼: 같은 종목 하나 · 최대 maxpos · 돈 한도.
    mode ew = 계좌/maxpos씩 같은 금액, risk = 계좌×risk / 손절폭 (최대 cap)."""
    n = D["n"]; Cf = D["Cf"]; dates = D["dates"]
    s0 = next(k for k, d in enumerate(dates) if str(d) >= start_date)
    t = tr[tr.i >= s0].copy()
    size = D.get("size_mult")
    si = t.signal_i.values if "signal_i" in t else t.i.values
    t["size_mult"] = size[si,t.j.values] if size is not None else 1.
    if rank == "rs":
        t["rk"] = -np.nan_to_num(D["RS"][t.i.values, t.j.values], nan=-1)
    elif rank == "risk":
        t["rk"] = t.risk.values
    else:
        t["rk"] = np.random.default_rng(int(rank)).random(len(t))
    t = t.sort_values(["i", "rk"])
    by_day = {}
    for row in t.itertuples(index=False):
        by_day.setdefault(row.i, []).append(row)
    cash, pos = 1.0, []                      # pos: [j, legs_left[(day, px, sh)], entry_i]
    held = set()
    eq = np.full(n, np.nan); inv = np.full(n, np.nan)
    done = []                                # (entry_i, ret_net)
    for d in range(s0, n):
        # 1) 정리 (시가·손절)
        keep = []
        for p in pos:
            j, legs, e_i, cost0, got = p
            left = []
            for (day, px, sh) in legs:
                if day == d:
                    v = sh * px * (1 - COST_SELL); cash += v; got += v
                else:
                    left.append((day, px, sh))
            if left:
                keep.append([j, left, e_i, cost0, got])
            else:
                held.discard(j); done.append((e_i, got / cost0 - 1))
        pos = keep
        # 2) 평가 (종가)
        mv = sum(sh * float(Cf[d, p[0]]) for p in pos for (_, _, sh) in p[1])
        equity = cash + mv
        # 3) 매수 (종가)
        for row in by_day.get(d, []):
            if row.j in held:
                continue
            if mode == "ew":
                if len(pos) >= maxpos:
                    break
                val = equity * row.size_mult / maxpos
            else:
                if len(pos) >= maxpos or not (row.risk > 0):
                    continue
                val = min(equity * risk * row.size_mult / max(row.risk,.003), equity * cap)
            if cash < val * (1 + COST_BUY):
                val = cash / (1 + COST_BUY)
                if val < equity * 0.02:
                    continue
            sh_tot = val / row.px0
            legs = [(day, px, sh_tot * w) for (day, px, w) in row.legs]
            cash -= val * (1 + COST_BUY)
            pos.append([row.j, legs, row.i, val * (1 + COST_BUY), 0.0]); held.add(row.j)
        mv = sum(sh * float(Cf[d, p[0]]) for p in pos for (_, _, sh) in p[1])
        eq[d] = cash + mv; inv[d] = mv / eq[d] if eq[d] > 0 else 0
    # 끝까지 들고 있는 것 = 마지막 종가로
    for p in pos:
        got = p[4] + sum(sh * float(Cf[n - 1, p[0]]) * (1 - COST_SELL) for (_, _, sh) in p[1])
        done.append((p[2], got / p[3] - 1))
    return eq, inv, done


def metrics(D, eq, inv, done):
    dates = D["dates"]; ds = np.array([str(x) for x in dates])
    out = {}
    for lab, a, b in PERIODS + [("전체", "2015-07-01", "2026-12-31")]:
        m = (ds >= a) & (ds <= b) & np.isfinite(eq)
        if m.sum() < 20:
            continue
        e = eq[m]; yrs = m.sum() / 245
        cagr = (e[-1] / e[0]) ** (1 / yrs) - 1 if yrs > 0.3 else e[-1] / e[0] - 1
        mdd = float(np.min(e / np.maximum.accumulate(e) - 1))
        r = np.diff(np.log(e))
        sh = float(np.mean(r) / np.std(r) * np.sqrt(245)) if np.std(r) > 0 else np.nan
        dn = [x for (i, x) in done if a <= str(dates[i]) <= b]
        out[lab] = {"수익(연)": cagr * 100, "최대낙폭": mdd * 100, "샤프": sh, "투자비중": float(np.nanmean(inv[m])) * 100,
                    "거래": len(dn), "이김": (np.mean([x > 0 for x in dn]) * 100) if dn else np.nan, "거래평균": (np.mean(dn) * 100) if dn else np.nan,
                    "기간수익": (e[-1] / e[0] - 1) * 100}
    return out


def trade_stats(D, df):
    """신호 품질 (같은 종목 겹침 뺀 것) — 기간별 거래 수 · 이김 · 평균 % · 평균 R · 평균 보유."""
    f = first_only(df)
    ds = np.array([str(x) for x in D["dates"]])[f.i.values]
    out = {}
    for lab, a, b in PERIODS:
        m = (ds >= a) & (ds <= b)
        g = f[m]
        if len(g) < 20:
            continue
        net = (1 + g.ret) * (1 - COST_SELL) - (1 + COST_BUY)
        out[lab] = {"건": len(g), "이김": float((net > 0).mean() * 100), "평균%": float(net.mean() * 100),
                    "R": float((net / g.risk).mean()) if g.risk.notna().any() else np.nan, "보유": float(g.hold.mean())}
    return out


def bench(D):
    """같은 무게 시장 지수 그냥 들고 있기."""
    lvl = D["lvl"]
    return lvl / lvl[0], np.ones_like(lvl), []


# ───────────────────────── 지금 사이트 매수 신호 ─────────────────────────
def our_buy(D, parts=("score", "ema", "hot"), B=None, rs=(70, 95), stop_arr=None):
    """stock_signals와 같은 규칙: 상승장 · 종가>EMA20>EMA60 · 거래대금 20일 평균 30억↑ · 강도(RS) 70~95 · 손절폭(저가 -1%) 8%↓
    + (종가 점수 6↑ | 이평선 모였다 돌파(정배열·+8% 미만) | 과열 매수(점수 5, 빠진 게 과열 두 개뿐))."""
    O, H, L, C, V, T = (D[k] for k in "ohlcvt")
    Cd, Hd, Vd, Td = pd.DataFrame(C), pd.DataFrame(H), pd.DataFrame(V), pd.DataFrame(T)
    e5, e10, e20, e60 = (ema(C, k) for k in (5, 10, 20, 60))
    chg = D["chg"]; RS = D["RS"]; liq = D["liq"]
    B = D["bull"][:, None] if B is None else np.asarray(B)[:, None]
    trend = (C > e20) & (e20 > e60) & liq
    vx = (Vd / Vd.shift(1).rolling(20).mean()).values
    ehi = np.maximum(np.maximum(e5, e10), e20); elo = np.minimum(np.minimum(e5, e10), e20)
    with np.errstate(invalid="ignore", divide="ignore"):
        F = [(Cd / Hd.rolling(60).max() - 1).values >= -0.05, (RS >= 70) & (RS < 95), (vx >= 0.7) & (vx < 3),
             (C - L) / np.where(H - L == 0, np.nan, H - L) >= 0.7, (chg >= 0) & (chg < 0.08), (Cd / Cd.rolling(20).mean() - 1).values < 0.15, (ehi - elo) / C < 0.06]
    F = [np.nan_to_num(f.astype(float)).astype(bool) for f in F]
    score = sum(f.astype(np.int8) for f in F)
    stop = (L * 0.99).astype("float32") if stop_arr is None else np.asarray(stop_arr, dtype="float32")     # stop_arr: 신호 날 손절가를 다른 값으로 (4시간봉 저가 등 · 2026-10-10)
    with np.errstate(invalid="ignore", divide="ignore"):
        risk = 1 - stop / C
    rsok = F[1] if rs == (70, 95) else (np.nan_to_num(RS) >= rs[0]) & (np.nan_to_num(RS) < rs[1])
    tvx = (Td / Td.rolling(20).mean().shift(1)).values
    gap_prev = np.vstack([np.full((1, C.shape[1]), np.nan), ((ehi - elo) / C)[:-1]])
    hi10p = Hd.shift(1).rolling(10).max().values
    up60 = (C > e60) & (e20 > e60)
    with np.errstate(invalid="ignore"):
        ema_brk = (gap_prev <= 0.04) & (C > ehi) & (C > hi10p) & (chg >= 0.03) & (chg < 0.08) & (tvx >= 1.5) & liq
    out, hot = entry_masks(B & trend, RS, risk, F, ema_brk & up60, parts, rs)
    if parts == ("score", "ema", "hot") and rs == (70, 95) and stop_arr is None:
        D["size_mult"] = np.where(hot, .5, 1.).astype("float32")
    return out, stop


def atr(D, n=22):
    H, L, C = D["h"], D["l"], D["c"]
    pc = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    tr = np.fmax(H - L, np.fmax(np.abs(H - pc), np.abs(L - pc)))
    return pd.DataFrame(tr).rolling(n).mean().values.astype("float32")


def below(D, line):
    """종가가 선 아래 = 정리 신호."""
    with np.errstate(invalid="ignore"):
        return D["c"] < line
