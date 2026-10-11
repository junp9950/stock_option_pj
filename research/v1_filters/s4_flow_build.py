"""시험 A 준비: 종목별 투자자 순매수(spot_investor_flows) → V1.0 신호마다 수급 특징 (2026-10-11 KST).
자료 확인 결과(이 스크립트 첫 부분 출력):
  - 기간 2026-01-02 ~ 2026-10-08 (189거래일)뿐. 1~4월은 큰 종목 ~200개, 5월부터 늘어 7월~ 약 2,000개.
  - 단위: 2026-04-06까지는 '주식 수', 04-07부터 '원' → 주식 수 날은 종가를 곱해 원으로 바꿈.
  - 04-02 · 09-22 · 10-01 · 10-02 등 값이 반 넘게 0인 날(장중 일부 수집·실패) → 빈 날로 처리. 남은 0 값은 그대로(실제 0일 수 있음).
특징(t일까지 자료만): 외국인/기관/합계 순매수 1·5·20일 합 ÷ 20일 평균 거래대금(t 포함). 20일은 15일↑ 있을 때만(빈 날 빼고 평균×20).
"""
import sys
sys.path.insert(0, "/home/junp/tmp_claude/v1_filters")
import os
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
import common as CM

eng = create_engine(os.environ["DATABASE_URL"])
with eng.connect() as cx:
    f = pd.DataFrame(cx.execute(text("select stock_code, trading_date, foreign_net_buy, institution_net_buy from spot_investor_flows")).all(),
                     columns=["code", "d", "fo", "ins"])
    p = pd.DataFrame(cx.execute(text("select stock_code, trading_date, close_price, trading_value from spot_daily_prices where trading_date >= '2025-11-01'")).all(),
                     columns=["code", "d", "c", "tv"])
f["d"] = pd.to_datetime(f.d); p["d"] = pd.to_datetime(p.d)
f = f.merge(p, on=["code", "d"], how="left")
share_days = f.d <= "2026-04-06"
f.loc[share_days, "fo"] = f.loc[share_days, "fo"] * f.loc[share_days, "c"]
f.loc[share_days, "ins"] = f.loc[share_days, "ins"] * f.loc[share_days, "c"]
zero_day = ((f.fo == 0) & (f.ins == 0)).groupby(f.d).mean() >= 0.5      # 반 넘게 0 = 장중 일부만 받았거나 실패
bad_days = list(zero_day[zero_day].index.strftime("%Y-%m-%d"))
print("반 넘게 0인 날(빈 날로):", bad_days)
f = f[~f.d.isin(zero_day[zero_day].index)]
chk = f[f.tv > 0].assign(r=lambda x: (x.fo.abs() / x.tv)).groupby(f.d.dt.to_period("M")).r.median()
print("단위 맞춘 뒤 |외국인 순매수| ÷ 거래대금 월별 중앙값:", " ".join(f"{k}:{v:.3f}" for k, v in chk.items()))

TV = p.pivot(index="d", columns="code", values="tv").sort_index()
days = TV.index
FO = f.pivot(index="d", columns="code", values="fo").reindex(index=days, columns=TV.columns)
IN = f.pivot(index="d", columns="code", values="ins").reindex(index=days, columns=TV.columns)
tv20 = TV.rolling(20, min_periods=15).mean()
feat = {}
for nm, X in (("fo", FO), ("ins", IN), ("fi", FO + IN)):
    for k in (1, 5, 20):
        cnt = X.notna().astype(float).rolling(k, min_periods=1).sum()
        s = X.rolling(k, min_periods=1).sum() / cnt * k
        need = k if k < 20 else 15
        feat[f"{nm}{k}"] = (s / tv20).where(cnt >= need)
    # 하루 전까지(실전 15:12엔 그날 수급 확정 전) 5일
    feat[f"{nm}5p"] = feat[f"{nm}5"].shift(1)

c, Cf, dates = CM.load()
c = c[c.date >= "2026-01-02"].copy()
ix = pd.to_datetime(c.date.values)
for k, F in feat.items():
    st = F.stack(future_stack=True)
    c[k] = st.reindex(list(zip(ix, c.code.values))).values
c["has"] = c[["fo5", "ins5", "fo20"]].notna().all(1)
c.to_pickle(f"{CM.OUT}/flowfeat.pkl")
mo = c.groupby(c.date.str[:7]).agg(후보=("R", "size"), 수급있음=("has", "sum"))
print("월별 V1.0 후보(겹침 포함) / 수급 특징 있음:\n", mo.T.to_string())
print("열린 채 끝난 거래(10/8 종가로 평가) 비율:", f"{100 * (c.xday >= len(dates)).mean():.0f}%")
