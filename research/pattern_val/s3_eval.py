"""3단계: 모양 돌파 vs 기준선(같은 날 무작위 = 그날 기본 조건 종목 전체 평균, 같은 날 20일 신고가 돌파) — 날짜 묶음 부트스트랩.
사용: python s3_eval.py dev   (2015-07~2022)   /   python s3_eval.py test  (2023~, 한 번만)
"""
import sys, numpy as np, pandas as pd

PER = sys.argv[1] if len(sys.argv) > 1 else "dev"
df = pd.read_pickle("/home/junp/tmp_claude/pattern_val/events.pkl")
df["R"] = df.rt / df.sd
df["up"] = df.state >= 1
COOL = 10

# 같은 종목 10거래일 안 같은 모양 돌파는 첫 번째만
def cool(flag):
    f = df[flag][["j", "t"]].sort_values(["j", "t"])
    keep = np.ones(len(f), bool); lastj, lastt = -1, -10**9
    for k, (j, t) in enumerate(zip(f.j.values, f.t.values)):
        if j != lastj:
            lastj = j; lastt = t
        elif t - lastt <= COOL:
            keep[k] = False
        else:
            lastt = t
    out = pd.Series(False, index=df.index); out.loc[f.index[keep]] = True
    return out

G = {}
G["hi20"] = cool(df.hi20)
G["box_site"] = cool(df.box_site == 1)
G["box_simple"] = cool(df.box == 1)
G["tri_all"] = cool(df.tri_b == 1)
G["tri_conv"] = cool((df.tri_b == 1) & df.tri.between(1, 6))
G["tri_tri"] = cool((df.tri_b == 1) & df.tri.between(1, 3))
G["tri_wedge"] = cool((df.tri_b == 1) & df.tri.between(4, 5))
G["chan_up"] = cool((df.tri_b == 1) & (df.tri == 7))
G["chan_dn"] = cool((df.tri_b == 1) & (df.tri == 8))
G["sq_brk"] = cool(df.sqprev & df.hi20)
vol = df.volx >= 1.5
for k in ("box_site", "box_simple", "tri_all", "tri_conv", "chan_up", "hi20"):
    G[k + "+sq"] = G[k] & df.sqprev
    G[k + "-sq"] = G[k] & ~df.sqprev
    G[k + "+vol"] = G[k] & vol
    G[k + "-vol"] = G[k] & ~vol
G["sq_brk+vol"] = G["sq_brk"] & vol

if PER == "dev":
    pm = df.date < "2023-01-01"
else:
    pm = df.date >= "2023-01-01"

MET = ["r5", "r10", "r20", "rt", "R"]
rng = np.random.default_rng(0)

def boot(d, t, B=2000):
    s = pd.DataFrame({"t": t, "d": d}).groupby("t").d.agg(["sum", "count"])
    S, N = s["sum"].values, s["count"].values; k = len(S)
    idx = rng.integers(0, k, size=(B, k))
    est = S[idx].sum(1) / N[idx].sum(1)
    return np.percentile(est, [2.5, 97.5])

lines = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)

