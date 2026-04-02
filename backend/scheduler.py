from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from backend.db.database import SessionLocal
from backend.services.daily_pipeline import run_daily_pipeline
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    def _job() -> None:
        db = SessionLocal()
        try:
            logger.info("Running scheduled daily pipeline")
            run_daily_pipeline(db)
        finally:
            db.close()

    scheduler.add_job(_job, "cron", hour=16, minute=0, id="daily_pipeline", replace_existing=True)
    scheduler.start()
    return scheduler

