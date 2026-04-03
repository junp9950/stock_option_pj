from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.api.schemas import HealthResponse, JobResponse, MarketSignalResponse, RecommendationItem, RecommendationResponse
from backend.backtest.backtester import run_backtest
from backend.db.database import get_db
from backend.db.models import BacktestResult, MarketSignal, Recommendation, Setting, SpotDailyPrice, SpotInvestorFlow, Stock, StockSignal, StockSignalDetail
from backend.services.daily_pipeline import run_daily_pipeline
from backend.utils.dates import latest_trading_day


def _count_consecutive(flows: list, check) -> int:
    """flows는 최신 순으로 정렬된 SpotInvestorFlow 리스트."""
    count = 0
    for f in flows:
        if check(f):
            count += 1
        else:
            break
    return count


def _build_tags(inst: float, foreign: float, indiv: float, co_days: int, inst_days: int, foreign_days: int) -> list[str]:
    tags: list[str] = []
    if inst > 0 and foreign > 0:
        tags.append("기관+외국인 동시매수")
    if co_days >= 2:
        tags.append(f"동시매수 {co_days}일 연속")
    if inst_days >= 3:
        tags.append(f"기관 {inst_days}일 연속")
    if foreign_days >= 3:
        tags.append(f"외국인 {foreign_days}일 연속")
    if abs(inst) >= 5_000_000_000 or abs(foreign) >= 10_000_000_000:
        tags.append("대규모 매집")
    if indiv < 0:
        tags.append("개인 매도 중")
    return tags


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/market-signal", response_model=MarketSignalResponse)
def get_market_signal(trading_date: date | None = None, db: Session = Depends(get_db)) -> MarketSignalResponse:
    target_date = trading_date or latest_trading_day()
    signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
    if signal is None:
        raise HTTPException(status_code=404, detail="시장 시그널 데이터가 없습니다.")
    return MarketSignalResponse(trading_date=target_date.isoformat(), score=signal.score, signal=signal.signal)


@router.get("/market-signal/history")
def get_market_signal_history(db: Session = Depends(get_db)) -> list[MarketSignalResponse]:
    signals = list(db.scalars(select(MarketSignal).order_by(desc(MarketSignal.trading_date)).limit(5)))
    return [
        MarketSignalResponse(trading_date=item.trading_date.isoformat(), score=item.score, signal=item.signal)
        for item in signals
    ]


@router.get("/recommendations", response_model=RecommendationResponse)
def get_recommendations(trading_date: date | None = None, db: Session = Depends(get_db)) -> RecommendationResponse:
    target_date = trading_date or latest_trading_day()
    items = list(
        db.scalars(
            select(Recommendation).where(Recommendation.trading_date == target_date).order_by(Recommendation.rank)
        )
    )
    if not items:
        return RecommendationResponse(trading_date=target_date.isoformat(), items=[])

    codes = [item.stock_code for item in items]

    # 시장 구분 (KOSPI/KOSDAQ)
    stocks_map = {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))}

    # 당일 투자자별 수급
    flows_today = {
        f.stock_code: f
        for f in db.scalars(
            select(SpotInvestorFlow).where(
                SpotInvestorFlow.trading_date == target_date,
                SpotInvestorFlow.stock_code.in_(codes),
            )
        )
    }

    # 연속일 계산용: 최근 10영업일치 수급 (최신 순)
    recent_raw = list(
        db.scalars(
            select(SpotInvestorFlow)
            .where(
                SpotInvestorFlow.stock_code.in_(codes),
                SpotInvestorFlow.trading_date <= target_date,
                SpotInvestorFlow.trading_date >= target_date - timedelta(days=14),
            )
            .order_by(SpotInvestorFlow.stock_code, desc(SpotInvestorFlow.trading_date))
        )
    )
    recent_flows: dict[str, list] = defaultdict(list)
    for f in recent_raw:
        if len(recent_flows[f.stock_code]) < 10:
            recent_flows[f.stock_code].append(f)

    result_items = []
    for item in items:
        flow = flows_today.get(item.stock_code)
        stock = stocks_map.get(item.stock_code)
        inst = flow.institution_net_buy if flow else 0.0
        foreign = flow.foreign_net_buy if flow else 0.0
        indiv = flow.individual_net_buy if flow else 0.0

        hist = recent_flows[item.stock_code]
        co_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0 and f.foreign_net_buy > 0)
        inst_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0)
        foreign_days = _count_consecutive(hist, lambda f: f.foreign_net_buy > 0)

        result_items.append(
            RecommendationItem(
                rank=item.rank,
                code=item.stock_code,
                name=item.stock_name,
                total_score=item.total_score,
                market_score=item.market_score,
                stock_score=item.stock_score,
                close_price=item.close_price,
                change_pct=item.change_pct,
                market=stock.market if stock else "KOSPI",
                institution_net_buy=inst,
                foreign_net_buy=foreign,
                individual_net_buy=indiv,
                consecutive_days=co_days,
                tags=_build_tags(inst, foreign, indiv, co_days, inst_days, foreign_days),
            )
        )

    return RecommendationResponse(trading_date=target_date.isoformat(), items=result_items)


