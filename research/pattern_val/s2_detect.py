"""2단계(numba venv): 날짜별(그날까지 데이터만) 모양 돌파 찾기 + 결과(고정 보유·추세 청산) 계산 → events.pkl
모양 정의는 backend/main.py chartPatterns()를 옮긴 것.
- 응축: BB(20, 2σ) 폭 4·std/mean ≤ 최근 120일 폭의 아래 20% (60개↑)
- 박스: 몸통(시가·종가 max/min) 폭 ≤ thr 로 가장 길게(20~150일). thr = clip(ATR%중간값(249일)×6, 12%, 16%)  (JS: min(BW,0.16), BW=max(.12,min(.25,..)))
    box_simple: t-1에서 끝나는 박스(20일↑) + C[t] > hi×1.005
    box_site  : + t에서 끝나는 20일↑ 박스가 없음(사이트 화면이 '상단 돌파'로 보여 주는 경우)
- 추세선: t-1까지 데이터로 몸통 고점·저점 피벗(k=3, 끝은 잘린 창) → 선(닿음 3↑, 1.5% 넘는 몸통 없음, 점수=닿음+길이/25, 상위 12)
    → 위·아래 짝 중 모양(수렴/채널)이고 t에 돌파/이탈한 것 중 점수 최고(JS j>0 규칙) → 위로 돌파면 기록 (+ C[t-1] ≤ 선×1.005 = 새 돌파)
"""
import numpy as np, pandas as pd, numba as nb, time, sys

T0 = time.time()
def log(*a): print(f"{time.time()-T0:7.1f}s", *a, flush=True)

z = np.load("/home/junp/tmp_claude/pattern_val/data.npz", allow_pickle=True)
dates = z["dates"]; n, m = z["c"].shape
O, H, L, C, V = (z[k].astype("float64") for k in "ohlcv")
tv20 = z["tv20"]; Cf = z["Cf"].astype("float64"); badcum = z["badcum"]
e20, e21, e60 = (z[k].astype("float64") for k in ("e20", "e21", "e60"))
state = z["state"]
log("loaded", n, m)

BH = np.fmax(O, C); BL = np.fmin(O, C)
BH[~(np.isfinite(O) & np.isfinite(C))] = np.nan; BL[~(np.isfinite(O) & np.isfinite(C))] = np.nan

START = 260
liq = np.nan_to_num(tv20) >= 3e9
prevC = np.vstack([np.full((1, m), np.nan), C[:-1]])
with np.errstate(invalid="ignore"):
    cand = liq & np.isfinite(C) & np.isfinite(O) & np.isfinite(H) & np.isfinite(L)
cand[:START] = False; cand[n - 1] = False


@nb.njit(cache=True)
def squeeze_col(c):
    n = c.shape[0]
    bw = np.full(n, np.nan); sq = np.zeros(n, np.bool_)
    for i in range(19, n):
        s = 0.0; ok = True
        for j in range(i - 19, i + 1):
            if not np.isfinite(c[j]): ok = False; break
            s += c[j]
        if not ok: continue
        mu = s / 20; v = 0.0
        for j in range(i - 19, i + 1): v += (c[j] - mu) ** 2
        bw[i] = 4 * np.sqrt(v / 20) / mu
    buf = np.empty(120)
    for i in range(60, n):
        if not np.isfinite(bw[i]): continue
        k = 0
        for j in range(max(19, i - 119), i + 1):
            if np.isfinite(bw[j]): buf[k] = bw[j]; k += 1
        if k < 60: continue
        w = np.sort(buf[:k])
        if bw[i] <= w[int(np.floor(k * 0.2))]: sq[i] = True
    return sq


@nb.njit(cache=True)
def box_at(bh, bl, e, thr):
    """e에서 끝나는 가장 긴 박스(최대 150일). 반환 (N, hi, lo); 끝 봉이 NaN이면 N=0."""
    if not (np.isfinite(bh[e]) and np.isfinite(bl[e])): return 0, np.nan, np.nan
    hi = bh[e]; lo = bl[e]; N = 1
    i = e - 1
    while i >= 1 and N < 150:         # JS: N ≤ e  → s0 ≥ 1
        if not (np.isfinite(bh[i]) and np.isfinite(bl[i])): break
        h2 = max(hi, bh[i]); l2 = min(lo, bl[i])
        if h2 / l2 - 1 > thr: break
        hi = h2; lo = l2; N += 1; i -= 1
    return N, hi, lo


