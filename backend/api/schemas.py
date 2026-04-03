from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class MarketSignalResponse(BaseModel):
    trading_date: str
    score: float
    signal: str


class RecommendationItem(BaseModel):
    rank: int
    code: str
    name: str
    total_score: float
    market_score: float
    stock_score: float
    close_price: float
    change_pct: float
    market: str = "KOSPI"
    institution_net_buy: float = 0.0
    foreign_net_buy: float = 0.0
    individual_net_buy: float = 0.0
    consecutive_days: int = 0
    tags: list[str] = []
    short_ratio: float = 0.0
    ma_score: float = 0.0
    rsi_14: float | None = None
    volume_surge: float = 1.0
    market_cap: float = 0.0


class RecommendationResponse(BaseModel):
    trading_date: str
    items: list[RecommendationItem]


class JobResponse(BaseModel):
    trading_date: str
    warnings: list[str]
    market_signal: str
    market_score: float
    stock_signal_count: int
    recommendation_count: int

