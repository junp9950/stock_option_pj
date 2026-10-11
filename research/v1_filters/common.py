"""V1 필터 검증 공용 (2026-10-11 KST) — 계좌 시뮬(redteam_run.sim2 기본형 그대로)·통계 도구.
s1_build.py가 만든 cand.pkl / Cf.npy / dates.npy 를 읽는다."""
import numpy as np, pandas as pd

OUT = "/home/junp/tmp_claude/v1_filters"
CB, CS = 0.0005, 0.0025


def load():
    c = pd.read_pickle(f"{OUT}/cand.pkl")
    Cf = np.load(f"{OUT}/Cf.npy", mmap_mode="r")
    dates = np.load(f"{OUT}/dates.npy")
    return c, Cf, dates


def orders(c, keys=None):
    """keys: 추가 우선 키(오름차순, 먼저 적은 게 우선) 목록. 기본 RS 내림차순 → 종목 j."""
    ks = [c.j.values, -c.rs.values]
    if keys:
        ks += list(keys)[::-1]
    ks.append(c.i.values)
    o = np.lexsort(tuple(ks))
    od = {}
    for r in o:
        od.setdefault(int(c.i.values[r]), []).append(r)
    return {d: np.array(v) for d, v in od.items()}


def sim(c, order, Cf, start, end, rp=0.005, maxpos=10, size=None):
    """redteam_run.sim2 (overlay 없음, mode=risk, 종가 진입)과 같은 계산. size: 행별 추가 배수(필터 절반 등).
    반환 eq, 진입한 행 목록."""
    CJ, CPX, CRK, CXD, CXP = c.j.values, c.px0.values, c.risk.values, c.xday.values.astype(int), c.xpx.values
    sizes = c.size_mult.values * (1.0 if size is None else size)
    cash, pos, exits = 1.0, {}, {}
    eq = np.empty(end - start + 1); ent = []
    for d in range(start, end + 1):
        for j in exits.pop(d, ()):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - CS); del pos[j]
        cf = Cf[d]
        E_ = cash + sum(p[0] * cf[j] for j, p in pos.items())
        rows = order.get(d)
        free = maxpos - len(pos)
        if rows is not None:
            for r in rows:
                if free <= 0:
                    break
                j = CJ[r]
                if j in pos:
                    continue
                val = rp * E_ * sizes[r] / max(CRK[r], .003)
                if val <= 0:
                    continue
                cash -= val * (1 + CB); xd = int(CXD[r])
                pos[j] = (val / CPX[r], xd, CXP[r]); exits.setdefault(xd, []).append(j); free -= 1; ent.append(r)
        for j in exits.pop(d, []):
            p = pos.get(j)
            if p is not None and p[1] == d:
                cash += p[0] * p[2] * (1 - CS); del pos[j]
        eq[d - start] = cash + sum(p[0] * cf[j] for j, p in pos.items())
    return eq, ent


def metr(eq):
    yrs = len(eq) / 245; cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1 if eq[-1] > 0 else -1
    mdd = float(np.min(eq / np.maximum.accumulate(eq) - 1)); r = np.diff(np.log(np.maximum(eq, 1e-12)))
    return dict(cagr=100 * cagr, mdd=100 * mdd, mar=cagr / abs(mdd) if mdd < 0 else np.nan,
                sharpe=float(r.mean() / r.std() * np.sqrt(245)) if r.std() > 0 else np.nan)


def sidx(dates, a):
    return int(np.searchsorted(dates, a))


def eidx(dates, b):
    return int(np.searchsorted(dates, b, side="right")) - 1


def first_only(c):
    """같은 종목은 앞 거래 청산 뒤 신호부터 (신호 품질 비교용, ma_lab.first_only와 같은 규칙)."""
    s = c.sort_values(["j", "i"])
    keep = []; last_j, free = -1, -1
    for idx, i, j, ex in zip(s.index.values, s.i.values, s.j.values, s.xday.values):
        if j != last_j:
            last_j, free = j, -1
        if i >= free:
            keep.append(idx); free = ex
    return c.loc[sorted(keep)]


def desc(g):
    if len(g) == 0:
        return "   0건"
    return f"{len(g):5d}건 R {g.R.mean():+.3f} 순 {100 * g.net.mean():+.2f}% 이김 {100 * (g.net > 0).mean():.0f}%"


def boot_diff(df, flag, nb=5000, seed=1, col="R"):
    """날짜 묶음 부트스트랩: 날짜를 복원 추출, 묶음 안 신호 전부 → (flag 평균 − 비flag 평균) 95% 구간."""
    g = df.groupby("date")
    days = list(g.groups.keys())
    a_sum = g.apply(lambda x: x.loc[x[flag], col].sum()).reindex(days).values
    a_n = g.apply(lambda x: x[flag].sum()).reindex(days).values
    b_sum = g.apply(lambda x: x.loc[~x[flag], col].sum()).reindex(days).values
    b_n = g.apply(lambda x: (~x[flag]).sum()).reindex(days).values
    rng = np.random.default_rng(seed); out = []
    for _ in range(nb // 500):
        ix = rng.integers(0, len(days), (500, len(days)))
        out.append(a_sum[ix].sum(1) / np.maximum(a_n[ix].sum(1), 1) - b_sum[ix].sum(1) / np.maximum(b_n[ix].sum(1), 1))
    out = np.concatenate(out)
    obs = df.loc[df[flag], col].mean() - df.loc[~df[flag], col].mean()
    return obs, np.percentile(out, 2.5), np.percentile(out, 97.5)
