"""무거운 스캔 결과 캐시. 데이터 버전(최신 거래일 + 최신 작업 로그)이 같으면 재계산하지 않는다."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

_TTL_SEC = 3600  # 버전 판정이 놓치는 변경(수동 DB 수정 등)에 대한 안전장치
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, tuple, Any]] = {}
_force = threading.local()


@contextmanager
def refreshing():
    """이 안에서 부른 cached()는 결과가 낡았으면 바로 다시 계산한다 (2분마다 도는 warm_caches 용).
    화면 요청은 낡은 결과라도 즉시 돌려주고, 새 계산은 warm_caches가 맡는다 — 데이터가 바뀐 직후 첫 사람이 10~25초 기다리지 않게."""
    _force.on = True
    try:
        yield
    finally:
        _force.on = False


def data_version(db: Session) -> tuple:
    row = db.execute(text(
        "select (select max(trading_date) from spot_daily_prices), (select max(id) from job_logs)"
    )).one()
    return tuple(row)


def cached(name: str, args: tuple, db: Session, compute: Callable[[], Any]) -> Any:
    key = (name, args)
    version = data_version(db)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[1] == version and time.time() - hit[0] < _TTL_SEC:
            return hit[2]
        if hit and not getattr(_force, "on", False):
            return hit[2]          # 낡았어도 우선 보여 주고, 2분 안에 warm_caches가 새로 계산
    value = compute()
    with _lock:
        _cache[key] = (time.time(), version, value)
    return value
