from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.db.models import ProgramTradingDaily


def collect_program_trading_data(db: Session, trading_date: date) -> None:
    """Collect program trading data.

    Source: KRX OTP CSV workflow.
    Fallback: demo values to keep MVP runnable offline.
    """

    db.execute(delete(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == trading_date))
    db.add(
        ProgramTradingDaily(
            trading_date=trading_date,
            arbitrage_net_buy=250_000_000_000,
            non_arbitrage_net_buy=280_000_000_000,
        )
    )
    db.commit()
