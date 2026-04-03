from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

import asyncio

from backend.collector.borrow import collect_borrow_data
from backend.collector.derivatives import collect_derivatives_data
from backend.collector.program_trading import collect_program_trading_data
from backend.collector.short_selling import collect_short_selling_data
from backend.collector.spot import collect_spot_data
from backend.db.models import JobLog
from backend.signal_engine.market_signal import calculate_market_signal
from backend.signal_engine.stock_signal import calculate_stock_signals
from backend.notification.telegram_bot import send_daily_message
from backend.screener.scorer import build_recommendations
from backend.services.validation import validate_daily_data
from backend.utils.dates import latest_trading_day


def run_daily_pipeline(db: Session, trading_date: date | None = None) -> dict[str, object]:
    target_date = trading_date or latest_trading_day()
    db.add(JobLog(trading_date=target_date, stage="pipeline", status="started", message="daily pipeline started"))
    db.commit()

    collect_spot_data(db, target_date)
    collect_short_selling_data(db, target_date)
    collect_borrow_data(db, target_date)
    collect_derivatives_data(db, target_date)
    collect_program_trading_data(db, target_date)
    warnings = validate_daily_data(db, target_date)
    market_signal = calculate_market_signal(db, target_date)
    stock_signals = calculate_stock_signals(db, target_date)
    recommendations = build_recommendations(db, target_date)

    db.add(JobLog(trading_date=target_date, stage="pipeline", status="completed", message="daily pipeline completed"))
    db.commit()

    # 텔레그램 전송 (토큰 미설정 시 자동 스킵)
    try:
        asyncio.run(send_daily_message(db, target_date.isoformat()))
    except RuntimeError:
        # 이미 실행 중인 이벤트 루프에서 호출된 경우 (uvicorn 환경)
        import threading
        threading.Thread(
            target=lambda: asyncio.run(send_daily_message(db, target_date.isoformat())),
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001
        pass

    return {
        "trading_date": target_date.isoformat(),
        "warnings": warnings,
        "market_signal": market_signal.signal,
        "market_score": market_signal.score,
        "stock_signal_count": len(stock_signals),
        "recommendation_count": len(recommendations),
    }


def run_backfill_pipeline(db: Session, start_date: date, end_date: date) -> list[dict]:
    """start_date ~ end_date 범위의 날짜를 순서대로 파이프라인 실행."""
    results = []
    current = start_date
    while current <= end_date:
        try:
            result = run_daily_pipeline(db, current)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            results.append({"trading_date": current.isoformat(), "error": str(exc)})
        current += timedelta(days=1)
    return results
