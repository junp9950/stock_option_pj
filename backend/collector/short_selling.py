from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.collector.universe import get_universe
from backend.db.models import ShortSellingDaily
from backend.utils.logger import get_logger


logger = get_logger(__name__)

_FALLBACK_VOL_BASE = 20_000
_FALLBACK_RATIO_BASE = 1.8
_FALLBACK_BAL_BASE = 90_000_000


def _pykrx_short_batch(yyyymmdd: str) -> dict[str, tuple[float, float, float]]:
    """pykrx로 KOSPI 전종목 공매도 데이터 일괄 조회.
    반환: {종목코드: (short_volume, short_ratio, short_balance)}
    실패 시 빈 dict 반환.
    """
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415
        vol_df = pykrx_stock.get_shorting_volume_by_ticker(yyyymmdd, market="KOSPI")
        bal_df = pykrx_stock.get_shorting_balance_by_ticker(yyyymmdd, market="KOSPI")

        result: dict[str, tuple[float, float, float]] = {}

        # volume/ratio data
        vol_map: dict[str, tuple[float, float]] = {}
        if vol_df is not None and not vol_df.empty:
            for code, row in vol_df.iterrows():
                code_str = str(code).zfill(6)
                vol = float(row["공매도"]) if "공매도" in row.index else 0.0
                ratio = float(row["비중"]) if "비중" in row.index else 0.0
                vol_map[code_str] = (vol, ratio)

        # balance data
        bal_map: dict[str, float] = {}
        if bal_df is not None and not bal_df.empty:
            for code, row in bal_df.iterrows():
                code_str = str(code).zfill(6)
                for col in ("공매도잔고금액", "잔고금액", "공매도잔고"):
                    if col in row.index:
                        bal_map[code_str] = float(row[col])
                        break

        all_codes = set(vol_map) | set(bal_map)
        for code in all_codes:
            vol, ratio = vol_map.get(code, (0.0, 0.0))
            bal = bal_map.get(code, 0.0)
            if vol > 0 or ratio > 0 or bal > 0:
                result[code] = (vol, ratio, bal)

        logger.info("pykrx batch short selling: %d stocks fetched for %s", len(result), yyyymmdd)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx batch short selling failed: %s", exc)
        return {}


def _pykrx_short_single(code: str, yyyymmdd: str) -> tuple[float, float, float] | None:
    """pykrx로 단일 종목 공매도 데이터 조회. 실패 시 None 반환."""
    try:
        from pykrx import stock as pykrx_stock  # noqa: PLC0415

        vol_df = pykrx_stock.get_shorting_volume_by_date(yyyymmdd, yyyymmdd, code)
        bal_df = pykrx_stock.get_shorting_balance_by_date(yyyymmdd, yyyymmdd, code)

        short_volume = 0.0
        short_ratio = 0.0
        short_balance = 0.0

        if vol_df is not None and not vol_df.empty:
            vrow = vol_df.iloc[0]
            short_volume = float(vrow["공매도"]) if "공매도" in vrow.index else 0.0
            short_ratio = float(vrow["비중"]) if "비중" in vrow.index else 0.0

        if bal_df is not None and not bal_df.empty:
            brow = bal_df.iloc[0]
            for col in ("공매도잔고금액", "잔고금액", "공매도잔고"):
                if col in brow.index:
                    short_balance = float(brow[col])
                    break
            if short_ratio == 0.0 and "비중" in brow.index:
                short_ratio = float(brow["비중"])

        if short_volume == 0.0 and short_ratio == 0.0 and short_balance == 0.0:
            return None

        return short_volume, short_ratio, short_balance
    except Exception as exc:  # noqa: BLE001
        logger.debug("pykrx short selling skipped for %s: %s", code, exc)
        return None


def collect_short_selling_data(db: Session, trading_date: date) -> None:
    """Collect short selling data.

    Source priority:
      1. pykrx 전종목 일괄 조회 (get_shorting_volume_by_ticker / get_shorting_balance_by_ticker)
      2. pykrx 단건 조회 (배치 실패 시)
      3. 합성 demo 값 (fallback)
    """
    yyyymmdd = trading_date.strftime("%Y%m%d")
    db.execute(delete(ShortSellingDaily).where(ShortSellingDaily.trading_date == trading_date))

    # 배치 조회 시도
    batch_data = _pykrx_short_batch(yyyymmdd)
    batch_ok = len(batch_data) > 0
    if not batch_ok:
        logger.warning("pykrx batch short selling failed — using single-stock fallback")

    for index, stock in enumerate(get_universe(db), start=1):
        if batch_ok and stock.code in batch_data:
            short_volume, short_ratio, short_balance = batch_data[stock.code]
        elif not batch_ok:
            result = _pykrx_short_single(stock.code, yyyymmdd)
            if result is not None:
                short_volume, short_ratio, short_balance = result
            else:
                short_volume = _FALLBACK_VOL_BASE + index * 1_500
                short_ratio = _FALLBACK_RATIO_BASE + index * 0.2
                short_balance = _FALLBACK_BAL_BASE + index * 10_000_000
        else:
            # batch ok but this code not in batch (likely not traded)
            short_volume = 0.0
            short_ratio = 0.0
            short_balance = 0.0

        db.add(
            ShortSellingDaily(
                trading_date=trading_date,
                stock_code=stock.code,
                short_volume=short_volume,
                short_ratio=short_ratio,
                short_balance=short_balance,
            )
        )
    db.commit()
