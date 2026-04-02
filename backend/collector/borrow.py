from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import BorrowDaily


def collect_borrow_data(db: Session, trading_date: date) -> None:
    """Optional borrow balance collection.

    Source: not reliably available in this MVP.
    Fallback: mark rows as unavailable to keep the pipeline running.
    """

    db.execute(delete(BorrowDaily).where(BorrowDaily.trading_date == trading_date))
    for stock in get_universe(db):
        db.add(
            BorrowDaily(
                trading_date=trading_date,
                stock_code=stock.code,
                balance_change=None,
                note="TODO: external borrow balance source not wired in MVP",
            )
        )
    db.commit()
