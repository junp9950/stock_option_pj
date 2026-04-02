from datetime import date

from sqlalchemy import select

from backend.db.database import Base, engine
from backend.db.database import SessionLocal
from backend.db.models import Recommendation
from backend.db.seed import seed_reference_data
from backend.services.daily_pipeline import run_daily_pipeline


def test_recommendations_are_created() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_reference_data(db)
        run_daily_pipeline(db, date(2026, 4, 2))
        rows = list(db.scalars(select(Recommendation)))
        assert isinstance(rows, list)
    finally:
        db.close()
