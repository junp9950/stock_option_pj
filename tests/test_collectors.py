from datetime import date

from backend.collector.derivatives import collect_derivatives_data
from backend.collector.short_selling import collect_short_selling_data
from backend.collector.spot import collect_spot_data
from backend.db.database import Base, SessionLocal, engine
from backend.db.seed import seed_reference_data


def test_collectors_run_without_error() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_reference_data(db)
        trading_date = date(2026, 4, 2)
        collect_spot_data(db, trading_date)
        collect_short_selling_data(db, trading_date)
        collect_derivatives_data(db, trading_date)
    finally:
        db.close()

