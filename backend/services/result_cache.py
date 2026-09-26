"""무거운 스캔 결과 캐시. 데이터 버전(최신 거래일 + 최신 작업 로그)이 같으면 재계산하지 않는다."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

_TTL_SEC = 3600  # 버전 판정이 놓치는 변경(수동 DB 수정 등)에 대한 안전장치
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, tuple, Any]] = {}


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
    value = compute()
    with _lock:
        _cache[key] = (time.time(), version, value)
    return value
