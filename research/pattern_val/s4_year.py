"""연도별 안정성: 기본조건·상승횡보장에서 응축 있음−없음 (추세청산 순수익 rt, R) — 20일 신고가·박스(site)."""
import numpy as np, pandas as pd
exec(open("/home/junp/tmp_claude/pattern_val/s3_eval.py").read().split("if PER ==")[0].replace('PER = sys.argv[1] if len(sys.argv) > 1 else "dev"', 'PER="all"'))
df["R"] = df.rt / df.sd; df["yr"] = df.date.str[:4]
u = df.base & (df.state >= 1)
for g in ("hi20", "box_site", "tri_conv"):
    e = df[u & G[g]].dropna(subset=["rt"])
    a = e[e.sqprev].groupby("yr").agg(n=("rt", "size"), rt=("rt", "mean"), R=("R", "mean"))
    b = e[~e.sqprev].groupby("yr").agg(n=("rt", "size"), rt=("rt", "mean"), R=("R", "mean"))
    t = a.join(b, lsuffix="_sq", rsuffix="_no"); t["dR"] = t.R_sq - t.R_no; t["drt%"] = (t.rt_sq - t.rt_no) * 100
    print(f"\n[{g}] 응축 있음−없음 연도별"); print(t[["n_sq", "n_no", "drt%", "dR"]].round(2).to_string())
    print("dR>0 연도 수:", int((t.dR > 0).sum()), "/", len(t))
