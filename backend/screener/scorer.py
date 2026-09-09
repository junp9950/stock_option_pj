from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import MarketSignal, Recommendation, SpotDailyPrice, Stock, StockSignal


def _t1_score(base_score: float, price: SpotDailyPrice, prev_change_pct: float = 0.0) -> float:
    """T+1 매수 적합도 점수: 기본 점수 - 급등 페널티.

    2026-09-09: 연속 수급 보너스(연속매수일수·동반매수비율 가산점)를 제거함 —
    8월 실데이터로 검증한 결과 보너스 있는 쪽이 오히려 더 나빴음
    (승률 54.8%->53.2%, 평균수익률 +1.023%->+1.002%). stock_signal.py의
    co_buy/consecutive_buy 지표 자체도 IC가 거의 0이거나 음수로 나와서
    같은 결론이었음 — 검증 안 된 가산점을 추가로 얹을 이유가 없음.
    """
    score = base_score

    # 당일 급등 페널티
    change_pct = float(price.change_pct) if price.change_pct else 0.0
    if change_pct >= 8:
        score -= 0.5
    elif change_pct >= 5:
        score -= 0.25
    elif change_pct >= 3:
        score -= 0.10
    elif change_pct <= -3:
        score += 0.05

    # 전일 급등 페널티 (당일보다 완화)
    if prev_change_pct >= 8:
        score -= 0.30
    elif prev_change_pct >= 5:
        score -= 0.15
    elif prev_change_pct >= 3:
        score -= 0.05

    return score


def build_recommendations(db: Session, trading_date: date) -> list[Recommendation]:
    config = get_config()
    market_signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == trading_date))
    if market_signal is None:
        return []

    # 기존 추천 삭제 (소량이라 빠름)
    db.query(Recommendation).filter(Recommendation.trading_date == trading_date).delete()
    db.commit()

    if market_signal.signal == "하방":
        return []

    stock_signals = list(db.scalars(select(StockSignal).where(StockSignal.trading_date == trading_date)))

    codes = [s.stock_code for s in stock_signals]

    # 전일 가격 일괄 조회 (전일 급등 페널티용)
    from sqlalchemy import func  # noqa: PLC0415
    prev_date = db.scalar(
        select(func.max(SpotDailyPrice.trading_date)).where(SpotDailyPrice.trading_date < trading_date)
    )
    prev_prices_map: dict[str, float] = {}
    if prev_date:
        prev_prices = db.scalars(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == prev_date,
                SpotDailyPrice.stock_code.in_(codes),
            )
        )
        prev_prices_map = {p.stock_code: float(p.change_pct or 0) for p in prev_prices}

    ranked = []
    for stock_signal in stock_signals:
        stock = db.scalar(select(Stock).where(Stock.code == stock_signal.stock_code))
        price = db.scalar(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == trading_date,
                SpotDailyPrice.stock_code == stock_signal.stock_code,
            )
        )
        if stock is None or price is None:
            continue
        if stock.market_cap < config.min_market_cap or price.trading_value < config.min_trading_value:
            continue

        base_score = round(
            market_signal.score * config.score_market_weight + stock_signal.score * config.score_stock_weight,
            2,
        )
        prev_change = prev_prices_map.get(stock_signal.stock_code, 0.0)
        total_score = round(_t1_score(base_score, price, prev_change), 4)
        ranked.append((total_score, base_score, stock, price, stock_signal))

    ranked.sort(key=lambda item: item[0], reverse=True)
    max_count = config.recommendation_count_bullish if market_signal.signal == "상방" else config.recommendation_count_neutral

    recommendations = []
    for rank, (total_score, base_score, stock, price, stock_signal) in enumerate(ranked[:max_count], start=1):
        vals = dict(
            trading_date=trading_date,
            stock_code=stock.code,
            rank=rank,
            stock_name=stock.name,
            total_score=total_score,
            market_score=market_signal.score,
            stock_score=stock_signal.score,
            close_price=price.close_price,
            change_pct=price.change_pct,
            market_signal=market_signal.signal,
        )
        db.execute(
            pg_insert(Recommendation).values(**vals)
            .on_conflict_do_update(
                constraint="uq_recommendations",
                set_={k: v for k, v in vals.items() if k not in ("trading_date", "stock_code")},
            )
        )
        recommendations.append(Recommendation(**vals))

    db.commit()
    return recommendations
