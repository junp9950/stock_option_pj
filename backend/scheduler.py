from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from backend.db.database import SessionLocal
from backend.db.seed import refresh_universe
from backend.services.daily_pipeline import run_daily_pipeline
from backend.utils.logger import get_logger


logger = get_logger(__name__)


def start_scheduler() -> BackgroundScheduler:
    from datetime import date  # noqa: PLC0415
    from sqlalchemy import func, select  # noqa: PLC0415
    from backend.db.models import SpotInvestorFlow  # noqa: PLC0415

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    # 오늘 수급 데이터가 실제로 올라왔는지 확인
    def _has_today_data() -> bool:
        db = SessionLocal()
        try:
            today = date.today()
            count = db.scalar(
                select(func.count()).select_from(SpotInvestorFlow).where(
                    SpotInvestorFlow.trading_date == today,
                    (SpotInvestorFlow.foreign_net_buy != 0) | (SpotInvestorFlow.institution_net_buy != 0)
                )
            )
            return (count or 0) > 0
        finally:
            db.close()

    def _daily_pipeline_job() -> None:
        if _has_today_data():
            # 이미 오늘 데이터 있으면 스킵 (재시도 중 이미 성공한 경우)
            logger.info("Scheduler: today's data already collected, skipping")
            return
        db = SessionLocal()
        try:
            logger.info("Scheduler: running daily pipeline")
            run_daily_pipeline(db)
            # 성공 후 재시도 잡 제거
            if scheduler.get_job("daily_pipeline_retry"):
                scheduler.remove_job("daily_pipeline_retry")
                logger.info("Scheduler: data confirmed, retry job removed")
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler daily pipeline error: %s", exc)
            # 실패 시 5분마다 재시도 등록 (없으면)
            if not scheduler.get_job("daily_pipeline_retry"):
                scheduler.add_job(
                    _daily_pipeline_job, "interval", minutes=5,
                    id="daily_pipeline_retry", replace_existing=True,
                    max_instances=1,
                )
                logger.info("Scheduler: retry job registered (every 5 min)")
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

    # 매일 16:30에 파이프라인 실행, 데이터 없으면 5분마다 재시도
    scheduler.add_job(_daily_pipeline_job, "cron", hour=16, minute=30, id="daily_pipeline", replace_existing=True)
    # 매주 월요일 오전 8시에 유니버스 갱신
    scheduler.add_job(_universe_refresh_job, "cron", day_of_week="mon", hour=8, minute=0, id="universe_refresh", replace_existing=True)

    scheduler.start()
    logger.info("Scheduler started: daily_pipeline=16:30 KST (retry every 5min if no data), universe_refresh=Mon 08:00 KST")
    return scheduler