def report(uni_name, uni):
    sub = df[pm & uni]
    # 기준선: 같은 날 기본 조건(종가>EMA20>EMA60 · 유동성) 종목 전체 평균 / 같은 날 20일 신고가 돌파 평균
    rnd = df[pm & df.base & uni_reg].groupby("t")[MET].mean()
    h20 = df[pm & uni & G["hi20"]].groupby("t")[MET].mean()
    P(f"\n### {PER} · {uni_name}")
    P(f"{'group':16s} {'n':>6s} {'r5':>6s} {'r10':>6s} {'r20':>6s} {'승10':>5s} | {'추세청산':>7s} {'승':>4s} {'R':>6s} {'보유':>4s} || "
      f"{'Δr10 vsRND [95%CI]':>24s} {'ΔR vsRND [95%CI]':>24s} || {'Δr10 vsH20 [95%CI]':>24s} {'ΔR vsH20 [95%CI]':>24s}")
    rows = []
    for name, g in G.items():
        e = sub[g[sub.index]].dropna(subset=["r10", "rt"])
        if len(e) < 30: P(f"{name:16s} {len(e):6d}  (표본 적음)"); continue
        r = dict(group=name, n=len(e), r5=e.r5.mean(), r10=e.r10.mean(), r20=e.r20.mean(), w10=(e.r10 > 0).mean(),
                 rt=e.rt.mean(), wt=(e.rt > 0).mean(), R=e.R.mean(), hold=e.hold.mean(), Rmed=e.R.median())
        out = []
        for bn, bl in (("RND", rnd), ("H20", h20)):
            for mtr in ("r10", "R", "r20", "rt", "r5"):
                bv = bl[mtr].reindex(e.t.values).values
                ok = np.isfinite(bv) & np.isfinite(e[mtr].values)
                d = e[mtr].values[ok] - bv[ok]
                lo, hi = boot(d, e.t.values[ok]) if ok.sum() > 10 else (np.nan, np.nan)
                r[f"d{mtr}_{bn}"] = d.mean(); r[f"d{mtr}_{bn}_lo"] = lo; r[f"d{mtr}_{bn}_hi"] = hi
            out.append(f"{r[f'dr10_{bn}']*100:+5.2f}% [{r[f'dr10_{bn}_lo']*100:+5.2f},{r[f'dr10_{bn}_hi']*100:+5.2f}] "
                       f"{r[f'dR_{bn}']:+5.2f} [{r[f'dR_{bn}_lo']:+5.2f},{r[f'dR_{bn}_hi']:+5.2f}]")
        rows.append(r)
        P(f"{name:16s} {len(e):6d} {r['r5']*100:+5.2f}% {r['r10']*100:+5.2f}% {r['r20']*100:+5.2f}% {r['w10']*100:4.0f}% | "
          f"{r['rt']*100:+6.2f}% {r['wt']*100:3.0f}% {r['R']:+5.2f} {r['hold']:4.0f} || {out[0]} || {out[1]}")
    # 기준선 자체
    rb = df[pm & df.base & uni_reg].dropna(subset=["r10", "rt"])
    P(f"{'(RND base 전체)':16s} {len(rb):6d} {rb.r5.mean()*100:+5.2f}% {rb.r10.mean()*100:+5.2f}% {rb.r20.mean()*100:+5.2f}% "
      f"{(rb.r10>0).mean()*100:4.0f}% | {rb.rt.mean()*100:+6.2f}% {(rb.rt>0).mean()*100:3.0f}% {rb.R.mean():+5.2f} {rb.hold.mean():4.0f}")
    return pd.DataFrame(rows).assign(uni=uni_name, per=PER)

def contrast(uni_name, uni):
    """같은 모양 안에서 (조건 있음) − (조건 없음) 평균 차이, 날짜 묶음 부트스트랩."""
    P(f"\n### {PER} · {uni_name} · 조건 대비 (있음 − 없음)")
    sub = df[pm & uni]
    for gname in ("box_site", "box_simple", "tri_all", "tri_conv", "hi20"):
        for cn, cflag in (("응축(t-5~t-1)", df.sqprev), ("거래량1.5배", vol)):
            e = sub[G[gname][sub.index]].dropna(subset=["r10", "rt"])
            a = e[cflag[e.index]]; b = e[~cflag[e.index]]
            txt = []
            for mtr in ("r10", "r20", "R"):
                obs = a[mtr].mean() - b[mtr].mean()
                days = np.unique(e.t.values); k = len(days)
                ga = a.groupby("t")[mtr].agg(["sum", "count"]).reindex(days, fill_value=0)
                gb = b.groupby("t")[mtr].agg(["sum", "count"]).reindex(days, fill_value=0)
                idx = rng.integers(0, k, size=(1000, k))
                est = ga["sum"].values[idx].sum(1) / ga["count"].values[idx].sum(1) - gb["sum"].values[idx].sum(1) / gb["count"].values[idx].sum(1)
                lo, hi = np.percentile(est, [2.5, 97.5])
                f = 100 if mtr != "R" else 1
                txt.append(f"{mtr} {obs*f:+.2f} [{lo*f:+.2f},{hi*f:+.2f}]")
            P(f"{gname:11s} {cn:14s} n {len(a):5d}/{len(b):5d} | " + " | ".join(txt))

allrows = []
for regn, reg in (("상승·횡보장", df.up), ("하락장", ~df.up), ("전체 국면", pd.Series(True, index=df.index))):
    uni_reg = reg
    allrows.append(report(f"기본조건(종가>EMA20>EMA60) · {regn}", df.base & reg))
uni_reg = df.up
allrows.append(report("유동성만(추세 조건 없음) · 상승·횡보장", df.up))
uni_reg = df.up
contrast("기본조건 · 상승·횡보장", df.base & df.up)
contrast("기본조건 · 전체 국면", df.base)
pd.concat(allrows).to_csv(f"/home/junp/tmp_claude/pattern_val/stats_{PER}.csv", index=False)
open(f"/home/junp/tmp_claude/pattern_val/out_{PER}.txt", "w").write("\n".join(lines))