@router.get("/screener")
def get_screener(trading_date: date | None = None, db: Session = Depends(get_db)) -> list[RecommendationItem]:
    """전체 종목 점수 스크리너 — 점수 높은 순 정렬."""
    from backend.config import get_config
    target_date = trading_date or latest_trading_day()
    config = get_config()

    market_signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
    market_score = market_signal.score if market_signal else 0.0

    stock_signals = list(db.scalars(select(StockSignal).where(StockSignal.trading_date == target_date)))
    if not stock_signals:
        return []

    codes = [s.stock_code for s in stock_signals]

    stocks_map = {s.code: s for s in db.scalars(select(Stock).where(Stock.code.in_(codes)))}
    prices_map = {
        p.stock_code: p
        for p in db.scalars(
            select(SpotDailyPrice).where(
                SpotDailyPrice.trading_date == target_date,
                SpotDailyPrice.stock_code.in_(codes),
            )
        )
    }
    flows_map = {
        f.stock_code: f
        for f in db.scalars(
            select(SpotInvestorFlow).where(
                SpotInvestorFlow.trading_date == target_date,
                SpotInvestorFlow.stock_code.in_(codes),
            )
        )
    }

    recent_raw = list(
        db.scalars(
            select(SpotInvestorFlow)
            .where(
                SpotInvestorFlow.stock_code.in_(codes),
                SpotInvestorFlow.trading_date <= target_date,
                SpotInvestorFlow.trading_date >= target_date - timedelta(days=14),
            )
            .order_by(SpotInvestorFlow.stock_code, desc(SpotInvestorFlow.trading_date))
        )
    )
    recent_flows: dict[str, list] = defaultdict(list)
    for f in recent_raw:
        if len(recent_flows[f.stock_code]) < 10:
            recent_flows[f.stock_code].append(f)

    ranked: list[RecommendationItem] = []
    for ss in stock_signals:
        stock = stocks_map.get(ss.stock_code)
        price = prices_map.get(ss.stock_code)
        if stock is None or price is None:
            continue
        if stock.market_cap < config.min_market_cap or price.trading_value < config.min_trading_value:
            continue

        flow = flows_map.get(ss.stock_code)
        inst = flow.institution_net_buy if flow else 0.0
        foreign = flow.foreign_net_buy if flow else 0.0
        indiv = flow.individual_net_buy if flow else 0.0

        hist = recent_flows[ss.stock_code]
        co_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0 and f.foreign_net_buy > 0)
        inst_days = _count_consecutive(hist, lambda f: f.institution_net_buy > 0)
        foreign_days = _count_consecutive(hist, lambda f: f.foreign_net_buy > 0)

        total_score = round(market_score * config.score_market_weight + ss.score * config.score_stock_weight, 2)
        ranked.append(
            RecommendationItem(
                rank=0,
                code=ss.stock_code,
                name=stock.name,
                total_score=total_score,
                market_score=market_score,
                stock_score=ss.score,
                close_price=price.close_price,
                change_pct=price.change_pct,
                market=stock.market,
                institution_net_buy=inst,
                foreign_net_buy=foreign,
                individual_net_buy=indiv,
                consecutive_days=co_days,
                tags=_build_tags(inst, foreign, indiv, co_days, inst_days, foreign_days),
            )
        )

    ranked.sort(key=lambda x: x.total_score, reverse=True)
    for i, item in enumerate(ranked, start=1):
        item.rank = i
    return ranked


