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
        # 2026-09-09: 2026-01~09 전체 이력(36,533건, 지표당 26,903~36,303 샘플)에서
        # 지표별 T+1/T+3/T+5/T+10 순방향 수익률과의 스피어만 상관(IC)을 측정해 재산정.
        # 기존 가중치는 T+1 IC가 -0.006 (사실상 역상관)이었는데, 이 가중치는 +0.027로
        # 개선됨 (상위20% 평균수익률 -0.02% -> +0.47%). momentum_5d/rsi_14/short_squeeze처럼
        # IC가 뚜렷하게 음수인 지표는 대폭 축소, volume_surge/foreign_strength/bollinger/
        # stealth_accumulation처럼 IC가 양수인 지표는 확대. 다만 이 검증은 동일 기간
        # 데이터로 가중치를 고르고 같은 기간에 평가한 것(in-sample)이라 과최적화 위험이
        # 있음 — 이후 새로 쌓이는 데이터로 주기적으로 재검증할 것.
        default_factory=lambda: {
            "volume_surge": 0.22,
            "foreign_strength": 0.18,
            "bollinger": 0.14,
            "stealth_accumulation": 0.14,
            "institution_strength": 0.06,
            "short_trend": 0.06,
            "co_buy": 0.04,
            "consecutive_buy": 0.04,
            "macd": 0.04,
            "ma_position": 0.03,
            "short_ratio_change": 0.02,
            "rsi_14": 0.02,
            "momentum_5d": 0.01,
            "short_squeeze": 0.00,
            "program_buy": 0.00,
        }
    )


def get_config() -> AppConfig:
    return AppConfig()
