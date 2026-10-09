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

    def _final_refresh_job() -> None:
        # 18:00 재수집: 15:41에는 외국인·기관 수급이 잠정치일 수 있어 최종치로 덮어쓴다 (upsert라 중복 없음, 알림은 보내지 않음)
        db = SessionLocal()
        try:
            logger.info("Scheduler: running 18:00 final refresh")
            run_daily_pipeline(db, notify=False)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler final refresh error: %s", exc)
        finally:
            db.close()

    # ── 텔레그램 (backend/services/telegram.py) ──
    def _tg(fn_name: str, *args) -> None:
        from backend.services import telegram  # noqa: PLC0415
        db = SessionLocal()
        try:
            getattr(telegram, fn_name)(db, *args)
        except Exception as exc:  # noqa: BLE001
            logger.error("텔레그램 %s 실패: %s", fn_name, type(exc).__name__)
        finally:
            db.close()

    def _tg_watch() -> None:
        from backend.services.watchlist import send_report  # noqa: PLC0415
        db = SessionLocal()
        try:
            send_report(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("관심 종목 점검 실패: %s", type(exc).__name__)
        finally:
            db.close()

    def _telegram_poll_job() -> None:
        _tg("poll")

    def _telegram_alert_job() -> None:
        from backend.services.telegram import is_market_time  # noqa: PLC0415
        if is_market_time():
            _tg("check_alerts")

    def _telegram_close_check_job() -> None:
        _tg("check_alerts", True)

    def _telegram_summary_job() -> None:
        from backend.api.routes import warm_caches  # noqa: PLC0415
        from backend.services.result_cache import refreshing  # noqa: PLC0415
        from backend.services.telegram import summary_pending  # noqa: PLC0415
        db = SessionLocal()
        try:
            if not summary_pending(db):
                return
            with refreshing():
                warm_caches(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("요약 전 캐시 갱신 실패: %s", exc)
        finally:
            db.close()
        _tg("send_summary_once")

    def _daily_pipeline_job() -> None:
        if _has_today_data():
            # 이미 오늘 데이터 있으면 스킵 (재시도 중 이미 성공한 경우)
            logger.info("Scheduler: today's data already collected, skipping")
            return
        db = SessionLocal()
        try:
            logger.info("Scheduler: running daily pipeline")
            run_daily_pipeline(db)
            try:
                from backend.services import trade_journal  # noqa: PLC0415
                trade_journal.warm(db)      # 새 시세로 매매 일지 미리 계산
            except Exception as exc:  # noqa: BLE001
                logger.warning("매매 일지 미리 계산 실패: %s", exc)
            _telegram_summary_job()     # 수집 끝나자마자 텔레그램 종베 요약 (시간외 종가 15:40~16:00 안에 보려고)
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

    def _sector_mapping_refresh_job() -> None:
        """매주 일요일 새벽 2시: 커스텀 섹터 + 네이버 테마 매핑 갱신."""
        from backend.collector.sector import refresh_sector_mapping  # noqa: PLC0415
        db = SessionLocal()
        try:
            logger.info("Scheduler: sector mapping weekly refresh")
            result = refresh_sector_mapping(db)
            logger.info("Scheduler: sector mapping done — %s", result)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler sector mapping refresh error: %s", exc)
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
        end_date = date.today() - timedelta(days=1)  # 어제까지 (오늘은 15:41에 따로 수집)
        start_date = end_date - timedelta(days=30)

        # 이미 가격·수급이 들어 있는 날은 건너뛴다. 예전엔 30일 전부를 매일 밤 다시 수집해 1시간씩, KIS 호출 수천 번을 썼다
        # (확정 가격 보정은 07:30 _price_fix_job이 한다).
        from sqlalchemy import text as _text  # noqa: PLC0415
        chk = SessionLocal()
        try:
            have = {d for (d,) in chk.execute(_text(
                "select p.trading_date from spot_daily_prices p where p.trading_date between :s and :e "
                "group by p.trading_date having count(*) >= 200 and exists (select 1 from spot_investor_flows f "
                "where f.trading_date = p.trading_date and (f.foreign_net_buy <> 0 or f.institution_net_buy <> 0))"),
                {"s": start_date, "e": end_date})}
        finally:
            chk.close()

        filled = 0
        errors = 0
        cur = start_date
        while cur <= end_date:
            if not is_trading_day(cur) or cur in have:
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

    def _record_picks_job() -> None:
        """레이더 신호 종목 실전 기록. 파이프라인 완료 후 하루 한 번만 저장되고, 나머지 호출은 그냥 넘어감."""
        from backend.screener.radar import record_picks  # noqa: PLC0415
        db = SessionLocal()
        try:
            logger.info("Scheduler: record radar picks — %s", record_picks(db))
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler record picks error: %s", exc)
        finally:
            db.close()

    def _warm_cache_job() -> None:
        from backend.api.routes import warm_caches  # noqa: PLC0415
        db = SessionLocal()
        try:
            from backend.services.result_cache import refreshing  # noqa: PLC0415
            with refreshing():
                warm_caches(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler cache warm error: %s", exc)
        finally:
            db.close()

    # 2분마다 화면용 스캔 결과를 미리 계산 (데이터가 안 바뀌었으면 버전 확인만 하고 바로 끝남). 서버 시작 5초 뒤 한 번
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    scheduler.add_job(_warm_cache_job, "interval", minutes=2, id="warm_cache", replace_existing=True,
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5), max_instances=1)
    # 평일 17:30~21:30 매시 정각 30분: 파이프라인 재시도가 늦어져도 그날 기록이 빠지지 않게
    scheduler.add_job(_record_picks_job, "cron", day_of_week="mon-fri", hour="17-21", minute=30, id="record_picks", replace_existing=True)
    # 매일 15:41에 파이프라인 실행, 데이터 없으면 5분마다 재시도
    scheduler.add_job(_daily_pipeline_job, "cron", hour=15, minute=41, id="daily_pipeline", replace_existing=True)
    # 매일 18:00에 한 번 더 강제 실행 (수급 최종치 반영)
    scheduler.add_job(_final_refresh_job, "cron", day_of_week="mon-fri", hour=18, minute=0, id="daily_pipeline_final", replace_existing=True, max_instances=1)
    # 매일 새벽 3시에 최근 30일 백필
    scheduler.add_job(_nightly_backfill_job, "cron", hour=3, minute=0, id="nightly_backfill", replace_existing=True)
    # 매주 월요일 오전 8시에 유니버스 갱신
    scheduler.add_job(_universe_refresh_job, "cron", day_of_week="mon", hour=8, minute=0, id="universe_refresh", replace_existing=True)
    # 매주 일요일 새벽 2시에 섹터 매핑 갱신
    scheduler.add_job(_sector_mapping_refresh_job, "cron", day_of_week="sun", hour=2, minute=0, id="sector_mapping_refresh", replace_existing=True)

    # AI 10일 전략(quant_strategy) 갱신은 껐다: 화면 탭은 5b0e9aa에서 제거됐고, 입력인 investor_flow_toss 표는
    # 2026-10-03 DB 용량 정리로 삭제(백업: 서버 /home/junp/backups/investor_flow_toss_2023-09_2026-09.parquet).
    def _jongbe_record_job() -> None:
        # 18:20: 18:00 최종 재수집 뒤 그날 종베 후보를 저장 (다음 날 결과를 붙여 실전 성적을 쌓는다)
        from backend.screener.jongbe import record  # noqa: PLC0415
        db = SessionLocal()
        try:
            logger.info("종베 후보 기록: %d종목", record(db))
        except Exception as exc:  # noqa: BLE001
            logger.error("종베 후보 기록 실패: %s", exc)
        finally:
            db.close()
    scheduler.add_job(_jongbe_record_job, 'cron', day_of_week='mon-fri', hour=18, minute=20,
                      id='jongbe_record', replace_existing=True, max_instances=1, coalesce=True)

    def _price_fix_job() -> None:
        # 07:30: 전날 15:41·18:00 수집 시세는 NXT 시간외 진행 중 값이라 확정 종가로 다시 덮어쓴다 (최근 5거래일)
        from datetime import date as _date  # noqa: PLC0415
        from backend.collector.spot import refresh_spot_prices  # noqa: PLC0415
        db = SessionLocal()
        try:
            refresh_spot_prices(db, _date.today() - timedelta(days=9), _date.today())
        except Exception as exc:  # noqa: BLE001
            logger.error("Scheduler price fix error: %s", exc)
        finally:
            db.close()
    scheduler.add_job(_price_fix_job, 'cron', day_of_week='tue-sat', hour=7, minute=30,
                      id='spot_price_fix', replace_existing=True, max_instances=1, coalesce=True)
    from backend.services.marcap_caps import refresh as refresh_marcap
    scheduler.add_job(refresh_marcap, 'cron', hour=7, minute=0, id='marcap_caps_daily', replace_existing=True, max_instances=1)

    def _sync_names_job() -> None:
        from backend.collector.spot import sync_stock_names  # noqa: PLC0415
        db = SessionLocal()
        try:
            sync_stock_names(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("종목 이름 맞추기 실패: %s", exc)
        finally:
            db.close()
    scheduler.add_job(_sync_names_job, 'cron', hour=7, minute=10, id='sync_stock_names', replace_existing=True, max_instances=1)
    # 08:30 어젯밤 미국 반도체 장비 → 소부장 시초 대응 알림 (2026-10-06)
    scheduler.add_job(lambda: _tg("send_us_overnight"), 'cron', day_of_week='mon-fri', hour=7, minute=50, id='us_overnight',   # 넥장 프리마켓(08:00) 전에 (2026-10-08, 원래 08:30)
                      replace_existing=True, max_instances=1)
    # 19:00 오늘 소부장·기판 종베가 있으면 미국 장비주 프리마켓 → 20:00 넥스트레이드 애프터마켓 전 정리 판단
    # 장중 4분마다 과매도 줍기 미리 계산 — 오늘 탭 카드가 바로 뜨게 (계산 12초, 토스 9번)
    def _warm_dip() -> None:
        from backend.screener.my_pattern import dip_live  # noqa: PLC0415
        db = SessionLocal()
        try:
            dip_live(db, max_age=0)
        except Exception as exc:  # noqa: BLE001
            logger.error("과매도 줍기 미리 계산 실패: %s", type(exc).__name__)
        finally:
            db.close()
    scheduler.add_job(_warm_dip, 'cron', day_of_week='mon-fri', hour='9-15', minute='*/4', id='dip_warm',
                      replace_existing=True, max_instances=1)
    # 배포·재시작 직후에도 카드가 바로 뜨게 장중이면 한 번 바로 계산
    from datetime import datetime as _dt, timedelta as _td  # noqa: PLC0415
    from zoneinfo import ZoneInfo as _Z  # noqa: PLC0415
    _now = _dt.now(_Z("Asia/Seoul"))
    if _now.weekday() < 5 and 900 <= _now.hour * 100 + _now.minute <= 1540:
        scheduler.add_job(_warm_dip, 'date', run_date=_now + _td(seconds=20), id='dip_warm_boot', replace_existing=True)
    # 20:20 60분봉 쌓기 (화면엔 안 씀, 4시간봉 신호 검증용 — backend/services/intraday_store.py, 2026-10-09)
    def _store_hourly() -> None:
        from backend.services.intraday_store import store_hourly  # noqa: PLC0415
        from backend.utils.dates import is_trading_day  # noqa: PLC0415
        if not is_trading_day(_dt.now(_Z("Asia/Seoul")).date()):
            return
        db = SessionLocal()
        try:
            store_hourly(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("60분봉 저장 실패: %s", type(exc).__name__)
        finally:
            db.close()
    scheduler.add_job(_store_hourly, 'cron', day_of_week='mon-fri', hour=20, minute=20, id='store_hourly', replace_existing=True, max_instances=1)

    def _log_signals() -> None:
        from backend.services.weekly_review import log_signals  # noqa: PLC0415
        db = SessionLocal()
        try:
            logger.info("마감 신호 기록: %s", log_signals(db))
        except Exception as exc:  # noqa: BLE001
            logger.error("마감 신호 기록 실패: %s", type(exc).__name__)
        finally:
            db.close()
    # 18:30 그날 ▲ 진입·종가 점수 6↑ 기록 (18:00 시세 다시 받은 뒤) — 차트는 지금 규칙으로 다시 그린 것이라 실제로 뜬 신호를 따로 쌓는다
    scheduler.add_job(_log_signals, 'cron', day_of_week='mon-fri', hour=18, minute=30, id='signal_log', replace_existing=True, max_instances=1)

    def _weekly() -> None:
        from backend.services.weekly_review import send_weekly  # noqa: PLC0415
        db = SessionLocal()
        try:
            send_weekly(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("주간 점검 실패: %s", type(exc).__name__)
        finally:
            db.close()
    def _close_entry() -> None:
        from backend.services.close_entry_alert import send as ce_send  # noqa: PLC0415
        db = SessionLocal()
        try:
            ce_send(db)
        except Exception as exc:  # noqa: BLE001
            logger.error("종가 진입 후보 알림 실패: %s", type(exc).__name__)
        finally:
            db.close()
    # 15:12 종가 진입 후보 (실시간 점수 6↑ · 손절폭 짧은 순) — 종가에 들어가기 전에 볼 수 있게 (휴장일엔 실시간 점수가 없어 안 보냄)
    scheduler.add_job(_close_entry, 'cron', day_of_week='mon-fri', hour=15, minute=12, id='close_entry_alert', replace_existing=True, max_instances=1)

    # 토요일 08:30 주간 점검 (규칙 어긴 매매 · 관심 종목 20일선 이탈 · 섹터 돈 흐름 · 이번 주 신호 성적)
    scheduler.add_job(_weekly, 'cron', day_of_week='sat', hour=8, minute=30, id='weekly_review', replace_existing=True, max_instances=1)
    # 14:50 과매도 줍기 점검 — 오른 섹터가 오늘 -2%↓면 종가 매수 후보
    scheduler.add_job(lambda: _tg("send_dip_live"), 'cron', day_of_week='mon-fri', hour=14, minute=50, id='dip_live',
                      replace_existing=True, max_instances=1)
    scheduler.add_job(lambda: _tg("send_us_premarket"), 'cron', day_of_week='mon-fri', hour=19, minute=0, id='us_premarket',
                      replace_existing=True, max_instances=1)
    scheduler.add_job(refresh_marcap, 'date', run_date=datetime.now(timezone.utc)+timedelta(seconds=30),
                      id='marcap_caps_startup', replace_existing=True)
    from backend.services.industry_map import refresh as refresh_industry
    scheduler.add_job(refresh_industry, 'cron', hour=7, minute=5, id='industry_map_daily', replace_existing=True, max_instances=1)
    scheduler.add_job(refresh_industry, 'date', run_date=datetime.now(timezone.utc)+timedelta(seconds=40),
                      id='industry_map_startup', replace_existing=True)
    from backend.services.earnings_screen import refresh as refresh_earnings
    scheduler.add_job(refresh_earnings, 'cron', day_of_week='mon-fri', hour=17, minute=40,
                      id='earnings_screen_daily', replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(refresh_earnings, 'date', run_date=datetime.now(timezone.utc)+timedelta(seconds=90),
                      id='earnings_screen_startup', replace_existing=True)
    scheduler.add_job(_telegram_poll_job, "interval", seconds=30, id="telegram_poll", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(_telegram_alert_job, "interval", minutes=2, id="telegram_alerts", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(_telegram_close_check_job, "cron", day_of_week="mon-fri", hour=15, minute=15, id="telegram_close_check",
                      replace_existing=True, max_instances=1)
    # 사용자 관심 종목 장 마감 점검 (backend/services/watchlist.py) — 휴장일이면 토스 일봉 날짜로 걸러져 안 보냄
    scheduler.add_job(lambda: _tg_watch(), "cron", day_of_week="mon-fri", hour=15, minute=40, id="user_watchlist_report",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(_telegram_summary_job, "cron", day_of_week="mon-fri", hour=15, minute="50,58", id="telegram_summary_fallback",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(_telegram_summary_job, "cron", day_of_week="mon-fri", hour=16, minute="10,30", id="telegram_summary_fallback2",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    logger.info("Scheduler started: daily_pipeline=15:41 + 18:00 KST, nightly_backfill=03:00 KST, universe_refresh=Mon 08:00 KST")
    return scheduler
