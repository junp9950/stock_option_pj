"""코스피·코스닥 투자자별 순매수 (2026-10-11 사용자 "외국인은 삼하 말고 코스피·코스닥 수급으로, 연기금·투신·보험도").

KIS 시장별 투자자매매동향(일별) FHPTJ04040000 — 한 번에 최근 약 300거래일. 금액 단위 = 백만원.
표 market_investor_flows (trading_date, market 'KOSPI'|'KOSDAQ', 투자자별 순매수). 매일 장 마감 뒤 받은 것을 덮어쓴다.
"""
from __future__ import annotations

import logging
import os
from datetime import date

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
URL = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor-daily-by-market"
MARKETS = {"KOSPI": ("0001", "KSP"), "KOSDAQ": ("1001", "KSQ")}
# 표 열 ← KIS 필드 (순매수 거래대금, 백만원)
COLS = {"frgn": "frgn_ntby_tr_pbmn", "prsn": "prsn_ntby_tr_pbmn", "orgn": "orgn_ntby_tr_pbmn", "scrt": "scrt_ntby_tr_pbmn",
        "ivtr": "ivtr_ntby_tr_pbmn", "pe_fund": "pe_fund_ntby_tr_pbmn", "bank": "bank_ntby_tr_pbmn", "insu": "insu_ntby_tr_pbmn",
        "mrbn": "mrbn_ntby_tr_pbmn", "fund": "fund_ntby_tr_pbmn", "etc_corp": "etc_corp_ntby_tr_pbmn"}


def _ensure(db: Session) -> None:
    cols = ", ".join(f"{c} bigint" for c in COLS)
    db.execute(text(f"create table if not exists market_investor_flows (trading_date date not null, market varchar(8) not null, {cols}, "
                    "primary key (trading_date, market))"))
    db.commit()


def fetch(market: str, upto: date) -> list[dict]:
    from backend.collector.spot import _get_kis_token  # noqa: PLC0415
    tok = _get_kis_token()
    if not tok:
        return []
    iscd, iscd1 = MARKETS[market]
    headers = {"content-type": "application/json; charset=utf-8", "authorization": f"Bearer {tok}",
               "appkey": os.getenv("KIS_APP_KEY", ""), "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": "FHPTJ04040000", "custtype": "P"}
    d = upto.strftime("%Y%m%d")
    params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": iscd, "FID_INPUT_DATE_1": d, "FID_INPUT_ISCD_1": iscd1,
              "FID_INPUT_DATE_2": d, "FID_INPUT_ISCD_2": iscd}
    try:
        r = requests.get(URL, headers=headers, params=params, timeout=15).json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("시장 수급 조회 실패 %s: %s", market, type(exc).__name__)
        return []
    if r.get("rt_cd") != "0":
        logger.warning("시장 수급 조회 실패 %s: %s", market, r.get("msg1"))
        return []
    out = []
    for row in r.get("output") or []:
        try:
            out.append({"trading_date": date.fromisoformat(f"{row['stck_bsop_date'][:4]}-{row['stck_bsop_date'][4:6]}-{row['stck_bsop_date'][6:]}"),
                        "market": market, **{c: int(row.get(k) or 0) for c, k in COLS.items()}})
        except (KeyError, ValueError):
            continue
    return out


def collect(db: Session, upto: date | None = None) -> str:
    _ensure(db)
    upto = upto or date.today()
    n = 0
    for m in MARKETS:
        rows = fetch(m, upto)
        for x in rows:
            sets = ", ".join(f"{c} = excluded.{c}" for c in COLS)
            db.execute(text(f"insert into market_investor_flows (trading_date, market, {', '.join(COLS)}) values (:trading_date, :market, "
                            f"{', '.join(':' + c for c in COLS)}) on conflict (trading_date, market) do update set {sets}"), x)
        n += len(rows)
    db.commit()
    return f"시장 수급 {n}줄"


def summary(db: Session, days: int = 5) -> dict | None:
    """최근 N거래일 합 (백만원) · 오늘 값. 화면 시장 카드용."""
    try:
        _ensure(db)
        ds = [r[0] for r in db.execute(text("select distinct trading_date from market_investor_flows order by 1 desc limit :n"), {"n": days}).all()]
    except Exception:  # noqa: BLE001
        return None
    if not ds:
        return None
    out = {"days": len(ds), "from": str(min(ds)), "to": str(max(ds))}
    for m in MARKETS:
        sums = db.execute(text(f"select {', '.join(f'coalesce(sum({c}), 0)' for c in COLS)} from market_investor_flows "
                               "where market = :m and trading_date = any(:d)"), {"m": m, "d": ds}).one()
        last = db.execute(text(f"select {', '.join(COLS)} from market_investor_flows where market = :m and trading_date = :d"),
                          {"m": m, "d": max(ds)}).one_or_none()
        out[m] = {"sum": dict(zip(COLS, map(int, sums))), "today": dict(zip(COLS, map(int, last))) if last else None}
    return out
