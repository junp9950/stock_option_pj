from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import requests

from backend.config import get_config
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_TOKEN_URL = "https://openapi.tossinvest.com/oauth2/token"
_API_BASE = "https://openapi.tossinvest.com/api/v1"
# 토큰은 재발급하면 이전 토큰이 즉시 무효화되므로, 앱과 백필 스크립트 등 여러 프로세스가 이 파일로 같은 토큰을 공유한다
_TOKEN_FILE = Path.home() / ".toss_token.json"

_lock = threading.Lock()
_token: str | None = None
_token_expires_at: float = 0.0


def _fetch_token() -> tuple[str, float] | None:
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
        return data["access_token"], float(data.get("expires_in", 3600))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Toss OAuth token 발급 실패: %s", exc)
        return None


def _read_shared() -> tuple[str | None, float]:
    try:
        d = json.loads(_TOKEN_FILE.read_text())
        return d["token"], float(d["expires_at"])
    except Exception:  # noqa: BLE001
        return None, 0.0


def _write_shared(token: str, expires_at: float) -> None:
    try:
        tmp = _TOKEN_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"token": token, "expires_at": expires_at}))
        os.chmod(tmp, 0o600)
        os.replace(tmp, _TOKEN_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Toss 토큰 공유 파일 저장 실패: %s", exc)


def get_token(rejected: str | None = None) -> str | None:
    """유효한 토큰 반환. rejected는 방금 401을 받은 토큰 — 공유 파일에 더 새 토큰이 있으면 그걸 쓰고, 없으면 재발급."""
    global _token, _token_expires_at
    with _lock:
        now = time.time()
        if _token and _token != rejected and now < _token_expires_at - 300:
            return _token
        shared, shared_exp = _read_shared()
        if shared and shared != rejected and now < shared_exp - 300:
            _token, _token_expires_at = shared, shared_exp
            return _token
        result = _fetch_token()
        if result is None:
            return None
        _token, expires_in = result
        _token_expires_at = now + expires_in
        _write_shared(_token, _token_expires_at)
        return _token


def _get(path: str, params: dict) -> requests.Response | None:
    """인증 GET. 다른 프로세스가 토큰을 재발급해 401이 나면 새 토큰으로 한 번 재시도."""
    token = get_token()
    if token is None:
        return None
    resp = requests.get(f"{_API_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if resp.status_code == 401:
        token = get_token(rejected=token)
        if token is None:
            return resp
        resp = requests.get(f"{_API_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    return resp


def fetch_candles(symbol: str, interval: str = "1d", count: int = 60) -> list[dict] | None:
    """일봉/분봉 캔들 조회. 응답은 최신순 -> 오래된순으로 뒤집어서 반환(차트 그리기 편하게)."""
    try:
        resp = _get("/candles", {"symbol": symbol, "interval": interval, "count": count})
        if resp is None:
            return None
        resp.raise_for_status()
        candles = resp.json().get("result", {}).get("candles", [])
        return list(reversed(candles))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Toss 캔들 조회 실패 (%s): %s", symbol, exc)
        return None


def fetch_investor_trading(symbol: str, count: int = 100, until: str | None = None) -> requests.Response | None:
    """투자자별 매매동향(개인·외국인·기관 세부·기타법인, 주식 수). until 이전(포함) 최신순 count일치, 다음 페이지는 result.nextUntil."""
    params: dict = {"count": count}
    if until:
        params["until"] = until
    return _get(f"/stocks/{symbol}/investor-trading", params)
