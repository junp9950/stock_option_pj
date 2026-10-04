"""유통주식 비율: 네이버 기업정보(wisereport)의 '발행주식수/유동비율'. 파일에 캐시하고 14일 지나면 다시 받는다.
유통 회전율 = 그날 거래량 / (발행주식수 × 유동비율). 유통 물량을 하루에 몇 % 돌렸는지."""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from backend.utils.logger import get_logger

logger = get_logger(__name__)
_FILE = Path.home() / ".float_ratio.json"
_TTL = 14 * 86400
_lock = threading.Lock()
_cache: dict[str, list] | None = None   # code → [발행주식수, 유동비율(%), 받은 시각]


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _fetch(code: str) -> list | None:
    try:
        r = requests.get("https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx", params={"cmp_cd": code},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
        m = re.search(r"발행주식수/유동비율 ([\d,]+)주 / ([\d.]+)%", t)
        if m:
            return [float(m[1].replace(",", "")), float(m[2]), time.time()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("유동비율 조회 실패 %s: %s", code, exc)
    return None


def get(codes: list[str], fetch_limit: int = 80) -> dict[str, tuple[float, float]]:
    """code → (발행주식수, 유동비율%). 캐시에 없거나 오래된 것은 최대 fetch_limit개까지 바로 받는다."""
    c = _load()
    now = time.time()
    need = [x for x in codes if x not in c or now - c[x][2] > _TTL][:fetch_limit]
    if need:
        with ThreadPoolExecutor(8) as ex:
            for code, v in zip(need, ex.map(_fetch, need)):
                if v:
                    c[code] = v
        with _lock:
            try:
                _FILE.write_text(json.dumps(c), encoding="utf-8")
            except OSError:
                pass
    return {x: (c[x][0], c[x][1]) for x in codes if x in c}
