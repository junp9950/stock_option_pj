"""
DB 기반 히스토리컬 백테스트.

FDR 다운로드 없이 DB에 저장된 StockSignal + SpotDailyPrice + MarketSignal로
T+1 수익률을 검증한다.

특징:
  - 실제 외인·기관 수급 데이터 포함 점수 사용
  - 시장 필터: MarketSignal 또는 KOSPI200 SpotDailyPrice MA20
  - 손절/익절 지원 (SpotDailyPrice에 OHLC 있을 때)
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from backend.db.models import MarketSignal, SpotDailyPrice, Stock, StockSignal
from backend.utils.logger import get_logger

logger = get_logger(__name__)

MIN_SCORE = 0.0   # DB 기반이므로 점수 필터는 API 파라미터로 조절
KOSPI200_CODE = "069500"  # KODEX 200 ETF 코드 (SpotDailyPrice에 있을 가능성 높음)


def _simulate_exit_ohlc(open_p: float, high_p: float, low_p: float, close_p: float,
                         entry_price: float, stop_loss: float, take_profit: float) -> float:
    """T+1 OHLC로 손절/익절 시뮬레이션."""
    stop_price = entry_price * (1 - stop_loss)
    tp_price = entry_price * (1 + take_profit)

    if open_p <= stop_price:
        return open_p  # 갭 다운 → 오픈에 손절
    if open_p >= tp_price:
        return open_p  # 갭 업 → 오픈에 익절
    if low_p <= stop_price:
        return stop_price  # 장중 손절
    if high_p >= tp_price:
        return tp_price  # 장중 익절
    return close_p


def run_db_backtest(
    db: Session,
    start_date: date,
    end_date: date,
    top_n: int = 5,
    fee_rate: float = 0.00015,
    slippage: float = 0.0005,
    min_score: float = 0.0,
    use_market_filter: bool = True,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
) -> dict:
    """
    DB 시그널 기반 T+1 백테스트.

    start_date ~ end_date 동안 매 거래일:
      1. StockSignal에서 상위 top_n 종목 선택 (min_score 이상)
      2. SpotDailyPrice에서 당일 종가(진입) + T+1 가격(청산) 조회
      3. 시장 필터: MarketSignal.regime이 없거나 bull이면 진입
    """
    stocks_map: dict[str, str] = {
        s.code: s.name for s in db.scalars(select(Stock).where(Stock.is_active.is_(True)))
    }
    if not stocks_map:
        return {"error": "종목 없음"}

    # 기간 내 모든 날짜의 StockSignal 일괄 조회
    all_signals = list(db.scalars(
        select(StockSignal).where(
            StockSignal.trading_date.between(start_date, end_date)
        ).order_by(StockSignal.trading_date, desc(StockSignal.score))
    ))

    # 날짜별로 그룹화
    from collections import defaultdict
    signals_by_date: dict[date, list[StockSignal]] = defaultdict(list)
    for sig in all_signals:
        signals_by_date[sig.trading_date].append(sig)

    if not signals_by_date:
        return {"error": f"해당 기간({start_date} ~ {end_date}) DB 시그널 없음. 시그널 재계산 필요."}

    # 기간 내 가격 데이터 일괄 조회 (진입일 + T+1)
    price_start = start_date
    price_end = end_date + timedelta(days=5)  # T+1 커버
    all_prices = list(db.scalars(
        select(SpotDailyPrice).where(
            SpotDailyPrice.trading_date.between(price_start, price_end)
        )
    ))
    # (code, date) → SpotDailyPrice
    price_map: dict[tuple[str, date], SpotDailyPrice] = {
        (p.stock_code, p.trading_date): p for p in all_prices
    }

    # 시장 필터: MarketSignal에서 날짜별 regime 조회
    market_signals: dict[date, str] = {}
    if use_market_filter:
        for ms in db.scalars(
            select(MarketSignal).where(
                MarketSignal.trading_date.between(start_date, end_date)
            )
        ):
            # signal: "강세매수"/"약세"/"중립" 등 — "약세" 포함 시 bear 처리
            market_signals[ms.trading_date] = "bear" if "약세" in (ms.signal or "") else "bull"

    # 거래일 정렬
    sorted_dates = sorted(signals_by_date.keys())

    daily_results = []
    all_returns: list[float] = []
    skipped_market = 0
    skipped_score = 0

    for i, signal_date in enumerate(sorted_dates):
        # T+1 날짜 찾기: signal_date 다음 가격 데이터가 있는 날
        next_date = _find_next_price_date(price_map, signal_date, sorted_dates, i)
        if next_date is None:
            continue

        # 시장 필터
        if use_market_filter and market_signals:
            regime = market_signals.get(signal_date, "bull")
            if regime == "bear":
                skipped_market += 1
                continue

        # 당일 상위 N 종목
        day_signals = signals_by_date[signal_date]
        candidates = [s for s in day_signals if s.score >= min_score][:top_n]

        if not candidates:
            skipped_score += 1
            continue

        returns = []
        for sig in candidates:
            entry_price_row = price_map.get((sig.stock_code, signal_date))
            exit_price_row = price_map.get((sig.stock_code, next_date))
            if entry_price_row is None or exit_price_row is None:
                continue

            entry = float(entry_price_row.close_price)
            if entry <= 0:
                continue

            # 손절/익절 시뮬레이션
            if stop_loss > 0 or take_profit > 0:
                sl = stop_loss if stop_loss > 0 else 1.0
                tp = take_profit if take_profit > 0 else 1.0
                exit_p = _simulate_exit_ohlc(
                    float(exit_price_row.open_price or entry),
                    float(exit_price_row.high_price or entry),
                    float(exit_price_row.low_price or entry),
                    float(exit_price_row.close_price),
                    entry, sl, tp,
                )
            else:
                exit_p = float(exit_price_row.close_price)

            net = (exit_p - entry) / entry - (fee_rate + slippage) * 2
            returns.append((sig.stock_code, net))

        if not returns:
            continue

        rets = [r for _, r in returns]
        avg = sum(rets) / len(rets)
        wr = sum(1 for r in rets if r > 0) / len(rets)
        all_returns.extend(rets)
        daily_results.append({
            "date": signal_date.isoformat(),
            "avg_return_pct": round(avg * 100, 3),
            "win_rate_pct": round(wr * 100, 1),
            "count": len(rets),
            "top_stocks": [
                f"{stocks_map.get(c, c)}({round(r*100,1)}%)"
                for c, r in returns
            ],
        })

    if not all_returns:
        return {"error": "수익률 계산 가능한 날짜 없음 (조건 확인 필요)"}

    avg_ret = sum(all_returns) / len(all_returns)
    win_rate = sum(1 for r in all_returns if r > 0) / len(all_returns)

    # 복리 누적 + MDD
    daily_avg_returns = [dr["avg_return_pct"] / 100 for dr in daily_results]
    compound = 1.0
    peak = 1.0
    max_dd = 0.0
    cum_curve = []
    for r in daily_avg_returns:
        compound *= (1 + r)
        if compound > peak:
            peak = compound
        dd = (peak - compound) / peak
        if dd > max_dd:
            max_dd = dd
        cum_curve.append(round((compound - 1) * 100, 3))

    # 샤프
    if len(daily_avg_returns) > 1:
        mean_d = sum(daily_avg_returns) / len(daily_avg_returns)
        var = sum((r - mean_d) ** 2 for r in daily_avg_returns) / (len(daily_avg_returns) - 1)
        std = math.sqrt(var)
        sharpe = (mean_d / std * math.sqrt(252)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    logger.info(
        "DB 백테스트 완료: %s~%s, 진입%d일, 승률=%.1f%%, 누적=%.1f%%",
        start_date, end_date, len(daily_results), win_rate * 100, (compound - 1) * 100,
    )

    return {
        "mode": "db",
        "period": f"{start_date.isoformat()} ~ {end_date.isoformat()}",
        "trading_days": len(sorted_dates),
        "simulated_days": len(daily_results),
        "skipped_market_filter": skipped_market,
        "skipped_score_filter": skipped_score,
        "total_trades": len(all_returns),
        "top_n": top_n,
        "filters": {
            "min_score": min_score,
            "market_filter": use_market_filter,
            "stop_loss_pct": round(stop_loss * 100, 1) if stop_loss > 0 else None,
            "take_profit_pct": round(take_profit * 100, 1) if take_profit > 0 else None,
        },
        "metrics": {
            "win_rate_pct": round(win_rate * 100, 1),
            "avg_return_pct": round(avg_ret * 100, 3),
            "cumulative_return_pct": round((compound - 1) * 100, 2),
            "sharpe": round(sharpe, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
        },
        "cumulative_curve": cum_curve,
        "daily_results": daily_results,
    }


def _find_next_price_date(
    price_map: dict[tuple[str, date], SpotDailyPrice],
    signal_date: date,
    sorted_dates: list[date],
    idx: int,
) -> date | None:
    """signal_date 다음으로 가격이 존재하는 날짜 반환 (최대 5영업일 탐색)."""
    # 정렬된 시그널 날짜 목록에서 다음 날 반환 (주말/공휴일 자동 스킵)
    if idx + 1 < len(sorted_dates):
        next_d = sorted_dates[idx + 1]
        # 7일 이내이면 정상 T+1
        if (next_d - signal_date).days <= 7:
            return next_d
    return None
