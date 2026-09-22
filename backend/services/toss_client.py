from __future__ import annotations

import threading
import time

import requests

from backend.config import get_config
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_TOKEN_URL = "https://openapi.tossinvest.com/oauth2/token"
_API_BASE = "https://openapi.tossinvest.com/api/v1"

_lock = threading.Lock()
_token: str | None = None
_token_expires_at: float = 0.0


def _fetch_token() -> str | None:
    config = get_config()
    if not config.toss_client_id or not config.toss_client_secret:
        return None
    try:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": config.toss_client_id,
                "client_secret": config.toss_client_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["access_token"], data.get("expires_in", 3600)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Toss OAuth token 발급 실패: %s", exc)
        return None


def get_token() -> str | None:
    """캐시된 토큰을 반환. 만료 5분 전이면 재발급 (토큰은 재발급 시 이전 토큰이 즉시 무효화됨)."""
    global _token, _token_expires_at
    with _lock:
        if _token and time.time() < _token_expires_at - 300:
            return _token
        result = _fetch_token()
        if result is None:
            return None
        _token, expires_in = result
        _token_expires_at = time.time() + expires_in
        return _token


def fetch_candles(symbol: str, interval: str = "1d", count: int = 60) -> list[dict] | None:
    """일봉/분봉 캔들 조회. 응답은 최신순 -> 오래된순으로 뒤집어서 반환(차트 그리기 편하게)."""
    token = get_token()
    if token is None:
        return None
    try:
        resp = requests.get(
            f"{_API_BASE}/candles",
            params={"symbol": symbol, "interval": interval, "count": count},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        candles = resp.json().get("result", {}).get("candles", [])
        return list(reversed(candles))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Toss 캔들 조회 실패 (%s): %s", symbol, exc)
        return None
