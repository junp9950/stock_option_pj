from __future__ import annotations

from datetime import date

import FinanceDataReader as fdr
from sqlalchemy import delete
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


def collect_derivatives_data(db: Session, trading_date: date) -> None:
    """Collect futures/options/index data.

    Source: pykrx for index data, KRX OTP for options/open interest when available.
    Fallback: synthetic local values for MVP.
    """

    db.execute(delete(IndexDaily).where(IndexDaily.trading_date == trading_date))
    db.execute(delete(FuturesDailyPrice).where(FuturesDailyPrice.trading_date == trading_date))
    db.execute(delete(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == trading_date))
    db.execute(delete(DerivativesOptionsDaily).where(DerivativesOptionsDaily.trading_date == trading_date))
    db.execute(delete(OpenInterestDaily).where(OpenInterestDaily.trading_date == trading_date))

    index_close = 350.5
    futures_close = 351.35
    try:
        index_df = fdr.DataReader("KS200", trading_date.isoformat(), trading_date.isoformat())
        if not index_df.empty:
            index_row = index_df.iloc[-1]
            index_close = float(index_row["Close"])
            # 선물 종가 source는 아직 안정적으로 확보하지 못해 index 기반 fallback을 유지한다.
            futures_close = index_close
    except Exception as exc:  # noqa: BLE001
        logger.warning("FDR KS200 index fetch failed, keeping fallback derivatives values: %s", exc)

    db.add(IndexDaily(trading_date=trading_date, index_code="1028", close_price=index_close))
    db.add(FuturesDailyPrice(trading_date=trading_date, symbol="KOSPI200", close_price=futures_close))
    db.add(
        DerivativesFuturesDaily(
            trading_date=trading_date,
            foreign_net_contracts=0.0,
            institution_net_contracts=0.0,
            individual_net_contracts=0.0,
            foreign_net_amount=0.0,
        )
    )
    db.add(
        DerivativesOptionsDaily(
            trading_date=trading_date,
            call_foreign_net=0.0,
            put_foreign_net=0.0,
            call_institution_net=0.0,
            put_institution_net=0.0,
        )
    )
    db.add(
        OpenInterestDaily(
            trading_date=trading_date,
            futures_oi=0.0,
            call_oi=0.0,
            put_oi=0.0,
        )
    )
    db.commit()
