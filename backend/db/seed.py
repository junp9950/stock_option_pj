from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Stock


DEFAULT_STOCKS = [
    {"code": "005930", "name": "삼성전자", "market": "KOSPI", "market_cap": 430_000_000_000_000},
    {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "market_cap": 130_000_000_000_000},
    {"code": "035420", "name": "NAVER", "market": "KOSPI", "market_cap": 34_000_000_000_000},
    {"code": "005380", "name": "현대차", "market": "KOSPI", "market_cap": 45_000_000_000_000},
    {"code": "105560", "name": "KB금융", "market": "KOSPI", "market_cap": 30_000_000_000_000},
]


def seed_reference_data(db: Session) -> None:
    if db.scalar(select(Stock.id).limit(1)):
        return
    for stock in DEFAULT_STOCKS:
        db.add(Stock(**stock))
    db.commit()

