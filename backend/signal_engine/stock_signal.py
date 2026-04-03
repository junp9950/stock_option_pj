from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select, desc
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


def _calc_ma_score(prices: list[float]) -> float:
    """가격 리스트(최신 순)로 MA 위치 점수 계산.
    20일 이동평균 대비 현재가 위치:
      +5% 초과  → +2.0
      0% 초과   → +1.0
      -5% 이상  →  0.0
      -5% 미만  → -1.0
      -10% 미만 → -2.0
    60일선도 계산해 평균.
    """
    if not prices:
        return 0.0
    current = prices[0]

    def _ma_score_single(ma_val: float) -> float:
        if ma_val <= 0:
            return 0.0
        diff_pct = (current - ma_val) / ma_val * 100
        if diff_pct > 5.0:
            return 2.0
        if diff_pct > 0.0:
            return 1.0
        if diff_pct >= -5.0:
            return 0.0
        if diff_pct >= -10.0:
            return -1.0
        return -2.0

    scores = []
    if len(prices) >= 20:
        ma20 = sum(prices[:20]) / 20
        scores.append(_ma_score_single(ma20))
    if len(prices) >= 60:
        ma60 = sum(prices[:60]) / 60
        scores.append(_ma_score_single(ma60))

    return sum(scores) / len(scores) if scores else 0.0


