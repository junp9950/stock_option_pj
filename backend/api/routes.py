from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.api.schemas import HealthResponse, JobResponse, MarketSignalResponse, RecommendationItem, RecommendationResponse
from backend.backtest.backtester import run_backtest
from backend.db.database import get_db
from backend.db.models import BacktestResult, BacktestRun, JobLog, MarketSignal, MarketSignalDetail, Recommendation, Setting, ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow, Stock, StockSignal, StockSignalDetail
from backend.db.seed import refresh_universe
from backend.services.daily_pipeline import run_backfill_pipeline, run_daily_pipeline
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
def get_market_signal_history(limit: int = 10, db: Session = Depends(get_db)) -> list[MarketSignalResponse]:
    signals = list(db.scalars(select(MarketSignal).order_by(desc(MarketSignal.trading_date)).limit(limit)))
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
def get_screener(
    trading_date: date | None = None,
    show_all: bool = False,
    db: Session = Depends(get_db),
) -> list[RecommendationItem]:
    """전체 종목 점수 스크리너 — 점수 높은 순 정렬.
    show_all=true이면 시총/거래대금 필터 무시하고 전종목 반환.
    """
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
    shorts_map = {
        s.stock_code: s
        for s in db.scalars(
            select(ShortSellingDaily).where(
                ShortSellingDaily.trading_date == target_date,
                ShortSellingDaily.stock_code.in_(codes),
            )
        )
    }
    # 시그널 상세에서 ma_position, rsi_14, volume_surge 추출
    signal_details_raw = list(db.scalars(
        select(StockSignalDetail).where(
            StockSignalDetail.trading_date == target_date,
            StockSignalDetail.stock_code.in_(codes),
            StockSignalDetail.key.in_(["ma_position", "rsi_14", "volume_surge"]),
        )
    ))
    ma_scores: dict[str, float] = {}
    rsi_values: dict[str, float | None] = {}
    volume_surges: dict[str, float] = {}
    for d in signal_details_raw:
        if d.key == "ma_position":
            ma_scores[d.stock_code] = d.normalized_score
        elif d.key == "rsi_14":
            rsi_values[d.stock_code] = d.raw_value
        elif d.key == "volume_surge":
            volume_surges[d.stock_code] = d.raw_value if d.raw_value is not None else 1.0

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
        if not show_all and (stock.market_cap < config.min_market_cap or price.trading_value < config.min_trading_value):
            continue

        flow = flows_map.get(ss.stock_code)
        short = shorts_map.get(ss.stock_code)
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
                short_ratio=short.short_ratio if short else 0.0,
                ma_score=ma_scores.get(ss.stock_code, 0.0),
                rsi_14=rsi_values.get(ss.stock_code),
                volume_surge=volume_surges.get(ss.stock_code, 1.0),
                market_cap=stock.market_cap or 0.0,
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
def get_data_sources(db: Session = Depends(get_db)):
    """각 데이터 항목의 현재 소스 상태 및 최근 수집 현황을 반환한다."""
    from backend.db.models import (
        DerivativesFuturesDaily, FuturesDailyPrice, IndexDaily,
        OpenInterestDaily, ProgramTradingDaily, ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow
    )
    target_date = latest_trading_day()

    # 최근 수집 결과를 DB에서 실제로 확인
    spot_count = db.scalar(select(func.count()).select_from(SpotDailyPrice).where(SpotDailyPrice.trading_date == target_date)) or 0
    flow_count = db.scalar(select(func.count()).select_from(SpotInvestorFlow).where(
        SpotInvestorFlow.trading_date == target_date, SpotInvestorFlow.foreign_net_buy != 0
    )) or 0
    short_row = db.scalar(select(ShortSellingDaily).where(ShortSellingDaily.trading_date == target_date))
    idx_row = db.scalar(select(IndexDaily).where(IndexDaily.trading_date == target_date))
    futures_row = db.scalar(select(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == target_date))
    program_row = db.scalar(select(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == target_date))
    oi_row = db.scalar(select(OpenInterestDaily).where(OpenInterestDaily.trading_date == target_date))
    fp_row = db.scalar(select(FuturesDailyPrice).where(FuturesDailyPrice.trading_date == target_date))

    def _status(condition: bool, real_label: str = "real") -> str:
        return real_label if condition else "fallback"

    return {
        "spot_price": {"source": "FinanceDataReader", "status": _status(spot_count > 0), "note": f"오늘 {spot_count}종목 수집"},
        "investor_flow": {"source": "pykrx", "status": _status(flow_count > 0, "real_with_fallback"), "note": f"외국인/기관 비제로 {flow_count}종목 (0이면 pykrx 실패)"},
        "short_selling": {"source": "pykrx", "status": "real_with_fallback", "note": f"공매도 데이터 {'수집됨' if short_row else '없음'}"},
        "kospi200_index": {"source": "FinanceDataReader/KS200", "status": _status(idx_row is not None), "note": f"종가: {idx_row.close_price:.2f}" if idx_row else "없음"},
        "futures_investor_flow": {"source": "KRX JSON API", "status": _status(futures_row is not None and futures_row.foreign_net_contracts != 0, "real_with_fallback"), "note": f"외국인 선물: {futures_row.foreign_net_contracts:.0f}계약" if futures_row else "없음"},
        "program_trading": {"source": "KRX JSON API", "status": _status(program_row is not None and (program_row.non_arbitrage_net_buy != 0 or program_row.arbitrage_net_buy != 0), "real_with_fallback"), "note": f"비차익 {program_row.non_arbitrage_net_buy/1e8:.0f}억" if program_row else "없음"},
        "open_interest": {"source": "pykrx", "status": _status(oi_row is not None and (oi_row.call_oi > 0 or oi_row.put_oi > 0), "real_with_fallback"), "note": f"콜OI={oi_row.call_oi:.0f} 풋OI={oi_row.put_oi:.0f}" if oi_row else "없음"},
        "kospi200_futures_price": {"source": "pykrx → 지수 fallback", "status": _status(fp_row is not None, "real_with_fallback"), "note": f"종가: {fp_row.close_price:.2f}" if fp_row else "없음"},
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


@router.post("/universe/refresh")
def refresh_universe_endpoint(db: Session = Depends(get_db)):
    """FDR로 유니버스를 최신 KOSPI 시총 상위 30종목으로 갱신."""
    added = refresh_universe(db)
    total = db.query(Stock).count()
    return {"status": "ok", "added": added, "total": total}


@router.post("/jobs/run-daily", response_model=JobResponse)
def run_daily_job(trading_date: date | None = None, db: Session = Depends(get_db)) -> JobResponse:
    result = run_daily_pipeline(db, trading_date)
    return JobResponse(**result)


@router.post("/jobs/backfill")
def run_backfill(start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)):
    """start_date ~ end_date 범위 전체 파이프라인 순차 실행.
    둘 다 없으면 오늘 하루만 실행. end_date만 있으면 그날 하루만 실행.
    """
    s = start_date or latest_trading_day()
    e = end_date or s
    if s > e:
        s, e = e, s
    results = run_backfill_pipeline(db, s, e)
    return {"status": "ok", "days_processed": len(results), "results": results}


