from __future__ import annotations

from datetime import date

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import (
    DerivativesFuturesDaily,
    FuturesDailyPrice,
    IndexDaily,
    MarketSignal,
    MarketSignalDetail,
    OpenInterestDaily,
    ProgramTradingDaily,
)


def _bucket_score(value: float, thresholds: list[tuple[float, float]]) -> float:
    for upper_bound, score in thresholds:
        if value <= upper_bound:
            return score
    return thresholds[-1][1]


def _normalize_weights(weights: dict[str, float], enabled: dict[str, bool]) -> dict[str, float]:
    filtered = {key: value for key, value in weights.items() if enabled.get(key, True)}
    total = sum(filtered.values()) or 1.0
    return {key: value / total for key, value in filtered.items()}


def calculate_market_signal(db: Session, trading_date: date) -> MarketSignal:
    config = get_config()
    futures = db.scalar(select(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == trading_date))
    index_daily = db.scalar(select(IndexDaily).where(IndexDaily.trading_date == trading_date))
    futures_price = db.scalar(select(FuturesDailyPrice).where(FuturesDailyPrice.trading_date == trading_date))
    open_interest = db.scalar(select(OpenInterestDaily).where(OpenInterestDaily.trading_date == trading_date))
    program = db.scalar(select(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == trading_date))

    previous_futures = list(
        db.scalars(
            select(DerivativesFuturesDaily)
            .where(DerivativesFuturesDaily.trading_date <= trading_date)
            .order_by(desc(DerivativesFuturesDaily.trading_date))
            .limit(5)
        )
    )

    db.execute(delete(MarketSignalDetail).where(MarketSignalDetail.trading_date == trading_date))
    db.execute(delete(MarketSignal).where(MarketSignal.trading_date == trading_date))
    db.commit()

    if not all([futures, index_daily, futures_price, open_interest, program]):
        signal = MarketSignal(trading_date=trading_date, score=0.0, signal="중립")
        db.add(signal)
        db.commit()
        return signal

    basis = futures_price.close_price - index_daily.close_price
    futures_5d = sum(item.foreign_net_contracts for item in previous_futures)
    previous_direction = previous_futures[1].foreign_net_contracts if len(previous_futures) > 1 else 0.0
    turn_value = 2.0 if previous_direction < 0 < futures.foreign_net_contracts else -2.0 if previous_direction > 0 > futures.foreign_net_contracts else 0.0
    volume_pcr = open_interest.put_oi / max(open_interest.call_oi, 1)
    oi_pcr = (open_interest.put_oi + 5_000) / max(open_interest.call_oi + 10_000, 1)
    basis_trend = basis - 0.6
    call_put_oi_delta = open_interest.call_oi - open_interest.put_oi
    arbitrage_pressure_score = 0.0

    details = [
        ("foreign_futures_daily", futures.foreign_net_contracts, _bucket_score(futures.foreign_net_contracts, [(-10000, -2), (-3000, -1), (3000, 0), (10000, 1), (float("inf"), 2)]), "외국인 선물 당일 순매수"),
        ("foreign_futures_5d", futures_5d, _bucket_score(futures_5d, [(-30000, -2), (-10000, -1), (10000, 0), (30000, 1), (float("inf"), 2)]), "외국인 선물 5일 누적"),
        ("foreign_turn", turn_value, turn_value, "외국인 선물 방향 전환"),
        ("basis_level", basis, _bucket_score(basis, [(-1.5, -2), (-0.5, -1), (0.5, 0), (1.5, 1), (float("inf"), 2)]), "베이시스 수준"),
        ("basis_trend", basis_trend, _bucket_score(basis_trend, [(-0.5, -2), (-0.1, -1), (0.1, 0), (0.5, 1), (float("inf"), 2)]), "베이시스 추세"),
        ("volume_pcr", volume_pcr, _bucket_score(volume_pcr, [(0.5, -2), (0.7, -1), (1.0, 0), (1.3, 1), (float("inf"), 2)]), "거래량 PCR"),
        ("oi_pcr", oi_pcr, _bucket_score(oi_pcr, [(0.6, -2), (0.8, -1), (1.0, 0), (1.2, 1), (float("inf"), 2)]), "미결제약정 PCR"),
        ("call_put_oi_change", call_put_oi_delta, _bucket_score(call_put_oi_delta, [(-10000, -2), (-1000, -1), (1000, 0), (10000, 1), (float("inf"), 2)]), "콜/풋 OI 변화"),
        ("program_non_arbitrage", program.non_arbitrage_net_buy / 100_000_000, _bucket_score(program.non_arbitrage_net_buy / 100_000_000, [(-3000, -2), (-500, -1), (500, 0), (3000, 1), (float("inf"), 2)]), "비차익 순매수"),
        ("arbitrage_pressure", None, arbitrage_pressure_score, "차익잔고 압력 TODO"),
    ]

    enabled = {key: key != "arbitrage_pressure" for key, *_ in details}
    normalized_weights = _normalize_weights(config.market_signal_weights, enabled)
    weighted_score = 0.0

    for key, raw_value, normalized_score, interpretation in details:
        is_enabled = enabled[key]
        if is_enabled:
            weighted_score += normalized_score * normalized_weights[key]
        db.add(
            MarketSignalDetail(
                trading_date=trading_date,
                key=key,
                raw_value=raw_value,
                normalized_score=normalized_score,
                interpretation=interpretation,
                is_enabled=is_enabled,
                source="computed" if is_enabled else "fallback",
                note=None if is_enabled else "Fallback disabled: direct arbitrage pressure data unavailable in MVP",
            )
        )

    final_score = round(weighted_score * 5, 2)
    final_signal = "상방" if final_score >= config.bullish_threshold else "하방" if final_score <= config.bearish_threshold else "중립"
    market_signal = MarketSignal(trading_date=trading_date, score=final_score, signal=final_signal)
    db.add(market_signal)
    db.commit()
    return market_signal