def _calc_rsi(prices: list[float], period: int = 14) -> float | None:
    """RSI(14) 계산. prices는 최신 순. 데이터 부족 시 None 반환."""
    if len(prices) < period + 1:
        return None
    # 오래된 것부터 순서 재정렬
    p = list(reversed(prices[:period + 1]))
    gains = []
    losses = []
    for i in range(1, len(p)):
        diff = p[i] - p[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _rsi_score(rsi: float | None) -> float:
    """RSI 값을 점수로 변환.
    RSI < 30 (과매도)  → +2.0 (매수 기회)
    RSI < 40           → +1.0
    RSI < 60           →  0.0 (중립)
    RSI < 70           → -1.0
    RSI >= 70 (과매수) → -2.0
    """
    if rsi is None:
        return 0.0
    if rsi < 30:
        return 2.0
    if rsi < 40:
        return 1.0
    if rsi < 60:
        return 0.0
    if rsi < 70:
        return -1.0
    return -2.0


def _calc_momentum_5d(prices: list[float]) -> float:
    """최근 5일 가격 모멘텀 점수 (최신 순).
    5거래일 전 대비 현재 수익률 기준:
      +3% 초과  → +2.0
      +1% 초과  → +1.0
      -1% 이상  →  0.0
      -3% 이상  → -1.0
      -3% 미만  → -2.0
    """
    if len(prices) < 5:
        return 0.0
    current, base = prices[0], prices[4]
    if base <= 0:
        return 0.0
    ret = (current - base) / base * 100
    if ret > 3.0:
        return 2.0
    if ret > 1.0:
        return 1.0
    if ret >= -1.0:
        return 0.0
    if ret >= -3.0:
        return -1.0
    return -2.0


def _calc_consecutive_buy(flows: list) -> float:
    """최신 순 SpotInvestorFlow 리스트에서 기관+외국인 동반 매수 연속일 점수."""
    count = 0
    for f in flows:
        if f.institution_net_buy > 0 and f.foreign_net_buy > 0:
            count += 1
        else:
            break
    if count >= 3:
        return 2.0
    if count >= 2:
        return 1.0
    if count >= 1:
        return 0.5
    return 0.0


def _calc_short_trend_score(short_ratios: list[float]) -> float:
    """공매도 비율 추세 점수 계산 (최신 순, 최소 3개 필요).
    최근 1일과 5일 전 비율을 비교해 개선/악화 판단.
    """
    if len(short_ratios) < 3:
        return 0.0
    current = short_ratios[0]
    past = sum(short_ratios[1:min(6, len(short_ratios))]) / min(5, len(short_ratios) - 1)
    change = past - current  # 개선이면 양수
    if change > 2.0:
        return 2.0
    if change > 0.5:
        return 1.0
    if change >= -0.5:
        return 0.0
    if change >= -2.0:
        return -1.0
    return -2.0


def calculate_stock_signals(db: Session, trading_date: date) -> list[StockSignal]:
    config = get_config()
    stocks = list(db.scalars(select(Stock).where(Stock.is_active.is_(True)).order_by(Stock.code)))
    results: list[StockSignal] = []

    db.query(StockSignalDetail).filter(StockSignalDetail.trading_date == trading_date).delete()
    db.query(StockSignal).filter(StockSignal.trading_date == trading_date).delete()
    db.commit()

    # 가격 히스토리 일괄 조회 (60일치)
    history_start = trading_date - timedelta(days=90)
    all_prices = list(db.scalars(
        select(SpotDailyPrice).where(
            SpotDailyPrice.trading_date.between(history_start, trading_date)
        ).order_by(SpotDailyPrice.stock_code, desc(SpotDailyPrice.trading_date))
    ))
    prices_history: dict[str, list[SpotDailyPrice]] = {}
    for p in all_prices:
        prices_history.setdefault(p.stock_code, []).append(p)

    # 공매도 히스토리 일괄 조회 (10일치)
    short_start = trading_date - timedelta(days=20)
    all_shorts = list(db.scalars(
        select(ShortSellingDaily).where(
            ShortSellingDaily.trading_date.between(short_start, trading_date)
        ).order_by(ShortSellingDaily.stock_code, desc(ShortSellingDaily.trading_date))
    ))
    short_history: dict[str, list[ShortSellingDaily]] = {}
    for s in all_shorts:
        short_history.setdefault(s.stock_code, []).append(s)

    # 수급 히스토리 일괄 조회 (10일치, 연속 매수 계산용)
    flow_start = trading_date - timedelta(days=20)
    all_flows_hist = list(db.scalars(
        select(SpotInvestorFlow).where(
            SpotInvestorFlow.trading_date.between(flow_start, trading_date)
        ).order_by(SpotInvestorFlow.stock_code, desc(SpotInvestorFlow.trading_date))
    ))
    flow_history: dict[str, list[SpotInvestorFlow]] = {}
    for f in all_flows_hist:
        flow_history.setdefault(f.stock_code, []).append(f)

    for stock in stocks:
        price_hist = prices_history.get(stock.code, [])
        price = next((p for p in price_hist if p.trading_date == trading_date), None)
        flow = db.scalar(
            select(SpotInvestorFlow).where(
                SpotInvestorFlow.trading_date == trading_date,
                SpotInvestorFlow.stock_code == stock.code,
            )
        )
        short_hist = short_history.get(stock.code, [])
        short = next((s for s in short_hist if s.trading_date == trading_date), None)

        if not all([price, flow, short]):
            continue

        # 20일 평균 거래량으로 거래량 급증 계산
        vols_20d = [p.volume for p in price_hist[:20] if p.volume > 0]
        avg_vol_20d = sum(vols_20d) / len(vols_20d) if vols_20d else price.volume or 1.0
        volume_surge = price.volume / max(avg_vol_20d, 1)

        # 거래대금 대비 수급 강도 (won 단위)
        # trading_value가 0이면 volume*price 추정치 사용
        tv = price.trading_value if price.trading_value > 0 else (price.volume * price.close_price)
        tv = max(tv, 1)
        foreign_strength = flow.foreign_net_buy / tv * 100  # 거래대금 대비 % (외국인)
        institution_strength = flow.institution_net_buy / tv * 100  # 거래대금 대비 %  (기관)
        co_buy = 2.0 if flow.foreign_net_buy > 0 and flow.institution_net_buy > 0 else 0.0

        # 공매도 비율 (pykrx: 0~100%)
        short_ratio_pct = short.short_ratio
        short_ratio_score = (
            2.0 if short_ratio_pct <= 1.0
            else 1.0 if short_ratio_pct <= 4.0
            else 0.0 if short_ratio_pct <= 10.0
            else -1.0 if short_ratio_pct <= 20.0
            else -2.0
        )

        # 공매도 추세: 최근 비율이 감소 중인지
        short_ratios = [s.short_ratio for s in short_hist]
        short_trend_score = _calc_short_trend_score(short_ratios)

        # 이동평균 위치 (20일/60일)
        close_prices = [p.close_price for p in price_hist]
        ma_score = _calc_ma_score(close_prices)

        # 5일 모멘텀
        momentum_score = _calc_momentum_5d(close_prices)

        # RSI(14)
        rsi_val = _calc_rsi(close_prices, period=14)
        rsi_score = _rsi_score(rsi_val)

        # 연속 동반매수 일수
        flow_hist = flow_history.get(stock.code, [])
        consecutive_buy_score = _calc_consecutive_buy(flow_hist)

        details = [
            ("foreign_strength", foreign_strength, _threshold_score(foreign_strength, 10.0, 3.0), "외국인 순매수 강도 (거래대금 대비%)"),
            ("institution_strength", institution_strength, _threshold_score(institution_strength, 8.0, 2.5), "기관 순매수 강도 (거래대금 대비%)"),
            ("co_buy", co_buy, co_buy, "외국인/기관 동반 매수"),
            ("volume_surge", volume_surge, 2.0 if volume_surge >= 3.0 else 1.0 if volume_surge >= 1.8 else 0.0 if volume_surge >= 0.8 else -1.0, "거래량 급증 (20일 평균 대비)"),
            ("short_ratio_change", short_ratio_pct, short_ratio_score, "공매도 비율 수준"),
            ("short_trend", None, short_trend_score, "공매도 비율 감소 추세"),
            ("ma_position", close_prices[0] if close_prices else None, ma_score, "20일/60일 이동평균 위치"),
            ("momentum_5d", close_prices[0] if close_prices else None, momentum_score, "5일 가격 모멘텀"),
            ("rsi_14", rsi_val, rsi_score, "RSI(14) — 과매도/과매수"),
            ("consecutive_buy", None, consecutive_buy_score, "기관+외국인 연속 동반매수"),
            ("program_buy", None, 0.0, "종목별 프로그램 순매수 TODO"),
        ]

        enabled = {key: key != "program_buy" for key, *_ in details}
        normalized_weights = _normalize_weights(config.stock_signal_weights, enabled)
        weighted_score = 0.0

        for key, raw_value, normalized_score, interpretation in details:
            is_enabled = enabled[key]
            if is_enabled:
                weighted_score += normalized_score * normalized_weights.get(key, 0.0)
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
