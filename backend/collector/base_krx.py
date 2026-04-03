from __future__ import annotations

import io
import time

import pandas as pd
import requests

from backend.config import get_config
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class KRXClient:
    """Common KRX OTP download flow.

    Source: KRX data portal OTP -> CSV download pattern.
    Fallback: callers may skip live collection and use demo data.
    """

    OTP_URL = "http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd"
    DOWNLOAD_URL = "http://data.krx.co.kr/comm/fileDn/download_csv/download.cmd"

    def __init__(self) -> None:
        self.config = get_config()
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://data.krx.co.kr/",
        }

    def download_csv(self, params: dict[str, str], *, backfill: bool = False) -> pd.DataFrame:
        interval = self.config.backfill_request_interval_seconds if backfill else self.config.request_interval_seconds
        otp_response = self.session.post(self.OTP_URL, data=params, headers=self.headers, timeout=20)
        otp_response.raise_for_status()
        time.sleep(interval)
        download_response = self.session.post(
            self.DOWNLOAD_URL,
            data={"code": otp_response.text},
            headers=self.headers,
            timeout=30,
        )
        download_response.raise_for_status()
        return pd.read_csv(io.BytesIO(download_response.content), encoding="euc-kr")

