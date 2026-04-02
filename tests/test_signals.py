from datetime import date

from backend.db.database import Base, SessionLocal, engine
from backend.db.seed import seed_reference_data
from backend.services.daily_pipeline import run_daily_pipeline


def test_daily_pipeline_creates_signal() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_reference_data(db)
        result = run_daily_pipeline(db, date(2026, 4, 2))
        assert "market_signal" in result
        assert result["stock_signal_count"] >= 1
    finally:
        db.close()

