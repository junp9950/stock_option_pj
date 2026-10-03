from __future__ import annotations

import time
from datetime import date

import FinanceDataReader as fdr
import requests
from sqlalchemy.orm import Session

from backend.db.models import (
    DerivativesFuturesDaily,
    DerivativesOptionsDaily,
    FuturesDailyPrice,
    IndexDaily,
    OpenInterestDaily,
)
from backend.utils.logger import get_logger


logger = get_logger(__name__)

_KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://data.krx.co.kr/",
}
_KRX_JSON_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
_KRX_TIMEOUT = 15


def _krx_post(params: dict) -> dict | None:
    """POST to KRX JSON API. Returns parsed JSON or None on failure."""
    try:
        r = requests.post(_KRX_JSON_URL, headers=_KRX_HEADERS, data=params, timeout=_KRX_TIMEOUT)
        if r.status_code == 200 and r.text and r.text.strip() not in ("LOGOUT", ""):
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("KRX JSON request failed: %s", exc)
    return None


def _fetch_futures_investor_krx(date_str: str) -> dict | None:
    """Try to get KOSPI200 futures investor data from KRX JSON API.

    Source: KRX 파생상품시장 → 투자자별 거래실적 (MDCSTAT12301)
    Returns dict with keys: foreign_net, institution_net, individual_net (contract units)
    """
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT12301",
        "trdDd": date_str,
        "mktCd": "T",       # 전체 시장
        "trdVolVal": "1",   # 거래량(계약)
        "askBid": "1",      # 전체(매도+매수)
        "money": "3",       # 억원 단위
        "csvxls_isNo": "false",
    }
    data = _krx_post(params)
    if data is None:
        return None

    output = data.get("output") or data.get("output1") or []
    if not output:
        return None

    # Column names may vary; try common KRX naming patterns
    investor_map = {
        "외국인": "foreign",
        "기관계": "institution",
        "개인": "individual",
    }
    result: dict[str, float] = {"foreign": 0.0, "institution": 0.0, "individual": 0.0}
    found_any = False

    for row in output:
        # Find investor type key
        investor_label = None
        for key_candidate in ("INVST_TP_NM", "invst_tp_nm", "투자자구분", "INVST_TP"):
            if key_candidate in row:
                investor_label = row[key_candidate]
                break

        if investor_label is None:
            continue

        for kr_name, en_key in investor_map.items():
            if kr_name in str(investor_label):
                # Net contracts: try various column name patterns
                for col in ("NETBID_TRDVOL", "NET_BID_VOL", "순매수계약수", "순매수"):
                    if col in row:
                        try:
                            val = str(row[col]).replace(",", "").replace("-", "")
                            result[en_key] = float(val) if val else 0.0
                            found_any = True
                        except ValueError:
                            pass
                        break

    if found_any:
        logger.info("KRX futures investor data fetched: %s", result)
        return result
    return None


def collect_derivatives_data(db: Session, trading_date: date) -> None:
    """Collect futures/options/index data.

    Source priority:
      1. FinanceDataReader KS200 index (선물 종가도 지수로 대신)
      2. KRX JSON API (futures investor breakdown)
      3. Demo fallback values when all sources unavailable
    (pykrx 선물 종가·옵션 미결제약정은 KRX 로그인 필수화 이후 계속 실패해 2026-10-03 제거 → OI는 0)
    """
    date_str = trading_date.strftime("%Y%m%d")
    date_iso = trading_date.isoformat()  # FDR은 ISO 형식(YYYY-MM-DD) 필요

    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

    # ── 1. KOSPI200 index close (FDR) ────────────────────────────────────────
    index_close = 350.5
    try:
        index_df = fdr.DataReader("KS200", date_iso, date_iso)
        if not index_df.empty:
            index_close = float(index_df.iloc[-1]["Close"])
            logger.info("FDR KS200 index close: %.2f", index_close)
    except Exception as exc:  # noqa: BLE001
        logger.warning("FDR KS200 index fetch failed, using fallback: %s", exc)

    # ── 2. KOSPI200 futures close: 지수 종가로 대신 ─────────────────────────
    futures_close = index_close

    # ── 3. Options & futures open interest: 소스 없음 → 0 ────────────────────
    call_oi, put_oi, futures_oi = 0.0, 0.0, 0.0

    # ── 4. Futures investor breakdown (KRX JSON API) ────────────────────────
    investor = _fetch_futures_investor_krx(date_str)
    if investor is not None:
        foreign_net = investor.get("foreign", 0.0)
        institution_net = investor.get("institution", 0.0)
        individual_net = investor.get("individual", 0.0)
        investor_source = "KRX"
    else:
        foreign_net = 0.0
        institution_net = 0.0
        individual_net = 0.0
        investor_source = "fallback(0)"
    logger.info(
        "Futures investor source=%s foreign=%s institution=%s individual=%s",
        investor_source, foreign_net, institution_net, individual_net,
    )

    # upsert (DELETE 대신 — Supabase timeout 방지)
    db.execute(
        pg_insert(IndexDaily).values(trading_date=trading_date, index_code="1028", close_price=index_close)
        .on_conflict_do_update(constraint="uq_index_daily", set_={"close_price": index_close})
    )
    db.execute(
        pg_insert(FuturesDailyPrice).values(trading_date=trading_date, symbol="KOSPI200", close_price=futures_close)
        .on_conflict_do_update(constraint="uq_futures_daily_price", set_={"close_price": futures_close})
    )
    db.execute(
        pg_insert(DerivativesFuturesDaily).values(
            trading_date=trading_date,
            foreign_net_contracts=foreign_net,
            institution_net_contracts=institution_net,
            individual_net_contracts=individual_net,
            foreign_net_amount=0.0,
        ).on_conflict_do_update(
            constraint="uq_derivatives_futures_daily",
            set_={"foreign_net_contracts": foreign_net, "institution_net_contracts": institution_net, "individual_net_contracts": individual_net},
        )
    )
    db.execute(
        pg_insert(DerivativesOptionsDaily).values(
            trading_date=trading_date,
            call_foreign_net=0.0, put_foreign_net=0.0,
            call_institution_net=0.0, put_institution_net=0.0,
        ).on_conflict_do_update(
            constraint="uq_derivatives_options_daily",
            set_={"call_foreign_net": 0.0},
        )
    )
    db.execute(
        pg_insert(OpenInterestDaily).values(
            trading_date=trading_date, futures_oi=futures_oi, call_oi=call_oi, put_oi=put_oi,
        ).on_conflict_do_update(
            constraint="uq_open_interest_daily",
            set_={"futures_oi": futures_oi, "call_oi": call_oi, "put_oi": put_oi},
        )
    )
    db.commit()
