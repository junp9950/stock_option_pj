from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_config
from backend.db.models import ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow, Stock, StockSignal, StockSignalDetail


def _normalize_weights(weights: dict[str, float], enabled: dict[str, bool]) -> dict[str, float]:
    filtered = {key: value for key, value in weights.items() if enabled.get(key, True)}
    total = sum(filtered.values()) or 1.0
    return {key: value / total for key, value in filtered.items()}


def _threshold_score(value: float, high: float, medium: float) -> float:
    if value >= high:
        return 2.0
    if value >= medium:
        return 1.0
    if value <= -high:
        return -2.0
    if value <= -medium:
        return -1.0
    return 0.0


def calculate_stock_signals(db: Session, trading_date: date) -> list[StockSignal]:
    config = get_config()
    stocks = list(db.scalars(select(Stock).where(Stock.is_active.is_(True)).order_by(Stock.code)))
    results: list[StockSignal] = []

    db.query(StockSignalDetail).filter(StockSignalDetail.trading_date == trading_date).delete()
    db.query(StockSignal).filter(StockSignal.trading_date == trading_date).delete()
    db.commit()

    for stock in stocks:
        price = db.scalar(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == trading_date,
                SpotDailyPrice.stock_code == stock.code,
            )
        )
        flow = db.scalar(
            select(SpotInvestorFlow).where(
                SpotInvestorFlow.trading_date == trading_date,
                SpotInvestorFlow.stock_code == stock.code,
            )
        )
        short = db.scalar(
            select(ShortSellingDaily).where(
                ShortSellingDaily.trading_date == trading_date,
                ShortSellingDaily.stock_code == stock.code,
            )
        )
        if not all([price, flow, short]):
            continue

        volume_base = max(price.volume, 1)
        foreign_strength = flow.foreign_net_buy / volume_base
        institution_strength = flow.institution_net_buy / volume_base
        co_buy = 2.0 if flow.foreign_net_buy > 0 and flow.institution_net_buy > 0 else 0.0
        volume_surge = price.volume / 1_800_000
        # short_ratio는 pykrx에서 0~100(%) 단위로 수신. 4% 이하면 양호, 1% 이하면 매우 양호.
        # fallback(demo) 데이터는 0~5 범위였으나 실데이터 기준으로 통일.
        short_ratio_pct = short.short_ratio  # 0~100 기준
        short_ratio_score = (
            2.0 if short_ratio_pct <= 1.0
            else 1.0 if short_ratio_pct <= 4.0
            else 0.0 if short_ratio_pct <= 10.0
            else -1.0 if short_ratio_pct <= 20.0
            else -2.0
        )
        ma_position = 2.0 if price.change_pct > 0 else 0.0

        details = [
            ("foreign_strength", foreign_strength, _threshold_score(foreign_strength, 700, 300), "외국인 순매수 강도"),
            ("institution_strength", institution_strength, _threshold_score(institution_strength, 400, 200), "기관 순매수 강도"),
            ("co_buy", co_buy, co_buy, "외국인/기관 동반 매수"),
            ("volume_surge", volume_surge, 2.0 if volume_surge >= 2.0 else 1.0 if volume_surge >= 1.5 else 0.0, "거래량 급증"),
            ("short_ratio_change", short_ratio_pct, short_ratio_score, "공매도 비율 개선"),
            ("ma_position", ma_position, ma_position, "20일선/60일선 상회 대체"),
            ("program_buy", None, 0.0, "종목별 프로그램 순매수 TODO"),
        ]

        enabled = {key: key != "program_buy" for key, *_ in details}
        normalized_weights = _normalize_weights(config.stock_signal_weights, enabled)
        weighted_score = 0.0

        for key, raw_value, normalized_score, interpretation in details:
            is_enabled = enabled[key]
            if is_enabled:
                weighted_score += normalized_score * normalized_weights[key]
            db.add(
                StockSignalDetail(
                    trading_date=trading_date,
                    stock_code=stock.code,
                    key=key,
                    raw_value=raw_value,
                    normalized_score=normalized_score,
                    interpretation=interpretation,
                    is_enabled=is_enabled,
                    source="computed" if is_enabled else "fallback",
                    note=None if is_enabled else "Fallback disabled: stock-level program trading data unavailable in MVP",
                )
            )

        stock_signal = StockSignal(
            trading_date=trading_date,
            stock_code=stock.code,
            score=round(max(0.0, weighted_score * 3.5), 2),
        )
        db.add(stock_signal)
        results.append(stock_signal)

    db.commit()
    return results