@router.post("/backtest/run")
def trigger_backtest(lookback_days: int = 60, db: Session = Depends(get_db)):
    """T+1 백테스트 실행 (lookback_days: 최근 몇일치 추천 기록 사용, 기본 60일)."""
    return run_backtest(db, lookback_days=lookback_days)


@router.get("/backtest/summary")
def get_backtest_summary(db: Session = Depends(get_db)):
    """가장 최근 백테스트 실행 결과 요약."""
    from backend.db.models import BacktestRun
    latest_run = db.scalar(select(BacktestRun).order_by(desc(BacktestRun.created_at)))
    if latest_run is None:
        return {"run_id": None, "period": None, "metrics": {}}
    results = list(db.scalars(select(BacktestResult).where(BacktestResult.run_id == latest_run.id)))
    metrics = {r.metric: r.value for r in results}
    return {
        "run_id": latest_run.id,
        "period": latest_run.period_label,
        "note": latest_run.note,
        "metrics": metrics,
    }


@router.get("/jobs/logs")
def get_job_logs(limit: int = 50, db: Session = Depends(get_db)):
    """최근 파이프라인 실행 이력."""
    logs = list(db.scalars(select(JobLog).order_by(desc(JobLog.created_at)).limit(limit)))
    return [
        {
            "id": l.id,
            "trading_date": l.trading_date.isoformat() if l.trading_date else None,
            "stage": l.stage,
            "status": l.status,
            "message": l.message,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


@router.get("/market-signal/details")
def get_market_signal_details(trading_date: date | None = None, db: Session = Depends(get_db)):
    """시장 시그널 지표별 상세 점수."""
    target_date = trading_date or latest_trading_day()
    details = list(db.scalars(
        select(MarketSignalDetail).where(MarketSignalDetail.trading_date == target_date)
    ))
    return [
        {
            "key": d.key,
            "raw_value": d.raw_value,
            "normalized_score": d.normalized_score,
            "interpretation": d.interpretation,
            "is_enabled": d.is_enabled,
            "source": d.source,
            "note": d.note,
        }
        for d in details
    ]


@router.get("/data-quality")
def get_data_quality(db: Session = Depends(get_db)):
    """오늘 데이터 수집 품질 요약 (실데이터 비율)."""
    from backend.db.models import (
        DerivativesFuturesDaily, IndexDaily, OpenInterestDaily,
        ProgramTradingDaily, ShortSellingDaily, SpotDailyPrice, SpotInvestorFlow, Stock
    )
    target_date = latest_trading_day()
    total_stocks = db.scalar(select(func.count()).select_from(Stock).where(Stock.is_active.is_(True))) or 1

    spot_count = db.scalar(select(func.count()).select_from(SpotDailyPrice).where(SpotDailyPrice.trading_date == target_date)) or 0
    flow_nonzero = db.scalar(select(func.count()).select_from(SpotInvestorFlow).where(
        SpotInvestorFlow.trading_date == target_date, SpotInvestorFlow.foreign_net_buy != 0
    )) or 0
    short_count = db.scalar(select(func.count()).select_from(ShortSellingDaily).where(ShortSellingDaily.trading_date == target_date)) or 0

    futures_row = db.scalar(select(DerivativesFuturesDaily).where(DerivativesFuturesDaily.trading_date == target_date))
    program_row = db.scalar(select(ProgramTradingDaily).where(ProgramTradingDaily.trading_date == target_date))
    oi_row = db.scalar(select(OpenInterestDaily).where(OpenInterestDaily.trading_date == target_date))
    idx_row = db.scalar(select(IndexDaily).where(IndexDaily.trading_date == target_date))

    checks = {
        "spot_coverage": spot_count / total_stocks,
        "flow_coverage": flow_nonzero / total_stocks,
        "short_coverage": short_count / total_stocks,
        "futures_real": 1.0 if futures_row and futures_row.foreign_net_contracts != 0 else 0.0,
        "program_real": 1.0 if program_row and (program_row.non_arbitrage_net_buy != 0 or program_row.arbitrage_net_buy != 0) else 0.0,
        "oi_real": 1.0 if oi_row and (oi_row.call_oi > 0 or oi_row.put_oi > 0) else 0.0,
        "index_real": 1.0 if idx_row else 0.0,
    }
    overall = sum(checks.values()) / len(checks)
    return {
        "trading_date": target_date.isoformat(),
        "overall_score": round(overall * 100, 1),
        "checks": checks,
    }


@router.get("/universe")
def get_universe(db: Session = Depends(get_db)):
    """현재 유니버스 종목 목록."""
    stocks = list(db.scalars(select(Stock).where(Stock.is_active.is_(True)).order_by(desc(Stock.market_cap))))
    return [
        {"code": s.code, "name": s.name, "market": s.market, "market_cap": s.market_cap}
        for s in stocks
    ]

