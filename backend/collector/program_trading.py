from __future__ import annotations

from datetime import date

import requests
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.spot import _get_kis_token
from backend.db.models import ProgramTradingDaily
from backend.utils.logger import get_logger


logger = get_logger(__name__)

# KIS "프로그램매매 종합현황(일별)" tr_pbmn 필드 단위는 백만원
_KIS_TR_PBMN_UNIT = 1_000_000

_KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://data.krx.co.kr/",
}
_KRX_JSON_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
_KRX_TIMEOUT = 15

# KOSPI market code on KRX
_KOSPI_MKT_ID = "1"


def _krx_post(params: dict) -> dict | None:
    """POST to KRX JSON API. Returns parsed JSON or None on failure."""
    try:
        r = requests.post(_KRX_JSON_URL, headers=_KRX_HEADERS, data=params, timeout=_KRX_TIMEOUT)
        if r.status_code == 200 and r.text and r.text.strip() not in ("LOGOUT", ""):
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("KRX JSON request failed: %s", exc)
    return None


def _fetch_program_trading_krx(date_str: str) -> dict | None:
    """Try to get KOSPI program trading data from KRX JSON API.

    Source: KRX 시장정보 → 거래실적 → 프로그램매매 거래실적 (MDCSTAT22901)
    Returns dict with keys: arbitrage_net_buy, non_arbitrage_net_buy (KRW)
    """
    params = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT22901",
        "trdDd": date_str,
        "mktId": _KOSPI_MKT_ID,
        "trdVolVal": "2",   # 거래대금
        "csvxls_isNo": "false",
    }
    data = _krx_post(params)
    if data is None:
        return None

    output = data.get("output") or data.get("output1") or []
    if not output:
        return None

    arbitrage_net = 0.0
    non_arbitrage_net = 0.0
    found = False

    for row in output:
        # Try to find arbitrage vs non-arbitrage row identifier
        category = None
        for key in ("PRGM_TP_NM", "prgm_tp_nm", "프로그램구분", "PRGM_TP"):
            if key in row:
                category = str(row[key])
                break

        # Also try direct total row
        if category is None:
            # Some formats return a single summary row
            arb_val = None
            non_arb_val = None
            for col in ("ARBT_NETBID_TRDVAL", "arbt_netbid_trdval", "차익순매수금액"):
                if col in row:
                    arb_val = col
                    break
            for col in ("NABT_NETBID_TRDVAL", "nabt_netbid_trdval", "비차익순매수금액"):
                if col in row:
                    non_arb_val = col
                    break
            if arb_val and non_arb_val:
                try:
                    arbitrage_net = float(str(row[arb_val]).replace(",", ""))
                    non_arbitrage_net = float(str(row[non_arb_val]).replace(",", ""))
                    found = True
                except (ValueError, TypeError):
                    pass
            continue

        # Row-based format
        net_val = 0.0
        for col in ("NETBID_TRDVAL", "netbid_trdval", "순매수금액", "NETBID_VAL"):
            if col in row:
                try:
                    net_val = float(str(row[col]).replace(",", ""))
                    found = True
                except (ValueError, TypeError):
                    pass
                break

        if "차익" in category and "비차익" not in category:
            arbitrage_net = net_val
        elif "비차익" in category:
            non_arbitrage_net = net_val

    if found:
        # KRX returns values in 억원; convert to KRW (× 100_000_000)
        # But if values already look like full KRW (> 1e10), skip conversion
        if abs(arbitrage_net) < 1_000_000:
            arbitrage_net *= 100_000_000
            non_arbitrage_net *= 100_000_000
        logger.info(
            "KRX program trading fetched: arbitrage=%.0f non_arbitrage=%.0f",
            arbitrage_net, non_arbitrage_net,
        )
        return {"arbitrage_net_buy": arbitrage_net, "non_arbitrage_net_buy": non_arbitrage_net}
    return None


def _fetch_program_trading_kis(date_str: str) -> dict | None:
    """KIS Open API로 프로그램매매 종합현황(일별) 조회.

    Endpoint: /uapi/domestic-stock/v1/quotations/comp-program-trade-daily (TR: FHPPG04600001)
    클라우드 VM IP에서도 차단 없이 동작 확인됨 (KRX 직접 호출은 LOGOUT으로 차단됨).
    Returns dict with keys: arbitrage_net_buy, non_arbitrage_net_buy (KRW, 전체 위탁+자기매매 합산)
    """
    token = _get_kis_token()
    if not token:
        return None

    import os
    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        return None

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHPPG04600001",
        "custtype": "P",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_MRKT_CLS_CODE": "K",
        "FID_INPUT_DATE_1": date_str,
        "FID_INPUT_DATE_2": date_str,
    }
    try:
        r = requests.get(
            "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/comp-program-trade-daily",
            headers=headers, params=params, timeout=10,
        )
        data = r.json()
        rows = data.get("output") or []
        row = next((row for row in rows if row.get("stck_bsop_date") == date_str), None)
        if row is None:
            return None

        arbitrage_net = (
            float(row.get("arbt_smtn_shnu_tr_pbmn") or 0) - float(row.get("arbt_smtn_seln_tr_pbmn") or 0)
        ) * _KIS_TR_PBMN_UNIT
        non_arbitrage_net = (
            float(row.get("nabt_smtn_shnu_tr_pbmn") or 0) - float(row.get("nabt_smtn_seln_tr_pbmn") or 0)
        ) * _KIS_TR_PBMN_UNIT
        logger.info(
            "KIS program trading fetched: arbitrage=%.0f non_arbitrage=%.0f",
            arbitrage_net, non_arbitrage_net,
        )
        return {"arbitrage_net_buy": arbitrage_net, "non_arbitrage_net_buy": non_arbitrage_net}
    except Exception as exc:  # noqa: BLE001
        logger.debug("KIS program trading fetch failed: %s", exc)
        return None


def collect_program_trading_data(db: Session, trading_date: date) -> None:
    """Collect program trading data.

    Source priority:
      1. KIS Open API (comp-program-trade-daily) — 클라우드 VM에서도 정상 동작
      2. KRX JSON API (MDCSTAT22901) — 프로그램매매 거래실적 (VM에서는 LOGOUT으로 대부분 실패)
      3. Demo fallback values when both unavailable
    """
    date_str = trading_date.strftime("%Y%m%d")

    db.execute(delete(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == trading_date))

    kis_result = _fetch_program_trading_kis(date_str)
    result = kis_result or _fetch_program_trading_krx(date_str)

    if result is not None:
        arbitrage_net_buy = result["arbitrage_net_buy"]
        non_arbitrage_net_buy = result["non_arbitrage_net_buy"]
        source = "KIS" if kis_result is not None else "KRX"
    else:
        # Demo fallback — neutral values (small positive)
        arbitrage_net_buy = 0.0
        non_arbitrage_net_buy = 0.0
        source = "fallback(0)"
        logger.warning(
            "Program trading: KRX unavailable, using fallback. "
            "Signal engine will treat non-arbitrage net buy as 0 (neutral)."
        )

    logger.info("Program trading source=%s arb=%.0f non_arb=%.0f", source, arbitrage_net_buy, non_arbitrage_net_buy)
    db.add(
        ProgramTradingDaily(
            trading_date=trading_date,
            arbitrage_net_buy=arbitrage_net_buy,
            non_arbitrage_net_buy=non_arbitrage_net_buy,
        )
    )
    db.commit()