@nb.njit(cache=True)
def thr_at(h, l, c, t):
    k = 0; buf = np.empty(249)
    for i in range(max(1, t - 248), t + 1):
        if np.isfinite(h[i]) and np.isfinite(l[i]) and np.isfinite(c[i - 1]) and c[i - 1] > 0:
            buf[k] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) / c[i - 1]; k += 1
    med = 0.025 if k == 0 else np.sort(buf[:k])[k // 2]
    bw = max(0.12, min(0.25, med * 6))
    return min(bw, 0.16)


@nb.njit(cache=True)
def fit(P, np_, V, up, e):
    """JS fit(): 상위 12개 선 (a, sl, v0, score)."""
    A = np.empty(4000, np.int64); SL = np.empty(4000); SC = np.empty(4000); k = 0
    P2 = np.empty(np_, np.int64); q = 0
    for x in range(np_):
        if P[x] <= e - 1 and P[x] >= e - 110: P2[q] = P[x]; q += 1
    for x in range(q):
        for y in range(q - 1, x, -1):
            a = P2[x]; b = P2[y]
            if b - a < 10 or e - b > 40: continue
            sl = (V[b] - V[a]) / (b - a); ok = True; touch = 0
            for i in range(a, e + 1):
                ln = V[a] + sl * (i - a)
                if ln <= 0: ok = False; break
                r = V[i] / ln
                if up:
                    if r > 1.015: ok = False; break
                    if r >= 0.98: touch += 1
                else:
                    if r < 0.985: ok = False; break
                    if r <= 1.02: touch += 1
            if not ok or touch < 3: continue
            if k < 4000:
                A[k] = a; SL[k] = sl; SC[k] = touch + (b - a) / 25.0; k += 1
    order = np.argsort(-SC[:k], kind="mergesort")[:12]
    return A[order], SL[order], SC[order]


@nb.njit(cache=True)
def tri_at(bh, bl, c, t):
    """t-1까지로 맞춘 모양 + t 돌파 판정. 반환 (kind, brk, lineU_t, g0, g1, sc). kind 0=없음,
    1 대칭삼각 2 상승삼각 3 하락삼각 4 하락쐐기 5 상승쐐기 6 수렴 7 상승채널 8 하락채널; brk 1=위 -1=아래 0=없음"""
    e = t - 1
    lo_i = e - 115
    if lo_i < 3: return 0, 0, np.nan, np.nan, np.nan, np.nan
    for i in range(lo_i, t + 1):
        if not (np.isfinite(bh[i]) and np.isfinite(bl[i]) and np.isfinite(c[i])): return 0, 0, np.nan, np.nan, np.nan, np.nan
    PH = np.empty(120, np.int64); PL = np.empty(120, np.int64); nh = 0; nl = 0
    for i in range(e - 110, e):          # 피벗 i ≤ e-1, 창은 e까지만 (그날까지 데이터)
        isH = True; isL = True
        for j in range(max(0, i - 3), min(e, i + 3) + 1):
            if bh[j] > bh[i]: isH = False
            if bl[j] < bl[i]: isL = False
        if isH: PH[nh] = i; nh += 1
        if isL: PL[nl] = i; nl += 1
    UA, USL, USC = fit(PH, nh, bh, True, e)
    DA, DSL, DSC = fit(PL, nl, bl, False, e)
    best = -1.0; bk = 0; bb = 0; bU = np.nan; bg0 = np.nan; bg1 = np.nan; bUe = np.nan
    for u in range(UA.shape[0]):
        for d in range(DA.shape[0]):
            ua = UA[u]; da = DA[d]
            if abs(ua - da) > 0.6 * (e - min(ua, da)): continue
            uv0 = bh[ua]; dv0 = bl[da]; usl = USL[u]; dsl = DSL[d]
            s0 = max(ua, da)
            g0 = (uv0 + usl * (s0 - ua)) / (dv0 + dsl * (s0 - da)) - 1
            g1 = (uv0 + usl * (e - ua)) / (dv0 + dsl * (e - da)) - 1
            su = usl / c[e] * 100; sd = dsl / c[e] * 100
            lu = uv0 + usl * (t - ua); ld = dv0 + dsl * (t - da)
            brk = 1 if c[t] > lu * 1.005 else (-1 if c[t] < ld * 0.995 else 0)
            if brk == 0: continue
            kind = 0
            if g1 > 0 and g1 < g0 * 0.75 and g0 <= 0.6:
                if su < -0.05 and sd > 0.05: kind = 1
                elif abs(su) <= 0.05 and sd > 0.05: kind = 2
                elif su < -0.05 and abs(sd) <= 0.05: kind = 3
                elif su < 0 and sd < 0: kind = 4
                elif su > 0 and sd > 0: kind = 5
                else: kind = 6
            elif g1 > 0 and g0 <= 0.4 and abs(g1 - g0) <= g0 * 0.25:
                if su > 0.05 and sd > 0.05: kind = 7
                elif su < -0.05 and sd < -0.05: kind = 8
            if kind == 0: continue
            sc = USC[u] + DSC[d]
            if best < 0 or sc > best:
                best = sc; bk = kind; bb = brk; bU = lu; bg0 = g0; bg1 = g1
                bUe = uv0 + usl * (e - ua)
    if bk == 0: return 0, 0, np.nan, np.nan, np.nan, np.nan
    if bb == 1 and c[e] > bUe * 1.005: bb = 2      # 전날 이미 선 위 = 새 돌파 아님
    return bk, bb, bU, bg0, bg1, best


@nb.njit(cache=True)
def detect_col(bh, bl, h, l, c, cnd):
    n = c.shape[0]
    bs = np.zeros(n, np.int8); bsi = np.zeros(n, np.int8); bN = np.zeros(n, np.int16)
    tk = np.zeros(n, np.int8); tb = np.zeros(n, np.int8)
    for t in range(1, n):
        if not cnd[t]: continue
        thr = thr_at(h, l, c, t)
        N1, hi1, lo1 = box_at(bh, bl, t - 1, thr)
        if N1 >= 20 and c[t] > hi1 * 1.005:
            bs[t] = 1; bN[t] = N1
            N0, _, _ = box_at(bh, bl, t, thr)
            if N0 < 20: bsi[t] = 1
        if c[t] > c[t - 1]:
            k, b, lu, g0, g1, sc = tri_at(bh, bl, c, t)
            if k > 0 and b >= 1:
                tk[t] = k; tb[t] = b
    return bs, bsi, bN, tk, tb


@nb.njit(cache=True)
def outcome_col(o, h, l, c, cf, e21, bc, t, HMAX):
    """종가 진입. 반환 r5, r10, r20 (순수익), 추세 청산 순수익·보유일·손절폭. 오류 봉 걸치면 NaN."""
    n = c.shape[0]; px0 = c[t]; cb = 1.0005; cs = 0.9975
    res = np.full(6, np.nan)
    for q, hh in enumerate((5, 10, 20)):
        d = min(t + hh, n - 1)
        if t + hh <= n - 1 and bc[d] == bc[t]:
            res[q] = cf[d] * cs / (px0 * cb) - 1
    st = l[t] * 0.99
    res[5] = 1 - st / px0
    # 마지막 거래일(상장폐지 처리)
    last = n - 1
    while last > t and not np.isfinite(c[last]): last -= 1
    xd = -1; xp = np.nan; kend = min(n - 1, t + HMAX)
    k = t + 1
    while k <= kend:
        if k > last:                       # 상장폐지: 마지막 거래일 종가
            xd = last; xp = c[last]; break
        if np.isfinite(l[k]):
            if l[k] < st:
                xd = k; xp = min(o[k], st) if np.isfinite(o[k]) else st; break
            if c[k] < e21[k]:
                d2 = k + 1
                while d2 <= last and not np.isfinite(o[d2]): d2 += 1
                if d2 > last:
                    xd = last; xp = c[last]
                else:
                    xd = d2; xp = o[d2]
                break
        k += 1
    if xd < 0:                             # 최대 보유(250일) 또는 데이터 끝 → 그날 종가로 평가
        xd = kend; xp = cf[kend]
    if bc[xd] == bc[t] and np.isfinite(xp):
        res[3] = xp * cs / (px0 * cb) - 1; res[4] = xd - t
    return res


@nb.njit(cache=True)
def outcomes(o, h, l, c, cf, e21, bc, ti, ji, HMAX):
    out = np.full((ti.shape[0], 6), np.nan)
    for q in range(ti.shape[0]):
        t = ti[q]; j = ji[q]
        out[q] = outcome_col(o[:, j], h[:, j], l[:, j], c[:, j], cf[:, j], e21[:, j], bc[:, j], t, HMAX)
    return out


SQ = np.zeros((n, m), bool)
BS = np.zeros((n, m), np.int8); BSI = np.zeros((n, m), np.int8); BN = np.zeros((n, m), np.int16)
TK = np.zeros((n, m), np.int8); TB = np.zeros((n, m), np.int8)
LIM = int(sys.argv[1]) if len(sys.argv) > 1 else m
if LIM < m: cand[:, LIM:] = False
for j in range(LIM):
    if not cand[:, j].any(): continue
    SQ[:, j] = squeeze_col(np.ascontiguousarray(C[:, j]))
    BS[:, j], BSI[:, j], BN[:, j], TK[:, j], TB[:, j] = detect_col(np.ascontiguousarray(BH[:, j]), np.ascontiguousarray(BL[:, j]),
                                                                  np.ascontiguousarray(H[:, j]), np.ascontiguousarray(L[:, j]),
                                                                  np.ascontiguousarray(C[:, j]), np.ascontiguousarray(cand[:, j]))
    if j % 300 == 0: log("col", j, "box", int(BS.sum()), "tri", int((TK > 0).sum()))
log("detect done")

Cd = pd.DataFrame(C); Vd = pd.DataFrame(V)
hi20 = (Cd > Cd.shift(1).rolling(20, min_periods=20).max()).values
volx = (Vd / Vd.shift(1).rolling(20, min_periods=20).mean()).values
sqprev = pd.DataFrame(SQ.astype(float)).shift(1).rolling(5, min_periods=1).max().fillna(0).values > 0   # t-5..t-1 중 응축
with np.errstate(invalid="ignore"):
    base = (C > e20) & (e20 > e60)

ti, ji = np.nonzero(cand)
log("rows", len(ti))
res = outcomes(O, H, L, C, Cf, e21, badcum, ti.astype(np.int64), ji.astype(np.int64), 250)
log("outcomes done")
df = pd.DataFrame({"t": ti.astype("int32"), "j": ji.astype("int32"), "base": base[ti, ji], "state": state[ti],
                   "box": BS[ti, ji], "box_site": BSI[ti, ji], "boxN": BN[ti, ji], "tri": TK[ti, ji], "tri_b": TB[ti, ji],
                   "sq": SQ[ti, ji], "sqprev": sqprev[ti, ji], "hi20": hi20[ti, ji], "volx": volx[ti, ji].astype("float32"),
                   "r5": res[:, 0], "r10": res[:, 1], "r20": res[:, 2], "rt": res[:, 3], "hold": res[:, 4], "sd": res[:, 5]})
df["date"] = dates[df.t.values]
df.to_pickle("/home/junp/tmp_claude/pattern_val/events.pkl" if LIM == m else "/home/junp/tmp_claude/pattern_val/events_test.pkl")
log("saved", df.shape, "box", int(df.box.sum()), "box_site", int(df.box_site.sum()), "tri(new)", int((df.tri_b == 1).sum()),
    "hi20", int(df.hi20.sum()))
print(df[df.tri_b == 1].tri.value_counts().sort_index())
