from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def retry(operation: Callable[[], T], attempts: int = 3, delay_seconds: float = 1.0) -> T:
    last_error: Exception | None = None
    for index in range(attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if index < attempts - 1:
                time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error

