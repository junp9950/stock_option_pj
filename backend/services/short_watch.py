"""공매도·대차잔고 감시 (KIS). 종목별 최근 약 30거래일: 공매도 체결량·비중, 대차잔고(빌린 주식 잔량)·신규·상환.
대차잔고가 늘면 공매도할 실탄이 쌓이는 것 — 교환사채(EB) 발행 전후 헤지 매도를 볼 때 쓴다 (2026-10-05 가온전선 EB 5,000억, 교환가 270,000원).
종목당 2번 호출, 3시간 캐시."""
from __future__ import annotations

import os
import time
from datetime import date, timedelta

import requests

_URL = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/"
_cache: dict[str, tuple[float, dict]] = {}


def _get(path: str, tr: str, params: dict, token: str) -> dict:
    r = requests.get(_URL + path, headers={"authorization": f"Bearer {token}", "appkey": os.getenv("KIS_APP_KEY", ""),
                                           "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": tr, "custtype": "P"},
                     params=params, timeout=10)
    return r.json()


def watch(code: str, shares: float | None = None, float_ratio: float | None = None) -> dict:
    hit = _cache.get(code)
    if hit and time.time() - hit[0] < 3 * 3600:
        return hit[1]
    from backend.collector.spot import _get_kis_token  # noqa: PLC0415
    tok = _get_kis_token()
    end = date.today()
    start = end - timedelta(days=50)
    rows: dict[str, dict] = {}
    try:
        j = _get("daily-short-sale", "FHPST04830000", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                                                         "FID_INPUT_DATE_1": f"{start:%Y%m%d}", "FID_INPUT_DATE_2": f"{end:%Y%m%d}"}, tok)
        for x in j.get("output2") or []:
            d = x.get("stck_bsop_date")
            if d:
                rows.setdefault(d, {})["close"] = float(x.get("stck_clpr") or 0)
                rows[d]["short_qty"] = float(x.get("ssts_cntg_qty") or 0)
                rows[d]["short_pct"] = float(x.get("ssts_vol_rlim") or 0)
                rows[d]["short_amt"] = float(x.get("ssts_tr_pbmn") or 0)
        time.sleep(0.1)
        j = _get("daily-loan-trans", "HHPST074500C0", {"MRKT_DIV_CLS_CODE": "3", "MKSC_SHRN_ISCD": code,
                                                       "START_DATE": f"{start:%Y%m%d}", "END_DATE": f"{end:%Y%m%d}", "CTS": ""}, tok)
        for x in j.get("output1") or []:
            d = x.get("bsop_date")
            if d:
                rows.setdefault(d, {})["loan_bal"] = float(x.get("rmnd_stcn") or 0)
                rows[d]["loan_new"] = float(x.get("new_stcn") or 0)
                rows[d]["loan_repay"] = float(x.get("rdmp_stcn") or 0)
    except Exception as exc:  # noqa: BLE001
        return {"code": code, "error": str(exc), "days": []}
    days = [dict(date=f"{d[:4]}-{d[4:6]}-{d[6:]}", **v) for d, v in sorted(rows.items())][-30:]
    bal = [x.get("loan_bal") for x in days if x.get("loan_bal") is not None]
    out = {"code": code, "days": days}
    if bal:
        out["loan_now"] = bal[-1]
        out["loan_5d_chg"] = bal[-1] - bal[-6] if len(bal) >= 6 else None
        out["loan_20d_chg"] = bal[-1] - bal[-21] if len(bal) >= 21 else None
        if shares:
            out["loan_pct_shares"] = round(bal[-1] / shares * 100, 2)
            if float_ratio:
                out["loan_pct_float"] = round(bal[-1] / (shares * float_ratio / 100) * 100, 1)
    sp = [x.get("short_pct", 0) for x in days[-5:]]
    out["short_pct_5d"] = round(sum(sp) / len(sp), 2) if sp else None
    sp20 = [x.get("short_pct", 0) for x in days[-25:-5]]
    out["short_pct_prev20"] = round(sum(sp20) / len(sp20), 2) if sp20 else None
    _cache[code] = (time.time(), out)
    return out
