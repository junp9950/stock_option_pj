"""① RS 순서 레드팀 + ② 계좌 낙폭 줄이기 — Claude 사전등록(prereg_claude_redteam_dd.md) 실행부 (2026-10-10 KST).
GPT 설계는 GPT 답을 받은 뒤 같은 데이터·같은 시뮬로 덧붙인다(redteam_gpt.py).
사용: from redteam_lab import build ; W = build("full") 또는 build("orig")
"""
from lab_paths import APP_ROOT, DATA_DIR, LAB_DIR
import sys
sys.path.insert(0, str(LAB_DIR))
import numpy as np, pandas as pd
import ma_lab as M

COSTB, COSTS = M.COST_BUY, M.COST_SELL


def build(which="full"):
    M.CACHE = str(DATA_DIR / 'ma_lab_cache_full.npz') if which == "full" else str(DATA_DIR / 'ma_lab_cache.npz')
    D = M.prep(M.load())
    n, m = D["n"], D["m"]
    O, H, L, C = D["o"], D["h"], D["l"], D["c"]
    dates = np.array([str(d) for d in D["dates"]])
    n0 = 2783 if which == "full" else m
    # 정리매매(폐지 직전 10거래일)의 큰 봉은 진짜 손실 → 오류 표시(badcum)에서 뺀다
    if which == "full":
        chg = D["chg"]; old = np.array([d < "2015-06-15" for d in dates])[:, None]
        bad = np.nan_to_num(np.abs(chg)) > np.where(old, 0.155, 0.305)
        for j in range(n0, m):
            fin = np.nonzero(np.isfinite(C[:, j]))[0]
            if len(fin):
                bad[max(fin[-1] - 9, 0):fin[-1] + 1, j] = False
        D["badcum"] = np.cumsum(bad, axis=0).astype("int32")
    E0, stop = M.our_buy(D)
    LEGS = [(np.nan_to_num((C < M.ema(C, 21)).astype(float)).astype(bool), 1.0)]
    t0 = M.trades(D, E0, LEGS, stop=stop, start=260)
    W = dict(D=D, n=n, m=m, dates=dates, E0=E0, stop=stop, which=which, n0=n0)
    W["cand"] = make_cand(W, t0)
    return W


def last_idx(C):
    fin = np.isfinite(C)
    return np.where(fin.any(0), C.shape[0] - 1 - np.argmax(fin[::-1], axis=0), -1)


def make_cand(W, t0, limit_lock=True, entry="close"):
    """Candidates retain signal-date ranks and allow entry-day stop exits."""
    D, n = W["D"], W["n"]
    if entry == "open":
        signals = np.zeros_like(D["c"],dtype=bool)
        si = (t0.signal_i if "signal_i" in t0 else t0.i).to_numpy(dtype=int)
        signals[si,t0.j.to_numpy(dtype=int)] = True
        t0 = M.trades(D,signals,[(D["c"] < M.ema(D["c"],21),1.)],stop=W["stop"],start=0,entry="open")
    si = (t0.signal_i if "signal_i" in t0 else t0.i).to_numpy(dtype=int)
    i, j = t0.i.to_numpy(dtype=int), t0.j.to_numpy(dtype=int)
    xday = np.array([lg[0][0] for lg in t0.legs],dtype=int)
    xpx = np.array([lg[0][1] for lg in t0.legs],dtype=float)
    phase = t0.exit_phase.to_numpy() if "exit_phase" in t0 else np.full(len(t0),"intraday")
    # Unknown cessation remains an open position. Never invent an executable last close.
    c = pd.DataFrame({"signal_i":si,"i":i,"j":j,"px0":t0.px0.values,"risk":t0.risk.values,
                      "xday":xday,"xpx":xpx,"exit_phase":phase,"entry":entry})
    c = c[np.isfinite(c.px0) & (c.px0 > 0) & (c.risk > 0)].reset_index(drop=True)
    c["R"] = (c.xpx / c.px0 * (1 - COSTS) - (1 + COSTB)) / c.risk
    c["rs"] = np.nan_to_num(D["RS"][c.signal_i.values,c.j.values],nan=-1)
    size = D.get("size_mult")
    c["size_mult"] = size[c.signal_i.values,c.j.values] if size is not None else 1.
    return c


def orders(c, key="rs"):
    o = np.lexsort((c.j.values, -c[key].values, c.i.values)) if key == "rs" else None
    od = {}
    for r in o:
        od.setdefault(int(c.i.values[r]), []).append(r)
    return {d: np.array(v) for d, v in od.items()}


