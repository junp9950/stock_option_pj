from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import MarketSignal, Recommendation, SpotDailyPrice, Stock, StockSignal


def build_recommendations(db: Session, trading_date: date) -> list[Recommendation]:
    config = get_config()
    market_signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == trading_date))
    if market_signal is None:
        return []

    db.query(Recommendation).filter(Recommendation.trading_date == trading_date).delete()
    db.commit()

    if market_signal.signal == "하방":
        return []

    stock_signals = list(db.scalars(select(StockSignal).where(StockSignal.trading_date == trading_date)))
    recommendations: list[Recommendation] = []
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
        total_score = round(
            market_signal.score * config.score_market_weight + stock_signal.score * config.score_stock_weight,
            2,
        )
        ranked.append((total_score, stock, price, stock_signal))

    ranked.sort(key=lambda item: item[0], reverse=True)
    max_count = config.recommendation_count_bullish if market_signal.signal == "상방" else config.recommendation_count_neutral

    for rank, (total_score, stock, price, stock_signal) in enumerate(ranked[:max_count], start=1):
        recommendation = Recommendation(
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
        db.add(recommendation)
        recommendations.append(recommendation)

    db.commit()
    return recommendations

