"""① RS 순서 레드팀 + ② 계좌 낙폭 줄이기 — Claude 사전등록(prereg_claude_redteam_dd.md) 실행부 (2026-10-10 KST).
GPT 설계는 GPT 답을 받은 뒤 같은 데이터·같은 시뮬로 덧붙인다(redteam_gpt.py).
사용: from redteam_lab import build ; W = build("full") 또는 build("orig")
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np, pandas as pd
import ma_lab as M

COSTB, COSTS = M.COST_BUY, M.COST_SELL


def build(which="full"):
    M.CACHE = "/home/junp/tmp_claude/ma_lab_cache_full.npz" if which == "full" else "/home/junp/tmp_claude/ma_lab_cache.npz"
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
    D, n = W["D"], W["n"]; O, H, L, C = D["o"], D["h"], D["l"], D["c"]
    xday = np.array([lg[0][0] for lg in t0.legs]); xpx = np.array([lg[0][1] for lg in t0.legs], dtype=float)
    i, j = t0.i.values, t0.j.values
    li = last_idx(C)
    # 폐지(데이터 끝) 뒤로 넘어간 정리 = 마지막 거래일 종가
    over = (xday > li[j]) & (li[j] < n - 1)
    xday = np.where(over, li[j], xday); xpx = np.where(over, D["Cf"][np.minimum(li[j], n - 1), j], xpx)
    if limit_lock:                               # T2: 정리 날이 하한가 잠김이면 다음 잠기지 않은 날 시가
        chg = D["chg"]
        locked = (np.nan_to_num(H) == np.nan_to_num(L)) & (np.nan_to_num(chg) <= -0.29) & np.isfinite(C)
        for k in range(len(xday)):
            d = xday[k]
            if d < n and locked[d, j[k]]:
                dd = d
                while dd < n - 1 and (locked[dd, j[k]] or not np.isfinite(O[dd, j[k]])) and dd < li[j[k]]:
                    dd += 1
                xday[k] = dd; xpx[k] = float(O[dd, j[k]]) if np.isfinite(O[dd, j[k]]) else float(D["Cf"][dd, j[k]])
    px0 = t0.px0.values.astype(float); risk = t0.risk.values.astype(float)
    if entry == "open":
        o1 = O[np.minimum(i + 1, n - 1), j]; st = W["stop"][i, j]
        ok = np.isfinite(o1) & (o1 > 0)
        px0 = np.where(ok, o1, np.nan); risk = np.where(ok & (o1 > st), 1 - st / o1, 0.01)
        xpx = np.where(ok & (o1 <= st), o1, xpx)
        i = i + 1
    c = pd.DataFrame({"i": i, "j": j, "px0": px0, "risk": risk, "xday": np.maximum(xday, i + 1), "xpx": xpx})
    c = c[np.isfinite(c.px0) & (c.px0 > 0)].reset_index(drop=True)
    c["R"] = (c.xpx / c.px0 - 1 - COSTB - COSTS) / c.risk
    c["rs"] = np.nan_to_num(D["RS"][np.minimum(c.i.values, n - 1), c.j.values], nan=-1)
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
    day_rows = W.get("_dr")
    if day_rows is None or W.get("_drc") is not c:
        day_rows = {d: g.index.values for d, g in c.groupby("i")}; W["_dr"] = day_rows; W["_drc"] = c
    cash, pos, exits = 1.0, {}, {}
    eq = np.empty(end - start + 1); peak = 1.0; used = []
    for d in range(start, end + 1):
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - cs); del pos[j]
        mv = sum(p[0] * Cf[d, j] for j, p in pos.items()); E_ = cash + mv
        peak = max(peak, E_)
        rpd = rp
        if dd_brake is not None and E_ < peak * (1 - dd_brake[0]):
            rpd = rp * dd_brake[1]
        if vol_scale is not None:
            rpd = rp * vol_scale[d]
        if rp_series is not None:
            rpd = rp_series
        rows = order.get(d) if order is not None else (rng.permutation(day_rows[d]) if d in day_rows else None)
        free = maxpos - len(pos); newn = 0
        if rows is not None:
            for r in rows:
                if free <= 0 or (day_cap is not None and newn >= day_cap):
                    break
                j = CJ[r]
                if j in pos:
                    continue
                val = rpd * E_ / CRK[r]
                if mode == "cash" and cash < val * (1 + cb):
                    continue
                cash -= val * (1 + cb); xd = int(CXD[r])
                pos[j] = (val / CPX[r], xd, CXP[r]); exits.setdefault(xd, []).append(j); free -= 1; newn += 1; used.append(rpd)
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
