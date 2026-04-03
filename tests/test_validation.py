from datetime import date

from backend.db.database import Base, engine
from backend.db.database import SessionLocal
from backend.db.seed import seed_reference_data
from backend.services.daily_pipeline import run_daily_pipeline
from backend.services.validation import validate_daily_data


def test_validation_returns_list() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_reference_data(db)
        run_daily_pipeline(db, date(2026, 4, 2))
        warnings = validate_daily_data(db, date(2026, 4, 2))
        assert isinstance(warnings, list)
    finally:
        db.close()
