from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Stock


def get_universe(db: Session) -> list[Stock]:
    return list(db.scalars(select(Stock).where(Stock.is_active.is_(True)).order_by(Stock.code)))

