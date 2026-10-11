"""1단계(운영 venv): 12년 캐시(상장폐지 포함) + 시장 국면 + EMA → pattern_val/data.npz
redteam_lab.build("full")과 같은 전처리(정리매매 10일 봉은 오류 표시에서 제외)."""
import sys
sys.path.insert(0, "/home/junp/tmp_claude")
import numpy as np
import ma_lab as M

M.CACHE = "/home/junp/tmp_claude/ma_lab_cache_full.npz"
D = M.prep(M.load())
n, m = D["n"], D["m"]
C = D["c"]
dates = np.array([str(d) for d in D["dates"]])
n0 = 2783
chg = D["chg"]; old = np.array([d < "2015-06-15" for d in dates])[:, None]
bad = np.nan_to_num(np.abs(chg)) > np.where(old, 0.155, 0.305)
for j in range(n0, m):
    fin = np.nonzero(np.isfinite(C[:, j]))[0]
    if len(fin):
        bad[max(fin[-1] - 9, 0):fin[-1] + 1, j] = False
badcum = np.cumsum(bad, axis=0).astype("int32")
e20, e21, e60 = (M.ema(C, k).astype("float32") for k in (20, 21, 60))
from backend.screener.market_regime import regime_series
reg = regime_series({d: float(v) * 100 for d, v in zip(D["dates"], D["mk"])})
state = np.array([{"상승": 2, "횡보": 1, "하락": 0}.get(reg.get(d, {}).get("state"), -1) for d in D["dates"]], dtype="int8")
np.savez("/home/junp/tmp_claude/pattern_val/data.npz", dates=dates, codes=np.array(D["codes"]),
         o=D["o"], h=D["h"], l=D["l"], c=C, v=D["v"], t=D["t"], tv20=D["tv20"], Cf=D["Cf"],
         badcum=badcum, e20=e20, e21=e21, e60=e60, state=state, n0=n0)
print("saved", C.shape, dates[0], dates[-1], "regime counts", np.unique(state, return_counts=True))
