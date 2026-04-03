from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from backend.db.database import SessionLocal
from backend.db.seed import refresh_universe
from backend.services.daily_pipeline import run_daily_pipeline
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    def _daily_pipeline_job() -> None:
        db = SessionLocal()
        try:
            logger.info("Scheduler: running daily pipeline")
            run_daily_pipeline(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler daily pipeline error: %s", exc)
        finally:
            db.close()

    def _universe_refresh_job() -> None:
        db = SessionLocal()
        try:
            logger.info("Scheduler: refreshing universe")
            refresh_universe(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler universe refresh error: %s", exc)
        finally:
            db.close()

    # 장마감 후 15:35에 파이프라인 실행 (데이터 반영 여유 5분)
    scheduler.add_job(_daily_pipeline_job, "cron", hour=15, minute=35, id="daily_pipeline", replace_existing=True)
    # 매주 월요일 오전 8시에 유니버스(시총 상위 30종목) 갱신
    scheduler.add_job(_universe_refresh_job, "cron", day_of_week="mon", hour=8, minute=0, id="universe_refresh", replace_existing=True)

    scheduler.start()
    logger.info("Scheduler started: daily_pipeline=15:35 KST, universe_refresh=Mon 08:00 KST")
    return scheduler

