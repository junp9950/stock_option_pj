from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import BacktestResult, BacktestRun, Recommendation, SpotDailyPrice
from backend.utils.dates import latest_trading_day


def run_backtest(db: Session, end_date: date | None = None) -> dict[str, float]:
    target_date = end_date or latest_trading_day()
    run = BacktestRun(period_label="최근 6개월", note="MVP 단순 백테스트")
    db.add(run)
    db.commit()
    db.refresh(run)

    recommendations = list(db.scalars(select(Recommendation).where(Recommendation.trading_date == target_date)))
    if not recommendations:
        metrics = {"avg_return_1d": 0.0, "win_rate_1d": 0.0, "recommendation_count": 0.0}
    else:
        sample_returns = []
        for rec in recommendations:
            future_price = db.scalar(
                select(SpotDailyPrice).where(
                    SpotDailyPrice.trading_date == target_date,
                    SpotDailyPrice.stock_code == rec.stock_code,
                )
            )
            if future_price:
                sample_returns.append(future_price.change_pct / 100)
        avg_return = sum(sample_returns) / len(sample_returns) if sample_returns else 0.0
        win_rate = sum(1 for item in sample_returns if item > 0) / len(sample_returns) if sample_returns else 0.0
        metrics = {
            "avg_return_1d": round(avg_return, 4),
            "win_rate_1d": round(win_rate, 4),
            "recommendation_count": float(len(recommendations)),
        }

    for key, value in metrics.items():
        db.add(BacktestResult(run_id=run.id, metric=key, value=value, note="MVP metric"))
    db.commit()
    return metrics

