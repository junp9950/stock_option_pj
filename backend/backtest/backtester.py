from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import BacktestResult, BacktestRun, Recommendation, SpotDailyPrice
from backend.utils.dates import latest_trading_day, is_trading_day


def _next_trading_day(d: date) -> date:
    """d 다음의 첫 번째 거래일 반환."""
    cursor = d + timedelta(days=1)
    for _ in range(14):  # 최대 2주 탐색
        if is_trading_day(cursor):
            return cursor
        cursor += timedelta(days=1)
    return d + timedelta(days=1)  # fallback


def _backtest_single_date(db: Session, rec_date: date, fee_rate: float = 0.00015, slippage: float = 0.0005) -> Optional[dict]:
    """rec_date의 추천 종목을 매수하고 T+1 종가에 매도하는 1일 수익률 계산."""
    recommendations = list(db.scalars(select(Recommendation).where(Recommendation.trading_date == rec_date)))
    if not recommendations:
        return None

    next_date = _next_trading_day(rec_date)
    returns = []
    for rec in recommendations:
        # T일 종가 (진입가)
        entry_price_row = db.scalar(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == rec_date,
                SpotDailyPrice.stock_code == rec.stock_code,
            )
        )
        # T+1일 종가 (청산가)
        exit_price_row = db.scalar(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == next_date,
                SpotDailyPrice.stock_code == rec.stock_code,
            )
        )
        if entry_price_row is None or exit_price_row is None:
            continue
        if entry_price_row.close_price <= 0:
            continue

        raw_return = (exit_price_row.close_price - entry_price_row.close_price) / entry_price_row.close_price
        net_return = raw_return - (fee_rate + slippage) * 2  # 매수/매도 양쪽
        returns.append(net_return)

    if not returns:
        return None

    avg_return = sum(returns) / len(returns)
    win_rate = sum(1 for r in returns if r > 0) / len(returns)
    return {
        "trading_date": rec_date,
        "avg_return_1d": round(avg_return, 6),
        "win_rate_1d": round(win_rate, 4),
        "sample_count": len(returns),
    }


def run_backtest(db: Session, end_date: date | None = None, lookback_days: int = 60) -> dict:
    """최근 lookback_days일 치 추천 기록을 T+1 수익률로 백테스트."""
    from backend.config import get_config
    config = get_config()
    target_end = end_date or latest_trading_day()
    target_start = target_end - timedelta(days=lookback_days)

    run = BacktestRun(
        period_label=f"{target_start.isoformat()} ~ {target_end.isoformat()} T+1 백테스트",
        note=f"lookback={lookback_days}일, fee={config.fee_rate}, slippage={config.slippage_rate}",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 해당 기간 추천이 존재하는 날짜만 수집
    rec_dates = sorted({
        r.trading_date
        for r in db.scalars(
            select(Recommendation).where(
                Recommendation.trading_date >= target_start,
                Recommendation.trading_date <= target_end,
            )
        )
    })

    all_returns = []
    daily_results = []
    for rec_date in rec_dates:
        result = _backtest_single_date(db, rec_date, config.fee_rate, config.slippage_rate)
        if result is None:
            continue
        all_returns.extend([result["avg_return_1d"]] * result["sample_count"])
        daily_results.append(result)

    if all_returns:
        avg_return = sum(all_returns) / len(all_returns)
        win_rate = sum(1 for r in all_returns if r > 0) / len(all_returns)
        # 단순 샤프 추정: 평균수익 / 표준편차 * sqrt(252)
        if len(all_returns) > 1:
            variance = sum((r - avg_return) ** 2 for r in all_returns) / (len(all_returns) - 1)
            std = variance ** 0.5
            sharpe = (avg_return / std * (252 ** 0.5)) if std > 0 else 0.0
        else:
            sharpe = 0.0
        # 누적 수익 (단순합)
        cumulative = sum(all_returns)
    else:
        avg_return = win_rate = sharpe = cumulative = 0.0

    metrics = {
        "avg_return_1d": round(avg_return, 6),
        "win_rate_1d": round(win_rate, 4),
        "sharpe_approx": round(sharpe, 4),
        "cumulative_return": round(cumulative, 4),
        "total_trades": float(len(all_returns)),
        "trading_days_covered": float(len(daily_results)),
    }

    for key, value in metrics.items():
        db.add(BacktestResult(run_id=run.id, metric=key, value=value, note=f"T+1 백테스트 ({target_start}~{target_end})"))
    db.commit()

    return {
        "run_id": run.id,
        "period": f"{target_start.isoformat()} ~ {target_end.isoformat()}",
        "metrics": metrics,
        "daily_results": [
            {
                "date": r["trading_date"].isoformat(),
                "avg_return_pct": round(r["avg_return_1d"] * 100, 3),
                "win_rate_pct": round(r["win_rate_1d"] * 100, 1),
                "count": r["sample_count"],
            }
            for r in daily_results
        ],
    }
