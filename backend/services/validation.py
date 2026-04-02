from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.models import DerivativesFuturesDaily, IndexDaily, JobLog, SpotDailyPrice, Stock


def validate_daily_data(db: Session, trading_date: date) -> list[str]:
    warnings: list[str] = []
    stock_count = db.scalar(select(func.count()).select_from(Stock))
    price_count = db.scalar(select(func.count()).select_from(SpotDailyPrice).where(SpotDailyPrice.trading_date == trading_date))
    if stock_count and price_count and price_count < stock_count * 0.9:
        warnings.append("현물 데이터 수집 비율이 90% 미만입니다.")

    futures = db.scalar(select(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == trading_date))
    if futures is not None:
        total = futures.foreign_net_contracts + futures.institution_net_contracts + futures.individual_net_contracts
        if abs(total) > 500:
            warnings.append("파생 순매수 합계가 0에 근접하지 않습니다.")

    if db.scalar(select(IndexDaily).where(IndexDaily.trading_date == trading_date)) is None:
        warnings.append("KOSPI200 지수 데이터가 비어 있습니다.")

    for message in warnings:
        db.add(JobLog(trading_date=trading_date, stage="validation", status="warning", message=message))
    db.commit()
    return warnings