@router.get("/recommendations/history")
def get_recommendation_history(db: Session = Depends(get_db)) -> list[RecommendationResponse]:
    dates = list({item.trading_date for item in db.scalars(select(Recommendation).order_by(desc(Recommendation.trading_date))).all()})
    responses: list[RecommendationResponse] = []
    for item_date in dates[:5]:
        items = list(db.scalars(select(Recommendation).where(Recommendation.trading_date == item_date).order_by(Recommendation.rank)))
        responses.append(
            RecommendationResponse(
                trading_date=item_date.isoformat(),
                items=[
                    RecommendationItem(
                        rank=item.rank,
                        code=item.stock_code,
                        name=item.stock_name,
                        total_score=item.total_score,
                        market_score=item.market_score,
                        stock_score=item.stock_score,
                        close_price=item.close_price,
                        change_pct=item.change_pct,
                    )
                    for item in items
                ],
            )
        )
    return responses


@router.get("/stock/{code}/signals")
def get_stock_signal_details(code: str, trading_date: date | None = None, db: Session = Depends(get_db)):
    target_date = trading_date or latest_trading_day()
    details = list(
        db.scalars(
            select(StockSignalDetail).where(
                StockSignalDetail.trading_date == target_date,
                StockSignalDetail.stock_code == code,
            )
        )
    )
    if not details:
        raise HTTPException(status_code=404, detail="종목 시그널 상세 데이터가 없습니다.")
    return [
        {
            "key": item.key,
            "raw_value": item.raw_value,
            "normalized_score": item.normalized_score,
            "interpretation": item.interpretation,
            "is_enabled": item.is_enabled,
            "note": item.note,
        }
        for item in details
    ]


@router.get("/data-sources")
def get_data_sources():
    """각 데이터 항목의 현재 소스 상태를 반환한다."""
    return {
        "spot_price": {"source": "FinanceDataReader", "status": "real"},
        "stock_name": {"source": "FinanceDataReader/StockListing", "status": "real"},
        "market_cap": {"source": "FinanceDataReader/StockListing", "status": "real"},
        "trading_value": {"source": "FinanceDataReader/StockListing", "status": "real"},
        "kospi200_index": {"source": "FinanceDataReader/KS200", "status": "real"},
        "foreign_institution_net_buy": {"source": "pykrx", "status": "real_with_fallback", "note": "pykrx 실패 시 0으로 적재"},
        "short_selling": {"source": "pykrx", "status": "real_with_fallback", "note": "pykrx 실패 시 demo 값 적재"},
        "futures_investor_flow": {"source": "fallback", "status": "fallback", "note": "0으로 적재 중"},
        "options_investor_flow": {"source": "fallback", "status": "fallback", "note": "0으로 적재 중"},
        "open_interest": {"source": "fallback", "status": "fallback", "note": "0으로 적재 중"},
        "program_trading": {"source": "fallback", "status": "fallback", "note": "demo 값 적재 중"},
        "kospi200_futures_price": {"source": "fallback", "status": "fallback", "note": "KOSPI200 지수로 대체 중"},
    }


@router.get("/derivatives/overview")
def get_derivatives_overview(trading_date: date | None = None, db: Session = Depends(get_db)):
    target_date = trading_date or latest_trading_day()
    signal = db.scalar(select(MarketSignal).where(MarketSignal.trading_date == target_date))
    return {"trading_date": target_date.isoformat(), "market_signal": signal.signal if signal else "중립", "score": signal.score if signal else 0.0}


@router.get("/backtest/results")
def get_backtest_results(db: Session = Depends(get_db)):
    results = list(db.scalars(select(BacktestResult).order_by(desc(BacktestResult.created_at)).limit(10)))
    return [{"metric": item.metric, "value": item.value, "note": item.note} for item in results]


@router.put("/settings/weights")
def update_settings(payload: dict[str, object], db: Session = Depends(get_db)):
    for key, value in payload.items():
        db.merge(Setting(key=key, value=json.dumps(value, ensure_ascii=True)))
    db.commit()
    return {"status": "ok"}


@router.post("/jobs/run-daily", response_model=JobResponse)
def run_daily_job(trading_date: date | None = None, db: Session = Depends(get_db)) -> JobResponse:
    result = run_daily_pipeline(db, trading_date)
    return JobResponse(**result)


@router.post("/jobs/backfill")
def run_backfill(start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)):
    result = run_daily_pipeline(db, end_date or start_date or latest_trading_day())
    return {"status": "ok", "result": result}


@router.post("/backtest/run")
def trigger_backtest(db: Session = Depends(get_db)):
    return run_backtest(db)

