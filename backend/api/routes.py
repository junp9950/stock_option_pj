from __future__ import annotations

from datetime import date
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.api.schemas import HealthResponse, JobResponse, MarketSignalResponse, RecommendationItem, RecommendationResponse
from backend.backtest.backtester import run_backtest
from backend.db.database import get_db
from backend.db.models import BacktestResult, MarketSignal, Recommendation, Setting, StockSignalDetail
from backend.services.daily_pipeline import run_daily_pipeline
from backend.utils.dates import latest_trading_day


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
    return RecommendationResponse(
        trading_date=target_date.isoformat(),
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

