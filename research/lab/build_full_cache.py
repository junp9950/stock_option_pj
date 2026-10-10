"""정정판 데이터: ma_lab_cache.npz(지금 상장 종목 위주) + KIND 상장폐지 종목(네이버 일봉) → ma_lab_cache_full.npz (2026-10-10 KST).
- 네이버 일봉은 수정주가, 거래대금 없음 → 종가×거래량으로 근사.
- 거래 없는 날(시가·고가·저가 0 또는 거래량 0)은 전부 NaN(거래정지로 취급).
- 이미 들어 있는 종목코드는 건너뜀.
"""
import os, numpy as np, pandas as pd
src = np.load("/home/junp/tmp_claude/ma_lab_cache.npz", allow_pickle=True)
dates = list(pd.to_datetime(src["dates"]).date); codes = list(src["codes"])
di = {d: i for i, d in enumerate(dates)}; have = set(codes)
kind = pd.read_csv("/home/junp/tmp_claude/kind_delisting.csv", dtype={"종목코드": str}); kind["code"] = kind["종목코드"].str.zfill(6)
new_codes, cols = [], {k: [] for k in "ohlcvt"}
skipped = {"이미 있음": 0, "파일 없음": 0, "기간 밖": 0}
for code in kind.code.unique():
    if code in have:
        skipped["이미 있음"] += 1; continue
    fn = f"/home/junp/tmp_claude/delisted/{code}.csv"
    if not os.path.exists(fn):
        skipped["파일 없음"] += 1; continue
    x = pd.read_csv(fn, dtype={"date": str})
    if x.empty:
        skipped["파일 없음"] += 1; continue
    x["d"] = pd.to_datetime(x.date).dt.date
    x = x[x.d.isin(di)]
    if x.empty:
        skipped["기간 밖"] += 1; continue
    arr = {k: np.full(len(dates), np.nan, dtype="float32") for k in "ohlcvt"}
    o, h, l, c, v = (x[k].astype(float).values for k in "ohlcv")
    trade = (o > 0) & (h > 0) & (l > 0) & (v > 0)
    idx = x.d.map(di).values
    for k, val in (("o", o), ("h", h), ("l", l), ("c", c), ("v", v)):
        arr[k][idx[trade]] = val[trade]
    arr["t"][idx[trade]] = (c * v)[trade]
    new_codes.append(code)
    for k in "ohlcvt":
        cols[k].append(arr[k])
print("추가", len(new_codes), "· 건너뜀", skipped)
out = {"dates": src["dates"], "codes": np.array(codes + new_codes)}
for k in "ohlcvt":
    out[k] = np.hstack([src[k], np.column_stack(cols[k])]).astype("float32") if new_codes else src[k]
np.savez("/home/junp/tmp_claude/ma_lab_cache_full.npz", **out)
print("저장", out["c"].shape)
