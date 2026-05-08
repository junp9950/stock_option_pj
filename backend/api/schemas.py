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
    foreign_consecutive_days: int = 0
    institution_consecutive_days: int = 0
    flow_ratio: str = "0/0"
    tags: list[str] = []
    short_ratio: float = 0.0
    ma_score: float = 0.0
    rsi_14: float | None = None
    volume_surge: float = 1.0
    market_cap: float = 0.0
    signal_confluence: int = 0


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
    sector_count: int = 0


class SectorItem(BaseModel):
    id: int
    sector_code: str
    sector_name: str
    source: str
    is_active: bool


class SectorFlowItem(BaseModel):
    sector_id: int
    sector_code: str
    sector_name: str
    source: str
    date: str
    foreign_net_buy: int
    inst_net_buy: int
    combined_net_buy: int
    stock_count: int
    up_count: int
    down_count: int
    avg_change_pct: float
    max_change_pct: float
    flow_score: float
    stealth_score: float
    buy_streak: int
    top_contributor_code: str | None
    top_contributor_name: str | None
    top_contributor_amount: int
    is_surged: bool  # 당일 급등 여부 (avg_change_pct >= 5%)


class SectorStockItem(BaseModel):
    stock_code: str
    stock_name: str
    market: str
    foreign_net_buy: float
    inst_net_buy: float
    combined_net_buy: float
    change_pct: float
    close_price: float

