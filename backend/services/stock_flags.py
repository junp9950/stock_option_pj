"""종목 위험 표시: 투자주의·경고·위험, 단기과열, 관리종목, 신용 불가(증거금 100%), 거래정지, 정리매매.
후보 종목만 조회하고 파일에 캐시한다 (12시간).
- 거래소가 정하는 것(투자주의·경고·위험·단기과열·관리종목) = 한국투자증권 현재가(FHKST01010100) — 메리츠 시세에는 이 항목이 없음
- 증권사마다 다른 것(신용 가능·증거금률) + 거래정지·정리매매·투자유의 = 메리츠 현재가(/market/v1/prices) — 사용자 계좌가 메리츠 (2026-10-13)
  예: 295310·020150 한국투자 신용불가(증거금 100%) / 메리츠 신용 가능(50%). 메리츠가 안 되면 한국투자 값."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import requests

from backend.utils.logger import get_logger

logger = get_logger(__name__)
_FILE = Path.home() / ".stock_flags_v2.json"     # v2 = 메리츠 기준 (예전 한국투자 캐시와 섞이지 않게)
_TTL = 12 * 3600
_lock = threading.Lock()
_WARN = {"01": "투자주의", "02": "투자경고", "03": "투자위험"}


def _meritz(code: str) -> dict | None:
    """메리츠 현재가의 신용·증거금·정지 항목. 키가 없거나 실패하면 None (그때는 한국투자 값)."""
    try:
        from backend.services import meritz as M  # noqa: PLC0415
        if not M.enabled():
            return None
        r = M.call("GET", "/market/v1/prices", params={"mrkt_div_code": "J", "iscd": code})
        d = r["data"] if isinstance(r.get("data"), dict) else None
        if not r["ok"] or not d or not d.get("crdt_able_yn"):
            return None
        return {k: d.get(k) for k in ("crdt_able_yn", "marg_rate", "tmpr_susp_yn", "sltr_yn", "invt_epmd_cntt")}
    except Exception as exc:  # noqa: BLE001
        logger.debug("메리츠 종목 상태 조회 실패 %s: %s", code, exc)
        return None


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
        mz = _meritz(code)
        credit_no = (mz["crdt_able_yn"] == "N") if mz else (o.get("crdt_able_yn") == "N")
        margin = float((mz or {}).get("marg_rate") or o.get("marg_rate") or 0)
        if mz:
            if mz.get("tmpr_susp_yn") == "Y":
                flags.insert(0, "거래정지")
            if mz.get("sltr_yn") == "Y":
                flags.insert(0, "정리매매")
            if (mz.get("invt_epmd_cntt") or "").strip() and "투자유의" not in flags:
                flags.append("투자유의")
        if credit_no:
            flags.append("신용불가")
        return {"flags": flags, "margin": margin, "src": "메리츠" if mz else "한국투자", "t": time.time()}
    except Exception as exc:  # noqa: BLE001
        logger.debug("종목 위험 표시 조회 실패 %s: %s", code, exc)
        return None


def get(codes: list[str], fetch: bool = True) -> dict[str, dict]:
    """code → {"flags": [...], "margin": 증거금률}. 캐시에 없거나 12시간 지난 것만 조회 (초당 약 15건)."""
    with _lock:
        try:
            cache = json.loads(_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        now = time.time()
        need = [c for c in dict.fromkeys(codes) if c not in cache or now - cache[c]["t"] > _TTL]
        if need and fetch:
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
