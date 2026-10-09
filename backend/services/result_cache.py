"""무거운 스캔 결과 캐시. 데이터 버전(최신 거래일 + 최신 작업 로그)이 같으면 재계산하지 않는다."""
from __future__ import annotations

import pickle
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

_TTL_SEC = 3600  # 버전 판정이 놓치는 변경(수동 DB 수정 등)에 대한 안전장치
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, tuple, Any]] = {}
_force = threading.local()
_DISK = Path.home() / ".result_cache"      # 재시작해도 마지막 결과를 바로 보여 주려고 디스크에도 둔다


def _disk_load(key: tuple):
    try:
        with open(_DISK / f"{key[0]}_{abs(hash(key[1])) if key[1] else 0}.pkl", "rb") as f:
            return pickle.load(f)
    except Exception:  # noqa: BLE001
        return None


def _disk_save(key: tuple, entry: tuple) -> None:
    try:
        _DISK.mkdir(exist_ok=True)
        tmp = _DISK / f".{key[0]}.tmp"
        with open(tmp, "wb") as f:
            pickle.dump(entry, f)
        tmp.replace(_DISK / f"{key[0]}_{abs(hash(key[1])) if key[1] else 0}.pkl")
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def refreshing():
    """이 안에서 부른 cached()는 결과가 낡았으면 바로 다시 계산한다 (2분마다 도는 warm_caches 용).
    화면 요청은 낡은 결과라도 즉시 돌려주고, 새 계산은 warm_caches가 맡는다 — 데이터가 바뀐 직후 첫 사람이 10~25초 기다리지 않게."""
    _force.on = True
    try:
        yield
    finally:
        _force.on = False


def _code_version() -> str:
    """배포된 코드 버전(git 커밋). 코드가 바뀌면(새 칸 추가 등) 데이터가 같아도 다시 계산되게 버전에 넣는다."""
    root = Path(__file__).resolve().parents[2]
    try:
        head = (root / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = root / ".git" / head.split(" ", 1)[1]
            if ref.exists():
                return ref.read_text().strip()[:12]
            packed = (root / ".git" / "packed-refs").read_text()
            for line in packed.splitlines():
                if line.endswith(head.split(" ", 1)[1]):
                    return line[:12]
        return head[:12]
    except OSError:
        return str(int(time.time()))


_CODE = _code_version()


def data_version(db: Session) -> tuple:
    row = db.execute(text(
        "select (select max(trading_date) from spot_daily_prices), (select max(id) from job_logs)"
    )).one()
    return (*tuple(row), _CODE)


_inflight: dict[tuple, threading.Lock] = {}


def peek(name: str, args: tuple = ()) -> Any:
    """계산하지 않고 들고 있는 결과만 (없으면 None) — 다른 화면이 곁가지로 쓸 때."""
    with _lock:
        hit = _cache.get((name, args))
    return hit[2] if hit else None


def cached(name: str, args: tuple, db: Session, compute: Callable[[], Any]) -> Any:
    key = (name, args)
    version = data_version(db)
    with _lock:
        hit = _cache.get(key)
        if hit is None and not args:
            hit = _disk_load(key)
            if hit:
                _cache[key] = hit
        if hit and hit[1] == version and time.time() - hit[0] < _TTL_SEC:
            return hit[2]
        if hit and not getattr(_force, "on", False):
            return hit[2]          # 낡았어도 우선 보여 주고, 2분 안에 warm_caches가 새로 계산 (계산 중이어도 기다리지 않음)
        kl = _inflight.setdefault(key, threading.Lock())
    with kl:   # 결과가 아예 없을 때만: 같은 계산을 여러 요청이 동시에 하지 않게 (2026-10-06)
        with _lock:
            hit = _cache.get(key)
            if hit and hit[1] == version:
                return hit[2]
        return _compute(key, args, version, compute)


def _compute(key: tuple, args: tuple, version: tuple, compute: Callable[[], Any]) -> Any:
    value = compute()
    entry = (time.time(), version, value)
    with _lock:
        _cache[key] = entry
    if not args:
        _disk_save(key, entry)
    return value
