"""종목 위험 표시: 투자주의·경고·위험, 단기과열, 관리종목, 신용 불가(증거금 100%). KIS 현재가 조회(FHKST01010100).
후보 종목만 조회하고 파일에 캐시한다 (12시간). 증거금·신용 가능 여부는 한국투자증권 기준."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import requests

from backend.utils.logger import get_logger

logger = get_logger(__name__)
_FILE = Path.home() / ".stock_flags.json"
_TTL = 12 * 3600
_lock = threading.Lock()
_WARN = {"01": "투자주의", "02": "투자경고", "03": "투자위험"}


def _fetch(code: str, token: str) -> dict | None:
    try:
        r = requests.get("https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price",
                         headers={"authorization": f"Bearer {token}", "appkey": os.getenv("KIS_APP_KEY", ""),
                                  "appsecret": os.getenv("KIS_APP_SECRET", ""), "tr_id": "FHKST01010100", "custtype": "P"},
                         params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}, timeout=6)
        o = r.json().get("output") or {}
        if not o:
            return None
        flags = []
        if o.get("mrkt_warn_cls_code") in _WARN:
            flags.append(_WARN[o["mrkt_warn_cls_code"]])
        if o.get("invt_caful_yn") == "Y" and "투자주의" not in flags:
            flags.append("투자유의")
        if o.get("short_over_yn") == "Y":
            flags.append("단기과열")
        if o.get("mang_issu_cls_code") == "Y":
            flags.append("관리종목")
        if o.get("crdt_able_yn") == "N":
            flags.append("신용불가")
        return {"flags": flags, "margin": float(o.get("marg_rate") or 0), "t": time.time()}
    except Exception as exc:  # noqa: BLE001
        logger.debug("종목 위험 표시 조회 실패 %s: %s", code, exc)
        return None


def get(codes: list[str]) -> dict[str, dict]:
    """code → {"flags": [...], "margin": 증거금률}. 캐시에 없거나 12시간 지난 것만 조회 (초당 약 15건)."""
    with _lock:
        try:
            cache = json.loads(_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        now = time.time()
        need = [c for c in dict.fromkeys(codes) if c not in cache or now - cache[c]["t"] > _TTL]
        if need:
            from backend.collector.spot import _get_kis_token  # noqa: PLC0415
            token = _get_kis_token()
            if token:
                for c in need:
                    v = _fetch(c, token)
                    if v:
                        cache[c] = v
                    time.sleep(0.07)
                try:
                    _FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
        return {c: cache[c] for c in codes if c in cache}
