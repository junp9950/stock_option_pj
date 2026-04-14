from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


@dataclass(slots=True)
class AppConfig:
    app_name: str = "Futures Options Analyzer"
    api_prefix: str = "/api"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    default_universe: str = "KOSPI200"
    max_retry_count: int = 3
    request_interval_seconds: float = 1.5
    backfill_request_interval_seconds: float = 3.0
    backfill_cooldown_every: int = 10
    backfill_cooldown_seconds: int = 30
    renormalize_disabled_weights: bool = True
    bearish_threshold: float = -3.0
    bullish_threshold: float = 3.0
    score_market_weight: float = 0.3
    score_stock_weight: float = 0.7
    recommendation_count_bullish: int = 5
    recommendation_count_neutral: int = 3
    min_market_cap: float = 100_000_000_000
    min_trading_value: float = 5_000_000_000
    fee_rate: float = 0.00015
    slippage_rate: float = 0.0005
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    frontend_origin: str = "http://localhost:5173"
    market_signal_weights: dict[str, float] = field(
        default_factory=lambda: {
            "foreign_futures_daily": 0.18,
            "foreign_futures_5d": 0.14,
            "foreign_turn": 0.12,
            "basis_level": 0.10,
            "basis_trend": 0.06,
            "volume_pcr": 0.10,
            "oi_pcr": 0.08,
            "call_put_oi_change": 0.06,
            "program_non_arbitrage": 0.10,
            "arbitrage_pressure": 0.06,
        }
    )
    stock_signal_weights: dict[str, float] = field(
        default_factory=lambda: {
            "foreign_strength": 0.12,
            "institution_strength": 0.12,
            "co_buy": 0.09,
            "volume_surge": 0.07,
            "short_ratio_change": 0.04,
            "short_trend": 0.03,
            "short_squeeze": 0.05,
            "ma_position": 0.09,
            "momentum_5d": 0.07,
            "rsi_14": 0.08,
            "bollinger": 0.06,
            "macd": 0.09,
            "consecutive_buy": 0.07,
            "program_buy": 0.02,
        }
    )


def get_config() -> AppConfig:
    return AppConfig()
