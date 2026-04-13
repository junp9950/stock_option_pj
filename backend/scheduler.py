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

    def _nightly_backfill_job() -> None:
        """매일 새벽 3시: 최근 30일 데이터 갭 채우기 + 시그널·추천 재계산."""
        from datetime import timedelta  # noqa: PLC0415
        from backend.collector.spot import collect_spot_data  # noqa: PLC0415
        from backend.collector.short_selling import collect_short_selling_data  # noqa: PLC0415
        from backend.collector.borrow import collect_borrow_data  # noqa: PLC0415
        from backend.collector.derivatives import collect_derivatives_data  # noqa: PLC0415
        from backend.collector.program_trading import collect_program_trading_data  # noqa: PLC0415
        from backend.signal_engine.stock_signal import calculate_stock_signals  # noqa: PLC0415
        from backend.signal_engine.market_signal import calculate_market_signal  # noqa: PLC0415
        from backend.screener.scorer import build_recommendations  # noqa: PLC0415
        from backend.utils.dates import is_trading_day  # noqa: PLC0415

        logger.info("Scheduler: nightly backfill started (last 30 days)")
        end_date = date.today() - timedelta(days=1)  # 어제까지 (오늘은 16:30에 따로 수집)
        start_date = end_date - timedelta(days=30)

        filled = 0
        errors = 0
        cur = start_date
        while cur <= end_date:
            if not is_trading_day(cur):
                cur += timedelta(days=1)
                continue
            fresh_db = SessionLocal()
            try:
                collect_spot_data(fresh_db, cur)
                collect_short_selling_data(fresh_db, cur)
                collect_borrow_data(fresh_db, cur)
                collect_derivatives_data(fresh_db, cur)
                collect_program_trading_data(fresh_db, cur)
                calculate_market_signal(fresh_db, cur)
                calculate_stock_signals(fresh_db, cur)
                build_recommendations(fresh_db, cur)
                filled += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Nightly backfill error on %s: %s", cur, exc)
                errors += 1
            finally:
                fresh_db.close()
            cur += timedelta(days=1)

        logger.info("Scheduler: nightly backfill done — %d days filled, %d errors", filled, errors)

    # 매일 16:30에 파이프라인 실행, 데이터 없으면 5분마다 재시도
    scheduler.add_job(_daily_pipeline_job, "cron", hour=16, minute=30, id="daily_pipeline", replace_existing=True)
    # 매일 새벽 3시에 최근 30일 백필
    scheduler.add_job(_nightly_backfill_job, "cron", hour=3, minute=0, id="nightly_backfill", replace_existing=True)
    # 매주 월요일 오전 8시에 유니버스 갱신
    scheduler.add_job(_universe_refresh_job, "cron", day_of_week="mon", hour=8, minute=0, id="universe_refresh", replace_existing=True)

    scheduler.start()
    logger.info("Scheduler started: daily_pipeline=16:30 KST, nightly_backfill=03:00 KST, universe_refresh=Mon 08:00 KST")
    return scheduler

