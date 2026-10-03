from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import ShortSellingDaily
from backend.utils.dates import latest_trading_day
from backend.utils.logger import get_logger


logger = get_logger(__name__)

def _kis_short_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """KIS Open API로 종목별 공매도 데이터 조회.
    TR_ID: FHPST04830000, endpoint: /uapi/domestic-stock/v1/quotations/daily-short-sale
    반환: {종목코드: (short_volume, short_ratio, short_balance)}
    실패 시 빈 dict 반환.
    """
    import os, time as _time, requests as _req  # noqa: PLC0415
    from backend.collector.spot import _get_kis_token  # noqa: PLC0415

    app_key = os.getenv("KIS_APP_KEY", "")
    app_secret = os.getenv("KIS_APP_SECRET", "")
    if not app_key or not app_secret:
        return {}

    token = _get_kis_token()
    if not token:
        return {}

    from backend.db.database import SessionLocal  # noqa: PLC0415
    from backend.collector.universe import get_universe  # noqa: PLC0415
    _db = SessionLocal()
    try:
        codes = [s.code for s in get_universe(_db)]
    finally:
        _db.close()

    result: dict[str, tuple[float, float, float]] = {}
    headers = {
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHPST04830000",
        "content-type": "application/json",
    }

    for code in codes:
        try:
            r = _req.get(
                "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/daily-short-sale",
                headers=headers,
                params={
                    "FID_COND_MRKT_DIV_CODE": "J",
                    "FID_INPUT_ISCD": code,
                    "FID_INPUT_DATE_1": yyyymmdd,
                    "FID_INPUT_DATE_2": yyyymmdd,
                },
                timeout=5,
            )
            rows = r.json().get("output2", [])
            for row in rows:
                if row.get("stck_bsop_date") == yyyymmdd:
                    # ssts_cntg_qty: 공매도 체결량, ssts_vol_rlim: 공매도 비중(%)
                    # ssts_tr_pbmn: 공매도 거래대금 (잔고 대체)
                    vol = float(row.get("ssts_cntg_qty") or 0)
                    ratio = float(row.get("ssts_vol_rlim") or 0)
                    bal = float(row.get("ssts_tr_pbmn") or 0)
                    if vol > 0 or ratio > 0:
                        result[code] = (vol, ratio, bal)
                    break
            _time.sleep(0.15)
        except Exception as exc:  # noqa: BLE001
            logger.debug("KIS short failed for %s: %s", code, exc)

    logger.info("KIS 공매도 수집 완료: %d/%d 종목", len(result), len(codes))
    return result


def collect_short_selling_data(db: Session, trading_date: date) -> None:
    """Collect short selling data.

    Source: KIS API (pykrx·KRX 데이터포털 직접 조회는 KRX 로그인 필수화 이후 계속 실패해 2026-10-03 제거).
    데이터 없음 → 레코드 미삽입 (signal engine이 None으로 처리 → 중립 점수)

    KRX 완전 차단 시 가짜 값 대신 레코드를 삽입하지 않는다.
    signal engine은 short=None일 때 공매도 점수 0.0(중립)으로 처리한다.
    """
    fetch_date = latest_trading_day(trading_date)
    if fetch_date != trading_date:
        logger.info("trading_date=%s is non-trading → fetching short data for %s", trading_date, fetch_date)
    yyyymmdd = fetch_date.strftime("%Y%m%d")
    db.execute(delete(ShortSellingDaily).where(ShortSellingDaily.trading_date == trading_date))

    batch_data = _kis_short_batch(yyyymmdd)
    source = "kis"

    batch_ok = len(batch_data) > 0

    if batch_ok:
        logger.info("공매도 배치 수집 성공 (%s): %d 종목", source, len(batch_data))
        # 배치 성공: 전종목 레코드 삽입 (배치에 없는 종목 = 당일 공매도 없음 = 실제 0)
        for stock in get_universe(db):
            if stock.code in batch_data:
                short_volume, short_ratio, short_balance = batch_data[stock.code]
            else:
                short_volume = 0.0
                short_ratio = 0.0
                short_balance = 0.0
            db.add(ShortSellingDaily(
                trading_date=trading_date,
                stock_code=stock.code,
                short_volume=short_volume,
                short_ratio=short_ratio,
                short_balance=short_balance,
            ))
        db.commit()
        return

    # 모든 소스 실패 → 레코드 미삽입. signal engine이 short=None → 중립 처리
    logger.warning("공매도 데이터 수집 실패 (%s) — 레코드 삽입 안 함 (중립 처리)", trading_date)
    db.commit()
