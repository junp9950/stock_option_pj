from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Stock(Base, TimestampMixin):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(20))
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    shares_outstanding: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TradingCalendar(Base, TimestampMixin):
    __tablename__ = "trading_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, default=True)


class SpotDailyPrice(Base, TimestampMixin):
    __tablename__ = "spot_daily_prices"
    __table_args__ = (UniqueConstraint("trading_date", "stock_code", name="uq_spot_daily_prices"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    open_price: Mapped[float] = mapped_column(Float)
    high_price: Mapped[float] = mapped_column(Float)
    low_price: Mapped[float] = mapped_column(Float)
    close_price: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    trading_value: Mapped[float] = mapped_column(Float)
    change_pct: Mapped[float] = mapped_column(Float)


class SpotInvestorFlow(Base, TimestampMixin):
    __tablename__ = "spot_investor_flows"
    __table_args__ = (UniqueConstraint("trading_date", "stock_code", name="uq_spot_investor_flows"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    foreign_net_buy: Mapped[float] = mapped_column(Float, default=0.0)
    institution_net_buy: Mapped[float] = mapped_column(Float, default=0.0)
    individual_net_buy: Mapped[float] = mapped_column(Float, default=0.0)


class ShortSellingDaily(Base, TimestampMixin):
    __tablename__ = "short_selling_daily"
    __table_args__ = (UniqueConstraint("trading_date", "stock_code", name="uq_short_selling_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    short_volume: Mapped[float] = mapped_column(Float, default=0.0)
    short_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    short_balance: Mapped[float] = mapped_column(Float, default=0.0)


class BorrowDaily(Base, TimestampMixin):
    __tablename__ = "borrow_daily"
    __table_args__ = (UniqueConstraint("trading_date", "stock_code", name="uq_borrow_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    balance_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DerivativesFuturesDaily(Base, TimestampMixin):
    __tablename__ = "derivatives_futures_daily"
    __table_args__ = (UniqueConstraint("trading_date", name="uq_derivatives_futures_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    foreign_net_contracts: Mapped[float] = mapped_column(Float, default=0.0)
    institution_net_contracts: Mapped[float] = mapped_column(Float, default=0.0)
    individual_net_contracts: Mapped[float] = mapped_column(Float, default=0.0)
    foreign_net_amount: Mapped[float] = mapped_column(Float, default=0.0)


class DerivativesOptionsDaily(Base, TimestampMixin):
    __tablename__ = "derivatives_options_daily"
    __table_args__ = (UniqueConstraint("trading_date", name="uq_derivatives_options_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    call_foreign_net: Mapped[float] = mapped_column(Float, default=0.0)
    put_foreign_net: Mapped[float] = mapped_column(Float, default=0.0)
    call_institution_net: Mapped[float] = mapped_column(Float, default=0.0)
    put_institution_net: Mapped[float] = mapped_column(Float, default=0.0)


class OpenInterestDaily(Base, TimestampMixin):
    __tablename__ = "open_interest_daily"
    __table_args__ = (UniqueConstraint("trading_date", name="uq_open_interest_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    futures_oi: Mapped[float] = mapped_column(Float, default=0.0)
    call_oi: Mapped[float] = mapped_column(Float, default=0.0)
    put_oi: Mapped[float] = mapped_column(Float, default=0.0)


class ProgramTradingDaily(Base, TimestampMixin):
    __tablename__ = "program_trading_daily"
    __table_args__ = (UniqueConstraint("trading_date", name="uq_program_trading_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    arbitrage_net_buy: Mapped[float] = mapped_column(Float, default=0.0)
    non_arbitrage_net_buy: Mapped[float] = mapped_column(Float, default=0.0)


class IndexDaily(Base, TimestampMixin):
    __tablename__ = "index_daily"
    __table_args__ = (UniqueConstraint("trading_date", "index_code", name="uq_index_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    index_code: Mapped[str] = mapped_column(String(20))
    close_price: Mapped[float] = mapped_column(Float)


class FuturesDailyPrice(Base, TimestampMixin):
    __tablename__ = "futures_daily_price"
    __table_args__ = (UniqueConstraint("trading_date", "symbol", name="uq_futures_daily_price"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(20), default="KOSPI200")
    close_price: Mapped[float] = mapped_column(Float)


class MarketSignal(Base, TimestampMixin):
    __tablename__ = "market_signals"
    __table_args__ = (UniqueConstraint("trading_date", name="uq_market_signals"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    signal: Mapped[str] = mapped_column(String(20), default="중립")


class MarketSignalDetail(Base, TimestampMixin):
    __tablename__ = "market_signal_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    key: Mapped[str] = mapped_column(String(50))
    raw_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_score: Mapped[float] = mapped_column(Float, default=0.0)
    interpretation: Mapped[str] = mapped_column(String(255), default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(50), default="computed")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class StockSignal(Base, TimestampMixin):
    __tablename__ = "stock_signals"
    __table_args__ = (UniqueConstraint("trading_date", "stock_code", name="uq_stock_signals"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)


class StockSignalDetail(Base, TimestampMixin):
    __tablename__ = "stock_signal_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    key: Mapped[str] = mapped_column(String(50))
    raw_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_score: Mapped[float] = mapped_column(Float, default=0.0)
    interpretation: Mapped[str] = mapped_column(String(255), default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(50), default="computed")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Recommendation(Base, TimestampMixin):
    __tablename__ = "recommendations"
    __table_args__ = (UniqueConstraint("trading_date", "stock_code", name="uq_recommendations"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    stock_name: Mapped[str] = mapped_column(String(100))
    total_score: Mapped[float] = mapped_column(Float)
    market_score: Mapped[float] = mapped_column(Float)
    stock_score: Mapped[float] = mapped_column(Float)
    close_price: Mapped[float] = mapped_column(Float)
    change_pct: Mapped[float] = mapped_column(Float)
    market_signal: Mapped[str] = mapped_column(String(20))
    earnings_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnings_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    earnings_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Sector(Base, TimestampMixin):
    __tablename__ = "sectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    sector_name: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(30))  # 'custom' / 'naver_theme'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SectorStock(Base):
    __tablename__ = "sector_stocks"
    __table_args__ = (UniqueConstraint("sector_id", "stock_code", name="uq_sector_stocks"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_id: Mapped[int] = mapped_column(Integer, ForeignKey("sectors.id"), index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)


class SectorFlowDaily(Base, TimestampMixin):
    __tablename__ = "sector_flow_daily"
    __table_args__ = (UniqueConstraint("date", "sector_id", name="uq_sector_flow_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    sector_id: Mapped[int] = mapped_column(Integer, ForeignKey("sectors.id"), index=True)
    foreign_net_buy: Mapped[int] = mapped_column(BigInteger, default=0)
    inst_net_buy: Mapped[int] = mapped_column(BigInteger, default=0)
    combined_net_buy: Mapped[int] = mapped_column(BigInteger, default=0)
    stock_count: Mapped[int] = mapped_column(Integer, default=0)
    up_count: Mapped[int] = mapped_column(Integer, default=0)
    down_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    max_change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    total_volume: Mapped[int] = mapped_column(BigInteger, default=0)
    flow_score: Mapped[float] = mapped_column(Float, default=0.0)
    stealth_score: Mapped[float] = mapped_column(Float, default=0.0)
    buy_streak: Mapped[int] = mapped_column(Integer, default=0)
    top_contributor_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    top_contributor_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    top_contributor_amount: Mapped[int] = mapped_column(BigInteger, default=0)


class BacktestRun(Base, TimestampMixin):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    period_label: Mapped[str] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BacktestResult(Base, TimestampMixin):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    metric: Mapped[str] = mapped_column(String(100))
    value: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RadarPick(Base, TimestampMixin):
    """눌림목 레이더가 그날 장 마감 후 보여준 신호 종목 기록 (실전 성과 추적용)."""

    __tablename__ = "radar_picks"
    __table_args__ = (UniqueConstraint("pick_date", "stock_code", name="uq_radar_picks"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pick_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100))
    total_score: Mapped[int] = mapped_column(Integer)
    signal_score: Mapped[int] = mapped_column(Integer)
    quality_score: Mapped[float] = mapped_column(Float)
    market_state: Mapped[str | None] = mapped_column(String(10), nullable=True)
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)
    close_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    vwap: Mapped[float] = mapped_column(Float)
    days_since_event: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[str] = mapped_column(Text, default="")


class BullFlagLabel(Base, TimestampMixin):
    """불플래그 탐지 결과에 대한 사용자 판정 (탐지 조건 다듬기용)."""

    __tablename__ = "bull_flag_labels"
    __table_args__ = (UniqueConstraint("detect_date", "stock_code", name="uq_bull_flag_labels"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detect_date: Mapped[date] = mapped_column(Date, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    is_flag: Mapped[bool] = mapped_column(Boolean)
    features: Mapped[str] = mapped_column(Text, default="")


class DiscussionPost(Base, TimestampMixin):
    """종목토론 게시판: 종목 태그(선택) + 글 + 스크린샷(선택, base64 data URI로 저장)."""

    __tablename__ = "discussion_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    stock_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    author: Mapped[str] = mapped_column(String(40), default="")
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)   # 2026-10-03 이전 글은 없음 (본문 첫 줄로 대신)
    content: Mapped[str] = mapped_column(Text, default="")
    image_data: Mapped[str | None] = mapped_column(Text, nullable=True)


class DiscussionComment(Base, TimestampMixin):
    """종목토론 게시글 댓글."""

    __tablename__ = "discussion_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("discussion_posts.id"), index=True)
    author: Mapped[str] = mapped_column(String(40), default="")
    content: Mapped[str] = mapped_column(Text)
    image_data: Mapped[str | None] = mapped_column(Text, nullable=True)   # 사진 한 장 또는 JSON 배열


class JongbePick(Base, TimestampMixin):
    """종베 후보 실전 기록: 장 마감 후 후보를 저장하고 다음 거래일 결과를 붙여 본다."""

    __tablename__ = "jongbe_picks"
    __table_args__ = (UniqueConstraint("trading_date", "code", name="uq_jongbe_picks"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100), default="")
    grade: Mapped[str] = mapped_column(String(10), default="")     # A / B / 상한가
    close_price: Mapped[float] = mapped_column(Float, default=0.0)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    market_ok: Mapped[bool] = mapped_column(Boolean, default=True)


class TradeExecution(Base, TimestampMixin):
    """매매 일지 체결 한 건. owner별로 나뉘고 dedup_key로 같은 체결을 두 번 넣지 않는다."""

    __tablename__ = "trade_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(40), index=True)
    dedup_key: Mapped[str] = mapped_column(String(200), unique=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    seq: Mapped[str] = mapped_column(String(20), default="")       # 증권사 체결 번호
    side: Mapped[str] = mapped_column(String(4))                    # 매수 / 매도
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100), default="")
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)          # 수수료+세금 (증권사 내역에 있을 때)
    broker_cost: Mapped[float | None] = mapped_column(Float, nullable=True)   # 매도 시 증권사가 계산한 매입금액
    broker_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    tag: Mapped[str] = mapped_column(String(40), default="")        # 직접 고른 근거
    memo: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(10), default="")       # 유형을 직접 바꿨을 때만


class ChartLabel(Base, TimestampMixin):
    """사용자 차트 판단 기록: 그날 목록을 보고 👍(살 만함)/👎(아님), 또는 나중에 본 '놓친 종목'(hindsight).
    고르는 눈을 배우려는 재료 — 결과를 모르고 누른 것과 나중에 본 것을 따로 쓴다."""

    __tablename__ = "chart_labels"
    __table_args__ = (UniqueConstraint("owner", "trading_date", "code", "hindsight", name="uq_chart_labels"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(40), default="")
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    label: Mapped[int] = mapped_column(Integer, default=0)          # 1 살 만함 / -1 아님
    reason: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(40), default="")      # 어느 목록에서 눌렀나
    hindsight: Mapped[bool] = mapped_column(Boolean, default=False)


class Suggestion(Base, TimestampMixin):
    """건의사항 탭: 사용자가 남긴 기능 요청·불편 사항과 처리 상태."""

    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author: Mapped[str] = mapped_column(String(40), default="")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="접수", index=True)
    reply: Mapped[str] = mapped_column(Text, default="")
    image_data: Mapped[str | None] = mapped_column(Text, nullable=True)   # 사진 JSON 배열 (종목토론과 같은 형식)


class JobLog(Base, TimestampMixin):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str] = mapped_column(Text)

