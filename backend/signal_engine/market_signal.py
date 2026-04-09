from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session

from backend.db.models import (
    MarketSignal,
    MarketSignalDetail,
    SpotDailyPrice,
    SpotInvestorFlow,
    StockSignal,
)


def _bucket(value: float, thresholds: list[tuple[float, float]]) -> float:
    for upper, score in thresholds:
        if value <= upper:
            return score
    return thresholds[-1][1]


def calculate_market_signal(db: Session, trading_date: date) -> MarketSignal:
    """
    DB 실데이터 기반 시장 시그널 계산.

    지표:
      1. 외인 순매수 합산 (전종목 합계, 100억원 단위)
      2. 기관 순매수 합산 (전종목 합계, 100억원 단위)
      3. 외인+기관 동시 매수 종목 비율 (전종목 대비 %)
      4. 외인 5일 누적 흐름 추세 (최근 5 영업일 합산)
      5. 평균 종목 시그널 점수 (StockSignal 평균)
      6. 종목 점수 상승 비율 (전일 대비 점수 오른 종목 %)
    """
    db.execute(delete(MarketSignalDetail).where(MarketSignalDetail.trading_date == trading_date))
    db.execute(delete(MarketSignal).where(MarketSignal.trading_date == trading_date))
    db.commit()

    # ── 당일 수급 합산
    flows_today = list(db.scalars(
        select(SpotInvestorFlow).where(SpotInvestorFlow.trading_date == trading_date)
    ))
    # 전부 0이면 데이터 미수집
    real_flows = [f for f in flows_today if f.foreign_net_buy != 0 or f.institution_net_buy != 0]

    if not real_flows:
        signal = MarketSignal(trading_date=trading_date, score=0.0, signal="중립")
        db.add(signal)
        db.commit()
        return signal

    total_foreign = sum(f.foreign_net_buy for f in real_flows) / 1e8       # 억원
    total_institution = sum(f.institution_net_buy for f in real_flows) / 1e8
    n = len(real_flows)
    both_buy_ratio = sum(1 for f in real_flows if f.foreign_net_buy > 0 and f.institution_net_buy > 0) / n * 100
    foreign_buy_ratio = sum(1 for f in real_flows if f.foreign_net_buy > 0) / n * 100
    institution_buy_ratio = sum(1 for f in real_flows if f.institution_net_buy > 0) / n * 100

    # ── 외인 5일 누적 추세 (최근 5 영업일 합산)
    recent_5d_start = trading_date - timedelta(days=10)
    recent_flows_5d = list(db.scalars(
        select(SpotInvestorFlow).where(
            SpotInvestorFlow.trading_date.between(recent_5d_start, trading_date)
        )
    ))
    # 날짜별 외인 합계
    from collections import defaultdict
    daily_foreign: dict[date, float] = defaultdict(float)
    for f in recent_flows_5d:
        daily_foreign[f.trading_date] += f.foreign_net_buy
    sorted_days = sorted(daily_foreign.keys())[-5:]
    foreign_5d_sum = sum(daily_foreign[d] for d in sorted_days) / 1e8  # 억원

    # ── 평균 종목 점수
    avg_score_row = db.execute(
        select(func.avg(StockSignal.score)).where(StockSignal.trading_date == trading_date)
    ).scalar()
    avg_score = float(avg_score_row or 0.0)

    # ── 전일 대비 점수 상승 종목 비율
    prev_date = db.scalar(
        select(func.max(StockSignal.trading_date)).where(StockSignal.trading_date < trading_date)
    )
    score_up_ratio = 0.0
    if prev_date:
        today_scores = {s.stock_code: s.score for s in db.scalars(
            select(StockSignal).where(StockSignal.trading_date == trading_date)
        )}
        prev_scores = {s.stock_code: s.score for s in db.scalars(
            select(StockSignal).where(StockSignal.trading_date == prev_date)
        )}
        common = set(today_scores) & set(prev_scores)
        if common:
            score_up_ratio = sum(1 for c in common if today_scores[c] > prev_scores[c]) / len(common) * 100

    # ── 지표별 점수화
    details = [
        ("foreign_net_total",
         round(total_foreign, 1),
         _bucket(total_foreign, [(-3000, -2), (-500, -1), (500, 0), (3000, 1), (float("inf"), 2)]),
         f"외인 순매수 합산 ({total_foreign:+.0f}억)"),

        ("institution_net_total",
         round(total_institution, 1),
         _bucket(total_institution, [(-2000, -2), (-300, -1), (300, 0), (2000, 1), (float("inf"), 2)]),
         f"기관 순매수 합산 ({total_institution:+.0f}억)"),

        ("both_buy_ratio",
         round(both_buy_ratio, 1),
         _bucket(both_buy_ratio, [(10, -1), (20, 0), (35, 1), (float("inf"), 2)]),
         f"외인+기관 동시매수 종목 비율 ({both_buy_ratio:.1f}%)"),

        ("foreign_5d_trend",
         round(foreign_5d_sum, 1),
         _bucket(foreign_5d_sum, [(-5000, -2), (-1000, -1), (1000, 0), (5000, 1), (float("inf"), 2)]),
         f"외인 5일 누적 추세 ({foreign_5d_sum:+.0f}억)"),

        ("avg_stock_score",
         round(avg_score, 3),
         _bucket(avg_score, [(-0.3, -2), (-0.1, -1), (0.1, 0), (0.3, 1), (float("inf"), 2)]),
         f"전종목 평균 시그널 점수 ({avg_score:+.3f})"),

        ("score_up_ratio",
         round(score_up_ratio, 1),
         _bucket(score_up_ratio, [(35, -1), (45, 0), (55, 1), (float("inf"), 2)]),
         f"전일 대비 점수 상승 종목 비율 ({score_up_ratio:.1f}%)"),
    ]

    weights = {
        "foreign_net_total": 0.25,
        "institution_net_total": 0.20,
        "both_buy_ratio": 0.15,
        "foreign_5d_trend": 0.20,
        "avg_stock_score": 0.10,
        "score_up_ratio": 0.10,
    }
    total_w = sum(weights.values())
    weighted_score = sum(score * weights[key] / total_w for key, _, score, _ in details)
    final_score = round(weighted_score * 5, 2)

    if final_score >= 2.5:
        signal_str = "강세매수"
    elif final_score >= 0.5:
        signal_str = "상방"
    elif final_score <= -2.5:
        signal_str = "강세매도"
    elif final_score <= -0.5:
        signal_str = "하방"
    else:
        signal_str = "중립"

    for key, raw_value, normalized_score, interpretation in details:
        db.add(MarketSignalDetail(
            trading_date=trading_date,
            key=key,
            raw_value=raw_value,
            normalized_score=normalized_score,
            interpretation=interpretation,
            is_enabled=True,
            source="computed",
            note=None,
        ))

    market_signal = MarketSignal(trading_date=trading_date, score=final_score, signal=signal_str)
    db.add(market_signal)
    db.commit()
    return market_signal
