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
    result = kis_result   # KRX 직접 조회는 KRX 로그인 필수화 이후 계속 실패해 2026-10-03 제거

    if result is not None:
        arbitrage_net_buy = result["arbitrage_net_buy"]
        non_arbitrage_net_buy = result["non_arbitrage_net_buy"]
        source = "KIS"
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
