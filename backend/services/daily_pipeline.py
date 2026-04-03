from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend.collector.borrow import collect_borrow_data
from backend.collector.derivatives import collect_derivatives_data
from backend.collector.program_trading import collect_program_trading_data
from backend.collector.short_selling import collect_short_selling_data
from backend.collector.spot import collect_spot_data
from backend.db.models import JobLog
from backend.signal_engine.market_signal import calculate_market_signal
from backend.signal_engine.stock_signal import calculate_stock_signals
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
    return {
        "trading_date": target_date.isoformat(),
        "warnings": warnings,
        "market_signal": market_signal.signal,
        "market_score": market_signal.score,
        "stock_signal_count": len(stock_signals),
        "recommendation_count": len(recommendations),
    }