def sim(W, c, order, start, end, maxpos=10, rp=0.005, cost=1.0, rng=None, mode="risk", day_cap=None, dd_brake=None, vol_scale=None, rp_series=None):
    """빠른 계좌 시뮬. order None이면 rng로 매일 섞음. day_cap(D1) · dd_brake=(낙폭, 배수)(D2) · vol_scale=날짜별 배수 배열(D3)."""
    Cf = W["D"]["Cf"]; cb, cs = COSTB * cost, COSTS * cost
    CJ, CPX, CRK, CXD, CXP = c.j.values, c.px0.values, c.risk.values, c.xday.values.astype(int), c.xpx.values
    open_entry = bool(len(c) and (c.get("entry",pd.Series("close",index=c.index)) == "open").all())
    phase = c.get("exit_phase",pd.Series("intraday",index=c.index)).values
    sizes = c.get("size_mult",pd.Series(1.,index=c.index)).values
    day_rows = W.get("_dr")
    if day_rows is None or W.get("_drc") is not c:
        day_rows = {d: g.index.values for d, g in c.groupby("i")}; W["_dr"] = day_rows; W["_drc"] = c
    cash, pos, exits = 1.0, {}, {}
    eq = np.empty(end - start + 1); peak = 1.0; used = []
    for d in range(start, end + 1):
        deferred = []
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                if open_entry and p[3] != "open":
                    deferred.append(j)
                else:
                    cash += p[0] * p[2] * (1 - cs); del pos[j]
        marks = np.where(np.isfinite(W["D"]["o"][d]) & (W["D"]["o"][d] > 0),W["D"]["o"][d],Cf[max(0,d-1)]) if open_entry else Cf[d]
        mv = sum(p[0] * marks[j] for j, p in pos.items()); E_ = cash + mv
        peak = max(peak, E_)
        rpd = rp
        if dd_brake is not None and E_ < peak * (1 - dd_brake[0]):
            rpd = rp * dd_brake[1]
        if vol_scale is not None:
            rpd = rp * vol_scale[max(0,d-1) if open_entry else d]
        if rp_series is not None:
            rpd = float(rp_series[max(0,d-1) if open_entry else d]) if np.ndim(rp_series) else float(rp_series)
        rows = order.get(d) if order is not None else (rng.permutation(day_rows[d]) if d in day_rows else None)
        free = maxpos - len(pos); newn = 0
        if rows is not None:
            for r in rows:
                if free <= 0 or (day_cap is not None and newn >= day_cap):
                    break
                j = CJ[r]
                if j in pos:
                    continue
                val = rpd * E_ * sizes[r] / max(CRK[r],.003)
                if val <= 0:
                    continue
                if mode == "cash" and cash < val * (1 + cb):
                    continue
                cash -= val * (1 + cb); xd = int(CXD[r])
                pos[j] = (val / CPX[r], xd, CXP[r], phase[r]); exits.setdefault(xd, []).append(j); free -= 1; newn += 1; used.append(rpd)
        for j in deferred + exits.pop(d, []):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - cs); del pos[j]
        mv = sum(p[0] * Cf[d, j] for j, p in pos.items()); eq[d - start] = cash + mv
    return eq, (float(np.mean(used)) if used else rp)


def metr(eq):
    yrs = len(eq) / 245; cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1 if eq[-1] > 0 else -1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1)); r = np.diff(np.log(np.maximum(eq, 1e-12)))
    return dict(cagr=100 * cagr, mdd=100 * mdd, mar=cagr / abs(mdd) if mdd < 0 else np.nan, sharpe=float(r.mean() / r.std() * np.sqrt(245)) if r.std() > 0 else np.nan)


def sidx(W, a):
    return int(np.searchsorted(W["dates"], a))


def eidx(W, b):
    return int(np.searchsorted(W["dates"], b, side="right")) - 1


def yearly(W, eq, start):
    ds = W["dates"][start:start + len(eq)]
    s = pd.Series(eq, index=pd.to_datetime(ds))
    return s.resample("YE").last().pct_change().dropna().rename(lambda x: x.year) if len(s) else pd.Series(dtype=float)


def market_vol_scale(W):
    """D3: 0.5% × min(1, 과거 3년(t−1까지) 시장 20일 변동성 중앙값 / 오늘 시장 20일 변동성). 시장 = 같은 무게 지수."""
    mk = pd.Series(W["D"]["mk"])
    rv = mk.rolling(20).std()
    med = rv.shift(1).rolling(735, min_periods=250).median()
    return np.nan_to_num(np.minimum(1.0, (med / rv).values), nan=1.0)
