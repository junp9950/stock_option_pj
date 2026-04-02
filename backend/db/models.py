from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
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

