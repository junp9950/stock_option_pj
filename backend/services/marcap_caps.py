"""종목별 최신 시가총액 (FinanceData/marcap). stocks 테이블에 시총·주식 수가 없는 종목(유니버스 밖)을 채우는 용도.

하루 한 번 받아 data/marcap_cache/caps.json에 저장하고, 화면 계산에서는 파일만 읽는다.
marcap 원본은 보통 전날 밤에 갱신되므로 값은 최근 거래일 하루 전 기준일 수 있다.
"""
from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from backend.utils.logger import get_logger

logger = get_logger(__name__)

PATH = Path(__file__).resolve().parents[2] / "data" / "marcap_cache" / "caps.json"
URL = "https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet"


def refresh() -> None:
    try:
        r = requests.get(URL.format(year=date.today().year), timeout=120)
        r.raise_for_status()
        df = pd.read_parquet(BytesIO(r.content), columns=["Date", "Code", "Marcap"])
        df["Date"] = pd.to_datetime(df.Date)
        last = df.sort_values("Date").groupby("Code").tail(1)
        payload = {"as_of": last.Date.max().date().isoformat(),
                   "caps": {str(c).zfill(6): float(m) for c, m in zip(last.Code, last.Marcap) if m and m > 0}}
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(PATH)
        logger.info("marcap 시총 캐시 갱신: %d종목, 기준일 %s", len(payload["caps"]), payload["as_of"])
    except Exception as exc:  # noqa: BLE001
        logger.error("marcap 시총 캐시 갱신 실패 (이전 캐시 유지): %s", exc)


def caps() -> dict[str, float]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))["caps"]
    except Exception:  # noqa: BLE001
        return {}
